"""Main entry point for the web scraper application."""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.data_processors import PROCESSORS
from src.scrapers import get_scraper
from src.utils.config import get_config
from src.utils.logging import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Web Scraper for Educational Institutions"
    )

    parser.add_argument(
        "--scraper",
        type=str,
        help="Scraper type to use (default: from SCRAPER_TYPE env var)",
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to config file (default: from CONFIG_PATH env var)",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        help="Output directory (default: from OUTPUT_DIRECTORY env var)",
    )

    parser.add_argument(
        "--output-file",
        type=str,
        help="Output filename (default: from OUTPUT_FILENAME env var)",
    )

    parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level (default: from LOG_LEVEL env var)",
    )

    return parser.parse_args()


def setup_environment(args: argparse.Namespace) -> None:
    """
    Set up environment variables from command line arguments.

    Args:
        args (argparse.Namespace): Command line arguments
    """
    # Set environment variables from command line arguments if provided
    if args.scraper:
        os.environ["SCRAPER_TYPE"] = args.scraper

    if args.config:
        os.environ["CONFIG_PATH"] = args.config

    if args.output_dir:
        os.environ["OUTPUT_DIRECTORY"] = args.output_dir

    if args.output_file:
        os.environ["OUTPUT_FILENAME"] = args.output_file

    if args.headless:
        os.environ["HEADLESS_BROWSER"] = "true"

    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level


def main() -> int:
    """
    Main entry point for the application.

    Returns:
        int: Exit code
    """
    start_time = time.time()

    # Parse command line arguments
    args = parse_args()

    # Set up environment variables
    setup_environment(args)

    # Set up logging
    logger = setup_logging()

    try:
        # Load configuration
        config = get_config()

        # Get scraper type from environment
        scraper_type = config.get_env("SCRAPER_TYPE")
        if not scraper_type:
            logger.error("Scraper type not specified. Set SCRAPER_TYPE env variable.")
            return 1

        # Get scraper class
        try:
            scraper_class = get_scraper(scraper_type)
        except ValueError as e:
            logger.error(str(e))
            return 1

        # Initialize and run scraper
        logger.info(f"Starting {scraper_type} scraper")
        with scraper_class() as scraper:
            data = scraper.run()

        # Process and export data
        if data:
            logger.info(f"Processing {len(data)} records")

            # Get output format from env or config, default to CSV
            output_format = os.getenv("OUTPUT_FORMAT", "csv").lower()
            if output_format not in PROCESSORS:
                logger.warning(f"Unsupported output format: {output_format}, using csv")
                output_format = "csv"

            # Initialize exporter
            exporter = PROCESSORS[output_format](scraper_type=scraper_type)

            # Set output path from environment variable
            output_path = os.getenv("OUTPUT_PATH")
            if output_path:
                # Ensure directory exists
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                # If no extension in output path, add it
                if not output_path.lower().endswith(f".{output_format}"):
                    output_path = f"{output_path}.{output_format}"

                # Set output path in exporter
                exporter.output_filename = os.path.basename(output_path)
                exporter.output_dir = output_dir or "."

                # Process data and export
                export_path = exporter.process(data)
                logger.info(f"Data exported to {export_path}")
            else:
                # Use default path handling in processor
                try:
                    export_path = exporter.process(data)
                    logger.info(f"Data exported to {export_path}")
                except Exception as e:
                    logger.error(f"Error exporting data: {str(e)}")
                    # Fallback to direct file writing
                    fallback_path = f"/app/data/{scraper_type}_data.{output_format}"
                    os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
                    if output_format == "csv":
                        import csv

                        with open(fallback_path, "w", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=data[0].keys())
                            writer.writeheader()
                            writer.writerows(data)
                        logger.info(f"Data exported to fallback path: {fallback_path}")
        else:
            logger.warning("No data extracted")

        # Log execution time
        execution_time = time.time() - start_time
        logger.info(f"Execution completed in {execution_time:.2f} seconds")

        return 0

    except Exception as e:
        logger.exception(f"Unhandled exception: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
