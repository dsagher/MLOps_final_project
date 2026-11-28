"""==========================================================================================
    Title:       BLS API Transform
    File:        transform.py
    Author:      Dan Sagher
    Description:
        Transform stage of the BLS ETL pipeline: turns raw BLS API responses and the
        series list into clean rows that match the PostgreSQL columns.
==========================================================================================
"""

import copy
import logging
import re
from typing import List, cast

from src.api.api_types import DataContainer, DataDict, BLSResponse, Series
from src.api.strategies import SeriesStrategy

logger = logging.getLogger(__name__)


def to_snake_case(key: str) -> str:
    """Convert camelCase keys (e.g. 'seriesID', 'periodName') to PostgreSQL-style snake_case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key).lower()


def log_messages(messages: list[str]) -> None:
    """
    Logs warning messages extracted from the API response when data for a given series/year is missing.

    Parameters:
        messages (list[str]): List of messages from the API response.
    """
    for message in messages:
        year_reg_match = re.fullmatch(
            r"No Data Available for Series (\w+) Year: (\d\d\d\d)", message
        )
        no_series_reg_match = re.fullmatch(
            r"Series does not exist for Series (\w+)", message
        )
        if year_reg_match:
            series_id, year = year_reg_match.group(1, 2)
            msg = "No Data Available"
            entry = {"message": msg, "series_id": series_id, "year": year}
            logger.warning(entry)
        elif no_series_reg_match:
            series_id = no_series_reg_match.group(1)
            msg = "Series does not exist"
            entry = {"message": msg, "series_id": series_id}
            logger.warning(entry)
        else:
            logger.warning(message)


def convert_adjusted(lst: list[dict]) -> list[dict]:
    """
    Processes a list of series dictionaries to:
        - Add a boolean indicating if a series is seasonally adjusted.
        - Remove adjustment phrases from the series name.

    Parameters:
        lst (list[dict]): List of series dictionaries.

    Returns:
        list[dict]: The updated list with an 'is_adjusted' flag and cleaned series names.
    """
    adjusted = ", seasonally adjusted"
    not_adjusted = ", not seasonally adjusted"

    def remove_terms(str):
        text_lower = str.lower()
        index1 = text_lower.find(adjusted)
        index2 = text_lower.find(not_adjusted)
        if index1 != -1:
            str = str[:index1]
        elif index2 != -1:
            str = str[:index2]
        return str

    for dct in lst:
        if dct["series"].lower().endswith(adjusted):
            dct["is_adjusted"] = True
            dct["series"] = remove_terms(dct["series"])
        elif dct["series"].lower().endswith(not_adjusted):
            dct["is_adjusted"] = False
            dct["series"] = remove_terms(dct["series"])
        else:
            dct["is_adjusted"] = None

    return lst


def transform_results(responses: list[BLSResponse]) -> list[DataDict]:
    """
    Flattens raw BLS API responses into one row per series data point.

    Logs any warnings from the API messages, converts keys to snake_case, and
    parses year and value ("-" becomes None).
    """
    results: list[DataDict] = []

    for response in responses:
        container: DataContainer = response["Results"]
        series_lst: List[Series] = container["series"]

        if response["message"] != []:
            message: list[str] = response["message"]
            log_messages(message)

        for series in series_lst:
            series_id: str = series["seriesID"]

            for raw_data_point in series["data"]:
                data_point = {to_snake_case(k): v for k, v in raw_data_point.items()}
                year = cast(str, data_point["year"])
                period = cast(str, data_point["period"])
                period_name = cast(str, data_point["period_name"])
                value = cast(str, data_point["value"])
                footnotes = data_point["footnotes"]
                data_dict: DataDict = {
                    "series_id": series_id,
                    "year": int(year),
                    "period": period,
                    "period_name": period_name,
                    "value": (float(value) if value != "-" else None),
                    "footnotes": (
                        str(footnotes) if str(footnotes) != str([{}]) else None
                    ),
                }
                results.append(data_dict)

    return results


def transform_series(strategy: SeriesStrategy) -> list[dict]:
    """
    Builds the series dimension rows from the strategy's series list: flags
    seasonal adjustment, strips it from the name, and converts keys to snake_case.
    """
    try:
        series = convert_adjusted(copy.deepcopy(strategy.get_series_list()))
    except copy.Error as e:
        logger.error(f"Error copying series lists: {e}")
        raise

    return [{to_snake_case(k): v for k, v in s.items()} for s in series]
