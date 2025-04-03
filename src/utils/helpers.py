"""Helper utilities for data extraction and processing."""

import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.utils.config import get_config
from src.utils.logging import get_logger

logger = get_logger()


def parse_address(address_text: str) -> Dict[str, str]:
    """
    Parse address text into components using regex patterns from config.

    Args:
        address_text (str): Full address text

    Returns:
        Dict[str, str]: Dictionary with address components
    """
    config = get_config()
    pattern = config.get("patterns.address.pattern")
    groups = config.get("patterns.address.groups", [])

    if not pattern or not groups:
        logger.warning("Address parsing pattern not found in config")
        return {
            "address1": address_text,
            "address2": "",
            "city": "",
            "state": "",
            "zip": "",
        }

    # Default empty address dict
    address_dict = {group: "" for group in groups}

    # Try to parse with regex
    match = re.search(pattern, address_text)
    if match:
        for i, group in enumerate(groups, 1):
            if i <= len(match.groups()):
                address_dict[group] = match.group(i) or ""
    else:
        # Fallback: put full text in address1
        address_dict["address1"] = address_text

    return address_dict


def format_phone(phone_text: str) -> str:
    """
    Format phone number to standard format.

    Args:
        phone_text (str): Raw phone number text

    Returns:
        str: Formatted phone number
    """
    config = get_config()
    pattern = config.get("patterns.phone.pattern")

    if not pattern:
        return phone_text.strip()

    # Extract digits
    digits = re.sub(r"\D", "", phone_text)

    # If we have 10 digits, format as (XXX) XXX-XXXX
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"

    return phone_text.strip()


def normalize_url(url: str) -> str:
    """
    Normalize URL by ensuring it has a scheme and removing trailing slash.

    Args:
        url (str): URL to normalize

    Returns:
        str: Normalized URL
    """
    if not url:
        return ""

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # Parse URL
    parsed = urlparse(url)

    # Normalize and rebuild
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    # Add query if present
    if parsed.query:
        normalized += f"?{parsed.query}"

    return normalized


def safe_get_text(element: Optional[WebElement]) -> str:
    """
    Safely get text from an element, handling None case.

    Args:
        element (WebElement, optional): Web element to get text from

    Returns:
        str: Element text or empty string
    """
    if element is None:
        return ""

    try:
        return element.text.strip()
    except Exception as e:
        logger.debug(f"Error getting text from element: {e}")
        return ""


def wait_for_element(
    driver: WebDriver,
    locator: Tuple[str, str],
    timeout: Optional[int] = None,
    visible: bool = True,
) -> Optional[WebElement]:
    """
    Wait for element to be present or visible.

    Args:
        driver (WebDriver): Selenium WebDriver
        locator (Tuple[str, str]): Locator tuple (By.XXX, "selector")
        timeout (int, optional): Wait timeout in seconds
        visible (bool): Wait for visibility or just presence

    Returns:
        WebElement, optional: Found element or None
    """
    config = get_config()
    if timeout is None:
        timeout = int(config.get("element_wait_timeout", 5))

    try:
        condition = (
            EC.visibility_of_element_located
            if visible
            else EC.presence_of_element_located
        )
        return WebDriverWait(driver, timeout).until(condition(locator))
    except TimeoutException:
        return None


def retry_on_exception(
    func: callable,
    max_attempts: int = 3,
    delay: int = 2,
    exceptions: tuple = (Exception,),
) -> Any:
    """
    Retry a function call on exception.

    Args:
        func (callable): Function to call
        max_attempts (int): Maximum number of attempts
        delay (int): Delay between attempts in seconds
        exceptions (tuple): Exceptions to catch and retry on

    Returns:
        Any: Function result
    """
    config = get_config()
    max_attempts = int(config.get("retry_attempts", max_attempts))
    delay = int(config.get("retry_delay", delay))

    attempt = 0
    last_exception = None

    while attempt < max_attempts:
        try:
            return func()
        except exceptions as e:
            attempt += 1
            last_exception = e

            if attempt < max_attempts:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed: {str(e)}. "
                    f"Retrying in {delay} seconds..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"All {max_attempts} attempts failed. " f"Last error: {str(e)}"
                )

    # Re-raise last exception
    if last_exception:
        raise last_exception

    return None
