# BLS API ETL Pipeline

An ETL pipeline that pulls national and state labor series from the
[Bureau of Labor Statistics (BLS) API](https://www.bls.gov/developers/), cleans them,
and loads them into PostgreSQL. It is a plain Python script you can run by hand or from
`cron`. Because the data changes infrequently, an optional Airflow DAG checks BLS weekly and
reloads a series set only when BLS has data the database does not (see
[Scheduling with Airflow](#scheduling-with-airflow-optional)).

## Requirements

- Python 3.12+ (the code uses `itertools.batched`)
- PostgreSQL, with a database you can create tables in
- A free BLS API key: <https://data.bls.gov/registrationEngine/>
- `make` (optional; the `make` targets read their CSV paths from `.env`)

## Setup

### 1. Clone and install

```bash
git clone <repo-url> && cd <repo-folder>
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` includes Apache Airflow, so the install is large; Airflow is only used for
scheduling. The notebooks and `src/scrape/state_scrape.py` additionally need `pandas` and
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
| `NATIONAL_SERIES_FILE` | Input CSV for the national `make` targets | `data/inputs/national_series.csv` |
| `STATE_SERIES_FILE` | Input CSV for the state `make` targets | `data/inputs/state_series.csv` |
| `DB_DRIVER` | SQLAlchemy driver name | `postgresql+psycopg2` |
| `DB_USERNAME` | Postgres user | `postgres` |
| `DB_PASSWORD` | Postgres password | |
| `DB_HOST` | Postgres host | `localhost` |
| `DB_DATABASE` | Database name from step 2 | `bls` |
| `DB_PORT` | Postgres port | `5432` |
| `AIRFLOW_HOME` | Optional. Absolute path to `<repo>/data/airflow`, for the Airflow DAG only | `/home/me/repo/data/airflow` |

Rules, because `make` parses this file rather than a shell:

- One `NAME=value` per line, no spaces around `=`, no quotes, no `export`.
- A `#` inside a value starts a comment, so avoid it in `DB_PASSWORD`.
- All `DB_*` variables are required; if any is empty or missing, `get_engine()` raises `ValueError: One or more required database connection parameters are missing.`
- `API_KEY` is sent with every request but is not checked locally, so a missing or wrong key shows up as an API error, not a startup error.
- The pipeline enforces BLS's registered limits: 500 queries/day, 20 years and 50 series per query.

`src.main` and `src.refresh.check_bls` call `load_dotenv()`, which finds `.env` in the project root,
so running `python -m ...` directly works without `make` or sourcing the file. Airflow itself does
not read `.env`; see [Scheduling with Airflow](#scheduling-with-airflow-optional).

The pipeline creates its tables on the first load, so there is no separate table setup step.

### 4. Run the tests

```bash
make test
```

Tests mock all HTTP calls and need neither a database nor an API key.

## Running the pipeline

Run everything from the project root: the query-count path (`data/outputs/runtime_output/query_count.csv`) is relative to the working directory.

```bash
make build_national         # national series, 2000-2005, 1 series
make build_state            # state series, 2000-2005, 1 series
make build_latest_national  # latest data point only, 1 series
make build_latest_state     # latest data point only, 1 series
make build_check            # national only: does BLS have newer data than the DB?
```

These targets pass `--series-count 1` so a trial run costs one query. For a full load, call it directly:

```bash
python -m src.main --path data/inputs/state_series.csv --series-type 2 --start-year 2000 --end-year 2005
python -m src.main --path data/inputs/state_series.csv --series-type 2 --latest
```

| Option | Description |
|---|---|
| `--path` | CSV of series IDs |
| `--series-type` | `1` national, `2` state |
| `--start-year`, `--end-year` | Year range for the query |
| `--latest` | Fetch only the latest data point per series from the BLS API, instead of a year range |
| `-n`, `--series-count` | Number of series IDs to use |
| `-t`, `--traceroute` | Traceroute to the BLS API, then exit |
| `-v`, `--verbose` | Debug-level logging |
| `-s`, `--silence` | Turn off logging |

Without `--latest`, `--path`, `--series-type`, `--start-year` and `--end-year` must all be given.
With `--latest`, give `--path` and `--series-type` and omit both years (combining them is an error).

## Checking for new data

`src.refresh.check_bls` fetches the latest data point for each series from BLS, compares it with
the newest row per series in the database, and prints `Comparison result: True` or `False`:

```bash
make build_check
python -m src.refresh.check_bls --path data/inputs/state_series.csv --series-type 2 --latest
```

It returns `True` only if **every** series has a data point the database does not have yet (an
empty database, or a table that does not exist yet, counts as new). It does not load anything.
It uses one BLS query per 50 series, against the same 500/day limit.

## Scheduling with Airflow (optional)

`data/airflow/dags/dags.py` defines the `refresh_bls_data` DAG, scheduled weekly (no catch-up).
For each of national and state it runs two tasks:

1. `check_new_<name>_data`: `has_new_bls_data()` from `check_bls.py`. If it returns `False`, the next task is skipped.
2. `run_main_<name>`: `python -m src.main --path <csv> --series-type <1|2> --latest`.

The DAG always uses every series in the CSV (no `--series-count`), so each run spends queries
from the daily limit: one check plus one load per 50 series, per series type.

From the project root:

```bash
export AIRFLOW_HOME="$PWD/data/airflow"
airflow standalone
```

- Start Airflow from the project root. The DAG imports `src`, and the query-count path is relative to the working directory.
- The tasks read `API_KEY` and `DB_*` from `.env` themselves (via `load_dotenv()`), so only `AIRFLOW_HOME` needs to be in the shell.
- `airflow.cfg`, `airflow.db*`, `logs/` and the generated password file land in `data/airflow/` and are git-ignored.

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

Each stage is a plain function that takes its inputs as arguments and returns its output; `main.py` passes the data between them. The refresh check reuses `extract()` and `transform_results()`, then compares against the database (`has_new_bls_data()` in `src/refresh/check_bls.py`); the Airflow DAG calls it before running `main.py`.

Built-in protections: daily query limit tracking in `data/outputs/runtime_output/query_count.csv` (resets each day), year and series-ID limits, HTTP retry and error logging, and input validation.

## Project layout

```
.
├── Makefile
├── requirements.txt
├── .env.example            # template; copy to .env
├── assets/                 # proposal and process diagram
├── data/
│   ├── airflow/
│   │   └── dags/dags.py    # refresh_bls_data DAG (everything else here is generated, git-ignored)
│   ├── inputs/             # national_series.csv, state_series.csv
│   ├── excel_files/        # source series and survey lists
│   └── outputs/            # git-ignored
│       ├── runtime_output/ # query_count.csv
│       ├── cleaning_op/    # cleaned notebook outputs
│       └── state_scrape_results/
└── src/
    ├── main.py             # entry point
    ├── api/                # extract.py, transform.py, load.py, strategies.py, api_types.py, tests/
    ├── db/                 # connect_db.py: SQLAlchemy engine from the DB_* variables
    ├── refresh/            # check_bls.py: does BLS have newer data than the DB?
    ├── scrape/             # state series ID scraper
    └── utils/              # arg_parser.py, parse_input.py, validate.py, shared.py (CSV reading)
```

Unit tests are the `*_unittest.py` files next to the code they test; `make test` discovers them.

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

- **`ValueError: One or more required database connection parameters are missing.`**: a `DB_*` variable is empty or unset. Check that `.env` is in the project root and every `DB_*` line has a value (`DB_USERNAME` and `DB_PASSWORD` are blank in the template).
- **`Queries may not exceed 500 within a day.`**: the daily limit was reached; wait for the next day or delete `data/outputs/runtime_output/query_count.csv` only if you know the real count is lower.
- **`connection refused` / `password authentication failed`**: check that Postgres is running and that `DB_HOST`, `DB_PORT`, `DB_USERNAME`, and `DB_PASSWORD` are correct.
- **`ModuleNotFoundError: No module named 'src'` when Airflow loads the DAG**: the project root is not on Python's path. Start Airflow from the project root, or add it to `PYTHONPATH`.
