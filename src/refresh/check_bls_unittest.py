"""Unit tests for src.refresh.check_bls.compare_results(). Plain data, no DB or network."""

import unittest
from unittest.mock import patch

from sqlalchemy.exc import NoSuchTableError

from src.refresh.check_bls import (
    compare_results,
    get_recent_survey_results_db,
    has_new_bls_data,
)


def bls(series_id, year, period):
    return {"series_id": series_id, "year": year, "period": period}


class TestCompareResults(unittest.TestCase):
    def test_all_series_newer(self):
        db = [("A", 2025, "M09"), ("B", 2025, "M09")]
        new = [bls("A", 2025, "M10"), bls("B", 2025, "M10")]
        self.assertTrue(compare_results(db, new))

    def test_all_series_identical(self):
        db = [("A", 2025, "M10"), ("B", 2025, "M10")]
        same = [bls("A", 2025, "M10"), bls("B", 2025, "M10")]
        self.assertFalse(compare_results(db, same))

    def test_mixed_waits_for_all(self):
        db = [("A", 2025, "M09"), ("B", 2025, "M10")]
        mixed = [bls("A", 2025, "M10"), bls("B", 2025, "M10")]
        self.assertFalse(compare_results(db, mixed))

    def test_series_missing_from_db_counts_as_new(self):
        self.assertTrue(compare_results([], [bls("A", 2025, "M10")]))

    def test_empty_bls_results(self):
        self.assertFalse(compare_results([("A", 2025, "M10")], []))

    def test_multiple_bls_points_use_newest(self):
        db = [("A", 2025, "M10")]
        two_points = [bls("A", 2025, "M10"), bls("A", 2025, "M09")]
        self.assertFalse(compare_results(db, two_points))

    def test_extra_db_series_are_ignored(self):
        db = [("A", 2025, "M09"), ("OTHER", 2020, "M01")]
        self.assertTrue(compare_results(db, [bls("A", 2025, "M10")]))


@patch("src.refresh.check_bls.load_dotenv")
@patch("src.refresh.check_bls.get_engine")
@patch("src.refresh.check_bls.read_file", return_value=[{"seriesID": "A"}])
@patch("src.refresh.check_bls.get_recent_survey_results_bls")
@patch("src.refresh.check_bls.get_recent_survey_results_db")
class TestHasNewBlsData(unittest.TestCase):
    def test_returns_compare_result_and_queries_national_table(
        self, mocked_db, mocked_bls, mocked_read, mocked_engine, mocked_dotenv
    ):
        mocked_db.return_value = [("A", 2025, "M09")]
        mocked_bls.return_value = [bls("A", 2025, "M10")]
        self.assertTrue(has_new_bls_data("series.csv", 1))
        self.assertEqual(mocked_db.call_args.args[1], "national_results")

    def test_state_series_type_queries_state_table(
        self, mocked_db, mocked_bls, mocked_read, mocked_engine, mocked_dotenv
    ):
        mocked_db.return_value = [("A", 2025, "M10")]
        mocked_bls.return_value = [bls("A", 2025, "M10")]
        self.assertFalse(has_new_bls_data("series.csv", 2))
        self.assertEqual(mocked_db.call_args.args[1], "state_results")


class TestGetRecentSurveyResultsDb(unittest.TestCase):
    @patch("src.refresh.check_bls.Table", side_effect=NoSuchTableError)
    def test_missing_table_means_empty_db(self, _mocked_table):
        self.assertEqual(get_recent_survey_results_db(object(), "national_results"), [])


if __name__ == "__main__":
    unittest.main()
