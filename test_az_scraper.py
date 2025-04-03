#!/usr/bin/env python
"""Test script for the Arizona schools scraper."""

import json
import logging
import os
import time
from pathlib import Path

from src.scrapers.az_schools import AZSchoolsScraper
from src.utils.config import ConfigManager
from src.utils.logging import setup_logging


def main():
    """Run the test for the Arizona schools scraper."""
    # Set up logging
    logger = setup_logging(name="az_scraper_test", log_level="INFO")

    logger.info("Starting Arizona scraper test")

    # Create a temporary config file
    temp_config_path = "temp_az_config.yaml"
    with open(temp_config_path, "w") as f:
        f.write(
            """
base_url: https://azreportcards.azed.gov/schools
selectors:
  search:
    input: "input[placeholder='Search by school name']"
  filters:
    alphabet_buttons: "button.v-btn.v-btn--icon.v-btn--small.theme--light"
  schools:
    links: "a.no-underline"
"""
        )

    # Set the config path environment variable
    os.environ["CONFIG_PATH"] = temp_config_path

    # Create the config manager
    config = ConfigManager(config_path=temp_config_path)

    # Initialize the scraper
    logger.info("Initializing scraper with headless=False for debugging")
    scraper = AZSchoolsScraper(config=config, headless=False)

    try:
        # Run the scraper
        logger.info("Running the scraper")
        start_time = time.time()
        data = scraper.run()
        end_time = time.time()

        # Log the results
        duration = end_time - start_time
        logger.info(f"Scraper completed in {duration:.2f} seconds")
        logger.info(f"Extracted {len(data)} school records")

        # Save the data to a JSON file
        if data:
            with open("az_schools_data.json", "w") as f:
                json.dump(data, f, indent=2)
            logger.info("Data saved to az_schools_data.json")

            # Print the first few records
            logger.info("First 3 schools extracted:")
            for i, school in enumerate(data[:3]):
                logger.info(
                    f"{i+1}. {school.get('company', 'Unknown')} - {school.get('city', 'Unknown')}, {school.get('state', 'Unknown')}"
                )
        else:
            logger.warning("No data was extracted")

    except Exception as e:
        logger.error(f"Error in test: {str(e)}")
    finally:
        # Clean up the temporary config file
        try:
            if os.path.exists(temp_config_path):
                os.remove(temp_config_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary config file: {str(e)}")
        logger.info("Test completed")


if __name__ == "__main__":
    main()
