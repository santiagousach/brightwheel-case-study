"""Logging utilities for the web scraper application."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import get_config


def setup_logging(
    name: str = "web_scraper",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    console: bool = True,
) -> logging.Logger:
    """
    Set up and configure logging for the application.

    Args:
        name (str): Logger name
        log_level (str, optional): Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file (str, optional): Path to log file
        console (bool): Whether to log to console

    Returns:
        logging.Logger: Configured logger
    """
    # Get config
    config = get_config()

    # Get log level from env if not provided
    if log_level is None:
        log_level = config.get_env("LOG_LEVEL", "INFO")

    # Get log file from env if not provided
    if log_file is None:
        log_file = config.get_env("LOG_FILE")

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers = []  # Remove existing handlers

    # Define log format
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Add file handler if log file provided
    if log_file:
        # Create log directory if it doesn't exist
        log_path = Path(log_file)
        log_dir = log_path.parent
        os.makedirs(log_dir, exist_ok=True)

        # Add timestamp to log filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{log_path.stem}_{timestamp}{log_path.suffix}"
        log_path = log_dir / log_filename

        # Create file handler
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)

    # Add console handler if requested
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_format)
        logger.addHandler(console_handler)

    return logger


# Global logger instance
_logger = None


def get_logger() -> logging.Logger:
    """
    Get the global logger instance.

    Returns:
        logging.Logger: Global logger
    """
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger
