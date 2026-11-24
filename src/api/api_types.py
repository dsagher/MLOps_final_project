from typing import TypedDict, List, Dict


class DataDict(TypedDict):
    """Cleaned row for the results table; snake_case to match PostgreSQL columns."""

    series_id: str
    year: int
    period: str
    period_name: str
    value: float | None
    footnotes: str | None


# The types below mirror the raw BLS API response, which uses camelCase keys.
class SeriesData(TypedDict):
    year: str
    period: str
    periodName: str
    value: str
    footnotes: List[Dict] | str


class Series(TypedDict):
    seriesID: str
    data: List[SeriesData]


class DataContainer(TypedDict):
    series: List[Series]


class BLSResponse(TypedDict):
    status: str
    responseTime: int
    message: List[str]
    Results: DataContainer
