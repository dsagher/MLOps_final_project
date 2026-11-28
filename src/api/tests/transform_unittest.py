"""Unit tests for src.api.transform. Pure functions; no I/O."""

import unittest
from unittest.mock import patch

from src.api.strategies import StateSeriesStrategy
from src.api.transform import transform_results, transform_series

MODULE = "src.api.transform"


def response(series, message=None):
    return {
        "status": "REQUEST_SUCCEEDED",
        "message": message or [],
        "Results": {"series": series},
    }


class TestTransform(unittest.TestCase):
    @patch(f"{MODULE}.log_messages")
    def test_api_messages_are_logged(self, mocked_log):
        messages = ["No Data Available for Series 123456 Year: 1972"]

        rows = transform_results(
            [response([{"seriesID": "123ABC", "data": []}], messages)]
        )

        self.assertEqual(rows, [])
        mocked_log.assert_called_once_with(messages)

    def test_results_snake_case_keys(self):
        data_point = {
            "year": "2005",
            "period": "M01",
            "periodName": "January",
            "value": "1.5",
            "footnotes": [{}],
        }

        rows = transform_results(
            [response([{"seriesID": "123ABC", "data": [data_point]}])]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            set(row), {"series_id", "year", "period", "period_name", "value", "footnotes"}
        )
        self.assertEqual(
            (row["series_id"], row["year"], row["period_name"], row["value"]),
            ("123ABC", 2005, "January", 1.5),
        )

    def test_results_values_and_footnotes(self):
        preliminary = [{"code": "P", "text": "Preliminary"}]
        data = [
            {"year": "2005", "period": "M01", "periodName": "January", "value": "-", "footnotes": [{}]},
            {"year": "2005", "period": "M02", "periodName": "February", "value": "2.5", "footnotes": preliminary},
        ]

        missing, revised = transform_results([response([{"seriesID": "A", "data": data}])])

        self.assertIsNone(missing["value"])
        self.assertIsNone(missing["footnotes"])
        self.assertEqual(revised["value"], 2.5)
        self.assertEqual(revised["footnotes"], str(preliminary))

    def test_series_snake_case_and_adjusted_flags(self):
        series = [
            {"seriesID": "A", "series": "Jobs, seasonally adjusted", "state": "MI", "survey": "X"},
            {"seriesID": "B", "series": "Jobs, not seasonally adjusted", "state": "MI", "survey": "X"},
            {"seriesID": "C", "series": "Jobs", "state": "MI", "survey": "X"},
        ]
        strategy = StateSeriesStrategy(series)

        rows = transform_series(strategy)

        self.assertEqual(
            set(rows[0]), {"series_id", "series", "state", "survey", "is_adjusted"}
        )
        self.assertEqual(
            [(s["series"], s["is_adjusted"]) for s in rows],
            [("Jobs", True), ("Jobs", False), ("Jobs", None)],
        )
        self.assertEqual(strategy.get_series_list()[0]["series"], "Jobs, seasonally adjusted")


if __name__ == "__main__":
    unittest.main()
