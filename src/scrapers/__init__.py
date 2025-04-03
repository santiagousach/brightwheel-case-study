"""Scrapers module for extracting data from different websites."""

from typing import Dict, Type

from src.scrapers.base_scraper import BaseScraper
from src.scrapers.tx_schools import TXSchoolsScraper
from src.scrapers.az_schools import AZSchoolsScraper

# Register scrapers for easy access
SCRAPERS: Dict[str, Type[BaseScraper]] = {
    "tx_schools": TXSchoolsScraper,
    "az_schools": AZSchoolsScraper,
}


def get_scraper(scraper_type: str) -> Type[BaseScraper]:
    """
    Get scraper class by type.

    Args:
        scraper_type (str): Scraper type identifier

    Returns:
        Type[BaseScraper]: Scraper class

    Raises:
        ValueError: If scraper type not found
    """
    if scraper_type not in SCRAPERS:
        raise ValueError(
            f"Scraper type '{scraper_type}' not found. "
            f"Available types: {', '.join(SCRAPERS.keys())}"
        )

    return SCRAPERS[scraper_type]
