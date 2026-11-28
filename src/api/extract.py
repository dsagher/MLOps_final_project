"""==========================================================================================
    Title:       BLS API Extract
    File:        extract.py
    Author:      Dan Sagher
    Description:
        Extract stage of the BLS ETL pipeline: sends requests to the Bureau of Labor
        Statistics API and returns the raw JSON responses.

    API Notes:
        - BLS API Version 2.0 (10/16/2014) requires user registration with email and organization.
        - Supports up to 20 years of data for a maximum of 50 series per query, with a daily limit of 500 queries.
        - Provides additional calculations such as net and percent changes, annual averages, and limited series catalog info.
==========================================================================================
"""

import csv
import datetime
import json
import logging
import os
import time
from http import HTTPStatus
from itertools import batched

import requests
from requests.exceptions import HTTPError

from src.api.api_types import BLSResponse
from src.api.strategies import SeriesStrategy

logger = logging.getLogger(__name__)

QUERY_COUNT_FILE = "data/outputs/runtime_output/query_count.csv"


def count_query() -> int:
    """
    Record one API request in the daily counter file and return today's count.

    The CSV has a "date,count" header and one row. A missing, corrupt, or old-day
    file starts a new count at today's date.

    Raises:
        Exception: If the daily query limit (500 queries) is already used up.
    """
    os.makedirs(os.path.dirname(QUERY_COUNT_FILE), exist_ok=True)
    today = datetime.date.today().isoformat()
    count = 0
    try:
        with open(QUERY_COUNT_FILE, newline="") as file:
            row = next(csv.DictReader(file))
        if row["date"] == today:
            count = int(row["count"])
    except (FileNotFoundError, StopIteration, KeyError, ValueError):
        pass

    if count >= 500:
        logger.critical("Queries may not exceed 500 within a day.")
        raise Exception("Queries may not exceed 500 within a day.")

    with open(QUERY_COUNT_FILE, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "count"])
        writer.writerow([today, count + 1])
    return count + 1


def bls_request(
    series: list,
    strategy: SeriesStrategy,
    request_id: str,
    start_year: str = "",
    end_year: str = "",
    latest: bool = False,
) -> BLSResponse:
    """
    Sends a POST request to the BLS API for the specified series and date range.

    Parameters:
        series (list): List of series IDs to query.
        strategy (SeriesStrategy): Used to log the request for national or state series.
        request_id (str): Identifier included in log messages.
        start_year (str): Desired start year. Ignored when latest is True.
        end_year (str): Desired end year. Ignored when latest is True.
        latest (bool): Request only the most recent data point for each series.

    Returns:
        BLSResponse: The JSON response from the API.

    Raises:
        ValueError: If more than 50 series IDs are provided or if the year range exceeds 20.
        HTTPError: If an HTTP error occurs (with retries for specific status codes).
        Exception: If the API response status is not "REQUEST_SUCCEEDED".
    """
    URL_ENDPOINT = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    RETRIES = 3
    TIMEOUT_SECONDS = 30
    YEAR_LIMIT = 20
    SERIES_LIMIT = 50
    RETRY_CODES: list = [
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    ]
    year_range = 0
    params: dict = {}
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("API_KEY")

    if not latest:
        year_range = int(end_year) - int(start_year) + 1
        payload = json.dumps(
            {
                "seriesid": series,
                "startyear": start_year,
                "endyear": end_year,
                "registrationKey": api_key,
            }
        )
    else:
        params["latest"] = True
        payload = json.dumps(
            {
                "seriesid": series,
                "registrationKey": api_key,
            }
        )

    if len(series) > SERIES_LIMIT:
        raise ValueError("Can only take up to 50 seriesID's per query.")
    elif year_range > YEAR_LIMIT:
        raise ValueError("Can only take in up to 20 years per query.")

    for attempt in range(1, RETRIES + 1):
        query_count = count_query()
        response_json = None

        try:
            response = requests.post(
                URL_ENDPOINT,
                data=payload,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                params=params,
            )
            strategy.log_request(
                query_count,
                len(series),
                start_year,
                end_year,
                request_id,
            )

            if response.status_code != HTTPStatus.OK.value:
                raise HTTPError(response=response.status_code, request=response.reason)
            elif response.status_code == HTTPStatus.OK.value:
                response_json = response.json()
                response_status = response_json["status"]

                if response_status != "REQUEST_SUCCEEDED":
                    logger.warning(
                        "Request #%s: Status Code: %s Response: %s",
                        query_count,
                        response.status_code,
                        response_status,
                    )
                    raise Exception
                else:
                    logger.info(
                        "Request #%s: Status Code: %s Response: %s Request ID: %s",
                        query_count,
                        response.status_code,
                        response_status,
                        request_id,
                    )
                    return response_json

        except HTTPError as e:
            if e.response in RETRY_CODES:
                final_error = str(e.response) + " " + str(e.request)
                logger.warning("HTTP Error: %s Attempt: %s", e.response, attempt)
                time.sleep(2**attempt)
                continue
            else:
                final_error = str(e.response) + " " + str(e.request)
                logger.critical("HTTP Error: %s", final_error)
                raise HTTPError(f"HTTP Error: {final_error}")

        except requests.RequestException as e:
            final_error = e
            logger.warning("Request failed: %s Attempt: %s", e, attempt)
            time.sleep(2**attempt)
            continue

        except Exception as e:
            logger.critical(
                'Response Status from API is not "REQUEST_SUCCEEDED": %s',
                response_json,
            )
            raise Exception(
                f'Response Status from API is not "REQUEST_SUCCEEDED": {response_json}'
            )

    logger.critical("API Error: %s", final_error)
    raise Exception(f"API Error: {final_error}")


def extract(
    strategy: SeriesStrategy,
    request_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    latest: bool = False,
    series_count: int | str = "",
) -> list[BLSResponse]:
    """
    Extracts data from the BLS API in batches of up to 50 series IDs.

    Iterates over the strategy's series IDs in batches, sends each batch via
    bls_request, and returns the JSON responses in order.

    Raises:
        ValueError: If the series list is empty or any row has no 'seriesID'.
    """
    BATCH_SIZE = 50
    start, end = ("", "") if latest else (str(start_year), str(end_year))

    series_id_lst = [i.get("seriesID") for i in strategy.get_series_list()][
        : strategy.get_series_count(series_count)
    ]
    if not series_id_lst or not all(series_id_lst):
        raise ValueError(
            "No series IDs to query: the CSV needs a 'seriesID' column with a value in every row."
        )

    total_size = len(series_id_lst)
    batch_progress = 0
    responses: list[BLSResponse] = []
    for batch_tuple in batched(series_id_lst, BATCH_SIZE):
        batch = list(batch_tuple)
        batch_progress += len(batch)

        logger.debug(f"Extracting batch of size: {batch_progress}")
        logger.debug(
            f"Progress: {batch_progress}/{total_size} {(batch_progress/total_size):.0%}"
        )

        responses.append(bls_request(batch, strategy, request_id, start, end, latest))
        time.sleep(0.25)

    logger.info(f"Successfully extracted {total_size} IDs")
    return responses
