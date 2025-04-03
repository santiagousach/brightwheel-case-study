"""Configuration utilities for loading and managing application settings."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


class ConfigManager:
    """Manage configuration settings from environment variables and YAML files."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            config_path (str, optional): Path to the YAML configuration file.
                If None, will use the path from CONFIG_PATH env variable.
        """
        # Load environment variables
        load_dotenv()

        # Get config path from env var if not provided
        self.config_path = config_path or os.getenv("CONFIG_PATH")
        if not self.config_path:
            raise ValueError("Config path not provided. Set CONFIG_PATH env variable.")

        # Load YAML config
        self.config = self._load_yaml_config()

    def _load_yaml_config(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Returns:
            Dict[str, Any]: Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML parsing fails
        """
        config_file = Path(self.config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(config_file, "r") as f:
            try:
                return yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise yaml.YAMLError(f"Error parsing config file: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key with dot notation support.

        Examples:
            config.get("selectors.search_results.schools_container")

        Args:
            key (str): Configuration key with dot notation for nested keys
            default (Any, optional): Default value if key not found

        Returns:
            Any: Configuration value or default
        """
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_env(self, key: str, default: Any = None) -> Any:
        """
        Get environment variable.

        Args:
            key (str): Environment variable name
            default (Any, optional): Default value if environment variable not found

        Returns:
            Any: Environment variable value or default
        """
        return os.getenv(key, default)

    @property
    def base_url(self) -> str:
        """Get the base URL from config."""
        return self.get("base_url")

    @property
    def selectors(self) -> Dict[str, Any]:
        """Get selectors dictionary from config."""
        return self.get("selectors", {})


# Singleton instance
_config_manager = None


def get_config() -> ConfigManager:
    """
    Get the singleton ConfigManager instance.

    Returns:
        ConfigManager: Configuration manager instance
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
