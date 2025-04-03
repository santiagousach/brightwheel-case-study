"""Data processors for formatting and exporting scraped data."""

from typing import Dict, Type

from src.data_processors.base_processor import BaseProcessor
from src.data_processors.csv_exporter import CSVExporter

# Register processors for easy access
PROCESSORS: Dict[str, Type[BaseProcessor]] = {
    "csv": CSVExporter,
}
