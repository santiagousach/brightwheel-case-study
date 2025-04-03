"""CSV exporter for saving data to CSV files."""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data_processors.base_processor import BaseProcessor


class CSVExporter(BaseProcessor):
    """Export data to CSV file."""

    def __init__(
        self, *args, add_timestamp: bool = False, encoding: str = "utf-8", **kwargs
    ):
        """
        Initialize CSV exporter.

        Args:
            add_timestamp (bool): Whether to add timestamp to filename
            encoding (str): CSV file encoding
            *args, **kwargs: Arguments to pass to BaseProcessor
        """
        super().__init__(*args, **kwargs)
        self.add_timestamp = add_timestamp
        self.encoding = encoding

    def process(self, data: List[Dict[str, Any]]) -> str:
        """
        Process data and write to CSV file.

        Args:
            data (List[Dict[str, Any]]): Data to write

        Returns:
            str: Path to output CSV file
        """
        # Get output path
        output_path = self.get_output_path("csv")

        # Add timestamp if requested
        if self.add_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path_obj = Path(output_path)
            output_path = str(
                path_obj.parent / f"{path_obj.stem}_{timestamp}{path_obj.suffix}"
            )

        self.logger.info(f"Writing {len(data)} records to CSV file: {output_path}")

        # Use pandas for better handling of data types and encoding
        try:
            df = pd.DataFrame(data)

            # Ensure columns are in the right order
            data_fields = self.config.get("data_fields", [])
            if data_fields:
                # Make sure all fields in data_fields are in df
                for field in data_fields:
                    if field not in df.columns:
                        df[field] = ""

                # Reorder columns
                df = df[data_fields]

            # Write CSV file
            df.to_csv(output_path, index=False, encoding=self.encoding)

            self.logger.info(f"Successfully wrote data to {output_path}")

            return output_path
        except Exception as e:
            self.logger.error(f"Error writing CSV file: {str(e)}")

            # Fallback to standard csv library if pandas fails
            self._write_csv_fallback(data, output_path)

            return output_path

    def _write_csv_fallback(self, data: List[Dict[str, Any]], output_path: str) -> None:
        """
        Fallback method to write CSV using standard library.

        Args:
            data (List[Dict[str, Any]]): Data to write
            output_path (str): Output file path
        """
        self.logger.warning("Using fallback CSV writer")

        try:
            # Get fieldnames from first record or config
            fieldnames = self.config.get(
                "data_fields", list(data[0].keys()) if data else []
            )

            with open(output_path, "w", newline="", encoding=self.encoding) as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)

            self.logger.info(
                f"Successfully wrote data to {output_path} using fallback method"
            )
        except Exception as e:
            self.logger.error(f"Fallback CSV writing also failed: {str(e)}")
            raise
