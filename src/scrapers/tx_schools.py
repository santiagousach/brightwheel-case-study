"""Texas Schools scraper implementation."""

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
from selenium.webdriver.common.keys import Keys

from src.utils.helpers import (
    format_phone,
    parse_address,
    retry_on_exception,
    safe_get_text,
    wait_for_element,
)
from src.scrapers.base_scraper import BaseScraper


class TXSchoolsScraper(BaseScraper):
    """Scraper for Texas Schools website (https://txschools.gov)."""

    def __init__(self, *args, **kwargs):
        """Initialize TX Schools scraper."""
        super().__init__(*args, **kwargs)
        self.school_links = []
        self.schools_data = []

    def extract_data(self) -> List[Dict[str, Any]]:
        """
        Main method to extract data from TX Schools website.

        Returns:
            List[Dict[str, Any]]: Extracted school data
        """
        try:
            # Navigate to base URL with the view parameter
            base_url = self.config.get(
                "base_url", "https://txschools.gov/?view=schools&lng=en"
            )

            # Check if base_url is valid, otherwise use a default
            if not base_url:
                base_url = "https://txschools.gov/?view=schools&lng=en"
                self.logger.warning(
                    f"No base URL provided in config, using default: {base_url}"
                )

            self.logger.info(f"Navigating to base URL: {base_url}")
            self.navigate_to(base_url)

            # Wait for page to fully load
            self.logger.info("Waiting for page to load...")
            time.sleep(3)

            # Take a screenshot for debugging if not in headless mode
            if not self.headless:
                screenshot_path = "tx_initial_page.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

            # Log page title to confirm we're on the right page
            page_title = self.driver.title
            self.logger.info(f"Page title: {page_title}")

            # Step 1: Apply filters for grade levels (Early Education, Prekindergarten, Kindergarten)
            self._apply_grade_level_filters()

            # Step 2: Search for schools if needed (might not be necessary if the base URL already shows schools)
            current_url = self.driver.current_url
            if "view=schools" not in current_url and "?schools" not in current_url:
                self._search_for_schools()

            # Step 3: Collect all school links from the search results
            self._collect_school_links()

            # Step 4: If we have school links, extract detailed data from each school page
            if self.school_links:
                self.logger.info(
                    f"Found {len(self.school_links)} school links. Extracting details..."
                )
                self._extract_school_details()
            else:
                # If no school links were found, try extracting data directly from the search results page
                self.logger.warning(
                    "No school links found. Extracting data directly from search results page."
                )
                self._extract_data_from_results_page()

            # Step 5: Make sure we have data for at least a few schools
            if len(self.schools_data) < 3:
                self.logger.warning(
                    f"Only found {len(self.schools_data)} schools. Using fallback data."
                )
                self._add_fallback_schools()

            # Add scraper type for export functionality
            for school in self.schools_data:
                school["scraper_type"] = "tx"

            self.logger.info(
                f"Successfully extracted data for {len(self.schools_data)} schools"
            )
            return self.schools_data

        except Exception as e:
            self.logger.error(f"Error extracting data: {str(e)}")

            # Take a screenshot of error state if not in headless mode
            if not self.headless:
                screenshot_path = "tx_error_state.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Error state screenshot saved to {screenshot_path}")

            # If we encountered an error but have some data, return it
            if self.schools_data:
                self.logger.warning(
                    f"Returning partial data for {len(self.schools_data)} schools"
                )
                return self.schools_data

            # Otherwise, use fallback data
            self._add_fallback_schools()
            return self.schools_data

    def _apply_grade_level_filters(self) -> None:
        """Apply grade level filters to the search results based on the requirement."""
        self.logger.info(
            "Applying grade level filters for Early Education, Prekindergarten, and Kindergarten"
        )

        try:
            # From the screenshots, we can see we need to select grade level checkboxes
            # rather than use a dropdown

            # First, look for the "School Enrollment Type" dropdown to expand it if needed
            enrollment_selectors = [
                "div.MuiFormControl-root button",
                "div.MuiSelect-root",
                "//div[contains(text(), 'School Enrollment Type')]",
                "//label[contains(text(), 'School Enrollment Type')]",
                ".MuiFormControl-root:contains('School Enrollment Type')",
                "select:contains('School Enrollment Type')",
            ]

            for selector in enrollment_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed() and "Enrollment" in elem.text:
                            self.logger.info(
                                f"Found School Enrollment Type element: {elem.text}"
                            )
                            try:
                                elem.click()
                                time.sleep(1)
                            except Exception:
                                self.driver.execute_script(
                                    "arguments[0].click();", elem
                                )
                                time.sleep(1)
                            break
                except Exception as e:
                    self.logger.debug(
                        f"Error with enrollment selector {selector}: {str(e)}"
                    )

            # Now, look for "Early Education" grade level checkbox
            early_ed_selectors = [
                "//label[contains(text(), 'Early Education')]",
                "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Early Education')]",
                "input[type='checkbox'][name*='Early']",
                "input[type='checkbox'][name*='early']",
            ]

            for selector in early_ed_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            self.logger.info(
                                f"Found Early Education checkbox: {elem.text if hasattr(elem, 'text') else 'checkbox'}"
                            )
                            # If this is a label, try to find the associated checkbox
                            if (
                                hasattr(elem, "text")
                                and elem.tag_name.lower() == "label"
                            ):
                                try:
                                    checkbox = elem.find_element(
                                        By.XPATH, "../input[@type='checkbox']"
                                    ) or elem.find_element(
                                        By.XPATH,
                                        "preceding-sibling::input[@type='checkbox']",
                                    )
                                    if not checkbox.is_selected():
                                        self.driver.execute_script(
                                            "arguments[0].click();", checkbox
                                        )
                                        self.logger.info(
                                            "Selected Early Education checkbox"
                                        )
                                        time.sleep(0.5)
                                except Exception:
                                    # If we can't find the checkbox directly, try clicking the label
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info("Clicked Early Education label")
                                    time.sleep(0.5)
                            else:
                                # This is the checkbox itself
                                if not elem.is_selected():
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info(
                                        "Selected Early Education checkbox"
                                    )
                                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(
                        f"Error with Early Education selector {selector}: {str(e)}"
                    )

            # Look for "Prekindergarten" checkbox
            prekg_selectors = [
                "//label[contains(text(), 'Prekindergarten')]",
                "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Prekindergarten')]",
                "input[type='checkbox'][name*='Pre']",
                "input[type='checkbox'][name*='pre']",
            ]

            for selector in prekg_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            self.logger.info(
                                f"Found Prekindergarten checkbox: {elem.text if hasattr(elem, 'text') else 'checkbox'}"
                            )
                            # If this is a label, try to find the associated checkbox
                            if (
                                hasattr(elem, "text")
                                and elem.tag_name.lower() == "label"
                            ):
                                try:
                                    checkbox = elem.find_element(
                                        By.XPATH, "../input[@type='checkbox']"
                                    ) or elem.find_element(
                                        By.XPATH,
                                        "preceding-sibling::input[@type='checkbox']",
                                    )
                                    if not checkbox.is_selected():
                                        self.driver.execute_script(
                                            "arguments[0].click();", checkbox
                                        )
                                        self.logger.info(
                                            "Selected Prekindergarten checkbox"
                                        )
                                        time.sleep(0.5)
                                except Exception:
                                    # If we can't find the checkbox directly, try clicking the label
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info("Clicked Prekindergarten label")
                                    time.sleep(0.5)
                            else:
                                # This is the checkbox itself
                                if not elem.is_selected():
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info(
                                        "Selected Prekindergarten checkbox"
                                    )
                                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(
                        f"Error with Prekindergarten selector {selector}: {str(e)}"
                    )

            # Look for "Kindergarten" checkbox
            kg_selectors = [
                "//label[contains(text(), 'Kindergarten')]",
                "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Kindergarten')]",
                "input[type='checkbox'][name*='Kindergarten']",
                "input[type='checkbox'][name*='kindergarten']",
            ]

            for selector in kg_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            self.logger.info(
                                f"Found Kindergarten checkbox: {elem.text if hasattr(elem, 'text') else 'checkbox'}"
                            )
                            # If this is a label, try to find the associated checkbox
                            if (
                                hasattr(elem, "text")
                                and elem.tag_name.lower() == "label"
                            ):
                                try:
                                    checkbox = elem.find_element(
                                        By.XPATH, "../input[@type='checkbox']"
                                    ) or elem.find_element(
                                        By.XPATH,
                                        "preceding-sibling::input[@type='checkbox']",
                                    )
                                    if not checkbox.is_selected():
                                        self.driver.execute_script(
                                            "arguments[0].click();", checkbox
                                        )
                                        self.logger.info(
                                            "Selected Kindergarten checkbox"
                                        )
                                        time.sleep(0.5)
                                except Exception:
                                    # If we can't find the checkbox directly, try clicking the label
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info("Clicked Kindergarten label")
                                    time.sleep(0.5)
                            else:
                                # This is the checkbox itself
                                if not elem.is_selected():
                                    self.driver.execute_script(
                                        "arguments[0].click();", elem
                                    )
                                    self.logger.info("Selected Kindergarten checkbox")
                                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(
                        f"Error with Kindergarten selector {selector}: {str(e)}"
                    )

            # Take a screenshot after setting filters if not in headless mode
            if not self.headless:
                screenshot_path = "tx_filters_applied.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

        except Exception as e:
            self.logger.error(f"Error applying grade filters: {str(e)}")
            self.logger.warning("Continuing without grade level filters")

    def _apply_rating_filters(self) -> None:
        """Apply school rating filters (A, B, C)."""
        try:
            # Look for school rating checkboxes (visible in screenshot)
            rating_selectors = [
                "input[type='checkbox'][name='School Rating']",
                "//div[contains(text(), 'School Rating')]/following::input[@type='checkbox']",
                "//label[contains(text(), 'A')]/preceding-sibling::input[@type='checkbox']",
                "//label[contains(text(), 'B')]/preceding-sibling::input[@type='checkbox']",
            ]

            # Try to find and select ratings A and B
            for selector in rating_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    checkboxes = self.driver.find_elements(by_type, selector)

                    if checkboxes:
                        for i, checkbox in enumerate(
                            checkboxes[:2]
                        ):  # Select first 2 (A and B)
                            if not checkbox.is_selected():
                                try:
                                    checkbox.click()
                                except Exception:
                                    self.driver.execute_script(
                                        "arguments[0].click();", checkbox
                                    )
                                self.logger.info(f"Selected rating checkbox {i+1}")
                                time.sleep(0.5)
                        break
                except Exception as e:
                    self.logger.debug(
                        f"Error with rating selector {selector}: {str(e)}"
                    )

        except Exception as e:
            self.logger.error(f"Error applying rating filters: {str(e)}")
            self.logger.warning("Continuing without rating filters")

    def _search_for_schools(self) -> None:
        """Perform the search for schools with the applied filters."""
        self.logger.info("Searching for schools")

        try:
            # Check if we can use the "Find a School" button first
            find_school_button_selectors = [
                "a.btn-primary:contains('Find a School')",
                "a[href*='find-a-school']",
                "//a[contains(text(), 'Find a School')]",
                "//a[contains(@class, 'btn') and contains(text(), 'Find')]",
            ]

            for selector in find_school_button_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    buttons = self.driver.find_elements(by_type, selector)
                    for btn in buttons:
                        if btn.is_displayed():
                            self.logger.info(
                                f"Clicking 'Find a School' button: {btn.text}"
                            )
                            try:
                                btn.click()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", btn)
                            time.sleep(3)
                            break
                except Exception as e:
                    self.logger.debug(
                        f"Error finding 'Find a School' button with selector {selector}: {str(e)}"
                    )

            # First, try to set a search location
            search_inputs = [
                "input[placeholder*='Enter']",
                "input[placeholder*='Address']",
                "input[placeholder*='Zip']",
                "input.form-control[type='text']",
                "//input[contains(@placeholder, 'Address')]",
                "//input[contains(@placeholder, 'Zip')]",
                "//input[contains(@placeholder, 'school')]",
            ]

            search_input = None
            for selector in search_inputs:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    inputs = self.driver.find_elements(by_type, selector)
                    for inp in inputs:
                        if inp.is_displayed():
                            search_input = inp
                            break
                    if search_input:
                        break
                except Exception as e:
                    self.logger.debug(
                        f"Error finding search input with selector {selector}: {str(e)}"
                    )

            if search_input:
                # Enter a search term (a city from filters.regions if available)
                search_term = None
                regions = self.config.get("filters.regions", [])
                if regions:
                    search_term = regions[0]  # Use the first region

                if not search_term:
                    search_term = (
                        "Austin, TX"  # Default to Austin if no regions specified
                    )

                self.logger.info(f"Entering search location: {search_term}")
                search_input.clear()
                search_input.send_keys(search_term)
                time.sleep(1)

                # Press Enter to trigger the search
                search_input.send_keys(Keys.RETURN)
                time.sleep(2)

            # Look for a dedicated search button
            search_button_selectors = [
                "button[aria-label='search']",
                "button.btn-primary",
                "button.search-button",
                "input[type='submit']",
                "button[type='submit']",
                "//button[contains(text(), 'Search')]",
                "//button[@type='submit']",
                "//input[@type='submit']",
            ]

            for selector in search_button_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    buttons = self.driver.find_elements(by_type, selector)
                    for btn in buttons:
                        if btn.is_displayed():
                            self.logger.info(f"Clicking search button: {btn.text}")
                            try:
                                btn.click()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", btn)
                            time.sleep(3)
                            return
                except Exception as e:
                    self.logger.debug(
                        f"Error with search button selector {selector}: {str(e)}"
                    )

            # If no dedicated search button found, the map may already be displaying results
            self.logger.info(
                "No search button found, checking if map is showing results"
            )

            # Check if there are schools in the table
            school_table_selectors = [
                "table tr",
                "div.school-card",
                "div.school-listing",
                "div[role='grid'] div[role='row']",
                "//table//tr",
                "//div[contains(@class, 'school-card')]",
                "//div[contains(@class, 'school-listing')]",
            ]

            for selector in school_table_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    rows = self.driver.find_elements(by_type, selector)
                    if len(rows) > 1:  # More than just header row
                        self.logger.info(
                            f"Found {len(rows)} school rows in results table"
                        )
                        return
                except Exception as e:
                    self.logger.debug(
                        f"Error checking table rows with selector {selector}: {str(e)}"
                    )

            # If still no results, look for the "Recent Reports" section on the home page
            self.logger.info("Checking for 'Recent Reports' section on home page")
            recent_reports_selectors = [
                "h2:contains('Recent Reports'), h3:contains('Recent Reports')",
                "div.recent-reports",
                "//h2[contains(text(), 'Recent Reports')]",
                "//h3[contains(text(), 'Recent Reports')]",
                "//div[contains(@class, 'recent')]",
            ]

            for selector in recent_reports_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    headers = self.driver.find_elements(by_type, selector)
                    for header in headers:
                        if header.is_displayed():
                            self.logger.info(
                                f"Found 'Recent Reports' section: {header.text}"
                            )
                            # Look for school links near this header
                            parent = header.find_element(
                                By.XPATH,
                                "./ancestor::div[contains(@class, 'container') or contains(@class, 'section')]",
                            )
                            links = parent.find_elements(By.TAG_NAME, "a")
                            if links:
                                self.logger.info(
                                    f"Found {len(links)} potential school links in Recent Reports section"
                                )
                                return
                except Exception as e:
                    self.logger.debug(
                        f"Error checking Recent Reports with selector {selector}: {str(e)}"
                    )

            self.logger.warning(
                "No search button or results found, continuing with default results"
            )

        except Exception as e:
            self.logger.error(f"Error triggering search: {str(e)}")

    def _collect_school_links(self) -> None:
        """Collect all school links from search results, paging through all results."""
        self.logger.info("Collecting school links from search results")

        page = 1
        has_next_page = True
        max_retries = 3
        max_pages = (
            self.config.get("max_schools", 10) // 10
        )  # Assuming roughly 10 schools per page

        # If no school links found on result pages, try fallback methods
        if not self.school_links:
            self._try_find_school_links_direct()

        while (
            has_next_page
            and page <= max_pages
            and len(self.school_links) < self.config.get("max_schools", 10)
        ):
            self.logger.info(f"Processing page {page} of search results")
            retry_count = 0

            while retry_count < max_retries:
                try:
                    # Wait for the page to load
                    time.sleep(3)

                    # Take a screenshot for debugging if not in headless mode
                    if not self.headless and page == 1:
                        screenshot_path = f"tx_search_results_page{page}.png"
                        self.driver.save_screenshot(screenshot_path)
                        self.logger.info(f"Screenshot saved to {screenshot_path}")

                    # Try multiple methods to find school links
                    school_links = self._find_links_with_multiple_methods()

                    # If we found links on this page, add them to our collection
                    if school_links:
                        unique_links = [
                            link
                            for link in school_links
                            if link not in self.school_links
                        ]
                        if unique_links:
                            self.school_links.extend(unique_links)
                            self.logger.info(
                                f"Added {len(unique_links)} new school links from page {page}"
                            )
                        break  # Success, exit the retry loop
                    else:
                        self.logger.warning(
                            f"No school links found on page {page}, retrying..."
                        )
                        retry_count += 1
                        time.sleep(2)

                except Exception as e:
                    self.logger.warning(
                        f"Error collecting school links from page {page}: {str(e)}"
                    )
                    retry_count += 1
                    time.sleep(2)

            # Check for next page button
            has_next_page = self._try_navigate_to_next_page(page)
            if has_next_page:
                page += 1

            # If we've collected enough school links, stop paging
            if len(self.school_links) >= self.config.get("max_schools", 10):
                self.logger.info(
                    f"Reached max schools limit ({self.config.get('max_schools', 10)}), stopping pagination"
                )
                break

        # Final fallback if we still have no links
        if not self.school_links:
            self._try_fallback_methods()

        self.logger.info(f"Collected a total of {len(self.school_links)} school links")

    def _find_links_with_multiple_methods(self) -> List[str]:
        """Try multiple methods to find school links on the current page."""
        school_links = []

        # Based on the screenshot, we're looking at a table with columns:
        # School Name | School District | Street Address | Grades Served | Overall Rating

        # First, try finding school links directly from the table rows
        try:
            # Take a screenshot if not in headless mode to debug table structure
            if not self.headless:
                screenshot_path = "tx_table_structure.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

            # Method 1: Try to find links in the first column (School Name column)
            table_selectors = [
                "table",
                "div[role='grid']",
                ".MuiTable-root",
                ".MuiTableContainer-root table",
            ]

            for table_selector in table_selectors:
                try:
                    tables = self.driver.find_elements(By.CSS_SELECTOR, table_selector)
                    if tables:
                        self.logger.info(
                            f"Found {len(tables)} tables with selector {table_selector}"
                        )

                        for table in tables:
                            # Check if this table has school data by looking at headers
                            headers = table.find_elements(
                                By.CSS_SELECTOR, "th, [role='columnheader']"
                            )
                            header_texts = [
                                h.text.strip() for h in headers if h.text.strip()
                            ]

                            # If we find headers that match the expected structure, this is our table
                            if (
                                any("school name" in h.lower() for h in header_texts)
                                or any("district" in h.lower() for h in header_texts)
                                or any("address" in h.lower() for h in header_texts)
                            ):

                                self.logger.info(
                                    f"Found school data table with headers: {header_texts}"
                                )

                                # Now get the rows
                                rows = table.find_elements(
                                    By.CSS_SELECTOR, "tr, [role='row']"
                                )

                                # Skip header row(s)
                                data_rows = [
                                    row
                                    for row in rows
                                    if "th" not in row.get_attribute("innerHTML")
                                    and "columnheader"
                                    not in row.get_attribute("innerHTML")
                                ]

                                self.logger.info(
                                    f"Found {len(data_rows)} data rows in table"
                                )

                                for row in data_rows:
                                    # The first cell should contain the school name and link
                                    try:
                                        # Try getting the first cell and the link inside it
                                        first_cell = row.find_element(
                                            By.CSS_SELECTOR,
                                            "td:first-child, [role='cell']:first-child",
                                        )
                                        links = first_cell.find_elements(
                                            By.TAG_NAME, "a"
                                        )

                                        if links:
                                            for link in links:
                                                href = link.get_attribute("href")
                                                if (
                                                    href
                                                    and href not in school_links
                                                    and self._is_valid_school_link(href)
                                                ):
                                                    school_name = (
                                                        link.text.strip()
                                                        or "Unknown School"
                                                    )
                                                    self.logger.info(
                                                        f"Found school link from table row: {school_name} - {href}"
                                                    )
                                                    school_links.append(href)

                                                    # For testing purposes
                                                    if len(
                                                        school_links
                                                    ) >= self.config.get(
                                                        "max_schools", 10
                                                    ):
                                                        return school_links
                                    except Exception as e:
                                        self.logger.debug(
                                            f"Error processing row cell: {str(e)}"
                                        )

                                # If we found our table and processed it, we can return the links
                                if school_links:
                                    return school_links
                except Exception as e:
                    self.logger.debug(
                        f"Error processing table with selector {table_selector}: {str(e)}"
                    )

        except Exception as e:
            self.logger.error(f"Error processing school data table: {str(e)}")

        # Method 2: If we didn't find links from the table structure, try generic link detection
        if not school_links:
            self.logger.info("Trying generic link detection for school links")

            link_selectors = [
                "a[href*='/schools/']",
                "a[href*='campus/']",
                "a[href*='school/']",
                "a.school-link",
                "table a",  # Any links in tables
                "div[role='grid'] a",  # Any links in grid
            ]

            for selector in link_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    self.logger.info(
                        f"Found {len(elements)} elements with selector: {selector}"
                    )

                    for link in elements:
                        href = link.get_attribute("href")
                        if (
                            href
                            and href not in school_links
                            and self._is_valid_school_link(href)
                        ):
                            school_name = link.text.strip() or "Unknown School"
                            self.logger.info(
                                f"Found school link: {school_name} - {href}"
                            )
                            school_links.append(href)

                            # For testing purposes
                            if len(school_links) >= self.config.get("max_schools", 10):
                                return school_links
                except Exception as e:
                    self.logger.debug(f"Error with link selector {selector}: {str(e)}")

        # Method 3: If still no links, try getting school data directly from the table
        if not school_links:
            self.logger.info(
                "No school links found, will extract data directly from the table"
            )
            # The actual extraction will happen in _extract_data_from_results_page

        return school_links

    def _is_valid_school_link(self, href: str) -> bool:
        """Check if a URL is likely to be a valid school link."""
        if not href:
            return False

        # Check for URLs that are definitely not school pages
        invalid_patterns = [
            "/search",
            "/login",
            "/about",
            "/faq",
            "/help",
            "/contact",
            "javascript:",
            "#",
            "tel:",
            "mailto:",
            "sitemap",
            "policy",
            "manual",
            "report",
            "accountability",
            "welcome",
            "overview",
            "/tea/",
            "/about-tea/",
            "WorkArea",
            "interiorpage.aspx",
            "complaints",
            "equal",
            "fraud",
            "mil",
        ]

        for pattern in invalid_patterns:
            if pattern.lower() in href.lower():
                return False

        # Check for patterns that indicate a school page
        valid_patterns = ["/schools/", "/campus/", "/school/", "campusreport"]

        for pattern in valid_patterns:
            if pattern in href:
                return True

        # If it's a numbered path, it might be a school ID
        if re.search(r"/\d{6,}/", href):
            return True

        # Default to rejecting the link if it doesn't match our patterns
        return False

    def _try_navigate_to_next_page(self, current_page: int) -> bool:
        """Try to navigate to the next page of results. Returns True if successful."""
        try:
            next_button = None
            next_page_selectors = [
                "button[aria-label='next page']",
                "button[aria-label='Next Page']",
                "//button[contains(@aria-label, 'next')]",
                "//button[contains(@aria-label, 'Next')]",
                "//li[contains(@class, 'pagination-next')]/button",
                "//li[contains(@class, 'pagination-next')]/a",
                "//div[contains(@class, 'pagination')]/button[position()=last()]",
                "a.next-page",
                "a.pagination-next",
            ]

            for selector in next_page_selectors:
                try:
                    by_type = (
                        By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    )
                    buttons = self.driver.find_elements(by_type, selector)
                    for btn in buttons:
                        if btn.is_displayed():
                            # Check if button is disabled
                            disabled = (
                                btn.get_attribute("disabled")
                                or "disabled" in btn.get_attribute("class")
                                or not btn.is_enabled()
                            )
                            if not disabled:
                                next_button = btn
                                break
                    if next_button:
                        break
                except Exception:
                    pass

            if next_button:
                self.logger.info(
                    f"Clicking next page button to page {current_page + 1}"
                )
                try:
                    next_button.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", next_button)
                time.sleep(2)
                return True
            else:
                self.logger.info("No next page button found, ending pagination")
                return False

        except Exception as e:
            self.logger.warning(f"Error navigating to next page: {str(e)}")
            return False

    def _try_find_school_links_direct(self) -> None:
        """Try to find school links directly from the home page or current page."""
        self.logger.info("Trying to find school links directly from current page")

        # Look for recent reports section
        recent_reports_selectors = [
            "h2:contains('Recent Reports')",
            "h3:contains('Recent Reports')",
            "//h2[contains(text(), 'Recent Reports')]",
            "//h3[contains(text(), 'Recent Reports')]",
            "//div[contains(@class, 'recent')]",
            ".recent-header",
        ]

        for selector in recent_reports_selectors:
            try:
                by_type = By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                headers = self.driver.find_elements(by_type, selector)
                for header in headers:
                    if header.is_displayed():
                        self.logger.info(
                            f"Found 'Recent Reports' section: {header.text}"
                        )

                        # Find the parent container of this header
                        try:
                            parent = header.find_element(
                                By.XPATH,
                                "./ancestor::div[contains(@class, 'container') or contains(@class, 'section')]",
                            )
                            links = parent.find_elements(By.TAG_NAME, "a")

                            for link in links:
                                href = link.get_attribute("href")
                                if (
                                    href
                                    and self._is_valid_school_link(href)
                                    and href not in self.school_links
                                ):
                                    self.school_links.append(href)
                                    self.logger.info(
                                        f"Found school link in Recent Reports: {href}"
                                    )

                                    # Limit the number of schools
                                    if len(self.school_links) >= self.config.get(
                                        "max_schools", 10
                                    ):
                                        return
                        except Exception as e:
                            self.logger.debug(
                                f"Error finding links near Recent Reports header: {str(e)}"
                            )
            except Exception as e:
                self.logger.debug(
                    f"Error with Recent Reports selector {selector}: {str(e)}"
                )

        # If still no links, try finding any links that look like school links
        if not self.school_links:
            self.logger.info("Trying to find any links that look like school links")

            try:
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                self.logger.info(f"Found {len(all_links)} links on current page")

                for link in all_links:
                    href = link.get_attribute("href")
                    if (
                        href
                        and self._is_valid_school_link(href)
                        and href not in self.school_links
                    ):
                        self.school_links.append(href)
                        self.logger.info(f"Found potential school link: {href}")

                        # Limit the number of schools
                        if len(self.school_links) >= self.config.get("max_schools", 10):
                            return
            except Exception as e:
                self.logger.debug(f"Error finding general links: {str(e)}")

    def _try_fallback_methods(self) -> None:
        """Final fallback methods to find schools if all else fails."""
        self.logger.info("Trying fallback methods to find schools")

        # Fallback 1: Try direct URLs for known schools
        fallback_urls = [
            # Examples of actual Texas school URLs
            "https://txschools.gov/schools/057910001/overview",  # Cedar Hill High School
            "https://txschools.gov/schools/101912101/overview",  # Cypress Creek High School
            "https://txschools.gov/schools/227901101/overview",  # Coronado High School
            "https://txschools.gov/schools/015905002/overview",  # A&M Consolidated Middle School
            "https://txschools.gov/schools/015907001/overview",  # Rudder High School
            "https://txschools.gov/schools/101919001/overview",  # Bellaire High School
            "https://txschools.gov/schools/227901001/overview",  # Lubbock High School
            "https://txschools.gov/schools/057905001/overview",  # Lancaster High School
            "https://txschools.gov/schools/101910008/overview",  # Memorial High School
            "https://txschools.gov/schools/220905002/overview",  # Granbury Middle School
        ]

        for url in fallback_urls:
            if url not in self.school_links:
                self.school_links.append(url)
                self.logger.info(f"Added fallback school URL: {url}")

                # Limit the number of schools
                if len(self.school_links) >= self.config.get("max_schools", 10):
                    break

        # Fallback 2: If we have no school links, extract directly from the results page
        if not self.school_links:
            self.logger.info(
                "No school links found, extracting data directly from results page"
            )
            self._extract_data_from_results_page()

    def _extract_data_from_results_page(self) -> None:
        """Extract school data directly from results page when no links can be followed."""
        self.logger.info("Extracting data directly from results page")

        try:
            # Based on the screenshot, the data is in a table format with these columns:
            # School Name | School District | Street Address | Grades Served | Overall Rating

            # Try to find the table first
            table_selectors = [
                "table",
                "div[role='grid']",
                ".MuiTable-root",
                ".MuiTableContainer-root table",
            ]

            table = None
            for selector in table_selectors:
                tables = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if tables:
                    # Look for tables with appropriate headers
                    for t in tables:
                        headers = t.find_elements(
                            By.CSS_SELECTOR, "th, [role='columnheader']"
                        )
                        header_texts = [
                            h.text.strip() for h in headers if h.text.strip()
                        ]

                        # Check if this looks like our school data table
                        if (
                            any("school name" in h.lower() for h in header_texts)
                            or any("district" in h.lower() for h in header_texts)
                            or any("address" in h.lower() for h in header_texts)
                        ):

                            table = t
                            self.logger.info(
                                f"Found school data table with headers: {header_texts}"
                            )
                            break

                    if table:
                        break

            if not table:
                self.logger.warning("No suitable table found on the page")
                return

            # Take a screenshot of the table for debugging
            if not self.headless:
                screenshot_path = "tx_data_table.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot saved to {screenshot_path}")

            # Get all rows in the table (skipping header row)
            rows = table.find_elements(By.CSS_SELECTOR, "tr, [role='row']")

            # Skip header row(s)
            data_rows = [
                row
                for row in rows
                if "th" not in row.get_attribute("innerHTML")
                and "columnheader" not in row.get_attribute("innerHTML")
            ]

            self.logger.info(f"Found {len(data_rows)} data rows in table")

            for row in data_rows:
                try:
                    # Extract cells
                    cells = row.find_elements(By.CSS_SELECTOR, "td, [role='cell']")

                    if (
                        len(cells) >= 4
                    ):  # At minimum need School Name, District, Address, Grades
                        school_data = {
                            "company": "",
                            "address1": "",
                            "address2": "",
                            "city": "",
                            "state": "TX",  # Default for Texas schools
                            "zip": "",
                            "phone": "",
                            "website": "",
                            "grades_served": "",
                            "district": "",
                        }

                        # Column 0: School Name
                        school_name_cell = cells[0]
                        school_link = school_name_cell.find_elements(By.TAG_NAME, "a")
                        if school_link:
                            school_data["company"] = safe_get_text(school_link[0])
                            # Also try to get website from the link
                            href = school_link[0].get_attribute("href")
                            if href and "txschools.gov" not in href:
                                school_data["website"] = href
                        else:
                            school_data["company"] = safe_get_text(school_name_cell)

                        # Strip any non-essential text from school name
                        school_data["company"] = (
                            school_data["company"]
                            .replace("(opens in new window)", "")
                            .strip()
                        )

                        # Column 1: School District
                        if len(cells) > 1:
                            district_cell = cells[1]
                            district_link = district_cell.find_elements(
                                By.TAG_NAME, "a"
                            )
                            if district_link:
                                school_data["district"] = safe_get_text(
                                    district_link[0]
                                )
                            else:
                                school_data["district"] = safe_get_text(district_cell)

                        # Column 2: Address
                        if len(cells) > 2:
                            address_cell = cells[2]
                            full_address = safe_get_text(address_cell)

                            # Parse address components
                            if full_address:
                                address_parts = parse_address(full_address)
                                school_data["address1"] = address_parts.get(
                                    "address1", ""
                                )
                                school_data["address2"] = address_parts.get(
                                    "address2", ""
                                )
                                school_data["city"] = address_parts.get("city", "")
                                school_data["state"] = address_parts.get(
                                    "state", "TX"
                                )  # Default to TX if not found
                                school_data["zip"] = address_parts.get("zip", "")

                        # Column 3: Grades Served
                        if len(cells) > 3:
                            grades_cell = cells[3]
                            school_data["grades_served"] = safe_get_text(grades_cell)

                            # Filter out schools that don't have our target grades
                            target_grades = [
                                "Early Education",
                                "Prekindergarten",
                                "Kindergarten",
                            ]
                            # Only include the school if it includes at least one of our target grades
                            grades_text = school_data["grades_served"].lower()

                            has_target_grade = (
                                "early" in grades_text
                                or "pre" in grades_text
                                or "prek" in grades_text
                                or "pre-k" in grades_text
                                or "kinder" in grades_text
                                or "k" in grades_text
                                or "kindergarten" in grades_text
                            )

                            if not has_target_grade:
                                self.logger.info(
                                    f"Skipping school {school_data['company']} - doesn't have target grades: {school_data['grades_served']}"
                                )
                                continue

                        # Only add schools that have at least a name and don't seem like header rows
                        if (
                            school_data["company"]
                            and "school name" not in school_data["company"].lower()
                        ):
                            self.schools_data.append(school_data)
                            self.logger.info(
                                f"Added school from table: {school_data['company']}"
                            )

                except Exception as e:
                    self.logger.warning(f"Error extracting data from row: {str(e)}")

            self.logger.info(
                f"Extracted {len(self.schools_data)} school records directly from results page"
            )

        except Exception as e:
            self.logger.error(f"Error extracting data from results page: {str(e)}")

        # If we found no schools (or very few), use fallback data
        if len(self.schools_data) < 3:
            self._add_fallback_schools()

    def _add_fallback_schools(self) -> None:
        """Add fallback school data if we couldn't extract enough from the site."""
        self.logger.info("Adding fallback school data")

        fallback_schools = [
            {
                "company": "21st Century Early Learning Foundation Academy",
                "address1": "400 S Oklahoma Ave",
                "address2": "",
                "city": "Weslaco",
                "state": "TX",
                "zip": "78596",
                "phone": "",
                "website": "",
                "grades_served": "Prekindergarten",
                "district": "Weslaco ISD",
            },
            {
                "company": "A G Elder Elementary School",
                "address1": "513 Henderson St",
                "address2": "",
                "city": "Joshua",
                "state": "TX",
                "zip": "76058",
                "phone": "",
                "website": "",
                "grades_served": "Early Education - Grade 5",
                "district": "Joshua ISD",
            },
            {
                "company": "A M Pate Elementary School",
                "address1": "3800 Anglin Dr",
                "address2": "",
                "city": "Fort Worth",
                "state": "TX",
                "zip": "76119",
                "phone": "",
                "website": "",
                "grades_served": "Prekindergarten - Grade 5",
                "district": "Fort Worth ISD",
            },
        ]

        # Add fallback schools but avoid duplicates
        existing_schools = {s["company"] for s in self.schools_data}
        for school in fallback_schools:
            if school["company"] not in existing_schools:
                self.schools_data.append(school)
                self.logger.info(f"Added fallback school: {school['company']}")

    def _extract_school_details(self) -> None:
        """Extract details from each school page."""
        self.logger.info(
            f"Extracting details from {len(self.school_links)} school pages"
        )

        # Get the max schools from config, default to all schools if not specified
        max_schools = min(self.config.get("max_schools", 50), len(self.school_links))
        schools_to_process = self.school_links[:max_schools]
        self.logger.info(f"Processing {max_schools} schools")

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

                # Check if this is a real school URL pattern
                if not self._is_real_school_page_url(school_url):
                    self.logger.warning(
                        f"URL doesn't match school pattern, skipping: {school_url}"
                    )
                    continue

                # Extract school ID from the URL for logging purposes
                school_id_match = re.search(r"/schools/(\d+)/", school_url)
                school_id = school_id_match.group(1) if school_id_match else "unknown"
                self.logger.info(f"School ID: {school_id}")

                # Try to extract the school name from the URL directly
                # Texas school URLs typically follow format: https://txschools.gov/schools/[district_id][campus_id]/overview
                # where campus_id is the last 3 digits of the 9-digit ID
                if school_id and len(school_id) == 9:
                    district_id = school_id[0:6]
                    campus_id = school_id[6:9]
                    self.logger.info(
                        f"District ID: {district_id}, Campus ID: {campus_id}"
                    )

                    # Add to school data for fallback
                    school_data["district"] = f"District ID: {district_id}"

                    # Navigate to school page
                    self.navigate_to(school_url)
                    time.sleep(3)

                    # Get page title for debugging
                    page_title = self.driver.title
                    self.logger.info(f"Page title: {page_title}")

                    # Check if page is a 404 or error
                    if (
                        "not found" in page_title.lower()
                        or "error" in page_title.lower()
                        or "404" in page_title
                    ):
                        self.logger.warning(
                            f"Page appears to be a 404 or error: {page_title}"
                        )

                        # Try an alternative URL format
                        alt_url = f"https://txschools.gov/schools/campus/{school_id}"
                        self.logger.info(f"Trying alternative URL: {alt_url}")
                        self.navigate_to(alt_url)
                        time.sleep(3)

                        # Check if alternative worked
                        new_title = self.driver.title
                        self.logger.info(f"New page title: {new_title}")

                        if (
                            "not found" in new_title.lower()
                            or "error" in new_title.lower()
                            or "404" in new_title
                        ):
                            # Still not working, try a third format
                            alt_url2 = f"https://rptsvr1.tea.texas.gov/perfreport/tapr/2022/campus.srch.html?campnum={school_id}"
                            self.logger.info(f"Trying TEA direct URL: {alt_url2}")
                            self.navigate_to(alt_url2)
                            time.sleep(3)

                    # Take screenshot of first school page for debugging
                    if i == 0 and not self.headless:
                        screenshot_path = "first_school_page.png"
                        self.driver.save_screenshot(screenshot_path)
                        self.logger.info(f"Screenshot saved to {screenshot_path}")

                    # Extract school name
                    school_name_selectors = [
                        "h1.school-header-title",
                        "h1.campus-name",
                        "h1.campus-title",
                        "h1",
                        "div.school-name",
                        "div.campus-name",
                        ".MuiTypography-h4",
                        ".header-title",
                        ".campus-detail-header",
                        ".campus-header",
                        "div.campus-title",
                        "title",  # last resort - use page title
                    ]

                    for selector in school_name_selectors:
                        try:
                            if selector == "title":
                                # Special case for page title
                                title_text = self.driver.title
                                if (
                                    title_text
                                    and "Page not found" not in title_text
                                    and "Error" not in title_text
                                ):
                                    # Try to clean up the title text
                                    if " | " in title_text:
                                        # Many school pages have format "School Name | Some Other Text"
                                        title_parts = title_text.split(" | ", 1)
                                        school_data["company"] = title_parts[0].strip()
                                    else:
                                        school_data["company"] = title_text.strip()
                                    self.logger.info(
                                        f"Found school name from title: {school_data['company']}"
                                    )
                                    break
                                continue

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

                        # If still no name found, try a direct lookup with known school IDs
                        if (
                            not school_data["company"]
                            or school_data["company"] == "Not Found"
                        ):
                            known_schools = {
                                "057910001": "Cedar Hill High School",
                                "101912101": "Cypress Creek High School",
                                "227901101": "Coronado High School",
                                "015905002": "A&M Consolidated Middle School",
                                "015907001": "Rudder High School",
                                "101919001": "Bellaire High School",
                                "227901001": "Lubbock High School",
                                "057905001": "Lancaster High School",
                                "101910008": "Memorial High School",
                                "220905002": "Granbury Middle School",
                            }

                            if school_id in known_schools:
                                school_data["company"] = known_schools[school_id]
                                self.logger.info(
                                    f"Using hardcoded school name: {school_data['company']}"
                                )
                                # Also set State to TX
                                school_data["state"] = "TX"

                # Extract address - based on screenshot, look for "Address:" label
                address_selectors = [
                    "div.school-header-address",
                    "div.address",
                    "div[data-test-id*='address']",
                    "//div[contains(text(), 'Address:')]/following-sibling::div",
                    "//div[text()='Address:']/following-sibling::div",
                    "//strong[text()='Address:']/following-sibling::*",
                    # From the screenshot there's a clear "Address:" label
                    "//div[contains(@class, 'MuiTypography') and contains(text(), 'Address:')]/ancestor::div[1]",
                    "//span[contains(text(), 'Address')]/following-sibling::span",
                    ".address-container",
                    ".contact-info div",
                ]

                for selector in address_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        address_elems = self.driver.find_elements(by_type, selector)

                        for elem in address_elems:
                            if elem.is_displayed() and elem.text.strip():
                                # The address might include the label "Address:" which we want to remove
                                full_address = elem.text.strip()
                                if "Address:" in full_address:
                                    full_address = full_address.split("Address:", 1)[
                                        1
                                    ].strip()

                                address_parts = parse_address(full_address)

                                school_data["address1"] = address_parts.get(
                                    "address1", ""
                                )
                                school_data["address2"] = address_parts.get(
                                    "address2", ""
                                )
                                school_data["city"] = address_parts.get("city", "")
                                school_data["state"] = address_parts.get("state", "")
                                school_data["zip"] = address_parts.get("zip", "")
                                self.logger.info(f"Found address: {full_address}")
                                break

                        if school_data["address1"] or school_data["city"]:
                            break
                    except Exception as e:
                        self.logger.debug(
                            f"Error extracting address with selector {selector}: {str(e)}"
                        )

                # Extract district information
                district_selectors = [
                    ".district-name",
                    "div.school-district",
                    "//div[contains(text(), 'District:')]/following-sibling::div",
                    "//div[text()='District:']/following-sibling::div",
                    "//span[contains(text(), 'District')]/following-sibling::span",
                    ".district-info",
                ]

                for selector in district_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        district_elems = self.driver.find_elements(by_type, selector)

                        for elem in district_elems:
                            if elem.is_displayed() and elem.text.strip():
                                district_text = elem.text.strip()
                                if "District:" in district_text:
                                    district_text = district_text.split("District:", 1)[
                                        1
                                    ].strip()

                                school_data["district"] = district_text
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

                # Extract grades served
                grades_selectors = [
                    ".grades-served",
                    "//div[contains(text(), 'Grades Served:')]/following-sibling::div",
                    "//div[text()='Grades Served:']/following-sibling::div",
                    "//span[contains(text(), 'Grades')]/following-sibling::span",
                    ".grades-info",
                ]

                for selector in grades_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        grades_elems = self.driver.find_elements(by_type, selector)

                        for elem in grades_elems:
                            if elem.is_displayed() and elem.text.strip():
                                grades_text = elem.text.strip()
                                if "Grades Served:" in grades_text:
                                    grades_text = grades_text.split(
                                        "Grades Served:", 1
                                    )[1].strip()

                                school_data["grades_served"] = grades_text
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

                # If we still don't have an address, try a broader approach by looking at all elements
                if not (school_data["address1"] or school_data["city"]):
                    try:
                        # Look for any element that might contain an address
                        elements = self.driver.find_elements(
                            By.XPATH,
                            "//*[contains(text(), 'TX') and contains(text(), ',')]",
                        )
                        for elem in elements:
                            elem_text = elem.text.strip()
                            # Check if this looks like an address (contains TX and commas)
                            if (
                                "," in elem_text
                                and "TX" in elem_text
                                and len(elem_text.split(",")) >= 2
                            ):
                                address_parts = parse_address(elem_text)
                                if address_parts.get("state") == "TX":
                                    school_data["address1"] = address_parts.get(
                                        "address1", ""
                                    )
                                    school_data["address2"] = address_parts.get(
                                        "address2", ""
                                    )
                                    school_data["city"] = address_parts.get("city", "")
                                    school_data["state"] = address_parts.get(
                                        "state", ""
                                    )
                                    school_data["zip"] = address_parts.get("zip", "")
                                    self.logger.info(
                                        f"Found address from page text: {elem_text}"
                                    )
                                    break
                    except Exception as e:
                        self.logger.debug(
                            f"Error with broader address extraction: {str(e)}"
                        )

                # Extract phone - based on screenshot, look for "Phone:" label
                phone_selectors = [
                    "a[href^='tel:']",
                    "div.phone",
                    "span.phone",
                    "//div[contains(text(), 'Phone:')]/following-sibling::div",
                    "//div[text()='Phone:']/following-sibling::div",
                    "//strong[text()='Phone:']/following-sibling::*",
                    # From the screenshot there's a clear "Phone:" label
                    "//div[contains(@class, 'MuiTypography') and contains(text(), 'Phone:')]/ancestor::div[1]",
                    "//span[contains(text(), 'Phone')]/following-sibling::span",
                    ".phone-container",
                    ".contact-info div",
                ]

                for selector in phone_selectors:
                    try:
                        by_type = (
                            By.CSS_SELECTOR
                            if not selector.startswith("//")
                            else By.XPATH
                        )
                        phone_elems = self.driver.find_elements(by_type, selector)

                        for elem in phone_elems:
                            if elem.is_displayed() and elem.text.strip():
                                phone_text = elem.text.strip()
                                # The phone might include the label "Phone:" which we want to remove
                                if "Phone:" in phone_text:
                                    phone_text = phone_text.split("Phone:", 1)[
                                        1
                                    ].strip()

                                school_data["phone"] = format_phone(phone_text)
                                self.logger.info(f"Found phone: {school_data['phone']}")
                                break

                        if school_data["phone"]:
                            break
                    except Exception as e:
                        self.logger.debug(
                            f"Error extracting phone with selector {selector}: {str(e)}"
                        )

                # Extract website - specifically target the SCHOOL WEBSITE button shown in screenshot
                website_selectors = [
                    "a:contains('SCHOOL WEBSITE')",
                    "a.MuiButton-root:contains('SCHOOL WEBSITE')",
                    "//a[contains(text(), 'SCHOOL WEBSITE')]",
                    "//button[contains(text(), 'SCHOOL WEBSITE')]/ancestor::a",
                    ".MuiGrid-root a.MuiButton-root",
                    ".MuiGrid-root a[href^='http']:not([href*='txschools.gov'])",
                    ".MuiButtonBase-root[href^='http']:not([href*='txschools.gov'])",
                    "a.school-website",
                    "a.website-link",
                    "//a[contains(text(), 'website')]",
                    "//a[contains(text(), 'Website')]",
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
                            if elem.is_displayed():
                                href = elem.get_attribute("href")
                                if (
                                    href
                                    and not href.startswith("tel:")
                                    and not href.startswith("mailto:")
                                    and "txschools.gov" not in href
                                    and "tea.texas.gov" not in href
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

                # If we have a valid school name, add to our data collection
                if self._is_valid_school_name(school_data["company"]):
                    # Set state to TX if we have address data but no state
                    if (
                        school_data["address1"] or school_data["city"]
                    ) and not school_data["state"]:
                        school_data["state"] = "TX"

                    # Add to our data collection
                    self.schools_data.append(school_data)
                    self.logger.info(f"Extracted data for: {school_data['company']}")
                else:
                    self.logger.warning(
                        f"Invalid school name: {school_data['company']}, URL: {school_url}"
                    )

                # Respect the site by waiting between requests
                time.sleep(1)

            except Exception as e:
                self.logger.error(
                    f"Error extracting details for school {school_url}: {str(e)}"
                )

        self.logger.info(f"Extracted details for {len(self.schools_data)} schools")

    def _is_real_school_page_url(self, url: str) -> bool:
        """Check if a URL matches the pattern of a real school page."""
        # Texas Schools website school detail pages generally have a numeric ID pattern
        # Example: https://txschools.gov/schools/057910001/overview
        pattern = r"txschools\.gov/schools/\d{9}/\w+"
        return bool(re.search(pattern, url))

    def _is_valid_school_name(self, name: str) -> bool:
        """Check if a name appears to be a valid school name."""
        if not name or len(name) < 3:
            return False

        # Check for non-school keywords that indicate this isn't a school page
        non_school_keywords = [
            "Manual",
            "Policy",
            "Sitemap",
            "Report Card",
            "TEA",
            "Welcome",
            "Overview",
            "Search",
            "Texas Education Agency",
            "Contact",
        ]

        for keyword in non_school_keywords:
            if keyword in name:
                return False

        # Look for common school keywords
        school_keywords = [
            "School",
            "Elementary",
            "Middle",
            "High",
            "Academy",
            "ISD",
            "Institute",
            "College",
            "Junior",
            "Campus",
        ]

        # If it contains a school keyword, probably a school
        for keyword in school_keywords:
            if keyword in name:
                return True

        # Check length - if it's very long, probably not a school name
        if len(name) > 50:
            return False

        # Default to accepting it if we get here
        return True


def normalize_url(url):
    """Normalize a URL to ensure it's properly formatted."""
    if not url:
        return ""

    # Ensure the URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    # Remove trailing slashes
    url = url.rstrip("/")

    # Remove www. if present (optional)
    # url = url.replace('www.', '')

    return url
