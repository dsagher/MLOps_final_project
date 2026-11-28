import sqlalchemy as sqlalc
from sqlalchemy.engine.url import URL
import os


def get_engine():
    driver = os.getenv("DB_DRIVER")
    username = os.getenv("DB_USERNAME")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    database = os.getenv("DB_DATABASE")
    port = int(os.getenv("DB_PORT")) if os.getenv("DB_PORT") else None  # type: ignore

    if (
        not driver
        or not username
        or not password
        or not host
        or not database
        or not port
    ):
        raise ValueError(
            "One or more required database connection parameters are missing."
        )
    url_object = URL.create(
        drivername=driver,
        username=username,
        password=password,
        host=host,
        database=database,
        port=port,
    )
    engine = sqlalc.create_engine(url_object, logging_name="SQLAlchemy")
    return engine
