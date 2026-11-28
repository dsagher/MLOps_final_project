# BLS API ETL Pipeline

An ETL pipeline that pulls national and state labor series from the
[Bureau of Labor Statistics (BLS) API](https://www.bls.gov/developers/), cleans them,
and loads them into PostgreSQL. It is a plain Python script meant to be run by hand or
from `cron`; the data changes infrequently, so no orchestration tool is needed.

## Requirements

- Python 3.12+ (the code uses `itertools.batched`)
- PostgreSQL, with a database you can create tables in
- A free BLS API key: <https://data.bls.gov/registrationEngine/>
- `make` (optional, but the `.env` loading below relies on it)

## Setup

### 1. Clone and install

```bash
git clone <repo-url> && cd <repo-folder>
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The notebooks and `src/scrape/state_scrape.py` additionally need `pandas` and
`beautifulsoup4`; the pipeline itself does not.

### 2. Create the PostgreSQL database

```bash
createdb bls                      # or: psql -c "CREATE DATABASE bls;"
```

Use any name, and any user that owns the database. The name goes in `DB_DATABASE` below.

### 3. Create your `.env`

`.env` holds secrets and is git-ignored, so it is never in the repo. Create it from the template:

```bash
cp .env.example .env
```

Then edit it:

| Variable | Meaning | Example |
|---|---|---|
| `API_KEY` | Your BLS registration key | `abc123...` |
| `NATIONAL_SERIES_FILE` | Input CSV for `make build_national` | `data/inputs/national_series.csv` |
| `STATE_SERIES_FILE` | Input CSV for `make build_state` | `data/inputs/state_series.csv` |
| `DB_DRIVER` | SQLAlchemy driver name | `postgresql+psycopg2` |
| `DB_USERNAME` | Postgres user | `postgres` |
| `DB_PASSWORD` | Postgres password | |
| `DB_HOST` | Postgres host | `localhost` |
| `DB_DATABASE` | Database name from step 2 | `bls` |
| `DB_PORT` | Postgres port | `5432` |

Rules, because `make` parses this file rather than a shell:

- One `NAME=value` per line, no spaces around `=`, no quotes, no `export`.
- A `#` inside a value starts a comment, so avoid it in `DB_PASSWORD`.
- All `DB_*` variables are required; a missing one raises a `ValueError` naming it.
- `BLS_API_KEY` is sent with every request but is not checked locally, so a missing or wrong key shows up as an API error, not a startup error.
- The pipeline enforces BLS's registered limits: 500 queries/day, 20 years and 50 series per query.

If you run Python directly instead of through `make`, load the file into your shell first:

```bash
set -a; source .env; set +a
```

The pipeline creates its tables on the first load, so there is no separate table setup step.

### 4. Run the tests

```bash
make test
```

Tests mock all HTTP calls and need neither a database nor an API key.

## Running the pipeline

Run everything from the project root: the log and query-count paths (`data/outputs/runtime_output/`) are relative to the working directory.

```bash
make build_national     # national series, 2000-2005, 1 series
make build_state        # state series, 2000-2005, 1 series
```

Or call it directly:

```bash
python -m src.main --path data/inputs/state_series.csv --series-type 2 --start-year 2000 --end-year 2005
```

| Option | Description |
|---|---|
| `--path` | CSV of series IDs |
| `--series-type` | `1` national, `2` state |
| `--start-year`, `--end-year` | Year range for the query |
| `-n`, `--series-count` | Number of series IDs to use |
| `-t`, `--traceroute` | Traceroute to the BLS API, then exit |
| `-v`, `--verbose` | Debug-level logging |
| `-s`, `--silence` | Turn off logging |

`--path`, `--series-type`, `--start-year` and `--end-year` must be given together.

## Input CSVs

`national_series.csv`:

```csv
series,seriesID,survey
Number of work stoppages,WSU100,WSP
```

`state_series.csv`:

```csv
survey,series,seriesID,state
CES,"Total Nonfarm, Seasonally adjusted",SMS01000000000000001,Alabama
```

## How it works

1. **Extract**: `extract()` in `src/api/extract.py` batches series IDs (max 50 per request, max 20 years) and POSTs them to the BLS API, retrying on server errors.
2. **Transform**: the raw response uses camelCase (`seriesID`, `periodName`); `transform_results()` and `transform_series()` in `src/api/transform.py` convert keys to snake_case and build rows matching the PostgreSQL columns.
3. **Load**: `load()` in `src/api/load.py` writes rows with SQLAlchemy using `ON CONFLICT DO NOTHING`, so re-running is safe.

Each stage is a plain function that takes its inputs as arguments and returns its output; `main.py` passes the data between them.

Built-in protections: daily query limit tracking in `data/outputs/runtime_output/query_count.csv` (resets each day), year and series-ID limits, HTTP retry and error logging, and input validation.

## Project layout

```
.
├── Makefile
├── requirements.txt
├── .env.example            # template; copy to .env
├── assets/                 # proposal and process diagram
├── data/
│   ├── inputs/             # national_series.csv, state_series.csv
│   ├── excel_files/        # source series and survey lists
│   └── outputs/
│       ├── runtime_output/ # main.log, query_count.csv
│       ├── cleaning_op/    # cleaned notebook outputs
│       └── state_scrape_results/
└── src/
    ├── main.py             # entry point
    ├── api/                # extract.py, transform.py, load.py, strategies.py, api_types.py, tests/
    ├── scrape/             # state series ID scraper
    └── utils/              # arg parsing, validation, logging, CSV reading
```

## Example API response

```json
{
    "status": "REQUEST_SUCCEEDED",
    "responseTime": 225,
    "message": [],
    "Results": {
        "series": [
            {
                "seriesID": "SMS01000000000000001",
                "data": [
                    {"year": "2020", "period": "M12", "periodName": "December", "value": "2022.5", "footnotes": [{}]}
                ]
            }
        ]
    }
}
```

## Troubleshooting

- **`Database host not specified in environment variable 'DB_HOST'`**: `.env` was not loaded. Use `make`, or `set -a; source .env; set +a`.
- **`Queries may not exceed 500 within a day.`**: the daily limit was reached; wait for the next day or delete `data/outputs/runtime_output/query_count.csv` only if you know the real count is lower.
- **`connection refused` / `password authentication failed`**: check that Postgres is running and that `DB_HOST`, `DB_PORT`, `DB_USERNAME`, and `DB_PASSWORD` are correct.
