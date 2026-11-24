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

from .api.api_bls import BlsApiCall, NationalSeriesStrategy, StateSeriesStrategy
from .utils.arg_parser import arg_router
from .utils.shared import read_file


def main() -> None:
    """
    Orchestrate the ETL pipeline by processing user input, validating parameters,
    and invoking the BlsApiCall class to extract, transform, and load BLS API data.

    Workflow:
        - Parse command-line arguments.
        - Configure logging.
        - Validate file path and year parameters.
        - Read the CSV file containing series IDs.
        - Instantiate the BlsApiCall object based on the series type.
        - Sequentially perform extraction, transformation, and loading.

    Raises:
        FileNotFoundError: If the CSV file path is invalid.
        ValueError: If year validation fails or required arguments are missing.
    """
    user_input = arg_router()
    request_id = str(uuid.uuid4())

    logger = logging.getLogger(__name__)
    logger = logging.LoggerAdapter(logger, {"request_id": request_id})
    logging.basicConfig(
        level=logging.DEBUG if user_input.get("verbose") else logging.INFO,
        format=f"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s | Request ID: {request_id}",
    )
    if user_input.get("silence"):
        logging.disable(logging.CRITICAL)

    try:
        series_input = read_file(user_input["path"])
        start_year = user_input["start_year"]
        series_type = user_input["series_type"]
        end_year = user_input["end_year"]
        series_count = user_input["series_count"]
        logger.debug("Successfully read CSV")
    except (csv.Error, PermissionError, ValueError, IOError, UnicodeDecodeError) as e:
        error_message = f"Error reading CSV file: {str(e)}"
        logger.error(error_message)
        print(error_message)
        sys.exit(1)

    try:
        if series_type == 1:
            logger.debug("Processing national series")
            strategy = NationalSeriesStrategy(series_input)
            api_engine = BlsApiCall(
                start_year,
                end_year,
                strategy,
                request_id,
                series_count=series_count,
            )
        else:
            logger.debug("Processing state series")
            strategy = StateSeriesStrategy(series_input)
            api_engine = BlsApiCall(
                start_year, end_year, strategy, request_id, series_count=series_count
            )
    except BaseException as e:
        logger.error(f"Error while instantiating BlsApiCall class: {e}", exc_info=True)
        raise

    try:
        logger.debug("Extracting data from BLS API")
        api_engine.extract()
        logger.debug("Successfully extracted data from BLS API")
    except BaseException as e:
        logger.error(f"Error while extracting data: {e}", exc_info=True)
        raise

    try:
        logger.debug("Transforming and cleaning data")
        api_engine.transform()
        logger.debug("Successfully transformed and cleaned data")
    except BaseException as e:
        logger.error(f"Error while transforming data: {e}", exc_info=True)
        raise

    try:
        logger.debug("Loading data into database")
        api_engine.load()
        logger.debug("Successfully loaded data into database")
    except BaseException as e:
        logger.error(f"Error while loading data: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
