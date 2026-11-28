from sqlalchemy import Table, MetaData, select
from sqlalchemy.exc import NoSuchTableError
from src.api.extract import extract
import logging
import uuid

from dotenv import load_dotenv

from src.api.strategies import NationalSeriesStrategy, StateSeriesStrategy
from src.api.transform import transform_results
from src.db.connect_db import get_engine
from src.utils.parse_input import parse_user_input
from src.utils.shared import read_file


def get_recent_survey_results_db(connection, table_name: str):
    try:
        table = Table(table_name, MetaData(), autoload_with=connection)
    except NoSuchTableError:
        # First run: main() creates the tables, so an empty DB means everything is new.
        logging.info("Table %s does not exist yet", table_name)
        return []
    series_id = table.c.series_id
    year = table.c.year
    period = table.c.period

    # DISTINCT ON (series_id) + ORDER BY ... DESC keeps the newest row per series.
    select_stmt = (
        select(series_id, year, period)
        .distinct(series_id)
        .order_by(series_id, year.desc(), period.desc())
    )

    logging.info("Executing select statement: %s", select_stmt)
    result = connection.execute(select_stmt).fetchall()
    logging.info("Retrieved results from the database: %s", result)
    return result


def get_recent_survey_results_bls(strategy, request_id, latest=True, series_count=""):
    logging.info(
        "Fetching recent survey results from BLS API with strategy: %s", strategy
    )
    response = extract(
        strategy=strategy,
        request_id=request_id,
        latest=latest,
        series_count=series_count,
    )
    response_transformed = transform_results(response)
    if not response_transformed:
        raise ValueError("No recent survey results returned from the BLS API.")
    return response_transformed


def compare_results(db_results, bls_results) -> bool:
    """True only if every series BLS returned has a newer data point than the DB (ready for the ML model)."""
    db_latest = {row[0]: (row[1], row[2]) for row in db_results}
    bls_latest: dict = {}
    for row in bls_results:
        key = (row["year"], row["period"])
        bls_latest[row["series_id"]] = max(bls_latest.get(row["series_id"], key), key)

    return bool(bls_latest) and all(
        latest != db_latest.get(series_id) for series_id, latest in bls_latest.items()
    )


def has_new_bls_data(
    path: str, series_type: int = 1, series_count: int | str = ""
) -> bool:
    """Whether BLS has newer data than the DB for every series in the CSV (1 = national, 2 = state)."""
    load_dotenv()
    strategy_cls = NationalSeriesStrategy if series_type == 1 else StateSeriesStrategy
    strategy = strategy_cls(read_file(path))
    with get_engine().connect() as connection:
        db_results = get_recent_survey_results_db(
            connection, strategy.get_series_tables()[1]
        )
    bls_results = get_recent_survey_results_bls(
        strategy, str(uuid.uuid4()), series_count=series_count
    )
    return compare_results(db_results, bls_results)


if __name__ == "__main__":
    parsed_input = parse_user_input()
    comparison = has_new_bls_data(
        parsed_input["user_input"]["path"],
        parsed_input["series_type"],
        parsed_input["series_count"],
    )
    print(f"Comparison result: {comparison}")
