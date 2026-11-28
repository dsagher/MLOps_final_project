"""==========================================================================================
    Title:       BLS API ETL Pipeline
    File:        main.py
    Author:      Dan Sagher
    Date:        03/11/2025
    Description:
        This script implements an ETL (Extract, Transform, Load) pipeline that interacts
        with the Bureau of Labor Statistics (BLS) API. It reads a CSV file containing series
        IDs, extracts data from the API, transforms the data into a clean format, and loads
        it into a PostgreSQL database.
==========================================================================================
"""

import logging
import sys
import csv
import uuid

from dotenv import load_dotenv

from src.utils.parse_input import parse_user_input

from .api.extract import extract
from .api.load import load
from .api.strategies import NationalSeriesStrategy, StateSeriesStrategy
from .api.transform import transform_results, transform_series
from .utils.arg_parser import arg_router
from .utils.shared import read_file


def main() -> None:
    """
    Orchestrate the ETL pipeline by processing user input, validating parameters,
    and passing data through the extract, transform, and load stages.

    Workflow:
        - Parse command-line arguments.
        - Configure logging.
        - Validate file path and year parameters.
        - Read the CSV file containing series IDs.
        - Pick the national or state series strategy.
        - Extract raw responses, transform them into rows, and load the rows.

    Raises:
        FileNotFoundError: If the CSV file path is invalid.
        ValueError: If year validation fails or required arguments are missing.
    """
    load_dotenv()
    parsed_input = parse_user_input()
    user_input = parsed_input["user_input"]
    request_id = parsed_input["request_id"]
    series_input = parsed_input["series_input"]
    start_year = parsed_input["start_year"]
    series_type = parsed_input["series_type"]
    end_year = parsed_input["end_year"]
    series_count = parsed_input["series_count"]
    latest = parsed_input["latest"]

    logger = logging.getLogger(__name__)
    logger = logging.LoggerAdapter(logger, {"request_id": request_id})
    logging.basicConfig(
        level=logging.DEBUG if user_input.get("verbose") else logging.INFO,
        format=f"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s | Request ID: {request_id}",
    )

    if series_type == 1:
        logger.debug("Processing national series")
        strategy = NationalSeriesStrategy(series_input)
    else:
        logger.debug("Processing state series")
        strategy = StateSeriesStrategy(series_input)

    try:
        logger.debug("Extracting data from BLS API")
        responses = extract(
            strategy,
            request_id,
            start_year=start_year,
            end_year=end_year,
            latest=latest,
            series_count=series_count,
        )
        logger.debug("Successfully extracted data from BLS API")
    except BaseException as e:
        logger.error(f"Error while extracting data: {e}", exc_info=True)
        raise

    try:
        logger.debug("Transforming and cleaning data")
        results = transform_results(responses)
        series = transform_series(strategy)
        logger.debug("Successfully transformed and cleaned data")
    except BaseException as e:
        logger.error(f"Error while transforming data: {e}", exc_info=True)
        raise

    try:
        logger.debug("Loading data into database")
        load(strategy, series, results)
        logger.debug("Successfully loaded data into database")
    except BaseException as e:
        logger.error(f"Error while loading data: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
