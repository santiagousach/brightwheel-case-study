# Schools Web Scraper

A professional, modular web scraping application that extracts school data from the Schools website.

## Features

- Scrapes school data from website
- Filters by grade levels (Early Education, Prekindergarten, Kindergarten)
- Extracts school details including name, address, contact info, etc.
- Exports data to CSV format
- Configurable via environment variables or command line arguments
- Docker support for easy deployment

## Requirements

If running locally:
- Python 3.9+
- Chrome browser (or Chromium for ARM64 systems like Apple Silicon Macs)
- Required Python packages (see `requirements.txt`)

If running with Docker:
- Docker
- Docker Compose (optional)

> **Note for Apple Silicon (M1/M2/M3) users:** The Docker image uses Chromium instead of Chrome for better ARM64 compatibility.

## Running the Application

### Using Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Create a `.env` file (or use the provided `.env.example`):
   ```bash
   cp .env.example .env
   ```

3. Run with Docker Compose:
   ```bash
   docker-compose up
   ```

   This will build the Docker image, run the scraper, and save results to the `data/output` directory.

### Running Locally

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Create a `.env` file (or use the provided `.env.example`):
   ```bash
   cp .env.example .env
   ```

4. Run the scraper:
   ```bash
   python -m src.main
   ```

### Command Line Options

The scraper supports various command line arguments:

```
usage: main.py [-h] [--scraper SCRAPER] [--config CONFIG] 
               [--output-dir OUTPUT_DIR] [--output-file OUTPUT_FILE] 
               [--headless] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]

optional arguments:
  -h, --help            show this help message and exit
  --scraper SCRAPER     Scraper type to use (default: from SCRAPER_TYPE env var)
  --config CONFIG       Path to config file (default: from CONFIG_PATH env var)
  --output-dir OUTPUT_DIR
                        Output directory (default: from OUTPUT_DIRECTORY env var)
  --output-file OUTPUT_FILE
                        Output filename (default: from OUTPUT_FILENAME env var)
  --headless            Run browser in headless mode
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Log level (default: from LOG_LEVEL env var)
```

## Web Scraping Libraries: Pros and Cons

### Selenium
- **Pros:**
  - Allows interaction with JavaScript-heavy websites
  - Can automate complex user interactions (clicking, form submission)
  - Simulates real browser behavior
  - Works well with dynamic content
- **Cons:**
  - Slower than alternatives
  - Resource-intensive
  - Requires browser drivers
  - More complex setup and maintenance

### Beautiful Soup
- **Pros:**
  - Easy to use and learn
  - Good for parsing HTML/XML
  - Lightweight and fast
  - Great documentation
- **Cons:**
  - Can't handle JavaScript or dynamic content
  - No built-in request functionality (requires requests library)
  - Limited to parsing existing HTML

### Requests
- **Pros:**
  - Simple and intuitive API
  - Fast performance
  - Low memory footprint
  - Excellent for static websites
- **Cons:**
  - Can't execute JavaScript
  - Limited to HTTP requests and responses
  - No DOM traversal capabilities without additional libraries

I chose Selenium as the primary library because:
1. The Texas Schools website uses JavaScript extensively
2. We needed to interact with filters and pagination
3. The requirement to click on school links and navigate between pages

## Architecture and Design

### Modular Design
The application is structured with modularity and reusability in mind:

- **Base classes**: Abstract base classes define interfaces for scrapers and data processors
- **Configuration**: External YAML config files for site-specific selectors and patterns
- **Environment variables**: Runtime configuration via env vars or command line args
- **Extensibility**: Easy to add new scrapers or data exporters

### Key Components

1. **Scrapers**: Handle website interaction and data extraction
   - `BaseScraper`: Common scraper functionality
   - `TXSchoolsScraper`: Texas Schools implementation 
   - `AZSchoolsScraper`: Arizona Schools implementation

2. **Data Processors**: Format and export scraped data
   - `BaseProcessor`: Common processor functionality
   - `CSVExporter`: CSV export implementation

3. **Utilities**:
   - Configuration management
   - Logging
   - Helper functions for data extraction

## Future Improvements

With more time, I would consider adding:

### Architecture
- Implement an asynchronous scraping approach using `asyncio` and `aiohttp`
- Add support for distributed scraping with message queues (RabbitMQ, Kafka)
- Create a web dashboard for monitoring scraping jobs

### Orchestration
- Add support for scheduled runs using Airflow or Prefect
- Implement retry mechanisms for failed jobs
- Add notification system for job completion or failures

### Data Quality
- Add more comprehensive data validation and cleaning
- Implement schema validation for extracted data
- Add duplicate detection and handling

### Transformations
- Support for multiple output formats (JSON, Excel, databases)
- Add geocoding for school addresses
- Implement data enrichment from additional sources

### Other Tools
- Add support for proxies to avoid rate limiting
- Implement caching layer to reduce website load
- Create a REST API to query scraped data
- Add support for other browsers (Firefox, Edge)
