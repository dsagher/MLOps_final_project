"""Unit tests for src.main.main(). arg_router, read_file and the ETL stages are mocked."""

import csv
import unittest
from unittest.mock import patch

from src.api.strategies import NationalSeriesStrategy, StateSeriesStrategy
from src.main import main

USER_INPUT = {
    "path": "path/to/csv",
    "series_type": 1,
    "start_year": 2000,
    "end_year": 2005,
    "series_count": "",
    "latest": False,
}


@patch("src.main.load")
@patch("src.main.transform_series")
@patch("src.main.transform_results")
@patch("src.main.extract")
@patch("src.main.read_file")
@patch("src.main.arg_router")
class TestMain(unittest.TestCase):
    def test_national_series(
        self, mocked_router, mocked_read, mocked_extract, mocked_results, mocked_series, mocked_load
    ):
        mocked_router.return_value = USER_INPUT
        mocked_read.return_value = [{"seriesID": "123ABC"}]

        main()

        mocked_read.assert_called_once_with("path/to/csv")
        strategy, _request_id = mocked_extract.call_args.args
        self.assertEqual(
            mocked_extract.call_args.kwargs,
            {"start_year": 2000, "end_year": 2005, "latest": False, "series_count": ""},
        )
        self.assertIsInstance(strategy, NationalSeriesStrategy)
        mocked_results.assert_called_once_with(mocked_extract.return_value)
        mocked_series.assert_called_once_with(strategy)
        mocked_load.assert_called_once_with(
            strategy, mocked_series.return_value, mocked_results.return_value
        )

    def test_state_series(
        self, mocked_router, mocked_read, mocked_extract, mocked_results, mocked_series, mocked_load
    ):
        mocked_router.return_value = {**USER_INPUT, "series_type": 2, "latest": True}
        mocked_read.return_value = [{"seriesID": "123ABC"}]

        main()

        self.assertIsInstance(mocked_extract.call_args.args[0], StateSeriesStrategy)
        self.assertTrue(mocked_extract.call_args.kwargs["latest"])

    def test_read_errors_exit(
        self, mocked_router, mocked_read, mocked_extract, mocked_results, mocked_series, mocked_load
    ):
        mocked_router.return_value = USER_INPUT
        for error in (PermissionError, ValueError, csv.Error, IOError):
            with self.subTest(error=error.__name__):
                mocked_read.side_effect = error
                with self.assertRaises(SystemExit):
                    main()
        mocked_extract.assert_not_called()

    def test_pipeline_error_propagates(
        self, mocked_router, mocked_read, mocked_extract, mocked_results, mocked_series, mocked_load
    ):
        mocked_router.return_value = USER_INPUT
        mocked_extract.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            main()

        mocked_results.assert_not_called()
        mocked_series.assert_not_called()
        mocked_load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
