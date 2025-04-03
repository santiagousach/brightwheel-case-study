"""Base scraper implementation with common functionality."""

import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from src.utils.config import ConfigManager, get_config
from src.utils.logging import get_logger


class BaseScraper(ABC):
    """Base scraper class that defines interface and common functionality."""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        headless: Optional[bool] = None,
    ):
        """
        Initialize the base scraper.

        Args:
            config (ConfigManager, optional): Configuration manager
            headless (bool, optional): Whether to run browser in headless mode
        """
        self.logger = get_logger()
        self.config = config or get_config()

        # Set headless mode from env if not provided
        if headless is None:
            headless_str = self.config.get_env("HEADLESS_BROWSER", "true")
            self.headless = headless_str.lower() in ("true", "1", "yes")
        else:
            self.headless = headless

        self.driver = None
        self.data = []

    def setup_driver(self) -> webdriver.Chrome:
        """
        Set up and configure Selenium WebDriver.

        Returns:
            webdriver.Chrome: Configured Chrome WebDriver
        """
        self.logger.info("Setting up Chrome WebDriver")

        chrome_options = Options()

        # Set a realistic user agent
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        # Add Cloudflare bypass improvements
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        if self.headless:
            chrome_options.add_argument("--headless=new")
            # These settings make headless Chrome more similar to regular Chrome
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option(
                "excludeSwitches", ["enable-automation"]
            )
            chrome_options.add_experimental_option("useAutomationExtension", False)

        # Add common options for stability
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=en-US")

        # Additional settings to mimic real browser
        chrome_options.add_argument(
            "--disable-features=IsolateOrigins,site-per-process"
        )
        chrome_options.add_argument("--blink-settings=imagesEnabled=true")

        # Check for custom Chrome binary path
        chrome_bin = os.environ.get("CHROME_BIN")
        if chrome_bin:
            self.logger.info(f"Using custom Chrome binary: {chrome_bin}")
            chrome_options.binary_location = chrome_bin

        # Set up ChromeDriver
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
        if chromedriver_path:
            self.logger.info(f"Using custom ChromeDriver: {chromedriver_path}")
            service = Service(executable_path=chromedriver_path)
        else:
            # Use ChromeDriverManager for automatic driver management
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=chrome_options)

        # Set page load timeout from config
        timeout = int(self.config.get("wait_timeout", 10))
        driver.set_page_load_timeout(timeout)

        # Execute CDP commands to set navigator properties
        if self.headless:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                window.chrome = {
                    runtime: {}
                };
                """
                },
            )

        return driver

    def start(self) -> None:
        """
        Start the scraper by initializing WebDriver.
        """
        self.driver = self.setup_driver()

    def stop(self) -> None:
        """
        Stop the scraper and clean up resources.
        """
        if self.driver:
            self.logger.info("Closing WebDriver")
            self.driver.quit()
            self.driver = None

    @abstractmethod
    def extract_data(self) -> List[Dict[str, Any]]:
        """
        Main method to extract data. Must be implemented by subclasses.

        Returns:
            List[Dict[str, Any]]: Extracted data as list of dictionaries
        """
        pass

    def run(self) -> List[Dict[str, Any]]:
        """
        Run the scraping process from start to finish.

        Returns:
            List[Dict[str, Any]]: Extracted data
        """
        try:
            self.start()
            self.logger.info("Starting data extraction")
            data = self.extract_data()
            self.logger.info(f"Extracted {len(data)} records")
            return data
        except Exception as e:
            self.logger.error(f"Error during scraping: {str(e)}")
            raise
        finally:
            self.stop()

    def navigate_to(self, url: str, delay: Optional[float] = None) -> None:
        """
        Navigate to a specified URL.

        Args:
            url: URL to navigate to
            delay: Optional delay after navigation
        """
        if not self.driver:
            raise RuntimeError("WebDriver not initialized. Call start() first.")

        if not url:
            raise ValueError("URL cannot be None or empty")

        if not isinstance(url, str):
            raise TypeError(f"URL must be a string, got {type(url).__name__}")

        # Add retry mechanism for more resilience
        max_retries = 3
        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                self.logger.debug(
                    f"Navigating to: {url} (attempt {retry_count + 1}/{max_retries})"
                )
                self.driver.get(url)
                break  # Success, exit the retry loop
            except Exception as e:
                last_error = e
                retry_count += 1
                self.logger.warning(
                    f"Error navigating to {url}: {str(e)}. Attempt {retry_count}/{max_retries}"
                )
                if retry_count < max_retries:
                    # Wait before retrying (increasing backoff)
                    backoff_time = 2**retry_count
                    self.logger.info(f"Waiting {backoff_time}s before retrying...")
                    time.sleep(backoff_time)

        # If all retries failed, log but continue (we might still be able to extract some data)
        if retry_count == max_retries and last_error:
            self.logger.error(
                f"Failed to navigate to {url} after {max_retries} attempts: {str(last_error)}"
            )

        # Apply delay if provided or from config
        if delay is None:
            delay = float(self.config.get_env("DELAY_BETWEEN_REQUESTS", 1.0))

        if delay > 0:
            time.sleep(delay)

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
