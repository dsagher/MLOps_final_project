"""Unit tests for BlsApiCall. All HTTP calls are mocked; the query-count file is cleaned up."""

import datetime
import json
import os
import tempfile
import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError, HTTPError

from src.api.api_bls import BlsApiCall, StateSeriesStrategy

MODULE = "src.api.api_bls"
SUCCESS = {"status": "REQUEST_SUCCEEDED"}


def mock_response(status_code=HTTPStatus.OK, json_data=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


class TestBlsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state_series = [
            {
                "seriesID": "123ABC",
                "series": "Always be Cool",
                "state": "MI",
                "survey": "ABC",
                "is_adjusted": "False",
            },
            {
                "seriesID": "124ABC",
                "series": "Always be Cooler",
                "state": "MI",
                "survey": "ABC",
                "is_adjusted": "False",
            },
        ]
        cls.series_ids = [s["seriesID"] for s in cls.state_series]
        cls.api_call = BlsApiCall(
            2000, 2005, StateSeriesStrategy(cls.state_series), "test-request-id"
        )

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.query_count_file = os.path.join(tmp.name, "query_count.csv")
        patcher = patch.object(BlsApiCall, "query_count_file", self.query_count_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch(f"{MODULE}.logger.info")
    @patch(f"{MODULE}.requests.post")
    def test_bls_request(self, mocked_post, mocked_log):
        mocked_post.return_value = mock_response(json_data=SUCCESS)
        payload = json.dumps(
            {
                "seriesid": self.series_ids,
                "startyear": 2005,
                "endyear": 2007,
                "registrationKey": os.getenv("BLS_API_KEY"),
            }
        )

        result = self.api_call.bls_request(self.series_ids, 2005, 2007)

        mocked_post.assert_called_once_with(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        self.assertEqual(result, SUCCESS)
        self.assertEqual(mocked_log.call_count, 1)

    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.requests.post")
    def test_bls_request_limit(self, mocked_post, mocked_log):
        for _ in range(500):
            self.api_call._count_query()

        with self.assertRaises(Exception) as e:
            self.api_call.bls_request(self.series_ids, 2005, 2007)

        self.assertEqual(str(e.exception), "Queries may not exceed 500 within a day.")
        mocked_log.assert_called_once()
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.requests.post")
    def test_bls_year_limit(self, mocked_post):
        with self.assertRaises(ValueError) as e:
            self.api_call.bls_request(self.series_ids, 2000, 2025)
        self.assertEqual(str(e.exception), "Can only take in up to 20 years per query.")
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.requests.post")
    def test_bls_id_limit(self, mocked_post):
        with self.assertRaises(ValueError) as e:
            self.api_call.bls_request(list(range(60)), 2000, 2005)
        self.assertEqual(
            str(e.exception), "Can only take up to 50 seriesID's per query."
        )
        mocked_post.assert_not_called()

    @patch("src.api.strategies.logger.info")
    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.requests.post")
    def test_bls_bad_request(self, mocked_post, mocked_critical, mocked_info):
        mocked_post.return_value = mock_response(HTTPStatus.BAD_REQUEST)

        with self.assertRaises(HTTPError) as e:
            self.api_call.bls_request(self.series_ids, 2000, 2005)

        self.assertEqual(str(e.exception), f"HTTP Error: {HTTPStatus.BAD_REQUEST.value}")
        mocked_critical.assert_called_once()
        mocked_post.assert_called_once()
        mocked_info.assert_called_once()

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.logger.warning")
    @patch(f"{MODULE}.requests.post")
    def test_http_error_retry(
        self, mocked_post, mocked_warning, mocked_critical, mocked_sleep
    ):
        mocked_post.return_value = mock_response(HTTPStatus.INTERNAL_SERVER_ERROR)

        with self.assertRaises(Exception) as e:
            self.api_call.bls_request(self.series_ids, 2000, 2002)

        self.assertEqual(
            str(e.exception), f"API Error: {HTTPStatus.INTERNAL_SERVER_ERROR.value}"
        )
        self.assertEqual(mocked_critical.call_count, 1)
        self.assertEqual(mocked_warning.call_count, 3)
        self.assertEqual(mocked_post.call_count, 3)
        self.assertEqual(mocked_sleep.call_count, 3)

    def test_bls_reset(self):
        for last_day in (
            datetime.date.today() - datetime.timedelta(days=1),
            datetime.date.today() - datetime.timedelta(days=31),
        ):
            with self.subTest(last_day=last_day):
                with open(self.query_count_file, "w") as file:
                    file.write(f"date,count\n{last_day.isoformat()},500\n")

                self.assertEqual(self.api_call._count_query(), 1)

                with open(self.query_count_file, newline="") as file:
                    self.assertEqual(
                        file.read(),
                        f"date,count\r\n{datetime.date.today().isoformat()},1\r\n",
                    )

    def test_count_survives_corrupt_file(self):
        with open(self.query_count_file, "w") as file:
            file.write("")

        self.assertEqual(self.api_call._count_query(), 1)

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.requests.post")
    def test_network_error_retried(self, mocked_post, mocked_sleep):
        mocked_post.side_effect = [ConnectionError(), mock_response(json_data=SUCCESS)]

        result = self.api_call.bls_request(self.series_ids, 2000, 2005)

        self.assertEqual(result, SUCCESS)
        self.assertEqual(mocked_post.call_count, 2)
        mocked_sleep.assert_called_once()

    def test_extract_rejects_missing_series_ids(self):
        call = BlsApiCall(
            2000, 2005, StateSeriesStrategy([{"series_id": "123ABC"}]), "test-id"
        )

        with self.assertRaises(ValueError):
            call.extract()

    @patch(f"{MODULE}.requests.post")
    def test_bls_year_limit_inclusive(self, mocked_post):
        with self.assertRaises(ValueError):
            self.api_call.bls_request(self.series_ids, 2000, 2020)
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.BlsApiCall._log_message")
    @patch(f"{MODULE}.requests.post")
    def test_bls_log_function(self, mocked_post, mocked_log_function, _sleep):
        mocked_post.return_value = mock_response(
            json_data={
                "status": "REQUEST_SUCCEEDED",
                "responseTime": 225,
                "message": ["No Data Available for Series 123456 Year: 1972"],
                "Results": {"series": [{"seriesID": "123ABC", "data": []}]},
            }
        )

        self.api_call.extract()
        self.api_call.transform()

        mocked_log_function.assert_called_once_with(
            ["No Data Available for Series 123456 Year: 1972"]
        )

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.requests.post")
    def test_transform_snake_case_keys(self, mocked_post, _sleep):
        data_point = {
            "year": "2005",
            "period": "M01",
            "periodName": "January",
            "value": "1.5",
            "footnotes": [{}],
        }
        mocked_post.return_value = mock_response(
            json_data={
                "status": "REQUEST_SUCCEEDED",
                "message": [],
                "Results": {"series": [{"seriesID": "123ABC", "data": [data_point]}]},
            }
        )

        self.api_call.extract()
        self.api_call.transform()

        self.assertEqual(len(self.api_call.final_dct_lst), 1)
        row = self.api_call.final_dct_lst[0]
        self.assertEqual(
            set(row), {"series_id", "year", "period", "period_name", "value", "footnotes"}
        )
        self.assertEqual(
            (row["series_id"], row["year"], row["period_name"], row["value"]),
            ("123ABC", 2005, "January", 1.5),
        )
        self.assertEqual(
            set(self.api_call.series[0]),
            {"series_id", "series", "state", "survey", "is_adjusted"},
        )

    def test_transform_values_and_adjusted_flags(self):
        series = [
            {"seriesID": "A", "series": "Jobs, seasonally adjusted", "state": "MI", "survey": "X"},
            {"seriesID": "B", "series": "Jobs, not seasonally adjusted", "state": "MI", "survey": "X"},
            {"seriesID": "C", "series": "Jobs", "state": "MI", "survey": "X"},
        ]
        call = BlsApiCall(2000, 2005, StateSeriesStrategy(series), "test-id")
        preliminary = [{"code": "P", "text": "Preliminary"}]
        call.lst_of_queries = [
            {
                "status": "REQUEST_SUCCEEDED",
                "message": [],
                "Results": {
                    "series": [
                        {
                            "seriesID": "A",
                            "data": [
                                {"year": "2005", "period": "M01", "periodName": "January", "value": "-", "footnotes": [{}]},
                                {"year": "2005", "period": "M02", "periodName": "February", "value": "2.5", "footnotes": preliminary},
                            ],
                        }
                    ]
                },
            }
        ]

        call.transform()

        missing, revised = call.final_dct_lst
        self.assertIsNone(missing["value"])
        self.assertIsNone(missing["footnotes"])
        self.assertEqual(revised["value"], 2.5)
        self.assertEqual(revised["footnotes"], str(preliminary))
        self.assertEqual(
            [(s["series"], s["is_adjusted"]) for s in call.series],
            [("Jobs", True), ("Jobs", False), ("Jobs", None)],
        )

    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.logger.warning")
    @patch(f"{MODULE}.requests.post", side_effect=Exception)
    def test_response_error(self, mocked_post, mocked_warning, mocked_critical):
        with self.assertRaises(Exception) as e:
            self.api_call.bls_request(self.series_ids, 2000, 2002)

        self.assertEqual(
            str(e.exception), 'Response Status from API is not "REQUEST_SUCCEEDED"'
        )
        self.assertEqual(mocked_warning.call_count, 0)
        self.assertEqual(mocked_critical.call_count, 1)
        self.assertEqual(mocked_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
