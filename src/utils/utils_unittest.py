"""Unit tests for src.utils: read_file, validate_path/validate_years, and arg_router."""

import datetime as dt
import os
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from src.utils.arg_parser import arg_router
from src.utils.shared import read_file
from src.utils.validate import validate_path, validate_years

THIS_YEAR = dt.datetime.now().year


def make_args(**overrides):
    args = dict(
        path=False,
        series_type=False,
        start_year=False,
        end_year=False,
        series_count=None,
        traceroute=False,
        verbose=False,
        silence=True,
        latest=False,
    )
    return Namespace(**{**args, **overrides})


class TestReadFile(unittest.TestCase):
    def test_reads_rows_as_dicts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("seriesID,series,state,survey,is_adjusted\n")
            f.write("123ABC,Always be Cool,MI,ABC,False\n")
            f.write("124ABC,Always be Cooler,MI,ABC,False\n")
        self.addCleanup(os.remove, f.name)

        rows = read_file(f.name)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["seriesID"], "123ABC")
        self.assertEqual(rows[1]["series"], "Always be Cooler")

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read_file("path/that/does/not/exist.csv")


class TestValidate(unittest.TestCase):
    def test_validate_path(self):
        self.assertEqual(validate_path(__file__), (True, None))
        self.assertEqual(validate_path("nope/nope.csv"), (False, "Path not found."))

    def test_validate_years(self):
        cases = [
            (2000, 2010, True, None),
            ("two thousand twenty", 2010, False, "Error: Years must be integers."),
            (-2000, 2010, False, "Error: Years must be positive integers."),
            (
                2000,
                THIS_YEAR + 10,
                False,
                f"Error: End year cannot be in the future (current year: {THIS_YEAR}).",
            ),
            (2010, 2000, False, "Error: Start year must be before end year."),
            (2000, 2019, True, None),
            (
                2000,
                2020,
                False,
                "Error: Year range cannot exceed 20 years due to API limitations.",
            ),
            (
                2000,
                2025,
                False,
                "Error: Year range cannot exceed 20 years due to API limitations.",
            ),
        ]
        for start, end, valid, message in cases:
            with self.subTest(start=start, end=end):
                self.assertEqual(validate_years(start, end), (valid, message))


@patch("src.utils.arg_parser._arg_parser")
class TestArgRouter(unittest.TestCase):
    def test_valid_args(self, mocked_parser):
        mocked_parser.return_value = make_args(
            path=__file__, series_type=1, start_year=2000, end_year=2005
        )

        self.assertEqual(
            arg_router(),
            {
                "path": __file__,
                "series_type": 1,
                "start_year": 2000,
                "end_year": 2005,
                "series_count": "",
                "verbose": False,
                "silence": True,
                "latest": False,
            },
        )

    def test_missing_args(self, mocked_parser):
        mocked_parser.return_value = make_args(
            path=__file__, series_type=1, start_year=2000
        )

        with self.assertRaises(ValueError) as e:
            arg_router()
        self.assertEqual(
            str(e.exception),
            "Please specify --path, --series-type, --start-year, and --end-year with the appropriate flags.",
        )

    def test_no_args(self, mocked_parser):
        mocked_parser.return_value = make_args()

        with self.assertRaises(ValueError):
            arg_router()

    def test_path_not_found(self, mocked_parser):
        mocked_parser.return_value = make_args(
            path="nope/nope.csv", series_type=1, start_year=2000, end_year=2005
        )

        with self.assertRaises(FileNotFoundError) as e:
            arg_router()
        self.assertEqual(str(e.exception), "Path not found.")

    def test_invalid_years(self, mocked_parser):
        mocked_parser.return_value = make_args(
            path=__file__, series_type=1, start_year=2010, end_year=2000
        )

        with self.assertRaises(ValueError) as e:
            arg_router()
        self.assertEqual(str(e.exception), "Error: Start year must be before end year.")


if __name__ == "__main__":
    unittest.main()
