"""==========================================================================================
    Title:       BLS API ETL Module
    File:        api_bls.py
    Author:      Dan Sagher
    Date:        03/11/2025
    Description:
        This module implements the extraction, transformation, and loading (ETL) logic
        for interacting with the Bureau of Labor Statistics (BLS) API. It defines the
        BlsApiCall class which manages API requests, response handling, data cleaning,
        and database insertion using PostgreSQL via SQLAlchemy.

    Dependencies:


    API Notes:
        - BLS API Version 2.0 (10/16/2014) requires user registration with email and organization.
        - Supports up to 20 years of data for a maximum of 50 series per query, with a daily limit of 500 queries.
        - Provides additional calculations such as net and percent changes, annual averages, and limited series catalog info.
==========================================================================================
"""

import copy
import csv
import datetime
import json
import logging
import os
import re
import time
from typing import List, cast
from http import HTTPStatus
from itertools import batched

from dotenv import load_dotenv
import requests
from requests.exceptions import HTTPError

from src.api.api_types import DataDict, Series, DataContainer, BLSResponse
from src.api.strategies import (
    SeriesStrategy,
    NationalSeriesStrategy,
    StateSeriesStrategy,
)

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Boolean,
    Float,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)


def _to_snake_case(key: str) -> str:
    """Convert camelCase keys (e.g. 'seriesID', 'periodName') to PostgreSQL-style snake_case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key).lower()


class BlsApiCall:
    """
    Manages the ETL process for retrieving data from the BLS API and loading it into a PostgreSQL database.

    Parameters:
        start_year (int): Desired starting year for the query.
        end_year (int): Desired ending year for the query.
        strategy (SeriesStrategy): Strategy for handling national or state series.
        series_count (int or str, optional): Maximum number of series IDs to process. Defaults to all provided.
    """

    os.makedirs("data/outputs/runtime_output", exist_ok=True)
    query_count_file = "data/outputs/runtime_output/query_count.csv"

    def __init__(
        self,
        start_year: int,
        end_year: int,
        strategy: SeriesStrategy,
        request_id: str,
        series_count: int | str = "",
    ):
        self.start_year = start_year
        self.end_year = end_year
        self.strategy = strategy
        self.series_count = strategy.get_series_count(series_count)
        self.request_id = request_id

        load_dotenv()

    def _count_query(self) -> int:
        """
        Record one API request in the daily counter file and return today's count.

        The CSV has a "date,count" header and one row. A missing, corrupt, or old-day
        file starts a new count at today's date.

        Raises:
            Exception: If the daily query limit (500 queries) is already used up.
        """
        today = datetime.date.today().isoformat()
        count = 0
        try:
            with open(self.query_count_file, newline="") as file:
                row = next(csv.DictReader(file))
            if row["date"] == today:
                count = int(row["count"])
        except (FileNotFoundError, StopIteration, KeyError, ValueError):
            pass

        if count >= 500:
            logger.critical("Queries may not exceed 500 within a day.")
            raise Exception("Queries may not exceed 500 within a day.")

        with open(self.query_count_file, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["date", "count"])
            writer.writerow([today, count + 1])
        return count + 1

    def bls_request(self, series: list, start_year: str, end_year: str) -> BLSResponse:
        """
        Sends a POST request to the BLS API for the specified series and date range.

        Parameters:
            series (list): List of series IDs to query.
            start_year (str): Desired start year.
            end_year (str): Desired end year.

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
        year_range = int(end_year) - int(start_year) + 1
        headers = {"Content-Type": "application/json"}
        payload = json.dumps(
            {
                "seriesid": series,
                "startyear": start_year,
                "endyear": end_year,
                "registrationKey": os.getenv("API_KEY"),
            }
        )

        if len(series) > SERIES_LIMIT:
            raise ValueError("Can only take up to 50 seriesID's per query.")
        elif year_range > YEAR_LIMIT:
            raise ValueError("Can only take in up to 20 years per query.")

        for attempt in range(1, RETRIES + 1):
            query_count = self._count_query()

            try:
                response = requests.post(
                    URL_ENDPOINT,
                    data=payload,
                    headers=headers,
                    timeout=TIMEOUT_SECONDS,
                )
                self.strategy.log_request(
                    query_count,
                    len(series),
                    start_year,
                    end_year,
                    self.request_id,
                )

                if response.status_code != HTTPStatus.OK.value:
                    raise HTTPError(response=response.status_code)
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
                            self.request_id,
                        )
                        return response_json

            except HTTPError as e:
                if e.response in RETRY_CODES:
                    final_error = e.response
                    logger.warning("HTTP Error: %s Attempt: %s", e.response, attempt)
                    time.sleep(2**attempt)
                    continue
                else:
                    final_error = e.response
                    logger.critical("HTTP Error: %s", e.response)
                    raise HTTPError(f"HTTP Error: {e.response}")

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

    def extract(self) -> None:
        """
        Extracts data from the BLS API in batches of up to 50 series IDs.

        The method iterates over the list of series IDs in batches, sends API requests via
        bls_request, and stores the JSON responses.
        """
        BATCH_SIZE = 50
        INPUT_AMOUNT: int = self.series_count
        start_year = str(self.start_year)
        end_year = str(self.end_year)
        self.lst_of_queries: list[BLSResponse] = []

        series_id_lst = [i.get("seriesID") for i in self.strategy.get_series_list()][
            :INPUT_AMOUNT
        ]
        if not series_id_lst or not all(series_id_lst):
            raise ValueError(
                "No series IDs to query: the CSV needs a 'seriesID' column with a value in every row."
            )

        batch_progress = 0
        for batch_tuple in batched(series_id_lst, BATCH_SIZE):
            batch = list(batch_tuple)
            batch_size = len(batch)
            batch_progress += batch_size
            total_size = len(series_id_lst)

            logger.debug(f"Extracting batch of size: {batch_progress}")
            logger.debug(
                f"Progress: {batch_progress}/{total_size} {(batch_progress/total_size):.0%}"
            )

            result = self.bls_request(batch, start_year, end_year)
            self.lst_of_queries.append(result)
            time.sleep(0.25)

        logger.info(f"Successfully extracted {total_size} IDs")

    def _log_message(self, messages: list[str]) -> None:
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

    def _convert_adjusted(self, lst: list[dict]) -> list[dict]:
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

    def transform(self) -> None:
        """
        Transforms the extracted JSON responses into a clean, deduplicated dataset.

        This involves:
            - Logging any warnings from the API messages.
            - Flattening nested JSON data into a list of dictionaries.
            - Removing duplicates.
            - Processing series metadata to flag seasonal adjustments.
        """
        self.final_dct_lst: list[DataDict] = []

        for response in self.lst_of_queries:
            results: DataContainer = response["Results"]
            series_lst: List[Series] = results["series"]

            if response["message"] != []:
                message: list[str] = response["message"]
                self._log_message(message)

            for series in series_lst:
                series_id: str = series["seriesID"]

                for raw_data_point in series["data"]:
                    data_point = {
                        _to_snake_case(k): v for k, v in raw_data_point.items()
                    }
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
                    self.final_dct_lst.append(data_dict)

        try:
            series = self._convert_adjusted(
                copy.deepcopy(self.strategy.get_series_list())
            )
            self.series = [{_to_snake_case(k): v for k, v in s.items()} for s in series]

        except copy.Error as e:
            logging.error(f"Error copying series lists: {e}")
            raise

    def load(self) -> None:
        """
        Loads the transformed data into the PostgreSQL database using SQLAlchemy.

        Reads database configuration from environmental variables, creates tables for series
        and results if they don't exist, and performs upsert operations to avoid duplicates.
        """

        driver = os.getenv("DB_DRIVER")

        if not driver:
            raise ValueError(
                "Database driver not specified in environment variable 'DB_DRIVER'"
            )
        username = os.getenv("DB_USERNAME")
        if not username:
            raise ValueError(
                "Database username not specified in environment variable 'DB_USERNAME'"
            )

        password = os.getenv("DB_PASSWORD")
        if not password:
            raise ValueError(
                "Database password not specified in environment variable 'DB_PASSWORD'"
            )
        host = os.getenv("DB_HOST")
        if not host:
            raise ValueError(
                "Database host not specified in environment variable 'DB_HOST'"
            )
        database = os.getenv("DB_DATABASE")
        if not database:
            raise ValueError(
                "Database name not specified in environment variable 'DB_DATABASE'"
            )
        port = int(os.getenv("DB_PORT")) if os.getenv("DB_PORT") else None  # type: ignore
        if not port:
            raise ValueError(
                "Database port not specified in environment variable 'DB_PORT'"
            )

        url_object = URL.create(
            drivername=driver,
            username=username,
            password=password,
            host=host,
            database=database,
            port=port,
        )
        engine = create_engine(url_object, logging_name="SQLAlchemy")
        metadata = MetaData()

        series_table_name, results_table_name = self.strategy.get_series_tables()

        # Determine columns based on strategy type
        if isinstance(self.strategy, StateSeriesStrategy):
            series_columns = [
                Column("series_id", String, primary_key=True),
                Column("series", String, nullable=False),
                Column("state", String, nullable=False),
                Column("survey", String),
                Column("is_adjusted", Boolean),
            ]
        else:  # NationalSeriesStrategy
            series_columns = [
                Column("series_id", String, primary_key=True),
                Column("series", String, nullable=False),
                Column("survey", String),
                Column("is_adjusted", Boolean),
            ]

        series_table = Table(series_table_name, metadata, *series_columns)
        results_table = Table(
            results_table_name,
            metadata,
            Column(
                "series_id",
                String,
                ForeignKey(f"{series_table_name}.series_id"),
                primary_key=True,
            ),
            Column("year", Integer, nullable=False, primary_key=True),
            Column("period", String, nullable=False, primary_key=True),
            Column("period_name", String, nullable=False),
            Column("value", Float),
            Column("footnotes", String),
        )

        metadata.create_all(bind=engine, checkfirst=True)

        series_stmt = insert(series_table).values(self.series).on_conflict_do_nothing()

        results_stmt = (
            insert(results_table).values(self.final_dct_lst).on_conflict_do_nothing()
        )

        with engine.connect() as connect:
            connect.execute(series_stmt)
            connect.execute(results_stmt)
            connect.commit()
