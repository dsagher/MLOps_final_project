"""==========================================================================================
    Title:       BLS API Load
    File:        load.py
    Author:      Dan Sagher
    Description:
        Load stage of the BLS ETL pipeline: writes transformed series and results rows
        into PostgreSQL via SQLAlchemy.
==========================================================================================
"""

from sqlalchemy import (
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

from src.api.api_types import DataDict
from src.api.strategies import SeriesStrategy, StateSeriesStrategy
from src.db.connect_db import get_engine


def load(strategy: SeriesStrategy, series: list[dict], results: list[DataDict]) -> None:
    """
    Loads the transformed data into the PostgreSQL database using SQLAlchemy.

    Reads database configuration from environmental variables, creates tables for series
    and results if they don't exist, and performs upsert operations to avoid duplicates.
    """
    engine = get_engine()
    metadata = MetaData()

    series_table_name, results_table_name = strategy.get_series_tables()

    if isinstance(strategy, StateSeriesStrategy):
        series_columns = [
            Column("series_id", String, primary_key=True),
            Column("series", String, nullable=False),
            Column("state", String, nullable=False),
            Column("survey", String),
            Column("is_adjusted", Boolean),
        ]
    else:
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

    series_stmt = insert(series_table).values(series).on_conflict_do_nothing()
    results_stmt = insert(results_table).values(results).on_conflict_do_nothing()

    with engine.connect() as connect:
        connect.execute(series_stmt)
        connect.execute(results_stmt)
        connect.commit()
