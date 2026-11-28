import argparse as ap
import subprocess
import sys
from .validate import validate_path, validate_years

import logging

logger = logging.getLogger(__name__)


def _arg_parser():
    """
    Parse command-line arguments for the BLS API ETL Pipeline.

    Returns:
        argparse.Namespace: Parsed command-line arguments including:
            - path: CSV file path with series IDs.
            - series_type: 1 for National Series or 2 for State Series.
            - start_year: The beginning year for data extraction.
            - end_year: The ending year for data extraction.
            - series_count: Optional limit on the number of series IDs to process.
            - traceroute: Flag to perform a traceroute to the BLS API.
            - verbose: Flag to enable detailed logging output.
            - silence: Flag to disable logging entirely.
    """
    parser = ap.ArgumentParser(
        prog="Bureau of Labor Statistics API Pipeline",
        description="This program uses a list of seriesIDs, start year, and end year as input \
                        to the Bureau of Labor Statistics API. The results are parsed, cleaned, and \
                        uploaded into a local PostgreSQL database.",
        usage="python -m src.main --path path/to/csv --series-type 1 --start-year 2000 --end-year 2005 -n 100 -v",
    )

    parser.add_argument(
        "--path",
        type=str,
        help="Path to CSV file containing seriesIDs",
        default=False,
        metavar="path/to/csv",
    )
    parser.add_argument(
        "--series-type",
        type=int,
        choices=[1, 2],
        help="Enter 1 for National Series or 2 for State Series",
        default=False,
        metavar="type",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Enter start year for query.",
        default=False,
        metavar="year",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Enter end year for query.",
        default=False,
        metavar="year",
    )
    parser.add_argument(
        "-n",
        "--series-count",
        type=int,
        help="Enter number of seriesIDs to input",
        default=None,
        metavar="# of series",
    )
    parser.add_argument(
        "-t",
        "--traceroute",
        help="Check routing to the BLS API. Will exit program after execution.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Include more information to logging output (Set level to debug).",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-s",
        "--silence",
        help="Turn off logging to console and file.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--latest",
        help="Fetch the most recent survey results from the database.",
        action="store_true",
        default=False,
    )

    return parser.parse_args()


def arg_router():
    """
    Parse and validate command line arguments for the BLS API data extraction script.

    Returns:
        dict: A dictionary containing validated user input for path, series type, start year, end year, and series count.
    Raises:
        FileNotFoundError: If the specified path does not exist.
        ValueError: If the provided years are invalid or incomplete arguments are provided.
    """
    args = _arg_parser()

    if args.traceroute:
        logger.info("Performing traceroute to the BLS API.")
        subprocess.run(args=["traceroute", "api.bls.gov"], stdout=sys.stdout)
        sys.exit()

    if not args.latest:
        if not (args.path and args.series_type and args.start_year and args.end_year):
            logger.error(
                "Error: Not enough information provided in Command Line Arguments."
            )
            raise ValueError(
                "Please specify --path, --series-type, --start-year, and --end-year with the appropriate flags."
            )
    if not args.latest:
        user_input = {
            "path": args.path,
            "series_type": args.series_type,
            "start_year": args.start_year,
            "end_year": args.end_year,
            "series_count": args.series_count or "",
            "verbose": args.verbose,
            "silence": args.silence,
            "latest": args.latest,
        }
        path_valid, path_message = validate_path(user_input["path"])
        years_valid, years_message = validate_years(
            user_input["start_year"], user_input["end_year"]
        )

        if not path_valid:
            logger.error(path_message)
            raise FileNotFoundError(path_message)

        if not years_valid:
            logger.error(years_message)
            raise ValueError(years_message)
    if args.latest and (args.start_year or args.end_year):
        logger.error("Error: Cannot specify --latest with --start-year or --end-year.")
        raise ValueError(
            "Please do not specify --start-year or --end-year when using --latest."
        )
    user_input = {
        "path": args.path,
        "series_type": args.series_type,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "series_count": args.series_count or "",
        "verbose": args.verbose,
        "silence": args.silence,
        "latest": args.latest,
    }
    logger.info(f"Using command line arguments: {user_input}")

    logger.info("Returning validated user input")
    return user_input
