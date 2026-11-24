from abc import ABC
from abc import abstractmethod
import logging

logger = logging.getLogger(__name__)


class SeriesStrategy(ABC):
    """Strategy for handling national or state series data."""

    def __init__(self, series_data: list[dict]):
        self.series_data = series_data

    def get_series_list(self) -> list[dict]:
        return self.series_data

    def get_series_count(self, requested: int | str) -> int:
        return int(requested) if requested != "" else len(self.series_data)

    @abstractmethod
    def log_request(
        self,
        query_count: int,
        num_series: int,
        start_year: str,
        end_year: str,
        request_id: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_series_tables(self):
        """Returns (series_table, results_table) names."""
        raise NotImplementedError


class NationalSeriesStrategy(SeriesStrategy):
    """Strategy for national series."""

    def log_request(
        self,
        query_count: int,
        num_series: int,
        start_year: str,
        end_year: str,
        request_id: str,
    ) -> None:
        logger.info(
            "Request #%s: %s National SeriesIDs, from %s to %s, Request ID: %s",
            query_count,
            num_series,
            start_year,
            end_year,
            request_id,
        )

    def get_series_tables(self):
        return ("national_series", "national_results")


class StateSeriesStrategy(SeriesStrategy):
    """Strategy for state series."""

    def log_request(
        self,
        query_count: int,
        num_series: int,
        start_year: str,
        end_year: str,
        request_id: str,
    ) -> None:
        logger.info(
            "Request #%s: %s State SeriesIDs, from %s to %s, Request ID: %s",
            query_count,
            num_series,
            start_year,
            end_year,
            request_id,
        )

    def get_series_tables(self):
        return ("state_series", "state_results")
