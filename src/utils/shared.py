"""Command-line and input utilities for the BLS API ETL Pipeline."""

import csv


def read_file(path: str) -> list[dict]:
    """
    Read and parse a CSV file containing series IDs.

    Args:
        path (str): Path to the CSV file.

    Returns:
        list[dict]: A list of dictionaries representing each row in the CSV.
    """
    with open(path, "r") as file:
        lst = []
        reader = csv.DictReader(file)
        for row in reader:
            lst.append(row)
        return lst
