"""Base data processor implementation with common functionality."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
from datetime import datetime

from src.utils.config import ConfigManager, get_config
from src.utils.logging import get_logger


class BaseProcessor(ABC):
    """Base processor class that defines interface for all data processors."""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        output_dir: Optional[str] = None,
        output_filename: Optional[str] = None,
        scraper_type: Optional[str] = None,
    ):
        """
        Initialize the base processor.

        Args:
            config (ConfigManager, optional): Configuration manager
            output_dir (str, optional): Output directory
            output_filename (str, optional): Output filename
            scraper_type (str, optional): Type of scraper being used
        """
        self.logger = get_logger()
        self.config = config or get_config()

        # Get output directory from env if not provided
        self.output_dir = output_dir or self.config.get_env(
            "OUTPUT_DIRECTORY", "data/output"
        )

        # Get output filename from env if not provided
        self.output_filename = output_filename or self.config.get_env("OUTPUT_FILENAME")

        # Get scraper type from env if not provided
        self.scraper_type = scraper_type or self.config.get_env(
            "SCRAPER_TYPE", "default"
        )

        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def process(self, data: List[Dict[str, Any]]) -> str:
        """
        Process data and write to output file.

        Args:
            data (List[Dict[str, Any]]): Data to process

        Returns:
            str: Path to output file
        """
        pass

    def get_output_path(self, extension: str = None) -> str:
        """
        Get output path with proper extension.

        Args:
            extension (str, optional): File extension

        Returns:
            str: Output path
        """
        # Use environment variable if set
        output_path = os.getenv("OUTPUT_PATH")

        # If not set, try config
        if not output_path:
            output_path = self.config.get("output.path") if self.config else None

        # If still not set, use default
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = (
                f"/app/data/{self.scraper_type}_{timestamp}.{extension or 'csv'}"
            )
            self.logger.info(f"Using default output path: {output_path}")
            return output_path

        # Handle extension
        if extension:
            filename = os.path.basename(output_path)
            if not filename:  # If filename is empty
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = (
                    f"{output_path}/{self.scraper_type}_{timestamp}.{extension}"
                )
            elif not filename.lower().endswith(f".{extension.lower()}"):
                output_path = f"{output_path}.{extension}"

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        return output_path
