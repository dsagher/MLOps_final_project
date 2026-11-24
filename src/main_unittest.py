"""Unit tests for src.main.main(). arg_router, read_file and BlsApiCall are mocked."""

import csv
import unittest
from unittest.mock import patch

from src.api.api_bls import NationalSeriesStrategy, StateSeriesStrategy
from src.main import main

USER_INPUT = {
    "path": "path/to/csv",
    "series_type": 1,
    "start_year": 2000,
    "end_year": 2005,
    "series_count": "",
}


@patch("src.main.BlsApiCall")
@patch("src.main.read_file")
@patch("src.main.arg_router")
class TestMain(unittest.TestCase):
    def test_national_series(self, mocked_router, mocked_read, mocked_bls):
        mocked_router.return_value = USER_INPUT
        mocked_read.return_value = [{"seriesID": "123ABC"}]

        main()

        mocked_read.assert_called_once_with("path/to/csv")
        start, end, strategy, _request_id = mocked_bls.call_args.args
        self.assertEqual((start, end), (2000, 2005))
        self.assertEqual(mocked_bls.call_args.kwargs, {"series_count": ""})
        self.assertIsInstance(strategy, NationalSeriesStrategy)
        engine = mocked_bls.return_value
        engine.extract.assert_called_once()
        engine.transform.assert_called_once()
        engine.load.assert_called_once()

    def test_state_series(self, mocked_router, mocked_read, mocked_bls):
        mocked_router.return_value = {**USER_INPUT, "series_type": 2}
        mocked_read.return_value = [{"seriesID": "123ABC"}]

        main()

        self.assertIsInstance(mocked_bls.call_args.args[2], StateSeriesStrategy)

    def test_read_errors_exit(self, mocked_router, mocked_read, mocked_bls):
        mocked_router.return_value = USER_INPUT
        for error in (PermissionError, ValueError, csv.Error, IOError):
            with self.subTest(error=error.__name__):
                mocked_read.side_effect = error
                with self.assertRaises(SystemExit):
                    main()
        mocked_bls.assert_not_called()

    def test_pipeline_error_propagates(self, mocked_router, mocked_read, mocked_bls):
        mocked_router.return_value = USER_INPUT
        mocked_bls.return_value.extract.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            main()

        mocked_bls.return_value.transform.assert_not_called()
        mocked_bls.return_value.load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
