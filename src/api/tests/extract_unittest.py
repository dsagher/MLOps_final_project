"""Unit tests for src.api.extract. All HTTP calls are mocked; the query-count file is a temp file."""

import datetime
import json
import os
import tempfile
import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError, HTTPError

from src.api.extract import bls_request, count_query, extract
from src.api.strategies import StateSeriesStrategy

MODULE = "src.api.extract"
SUCCESS = {"status": "REQUEST_SUCCEEDED"}
REQUEST_ID = "test-request-id"


def mock_response(status_code=HTTPStatus.OK, json_data=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


class TestExtract(unittest.TestCase):
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
        cls.strategy = StateSeriesStrategy(cls.state_series)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.query_count_file = os.path.join(tmp.name, "query_count.csv")
        for patcher in (
            patch(f"{MODULE}.QUERY_COUNT_FILE", self.query_count_file),
            patch.dict(os.environ, {"API_KEY": "test-key"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def request(self, series=None, start_year=2005, end_year=2007, **kwargs):
        return bls_request(
            series or self.series_ids,
            self.strategy,
            REQUEST_ID,
            start_year,
            end_year,
            **kwargs,
        )

    @patch(f"{MODULE}.logger.info")
    @patch(f"{MODULE}.requests.post")
    def test_bls_request(self, mocked_post, mocked_log):
        mocked_post.return_value = mock_response(json_data=SUCCESS)
        payload = json.dumps(
            {
                "seriesid": self.series_ids,
                "startyear": 2005,
                "endyear": 2007,
                "registrationKey": "test-key",
            }
        )

        result = self.request()

        mocked_post.assert_called_once_with(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
            params={},
        )
        self.assertEqual(result, SUCCESS)
        self.assertEqual(mocked_log.call_count, 1)

    @patch(f"{MODULE}.requests.post")
    def test_bls_request_latest(self, mocked_post):
        mocked_post.return_value = mock_response(json_data=SUCCESS)

        result = self.request(start_year="", end_year="", latest=True)

        mocked_post.assert_called_once_with(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            data=json.dumps({"seriesid": self.series_ids, "registrationKey": "test-key"}),
            headers={"Content-Type": "application/json"},
            timeout=30,
            params={"latest": True},
        )
        self.assertEqual(result, SUCCESS)

    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.requests.post")
    def test_bls_request_limit(self, mocked_post, mocked_log):
        for _ in range(500):
            count_query()

        with self.assertRaises(Exception) as e:
            self.request()

        self.assertEqual(str(e.exception), "Queries may not exceed 500 within a day.")
        mocked_log.assert_called_once()
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.requests.post")
    def test_bls_year_limit(self, mocked_post):
        with self.assertRaises(ValueError) as e:
            self.request(start_year=2000, end_year=2025)
        self.assertEqual(str(e.exception), "Can only take in up to 20 years per query.")
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.requests.post")
    def test_bls_year_limit_inclusive(self, mocked_post):
        with self.assertRaises(ValueError):
            self.request(start_year=2000, end_year=2020)
        mocked_post.assert_not_called()

    @patch(f"{MODULE}.requests.post")
    def test_bls_id_limit(self, mocked_post):
        with self.assertRaises(ValueError) as e:
            self.request(series=list(range(60)), start_year=2000, end_year=2005)
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
            self.request(start_year=2000, end_year=2005)

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
            self.request(start_year=2000, end_year=2002)

        self.assertEqual(
            str(e.exception), f"API Error: {HTTPStatus.INTERNAL_SERVER_ERROR.value}"
        )
        self.assertEqual(mocked_critical.call_count, 1)
        self.assertEqual(mocked_warning.call_count, 3)
        self.assertEqual(mocked_post.call_count, 3)
        self.assertEqual(mocked_sleep.call_count, 3)

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.requests.post")
    def test_network_error_retried(self, mocked_post, mocked_sleep):
        mocked_post.side_effect = [ConnectionError(), mock_response(json_data=SUCCESS)]

        result = self.request(start_year=2000, end_year=2005)

        self.assertEqual(result, SUCCESS)
        self.assertEqual(mocked_post.call_count, 2)
        mocked_sleep.assert_called_once()

    @patch(f"{MODULE}.logger.critical")
    @patch(f"{MODULE}.logger.warning")
    @patch(f"{MODULE}.requests.post", side_effect=Exception)
    def test_response_error(self, mocked_post, mocked_warning, mocked_critical):
        with self.assertRaises(Exception) as e:
            self.request(start_year=2000, end_year=2002)

        self.assertEqual(
            str(e.exception), 'Response Status from API is not "REQUEST_SUCCEEDED": None'
        )
        self.assertEqual(mocked_warning.call_count, 0)
        self.assertEqual(mocked_critical.call_count, 1)
        self.assertEqual(mocked_post.call_count, 1)

    def test_count_resets_on_old_day(self):
        for last_day in (
            datetime.date.today() - datetime.timedelta(days=1),
            datetime.date.today() - datetime.timedelta(days=31),
        ):
            with self.subTest(last_day=last_day):
                with open(self.query_count_file, "w") as file:
                    file.write(f"date,count\n{last_day.isoformat()},500\n")

                self.assertEqual(count_query(), 1)

                with open(self.query_count_file, newline="") as file:
                    self.assertEqual(
                        file.read(),
                        f"date,count\r\n{datetime.date.today().isoformat()},1\r\n",
                    )

    def test_count_survives_corrupt_file(self):
        with open(self.query_count_file, "w") as file:
            file.write("")

        self.assertEqual(count_query(), 1)

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.requests.post")
    def test_extract_returns_responses(self, mocked_post, _sleep):
        mocked_post.return_value = mock_response(json_data=SUCCESS)

        responses = extract(self.strategy, REQUEST_ID, 2000, 2005)

        self.assertEqual(responses, [SUCCESS])
        self.assertEqual(mocked_post.call_count, 1)

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.requests.post")
    def test_extract_latest_and_series_count(self, mocked_post, _sleep):
        mocked_post.return_value = mock_response(json_data=SUCCESS)

        extract(self.strategy, REQUEST_ID, latest=True, series_count=1)

        kwargs = mocked_post.call_args.kwargs
        self.assertEqual(kwargs["params"], {"latest": True})
        self.assertEqual(json.loads(kwargs["data"])["seriesid"], ["123ABC"])

    def test_extract_rejects_missing_series_ids(self):
        strategy = StateSeriesStrategy([{"series_id": "123ABC"}])

        with self.assertRaises(ValueError):
            extract(strategy, REQUEST_ID, 2000, 2005)


if __name__ == "__main__":
    unittest.main()
