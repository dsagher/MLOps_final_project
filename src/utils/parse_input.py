import uuid
import logging
import sys
import csv
from src.utils.shared import read_file
from src.utils.arg_parser import arg_router


def parse_user_input():
    user_input = arg_router()
    request_id = str(uuid.uuid4())
    logger = logging.getLogger(__name__)
    if user_input.get("silence"):
        logging.disable(logging.CRITICAL)

    try:
        series_input = read_file(user_input["path"])
        start_year = user_input["start_year"]
        series_type = user_input["series_type"]
        end_year = user_input["end_year"]
        series_count = user_input["series_count"]
        latest = user_input["latest"]
        logger.debug("Successfully read CSV")
    except (csv.Error, PermissionError, ValueError, IOError, UnicodeDecodeError) as e:
        error_message = f"Error reading CSV file: {str(e)}"
        logger.error(error_message)
        print(error_message)
        sys.exit(1)

    return {
        "user_input": user_input,
        "request_id": request_id,
        "series_input": series_input,
        "start_year": start_year,
        "series_type": series_type,
        "end_year": end_year,
        "series_count": series_count,
        "latest": latest,
    }
