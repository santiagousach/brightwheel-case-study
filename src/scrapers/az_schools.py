"""Arizona Schools scraper implementation."""

import time
from typing import Any, Dict, List, Optional
import re
import csv
import os
import logging

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tqdm import tqdm

from src.utils.helpers import (
    format_phone,
    parse_address,
    retry_on_exception,
    safe_get_text,
    wait_for_element,
)
from src.scrapers.base_scraper import BaseScraper


class AZSchoolsScraper(BaseScraper):
    """Scraper for Arizona Schools website (https://azreportcards.azed.gov/schools)."""

    def __init__(self, *args, **kwargs):
        """Initialize AZ Schools scraper."""
        super().__init__(*args, **kwargs)
        self.school_links = []
        self.schools_data = []
        self.school_names_dict = {}

    def extract_data(self) -> List[Dict[str, Any]]:
        """
        Main method to extract data from AZ Schools website.

        Returns:
            List[Dict[str, Any]]: Extracted school data
        """
        try:
            # Navigate to base URL
            base_url = self.config.base_url

            # Check if base_url is valid, otherwise use a default
            if not base_url:
                base_url = "https://azreportcards.azed.gov/schools"
                self.logger.warning(
                    f"No base URL provided in config, using default: {base_url}"
                )

            self.logger.info(f"Navigating to base URL: {base_url}")
            self.navigate_to(base_url)

            # Wait for page to fully load
            self.logger.info("Waiting for page to load...")
            time.sleep(5)

            # Log page title to confirm we're on the right page
            page_title = self.driver.title
            self.logger.info(f"Page title: {page_title}")

            # Check for Cloudflare protection
            if "Cloudflare" in page_title or "Attention Required" in page_title:
                self.logger.warning(
                    "Detected Cloudflare protection - unable to access the site"
                )
                self.logger.warning("Trying alternative URL...")
                # Try alternative URL
                alt_url = "https://www.azed.gov/edd/schools"
                self.logger.info(f"Navigating to alternative URL: {alt_url}")
                self.navigate_to(alt_url)
                time.sleep(5)
                page_title = self.driver.title
                self.logger.info(f"New page title: {page_title}")

            # Take a screenshot for debugging if not in headless mode
            if not self.headless:
                screenshot_path = "az_debug_screenshot.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

            # Close any overlays or popups that might be blocking interactions
            self._close_overlays()

            # Based on the screenshot, we'll iterate through the alphabetical navigation
            self._collect_school_links()

            # Extract data from each school page
            self._extract_school_details()

            return self.schools_data
        except Exception as e:
            self.logger.error(f"Error extracting data: {str(e)}")
            raise

    def _close_overlays(self) -> None:
        """Close any overlays or popups that might be blocking interactions."""
        try:
            # Look for various types of overlays and close buttons
            overlay_selectors = [
                ".v-overlay--active",  # From the error message
                ".modal-active",
                ".popup-container",
                ".cookie-notice",
                ".alert",
                ".v-dialog--active",
                "div[role='dialog']",
                "button.close",
                "button[aria-label='Close']",
                "button.v-dialog__close",
            ]

            for selector in overlay_selectors:
                try:
                    overlays = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for overlay in overlays:
                        if overlay.is_displayed():
                            self.logger.info(f"Found active overlay: {selector}")

                            # First try to find a close button within the overlay
                            close_buttons = overlay.find_elements(
                                By.CSS_SELECTOR,
                                "button.close, button[aria-label='Close'], .v-btn--icon, button.v-dialog__close",
                            )

                            if close_buttons:
                                for btn in close_buttons:
                                    if btn.is_displayed():
                                        self.logger.info("Clicking close button")
                                        try:
                                            btn.click()
                                        except:
                                            self.driver.execute_script(
                                                "arguments[0].click();", btn
                                            )
                                        time.sleep(1)
                                        break
                            else:
                                # Try to remove the overlay with JavaScript
                                self.logger.info(
                                    "Trying to remove overlay with JavaScript"
                                )
                                self.driver.execute_script(
                                    """
                                    var overlays = document.querySelectorAll('.v-overlay--active, .modal-active, .popup-container');
                                    overlays.forEach(function(overlay) {
                                        overlay.remove();
                                    });
                                """
                                )
                                time.sleep(1)
                except Exception as e:
                    self.logger.debug(
                        f"Error handling overlay with selector {selector}: {str(e)}"
                    )

            # Also try to press Escape key to close any active dialogs
            from selenium.webdriver.common.keys import Keys

            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(1)
            except:
                pass

        except Exception as e:
            self.logger.warning(f"Error closing overlays: {str(e)}")

    def _collect_school_links(self) -> None:
        """Collect all school links by navigating through alphabetical navigation."""
        self.logger.info("Collecting school links from alphabetical navigation")

        # Create a dict to store school names from the list page
        self.school_names_dict = {}

        # First try to get all schools at once by clicking the "ALL" button
        try:
            # Based on the screenshot, the button has a value attribute of "ALL"
            all_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[value='ALL']"
            )
            all_button.click()
            time.sleep(3)
            self._extract_links_from_current_page()

            # Check if we have schools, if yes, we don't need to go through letters
            if self.school_links:
                self.logger.info(
                    f"Found {len(self.school_links)} school links using ALL filter"
                )
                return
        except Exception as e:
            self.logger.debug(f"Could not use ALL filter: {str(e)}")

        # For testing, just use A-C for a limited test
        alphabet = "ABC"

        for letter in alphabet:
            try:
                self.logger.info(f"Processing schools starting with letter: {letter}")

                # Based on the screenshot, try these selectors for letter buttons
                letter_button = None
                button_selectors = [
                    f"button[value='{letter}']",  # From the screenshot, buttons have value attributes
                    f"button.v-btn[value='{letter}']",  # With additional class
                    f"button.v-btn--small[value='{letter}']",  # Another possible class
                    f"button.theme--light[value='{letter}']",  # From the screenshot
                    f"button.v-btn.v-btn--icon.v-btn--small.theme--light[value='{letter}']",  # Complete class
                    f"//button[@value='{letter}']",  # XPath alternative
                ]

                for selector in button_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        buttons = self.driver.find_elements(by_type, selector)
                        for btn in buttons:
                            if btn.is_displayed():
                                letter_button = btn
                                break
                        if letter_button:
                            break
                    except Exception:
                        pass

                if letter_button:
                    self.logger.info(f"Found and clicking button for letter: {letter}")
                    # Use JavaScript to click to avoid overlay issues
                    try:
                        self.driver.execute_script(
                            "arguments[0].click();", letter_button
                        )
                        time.sleep(2)
                    except Exception as e:
                        self.logger.warning(
                            f"Error clicking letter button with JS: {str(e)}"
                        )
                        continue

                    # Extract school links from this letter's page
                    initial_count = len(self.school_links)
                    self._extract_links_from_current_page()
                    new_count = len(self.school_links) - initial_count

                    self.logger.info(
                        f"Added {new_count} school links starting with {letter}"
                    )
                else:
                    self.logger.warning(f"Could not find button for letter: {letter}")
                    # Try to search for a school that starts with this letter as a fallback
                    self._search_for_letter(letter)

            except Exception as e:
                self.logger.error(f"Error processing letter {letter}: {str(e)}")
                # Try search as fallback
                self._search_for_letter(letter)

        # If still no links, try using direct school search
        if not self.school_links:
            self.logger.warning(
                "No school links found via alphabetical navigation, trying direct search"
            )
            sample_schools = ["Mitchell", "Paradise", "Academy"]
            for school in sample_schools:
                self._search_for_school(school)

        # If still no schools found after all attempts, use direct URL construction
        if not self.school_links:
            self.logger.warning(
                "No schools found after all attempts, using direct URLs"
            )
            self._use_direct_urls()

        self.logger.info(f"Collected a total of {len(self.school_links)} school links")

    def _use_direct_urls(self) -> None:
        """Add known school URLs directly to the list."""
        # These are actual school IDs from the Arizona Department of Education website
        school_ids = [
            "5958",  # A J Mitchell Elementary School
            "1000972",  # A+ Charter Schools
            "5768",  # A. C. E.
            "4276",  # AAEC - Paradise Valley
            "4285",  # AAEC - SMCC Campus
            "4287",  # AAEC Online
        ]

        for school_id in school_ids:
            school_url = f"https://azreportcards.azed.gov/schools/detail/{school_id}"
            if school_url not in self.school_links:
                self.school_links.append(school_url)
                self.logger.info(f"Added direct URL: {school_url}")

        self.logger.info(f"Added {len(school_ids)} direct school URLs")

    def _search_for_letter(self, letter):
        """Search for schools starting with a specific letter."""
        try:
            # Find search input
            search_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='text']"
            )
            search_input = None

            for input_elem in search_inputs:
                if input_elem.is_displayed():
                    placeholder = input_elem.get_attribute("placeholder") or ""
                    if (
                        "search" in placeholder.lower()
                        or "school" in placeholder.lower()
                    ):
                        search_input = input_elem
                        break

            if not search_input:
                # Try to find by XPath containing "Search by school name"
                search_input = self.driver.find_element(
                    By.XPATH, "//input[contains(@placeholder, 'Search by school name')]"
                )

            if search_input:
                # Clear any existing text
                search_input.clear()
                # Type the letter and a space to find schools starting with that letter
                search_input.send_keys(f"{letter}")
                time.sleep(1)

                # Look for a search button or just press Enter
                search_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(@class, 'search-button') or contains(@aria-label, 'search')]",
                )
                search_button = None
                for btn in search_buttons:
                    if btn.is_displayed():
                        search_button = btn
                        break

                if search_button:
                    search_button.click()
                else:
                    # Press Enter if no search button found
                    from selenium.webdriver.common.keys import Keys

                    search_input.send_keys(Keys.RETURN)

                time.sleep(2)
                self._extract_links_from_current_page()

        except Exception as e:
            self.logger.error(f"Error in search for letter {letter}: {str(e)}")

    def _search_for_school(self, school_name):
        """Search for a specific school name."""
        try:
            # Find search input - same as above but with specific school name
            search_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='text']"
            )
            search_input = None

            for input_elem in search_inputs:
                if input_elem.is_displayed():
                    placeholder = input_elem.get_attribute("placeholder") or ""
                    if (
                        "search" in placeholder.lower()
                        or "school" in placeholder.lower()
                    ):
                        search_input = input_elem
                        break

            if not search_input:
                # Try to find by XPath containing "Search by school name"
                search_input = self.driver.find_element(
                    By.XPATH, "//input[contains(@placeholder, 'Search by school name')]"
                )

            if search_input:
                # Clear any existing text
                search_input.clear()
                # Type the school name
                search_input.send_keys(school_name)
                time.sleep(1)

                # Look for a search button or just press Enter
                search_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(@class, 'search-button') or contains(@aria-label, 'search')]",
                )
                search_button = None
                for btn in search_buttons:
                    if btn.is_displayed():
                        search_button = btn
                        break

                if search_button:
                    search_button.click()
                else:
                    # Press Enter if no search button found
                    from selenium.webdriver.common.keys import Keys

                    search_input.send_keys(Keys.RETURN)

                time.sleep(2)
                self._extract_links_from_current_page()

        except Exception as e:
            self.logger.error(f"Error in search for school {school_name}: {str(e)}")

    def _extract_links_from_current_page(self) -> None:
        """Extract school links from the current page."""
        try:
            # Wait for the school list to load
            time.sleep(2)

            # Take a screenshot for debugging
            if not self.headless:
                screenshot_path = "az_links_extraction.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

            # Based on the screenshots, there are three columns of schools, each with links
            # Try these selectors in order of specificity
            school_link_selectors = [
                "a.no-underline",  # From the screenshot, links have this class
                "a[href*='/schools/detail/']",  # Links to school details
                "p.entity_name.body-2.primary-text a",  # From the class seen in the screenshot
                "div.flex.dflex.xs12.sm6.md4 a",  # Flex container with links
                "div.layout.row.wrap a",  # Another container pattern seen in screenshot
                "a",  # Fallback to all links
            ]

            links_found = False
            for selector in school_link_selectors:
                try:
                    self.logger.info(f"Trying selector: {selector}")
                    links = self.driver.find_elements(By.CSS_SELECTOR, selector)

                    if links:
                        self.logger.info(
                            f"Found {len(links)} potential school links with selector: {selector}"
                        )

                        new_links_added = 0
                        for link in links:
                            href = link.get_attribute("href")
                            text = link.text.strip()

                            # Check if this is a school link - must have href and text
                            if (
                                href
                                and text
                                and "schools/detail" in href
                                and href not in self.school_links
                            ):
                                self.school_links.append(href)
                                # Store the name from the link text in our dictionary
                                self.school_names_dict[href] = text
                                new_links_added += 1

                                # Log the first few links for debugging
                                if len(self.school_links) <= 3:
                                    self.logger.info(
                                        f"Added school link: {text} - {href}"
                                    )

                        if new_links_added > 0:
                            self.logger.info(
                                f"Added {new_links_added} school links with selector: {selector}"
                            )
                            links_found = True
                            break
                except Exception as e:
                    self.logger.debug(f"Error with selector {selector}: {str(e)}")

            # If no school links found with specific selectors, try a more general approach by checking text content
            if not links_found:
                self.logger.warning(
                    "No school links found with specific selectors, trying general approach"
                )

                # Get all links on the page
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                new_links_added = 0

                for link in all_links:
                    try:
                        href = link.get_attribute("href")
                        text = link.text.strip()

                        # Look for text that indicates a school (common school terms)
                        if (
                            href
                            and text
                            and text
                            not in (
                                "ALL",
                                "A",
                                "B",
                                "C",
                                "D",
                                "E",
                                "F",
                                "G",
                                "H",
                                "I",
                                "J",
                                "K",
                                "L",
                                "M",
                                "N",
                                "O",
                                "P",
                                "Q",
                                "R",
                                "S",
                                "T",
                                "U",
                                "V",
                                "W",
                                "X",
                                "Y",
                                "Z",
                            )
                        ):
                            school_keywords = [
                                "elementary",
                                "middle",
                                "high school",
                                "academy",
                                "school",
                                "charter",
                                "education",
                            ]

                            # Check if the link text contains any school keywords
                            if (
                                any(
                                    keyword in text.lower()
                                    for keyword in school_keywords
                                )
                                or "school" in href
                            ):
                                if href not in self.school_links:
                                    self.school_links.append(href)
                                    # Store the name from the link text
                                    self.school_names_dict[href] = text
                                    new_links_added += 1
                    except Exception:
                        continue

                if new_links_added > 0:
                    self.logger.info(
                        f"Added {new_links_added} school links with general text approach"
                    )

        except Exception as e:
            self.logger.error(f"Error extracting links from current page: {str(e)}")

    def _handle_pagination(self) -> None:
        """Handle pagination by clicking through page numbers if present."""
        page = 1
        has_next_page = True

        while has_next_page:
            try:
                # Look for next page button/link
                next_buttons = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(@aria-label, 'next') or contains(text(), 'Next')]",
                )

                next_button = None
                for btn in next_buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        next_button = btn
                        break

                if next_button:
                    page += 1
                    self.logger.info(f"Moving to page {page}")
                    next_button.click()
                    time.sleep(2)

                    # Extract links from this page
                    initial_count = len(self.school_links)
                    self._extract_links_from_current_page()
                    new_count = len(self.school_links) - initial_count

                    self.logger.info(f"Added {new_count} school links from page {page}")

                    # If no new links found, we might be done
                    if new_count == 0:
                        has_next_page = False
                else:
                    has_next_page = False

            except Exception as e:
                self.logger.error(f"Error handling pagination: {str(e)}")
                has_next_page = False

    def _extract_school_details(self) -> None:
        """Extract details from each school page."""
        self.logger.info(
            f"Extracting details from {len(self.school_links)} school pages"
        )

        # Limit to only 3 schools for testing
        schools_to_process = self.school_links[:3]
        self.logger.info(f"Testing with first 3 schools only")

        for i, school_url in enumerate(tqdm(schools_to_process)):
            school_data = {
                "company": "",
                "address1": "",
                "address2": "",
                "city": "",
                "state": "",
                "zip": "",
                "phone": "",
                "website": "",
                "grades_served": "",
                "district": "",
            }

            try:
                self.logger.info(
                    f"Processing school {i+1}/{len(schools_to_process)}: {school_url}"
                )

                # First, check if we already have the school name from the list page
                if school_url in self.school_names_dict:
                    school_name = self.school_names_dict[school_url]
                    if school_name:
                        school_data["company"] = school_name
                        self.logger.info(f"Using stored school name: {school_name}")

                # Navigate to school page
                self.navigate_to(school_url)
                time.sleep(2)

                # Take screenshot of first school page for debugging
                if i == 0 and not self.headless:
                    screenshot_path = "az_first_school_page.png"
                    self.driver.save_screenshot(screenshot_path)
                    self.logger.info(f"Screenshot saved to {screenshot_path}")

                # If we don't have a school name from the list page, try to extract it from the detail page
                if not school_data["company"]:
                    # Based on the screenshots, extract the school name
                    # New, more accurate selectors based on the DOM inspection
                    school_name_selectors = [
                        "p.entity_name.body-2.primary-text",  # From DOM inspection
                        "p.text-xs-center",  # Alternate class
                        "h1",  # Fallback to any h1
                        ".school-header h1",  # Another possible structure
                        "div.school-header",  # Container that might have the name
                    ]

                    for selector in school_name_selectors:
                        try:
                            name_elems = self.driver.find_elements(
                                By.CSS_SELECTOR, selector
                            )
                            for elem in name_elems:
                                if elem.is_displayed() and elem.text.strip():
                                    school_data["company"] = elem.text.strip()
                                    self.logger.info(
                                        f"Found school name: {school_data['company']}"
                                    )
                                    break
                            if school_data["company"]:
                                break
                        except Exception as e:
                            self.logger.debug(
                                f"Error finding school name with selector {selector}: {str(e)}"
                            )

                # If still no name found, try using the URL
                if not school_data["company"]:
                    try:
                        # Extract school ID from URL for debugging
                        school_id = school_url.split("/")[-1]
                        self.logger.info(f"Extracting from URL, school ID: {school_id}")

                        # Try to extract from URL using a regex pattern
                        import re

                        url_pattern = r"/schools/detail/(\d+)(?:/([^/]+))?"
                        match = re.search(url_pattern, school_url)
                        if match:
                            school_id = match.group(1)
                            # Try to use school name from URL if available
                            if match.group(2):
                                school_name = match.group(2).replace("-", " ").title()
                                school_data["company"] = school_name
                                self.logger.info(
                                    f"Extracted school name from URL: {school_name}"
                                )

                        # If still no name, try a broader page search
                        if not school_data["company"]:
                            page_text = self.driver.find_element(
                                By.TAG_NAME, "body"
                            ).text

                            # Look for common school name patterns in the page
                            school_keywords = [
                                "Elementary",
                                "Middle",
                                "High School",
                                "Academy",
                                "School",
                            ]
                            lines = page_text.split("\n")

                            for line in lines:
                                if (
                                    any(keyword in line for keyword in school_keywords)
                                    and len(line) < 100
                                ):
                                    school_data["company"] = line.strip()
                                    self.logger.info(
                                        f"Found school name from page: {school_data['company']}"
                                    )
                                    break
                    except Exception as e:
                        self.logger.debug(
                            f"Error extracting school name from page: {str(e)}"
                        )

                # Extract district information
                district_selectors = [
                    "span.title",  # Based on DOM inspection
                    ".district-info p",  # Another possible structure
                    "p.subtitle",  # Possible district indicator
                ]

                for selector in district_selectors:
                    try:
                        district_elems = self.driver.find_elements(
                            By.CSS_SELECTOR, selector
                        )
                        for elem in district_elems:
                            text = elem.text.strip()
                            # Check if this is a district name (usually contains "District", "USD", or "School District")
                            if text and (
                                "District" in text or "USD" in text or "Unified" in text
                            ):
                                school_data["district"] = text
                                self.logger.info(
                                    f"Found district: {school_data['district']}"
                                )
                                break

                        if school_data["district"]:
                            break
                    except Exception as e:
                        self.logger.debug(
                            f"Error finding district with selector {selector}: {str(e)}"
                        )

                # Extract address from detailed contact information section
                try:
                    # Try to find contact information section
                    contact_sections = self.driver.find_elements(
                        By.XPATH,
                        "//h3[contains(text(), 'Contact Information')]/following-sibling::div",
                    )

                    if contact_sections:
                        contact_section = contact_sections[0]
                        contact_text = contact_section.text
                        self.logger.info(f"Found contact section: {contact_text}")

                        # Look for Arizona address pattern in the text (City, AZ ZIP)
                        address_pattern = (
                            r"([^,]+),\s*([^,]+),\s*AZ\s+(\d{5}(?:-\d{4})?)"
                        )
                        import re

                        address_matches = re.search(address_pattern, contact_text)

                        if address_matches:
                            address1 = address_matches.group(1).strip()
                            city = address_matches.group(2).strip()
                            zip_code = address_matches.group(3).strip()

                            school_data["address1"] = address1
                            school_data["city"] = city
                            school_data["state"] = "AZ"
                            school_data["zip"] = zip_code

                            self.logger.info(
                                f"Extracted address: {address1}, {city}, AZ {zip_code}"
                            )

                        # Look for phone number in the contact text (using general pattern)
                        phone_pattern = r"(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
                        phone_matches = re.search(phone_pattern, contact_text)

                        if phone_matches:
                            phone = phone_matches.group(1)
                            school_data["phone"] = format_phone(phone)
                            self.logger.info(f"Extracted phone: {school_data['phone']}")

                except Exception as e:
                    self.logger.debug(f"Error extracting contact info: {str(e)}")

                # Extract website from links
                website_selectors = [
                    "a[href*='http']:not([href*='azreportcards.azed.gov']):not([href*='maps.google.com'])",
                    "//a[contains(text(), 'Website')]",
                    "//a[contains(text(), 'website')]",
                    "//a[contains(text(), 'School Website')]",
                ]

                for selector in website_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        website_elems = self.driver.find_elements(by_type, selector)

                        for elem in website_elems:
                            href = elem.get_attribute("href")
                            if (
                                href
                                and "azreportcards.azed.gov" not in href
                                and "maps.google.com" not in href
                                and not href.startswith("mailto:")
                            ):
                                school_data["website"] = normalize_url(href)
                                self.logger.info(
                                    f"Found website: {school_data['website']}"
                                )
                                break

                        if school_data["website"]:
                            break
                    except Exception as e:
                        self.logger.debug(
                            f"Error finding website with selector {selector}: {str(e)}"
                        )

                # Parse Google Maps URL for address if we don't have address yet
                if (
                    not school_data["address1"]
                    and school_data["website"]
                    and "maps.google.com" in school_data["website"]
                ):
                    try:
                        self._parse_google_maps_url(school_data)
                    except Exception as e:
                        self.logger.debug(f"Error parsing Google Maps URL: {str(e)}")

                # Look for Google Maps links if we still don't have an address
                if not school_data["address1"]:
                    try:
                        maps_links = self.driver.find_elements(
                            By.CSS_SELECTOR, "a[href*='maps.google.com']"
                        )
                        if maps_links:
                            maps_url = maps_links[0].get_attribute("href")
                            if maps_url:
                                self._parse_google_maps_url(school_data, maps_url)
                    except Exception as e:
                        self.logger.debug(f"Error finding Google Maps link: {str(e)}")

                # Extract grades served
                grades_selectors = [
                    "//div[contains(text(), 'Grades')]/following-sibling::div",
                    "//span[contains(text(), 'Grades')]/following-sibling::span",
                    "//p[contains(text(), 'Grades')]",
                ]

                for selector in grades_selectors:
                    try:
                        grade_elems = self.driver.find_elements(By.XPATH, selector)

                        for elem in grade_elems:
                            text = elem.text.strip()
                            if text:
                                # If the text includes "Grades:", extract just the part after it
                                if "Grades:" in text:
                                    text = text.split("Grades:", 1)[1].strip()
                                elif "Grades" in text:
                                    text = text.split("Grades", 1)[1].strip()
                                    # Remove any leading punctuation
                                    text = text.lstrip(":")

                                school_data["grades_served"] = text.strip()
                                self.logger.info(
                                    f"Found grades: {school_data['grades_served']}"
                                )
                                break

                        if school_data["grades_served"]:
                            break
                    except Exception as e:
                        self.logger.debug(
                            f"Error finding grades with selector {selector}: {str(e)}"
                        )

                # Add to our data collection if we have at least a school name
                if school_data["company"]:
                    self.schools_data.append(school_data)
                    self.logger.info(f"Extracted data for: {school_data['company']}")
                else:
                    self.logger.warning(
                        f"Could not extract school name for URL: {school_url}"
                    )

                # Respect the site by waiting between requests
                time.sleep(1)

            except Exception as e:
                self.logger.error(
                    f"Error extracting details for school {school_url}: {str(e)}"
                )

        self.logger.info(f"Extracted details for {len(self.schools_data)} schools")

    def _parse_google_maps_url(
        self, school_data: Dict[str, Any], maps_url: Optional[str] = None
    ) -> None:
        """
        Parse a Google Maps URL to extract address information.

        Args:
            school_data: Dictionary to update with extracted address
            maps_url: Optional Google Maps URL to parse, if not provided uses school_data["website"]
        """
        url = maps_url or school_data["website"]

        if not url or "maps.google.com" not in url:
            return

        self.logger.info(f"Parsing Google Maps URL for address: {url}")

        try:
            # Extract the 'q' parameter which contains the address
            import urllib.parse

            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)

            if "q" in query_params:
                address = query_params["q"][0]
                self.logger.info(f"Extracted address from Maps URL: {address}")

                # Try to parse the address components
                address_parts = address.split(",")

                if len(address_parts) >= 3:
                    # Format typically: STREET, CITY, AZ ZIP
                    school_data["address1"] = address_parts[0].strip()
                    school_data["city"] = address_parts[1].strip()

                    # Last part typically contains state and zip
                    state_zip = address_parts[2].strip()
                    state_zip_parts = state_zip.split()

                    if len(state_zip_parts) >= 2:
                        school_data["state"] = state_zip_parts[0].strip()
                        school_data["zip"] = state_zip_parts[1].strip()

                        # Some zip codes include a hyphen with extended code
                        if len(address_parts) > 3 and "-" in address_parts[3]:
                            school_data["zip"] += address_parts[3].strip()

                    self.logger.info(
                        f"Parsed address: {school_data['address1']}, {school_data['city']}, {school_data['state']} {school_data['zip']}"
                    )

                    # Store the maps URL in a separate field if we don't have an actual website
                    if not school_data["website"] or school_data["website"] == url:
                        school_data["website"] = ""

        except Exception as e:
            self.logger.error(f"Error parsing Google Maps URL: {str(e)}")

        # Special case for AZ schools website - update if needed
        if school_data["website"] == url:
            school_data["website"] = ""


def normalize_url(url):
    """Normalize a URL to ensure it's properly formatted."""
    if not url:
        return ""

    # Ensure the URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    # Remove trailing slashes
    url = url.rstrip("/")

    return url
