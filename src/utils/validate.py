from typing import Tuple, Union
import os
import datetime as dt
import logging

logger = logging.getLogger(__name__)


def validate_path(path: str) -> Tuple[bool, Union[str, None]]:
    """
    Check if the provided file path exists.

    Args:
        path (str): The file path to check.

    Returns:
        Tuple[bool, Union[str, None]]: A tuple containing a boolean indicating validity,
        and an error message if invalid.
    """

    if os.path.exists(path):
        return True, None
    else:
        return False, "Path not found."


def validate_years(start_year: int, end_year: int) -> Tuple[bool, Union[str, None]]:
    """
    Validate the start and end years for the data extraction.

    Conditions:
        - Both years must be positive integers.
        - The end year cannot be in the future.
        - The start year must precede the end year.
        - The range between years cannot exceed 20 years.

    Args:
        start_year (int): The starting year.
        end_year (int): The ending year.

    Returns:
        Tuple[bool, Union[str, None]]: A tuple with a boolean indicating validity and an error message if invalid.
    """
    this_year = int(dt.datetime.strftime(dt.datetime.now(), "%Y"))
    try:
        start_year = int(start_year)
        end_year = int(end_year)
    except ValueError:
        return False, "Error: Years must be integers."
    if start_year <= 0 or end_year <= 0:
        logger.error("Error: Years must be positive integers.")
        return False, "Error: Years must be positive integers."
    elif end_year > this_year:
        logger.error(
            f"Error: End year cannot be in the future (current year: {this_year})."
        )
        return (
            False,
            f"Error: End year cannot be in the future (current year: {this_year}).",
        )
    elif start_year > end_year:
        logger.error("Error: Start year must be before end year.")
        return False, "Error: Start year must be before end year."
    if end_year - start_year + 1 > 20:
        logger.error("Error: Year range cannot exceed 20 years due to API limitations.")
        return False, "Error: Year range cannot exceed 20 years due to API limitations."
    else:
        logger.info("Year validation passed.")
        return True, None
