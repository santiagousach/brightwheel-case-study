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
            else:
                # Return empty list if no data was collected
                self.logger.warning("No data was collected")
                return []

    def _apply_grade_level_filters(self) -> None:
        """Apply grade level filters to the search results based on the requirement."""
        self.logger.info(
            "Applying grade level filters for Early Education, Prekindergarten, and Kindergarten"
        )

        try:
            # Wait for the page to be properly loaded
            wait = WebDriverWait(self.driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Look for the filter section/button first
            filter_selectors = [
                "button[aria-label='filter']", 
                "button:contains('Filter')",
                "[data-testid='FilterListIcon']",
                ".MuiButton-contained:contains('Filter')",
                "div.filter-button button",
                "button.filter-button",
                "//button[contains(text(), 'Filter')]",
                "//span[contains(text(), 'Filter')]/parent::button",
            ]
            
            # Try to open the filter panel if needed
            for selector in filter_selectors:
                try:
                    by_type = By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            self.logger.info(f"Found filter button: {elem.text if hasattr(elem, 'text') else 'Button'}")
                            try:
                                elem.click()
                                time.sleep(2)  # Wait for filter panel to open
                                self.logger.info("Clicked filter button")
                                # Take a screenshot after opening filter panel if not in headless mode
                                if not self.headless:
                                    screenshot_path = "tx_filter_panel.png"
                                    self.driver.save_screenshot(screenshot_path)
                                    self.logger.info(f"Screenshot saved to {screenshot_path}")
                                break
                            except Exception as e:
                                self.logger.debug(f"Error clicking filter button: {str(e)}")
                                try:
                                    self.driver.execute_script("arguments[0].click();", elem)
                                    time.sleep(2)
                                    self.logger.info("Clicked filter button using JavaScript")
                                    break
                                except Exception as e2:
                                    self.logger.debug(f"Error clicking filter button with JS: {str(e2)}")
                except Exception as e:
                    self.logger.debug(f"Error with filter selector {selector}: {str(e)}")

            # Expanded list of selectors for the grade level section
            grade_section_selectors = [
                "div.MuiAccordion-root:contains('Grade')",
                "//div[contains(text(), 'Grade')]/ancestor::div[contains(@class, 'MuiAccordion-root')]",
                "//div[contains(text(), 'Grade Level')]/ancestor::div[contains(@class, 'MuiAccordion-root')]",
                "div.grade-filter",
                "[data-testid='grade-filter']",
                "div.filter-section:contains('Grade')",
                "//button[contains(text(), 'Grade')]/parent::div",
                "//span[contains(text(), 'Grade')]/ancestor::div[3]",
                "div.filter-panel div.filter-group:contains('Grade')"
            ]
            
            # Try to expand the grade level section if it's collapsed
            for selector in grade_section_selectors:
                try:
                    by_type = By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                    elements = self.driver.find_elements(by_type, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            self.logger.info(f"Found grade level section: {elem.text if hasattr(elem, 'text') else 'Section'}")
                            # Try to expand it if it's collapsed
                            try:
                                expand_elements = elem.find_elements(By.CSS_SELECTOR, ".MuiAccordionSummary-root, .MuiButtonBase-root")
                                for expand_elem in expand_elements:
                                    if expand_elem.is_displayed():
                                        expand_elem.click()
                                        self.logger.info("Expanded grade level section")
                                        time.sleep(1)
                                        break
                            except Exception as e:
                                self.logger.debug(f"Error expanding grade section: {str(e)}")
                except Exception as e:
                    self.logger.debug(f"Error with grade section selector {selector}: {str(e)}")
            
            # Enhanced list of grade level checkbox selectors
            grade_checkboxes = [
                # Early Education
                {"name": "Early Education", "selectors": [
                    "//label[contains(text(), 'Early Education')]",
                    "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Early Education')]",
                    "input[type='checkbox'][name*='Early']",
                    "input[type='checkbox'][name*='early']",
                    "//span[contains(text(), 'Early Education')]/ancestor::label",
                    "//div[contains(text(), 'Early Education')]/preceding-sibling::span/input",
                    "[data-testid='early-education-checkbox']"
                ]},
                # Prekindergarten
                {"name": "Prekindergarten", "selectors": [
                    "//label[contains(text(), 'Prekindergarten')]",
                    "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Prekindergarten')]",
                    "input[type='checkbox'][name*='Pre']",
                    "input[type='checkbox'][name*='pre']",
                    "//span[contains(text(), 'Prekindergarten')]/ancestor::label",
                    "//div[contains(text(), 'Prekindergarten')]/preceding-sibling::span/input",
                    "[data-testid='prekindergarten-checkbox']",
                    "//label[contains(text(), 'Pre-K')]",
                    "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Pre-K')]",
                ]},
                # Kindergarten
                {"name": "Kindergarten", "selectors": [
                    "//label[contains(text(), 'Kindergarten')]",
                    "//input[@type='checkbox']/following-sibling::*[contains(text(), 'Kindergarten')]",
                    "input[type='checkbox'][name*='Kinder']",
                    "input[type='checkbox'][name*='kinder']",
                    "//span[contains(text(), 'Kindergarten')]/ancestor::label",
                    "//div[contains(text(), 'Kindergarten')]/preceding-sibling::span/input",
                    "[data-testid='kindergarten-checkbox']",
                    "//label[contains(text(), 'K')]",
                    "//input[@type='checkbox']/following-sibling::*[contains(text(), 'K ')]",
                ]}
            ]

            # Track whether we successfully selected any grade
            selected_any_grade = False

            # Try to select each grade level checkbox
            for grade in grade_checkboxes:
                grade_selected = False
                for selector in grade["selectors"]:
                    try:
                        by_type = By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                        elements = self.driver.find_elements(by_type, selector)
                        for elem in elements:
                            if elem.is_displayed():
                                self.logger.info(f"Found {grade['name']} checkbox/label")
                                
                                # If this is a label, try to find the associated checkbox
                                if hasattr(elem, "tag_name") and elem.tag_name.lower() == "label":
                                    try:
                                        checkbox = elem.find_element(By.XPATH, "..//input[@type='checkbox']") or \
                                                elem.find_element(By.XPATH, "preceding-sibling::input[@type='checkbox']") or \
                                                elem.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                                        
                                        if not checkbox.is_selected():
                                            try:
                                                checkbox.click()
                                                self.logger.info(f"Selected {grade['name']} checkbox")
                                                time.sleep(0.5)
                                                grade_selected = True
                                                selected_any_grade = True
                                                break
                                            except:
                                                self.driver.execute_script("arguments[0].click();", checkbox)
                                                self.logger.info(f"Selected {grade['name']} checkbox using JavaScript")
                                                time.sleep(0.5)
                                                grade_selected = True
                                                selected_any_grade = True
                                                break
                                    except Exception as e:
                                        # If we can't find the checkbox directly, try clicking the label
                                        try:
                                            elem.click()
                                            self.logger.info(f"Clicked {grade['name']} label")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                                        except:
                                            self.driver.execute_script("arguments[0].click();", elem)
                                            self.logger.info(f"Clicked {grade['name']} label using JavaScript")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                                else:
                                    # This is the checkbox itself or another clickable element
                                    if hasattr(elem, "is_selected") and not elem.is_selected():
                                        try:
                                            elem.click()
                                            self.logger.info(f"Selected {grade['name']} checkbox")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                                        except:
                                            self.driver.execute_script("arguments[0].click();", elem)
                                            self.logger.info(f"Selected {grade['name']} checkbox using JavaScript")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                                    else:
                                        try:
                                            elem.click()
                                            self.logger.info(f"Clicked {grade['name']} element")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                                        except:
                                            self.driver.execute_script("arguments[0].click();", elem)
                                            self.logger.info(f"Clicked {grade['name']} element using JavaScript")
                                            time.sleep(0.5)
                                            grade_selected = True
                                            selected_any_grade = True
                                            break
                    except Exception as e:
                        self.logger.debug(f"Error with {grade['name']} selector {selector}: {str(e)}")
                
                if grade_selected:
                    self.logger.info(f"Successfully selected {grade['name']} grade level")
                else:
                    self.logger.warning(f"Failed to select {grade['name']} grade level")
            
            # Look for an "Apply" or "Submit" button and click it
            if selected_any_grade:
                apply_selectors = [
                    "button[type='submit']",
                    "button.submit-button",
                    "button.apply-button",
                    ".MuiButton-contained:contains('Apply')",
                    ".MuiButton-contained:contains('Submit')",
                    "//button[contains(text(), 'Apply')]",
                    "//button[contains(text(), 'Submit')]",
                    "//span[contains(text(), 'Apply')]/parent::button",
                    "//span[contains(text(), 'Submit')]/parent::button",
                ]
                
                for selector in apply_selectors:
                    try:
                        by_type = By.CSS_SELECTOR if not selector.startswith("//") else By.XPATH
                        elements = self.driver.find_elements(by_type, selector)
                        for elem in elements:
                            if elem.is_displayed():
                                try:
                                    elem.click()
                                    self.logger.info(f"Clicked apply button: {elem.text if hasattr(elem, 'text') else 'Button'}")
                                    time.sleep(2)  # Wait for filter to be applied
                                    # Take a screenshot after applying filters if not in headless mode
                                    if not self.headless:
                                        screenshot_path = "tx_after_filter.png"
                                        self.driver.save_screenshot(screenshot_path)
                                        self.logger.info(f"Screenshot saved to {screenshot_path}")
                                    break
                                except:
                                    self.driver.execute_script("arguments[0].click();", elem)
                                    self.logger.info(f"Clicked apply button using JavaScript: {elem.text if hasattr(elem, 'text') else 'Button'}")
                                    time.sleep(2)
                                    break
                    except Exception as e:
                        self.logger.debug(f"Error with apply button selector {selector}: {str(e)}")
                
            # Wait for any loading indicators to disappear
            loading_selectors = [
                ".MuiCircularProgress-root",
                "[role='progressbar']",
                ".loading-indicator",
                ".MuiLinearProgress-root",
            ]
            
            for selector in loading_selectors:
                try:
                    loaders = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if loaders:
                        wait = WebDriverWait(self.driver, 15)
                        wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, selector)))
                        self.logger.info("Waited for loading indicator to disappear")
                except Exception as e:
                    self.logger.debug(f"Error waiting for loading indicator: {str(e)}")
            
        except Exception as e:
            self.logger.error(f"Error applying grade level filters: {str(e)}")
            # Take screenshot of the error state if not in headless mode
            if not self.headless:
                screenshot_path = "tx_filter_error.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Error state screenshot saved to {screenshot_path}")
            raise  # Re-raise the exception to be handled by the calling method

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
        """Try additional methods to find school data if primary methods fail."""
        self.logger.info("Trying fallback methods to find school data")

        try:
            # Look for school cards or list items instead of a table
            card_selectors = [
                ".MuiCard-root",
                "div[role='listitem']",
                "div.school-card",
                "div.school-item",
                "div.result-item",
                ".MuiPaper-root",
                "div.search-result-item",
                "div.school-result",
            ]

            cards_found = False
            for selector in card_selectors:
                cards = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    self.logger.info(f"Found {len(cards)} potential school cards with selector {selector}")
                    for card in cards:
                        try:
                            school_data = {
                                "company": "",
                                "address1": "",
                                "address2": "",
                                "city": "",
                                "state": "TX",  # Default for Texas
                                "zip": "",
                                "phone": "",
                                "website": "",
                                "grades_served": "",
                                "district": "",
                            }

                            # Try to find the school name
                            name_elements = card.find_elements(
                                By.CSS_SELECTOR, 
                                "h2, h3, h4, div.title, div.school-name, div.name, .MuiTypography-h5, .MuiTypography-h6, a"
                            )
                            for name_elem in name_elements:
                                if name_elem.is_displayed() and name_elem.text.strip():
                                    school_data["company"] = name_elem.text.strip()
                                    break

                            # Skip if we couldn't find a name or if it's too short to be a real school name
                            if not school_data["company"] or len(school_data["company"]) < 3:
                                continue

                            # Try to find the address
                            address_elements = card.find_elements(
                                By.CSS_SELECTOR,
                                "div.address, div.location, .MuiTypography-body1, p"
                            )
                            for addr_elem in address_elements:
                                text = addr_elem.text.strip()
                                if text and ("TX" in text or "," in text):
                                    # This looks like an address
                                    address_parts = parse_address(text)
                                    school_data["address1"] = address_parts.get("address1", "")
                                    school_data["address2"] = address_parts.get("address2", "")
                                    school_data["city"] = address_parts.get("city", "")
                                    school_data["state"] = address_parts.get("state", "TX")
                                    school_data["zip"] = address_parts.get("zip", "")
                                    break

                            # Try to find the district
                            district_elements = card.find_elements(
                                By.CSS_SELECTOR,
                                "div.district, div.school-district, .district-name, .MuiTypography-body2"
                            )
                            for district_elem in district_elements:
                                text = district_elem.text.strip()
                                if text and "district" in text.lower():
                                    school_data["district"] = text
                                    break

                            # Try to find grades served
                            grades_elements = card.find_elements(
                                By.CSS_SELECTOR,
                                "div.grades, div.grade-levels, .grades-served, .MuiTypography-caption"
                            )
                            for grades_elem in grades_elements:
                                text = grades_elem.text.strip()
                                if text and ("grade" in text.lower() or "prek" in text.lower() or "kindergarten" in text.lower()):
                                    school_data["grades_served"] = text
                                    break

                            # Try to find phone number
                            phone_elements = card.find_elements(
                                By.CSS_SELECTOR,
                                "div.phone, div.contact, a[href^='tel:'], .phone-number"
                            )
                            for phone_elem in phone_elements:
                                if phone_elem.tag_name == "a" and phone_elem.get_attribute("href").startswith("tel:"):
                                    school_data["phone"] = format_phone(phone_elem.get_attribute("href").replace("tel:", ""))
                                    break
                                elif phone_elem.text and re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', phone_elem.text):
                                    phone_match = re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', phone_elem.text)
                                    if phone_match:
                                        school_data["phone"] = format_phone(phone_match.group(0))
                                        break

                            # Try to find website
                            website_elements = card.find_elements(
                                By.CSS_SELECTOR,
                                "a[href^='http']:not([href*='txschools.gov']), a.website, a.school-website"
                            )
                            for website_elem in website_elements:
                                href = website_elem.get_attribute("href")
                                if href and "txschools.gov" not in href:
                                    school_data["website"] = href
                                    break

                            # Only include schools with target grades
                            target_grades = ["early education", "prekindergarten", "pre-k", "prek", "kindergarten", "k-"]
                            
                            # Either use grades_served field if it's populated, or check the whole card text
                            grades_text = school_data["grades_served"].lower()
                            if not grades_text:
                                grades_text = card.text.lower()
                                
                            has_target_grade = any(grade in grades_text for grade in target_grades)
                            
                            if has_target_grade and school_data["company"]:
                                self.schools_data.append(school_data)
                                self.logger.info(f"Added school from card: {school_data['company']}")
                                cards_found = True
                        except Exception as e:
                            self.logger.warning(f"Error extracting data from card: {str(e)}")

            if cards_found:
                self.logger.info(f"Found {len(self.schools_data)} schools using card selectors")
                return

            # If we still don't have schools, try to parse the page content directly
            self.logger.info("Trying to parse page content directly")
            
            # Get all the text content from the page
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            
            # Look for patterns that might indicate school listings
            # Texas school names often follow patterns
            school_patterns = [
                r'([A-Z][a-z]+\s(?:Elementary|Middle|High|Primary|Academy|School))',
                r'([A-Z][a-z]+\s[A-Z][a-z]+\s(?:Elementary|Middle|High|Primary|Academy|School))',
                r'([A-Z][a-z]+\s[A-Z][.]?\s[A-Z][a-z]+\s(?:Elementary|Middle|High|Primary|Academy|School))',
                r'((?:Early|Learning|Academy|Education|Pre-K).{3,30}(?:School|Center|Campus))'
            ]
            
            schools_found = set()
            for pattern in school_patterns:
                matches = re.finditer(pattern, body_text)
                for match in matches:
                    school_name = match.group(1).strip()
                    if school_name not in schools_found and len(school_name) > 5:
                        schools_found.add(school_name)
                        
                        # Try to find context for this school (text around the name)
                        name_idx = body_text.find(school_name)
                        if name_idx > 0:
                            start_idx = max(0, name_idx - 300)
                            end_idx = min(len(body_text), name_idx + 300)
                            context = body_text[start_idx:end_idx]
                            
                            # Create a basic school entry
                            school_data = {
                                "company": school_name,
                                "address1": "",
                                "address2": "",
                                "city": "",
                                "state": "TX",  # Default for Texas
                                "zip": "",
                                "phone": "",
                                "website": "",
                                "grades_served": "",
                                "district": "",
                            }
                            
                            # Try to extract address from context
                            address_match = re.search(r'\d+\s[A-Z][a-z]+\s(?:St|Dr|Ave|Rd|Blvd|Lane|Circle|Highway|Pkwy|Court)[,.]?\s[A-Za-z]+,?\s(?:TX|Texas)\s\d{5}', context)
                            if address_match:
                                address_parts = parse_address(address_match.group(0))
                                school_data["address1"] = address_parts.get("address1", "")
                                school_data["city"] = address_parts.get("city", "")
                                school_data["state"] = address_parts.get("state", "TX")
                                school_data["zip"] = address_parts.get("zip", "")
                            
                            # Try to extract phone from context
                            phone_match = re.search(r'(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}', context)
                            if phone_match:
                                school_data["phone"] = format_phone(phone_match.group(0))
                            
                            # Try to extract district from context
                            district_match = re.search(r'([A-Za-z\s]+\sISD)', context)
                            if district_match:
                                school_data["district"] = district_match.group(1)
                            
                            # Try to find grade levels
                            if "early education" in context.lower() or "pre-k" in context.lower() or "prek" in context.lower() or "kindergarten" in context.lower():
                                for line in context.split('\n'):
                                    line = line.lower()
                                    if "grade" in line or "prek" in line or "pre-k" in line or "kindergarten" in line:
                                        school_data["grades_served"] = line.strip()
                                        break
                            
                            # Only add if we think this is actually a preK/K school
                            target_grades = ["early education", "prekindergarten", "pre-k", "prek", "kindergarten", "k-"]
                            if any(grade in context.lower() for grade in target_grades):
                                self.schools_data.append(school_data)
                                self.logger.info(f"Added school from text analysis: {school_name}")
            
            if schools_found:
                self.logger.info(f"Found {len(schools_found)} schools using text pattern analysis")

        except Exception as e:
            self.logger.error(f"Error in fallback methods: {str(e)}")
            # Take a screenshot of the error state if not in headless mode
            if not self.headless:
                screenshot_path = "tx_fallback_error.png"
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Error state screenshot saved to {screenshot_path}")

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

                        # If still no name found, use the school ID as a last resort
                        if not school_data["company"] or school_data["company"] == "Not Found":
                            school_data["company"] = f"School ID: {school_id}"
                            self.logger.info(f"Using school ID as name: {school_data['company']}")
                            # Default state to TX
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
