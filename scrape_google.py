#!/usr/bin/env python3
"""
Minimal Google scraper using undetected-chromedriver + BeautifulSoup.

Usage:
  python scrape_google.py --query "zumba" --headless --max 5

Notes:
- This is intentionally minimal: it always uses the direct /search URL.
- Headless mode is fully supported with proper configuration.
- Requires: pip install setuptools undetected-chromedriver selenium beautifulsoup4
"""
from dataclasses import dataclass, asdict
from urllib.parse import urlencode, quote_plus, urlparse
import argparse
import json
import logging
import os
import shutil
import tempfile
import time

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


@dataclass
class SearchResult:
    rank: int
    title: str
    snippet: str
    url: str
    domain: str


class SimpleGoogleScraper:
    """
    Simple Google search scraper with proper headless mode support.
    
    Attributes:
        headless (bool): Whether to run in headless mode
        timeout (int): Timeout for page loads in seconds
        lang (str): Language preference (e.g., "en-US")
        driver: Selenium WebDriver instance
        driver_path (str): Path to writable chromedriver executable
    """
    
    def __init__(self, headless: bool = True, timeout: int = 10, lang: str = "en-US"):
        self.headless = headless
        self.timeout = timeout
        self.lang = lang
        self.driver = None
        self.driver_path = None
        self._setup_driver_path()
        self.options = self._configure_chrome_options()

    def _setup_driver_path(self):
        """
        Setup a writable chromedriver path.
        undetected-chromedriver patches the driver binary, so it needs write access.
        """
        # Check if system chromedriver exists
        system_driver = shutil.which("chromedriver")
        if system_driver:
            # Copy to a writable location
            temp_dir = tempfile.mkdtemp(prefix="uc_driver_")
            self.driver_path = os.path.join(temp_dir, "chromedriver")
            shutil.copy2(system_driver, self.driver_path)
            os.chmod(self.driver_path, 0o755)
            logging.info(f"Using chromedriver from: {self.driver_path}")
        else:
            # Let undetected-chromedriver download it (requires internet)
            self.driver_path = None
            logging.info("System chromedriver not found, will download if needed")

    def _configure_chrome_options(self):
        """
        Configure Chrome options with proper settings for both headless and normal modes.
        """
        opts = uc.ChromeOptions()
        
        # Basic language and locale settings
        opts.add_argument(f"--lang={self.lang}")
        
        # Essential anti-detection measures
        opts.add_argument("--disable-blink-features=AutomationControlled")
        
        # Sandboxing and stability settings
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        
        if self.headless:
            # Modern headless mode (Chrome 96+)
            opts.add_argument("--headless=new")
            
            # GPU and rendering settings for headless
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-software-rasterizer")
            
            # Set explicit window size for consistent rendering
            opts.add_argument("--window-size=1920,1080")
            
            # Disable unnecessary features in headless mode
            opts.add_argument("--disable-extensions")
            opts.add_argument("--disable-logging")
            opts.add_argument("--disable-notifications")
            
            # Additional headless stability options
            opts.add_argument("--disable-background-timer-throttling")
            opts.add_argument("--disable-backgrounding-occluded-windows")
            opts.add_argument("--disable-renderer-backgrounding")
            
            logging.info("Configured for headless mode")
        else:
            logging.info("Configured for normal (non-headless) mode")
        
        return opts

    def start(self):
        """
        Start the Chrome WebDriver with proper configuration.
        """
        try:
            if self.driver_path:
                # Use local chromedriver
                self.driver = uc.Chrome(
                    options=self.options,
                    driver_executable_path=self.driver_path,
                    use_subprocess=True
                )
            else:
                # Let undetected-chromedriver handle driver download
                self.driver = uc.Chrome(options=self.options)
            
            logging.info(f"WebDriver started successfully (headless={self.headless})")
            
            # Log window size for debugging
            if self.driver:
                size = self.driver.get_window_size()
                logging.info(f"Window size: {size['width']}x{size['height']}")
                
        except Exception as e:
            logging.error(f"Failed to start WebDriver: {e}")
            raise

    def stop(self):
        """
        Clean up WebDriver and temporary files.
        """
        try:
            if self.driver:
                try:
                    self.driver.quit()
                    logging.info("WebDriver closed successfully")
                except Exception as e:
                    logging.warning(f"Error closing driver: {e}")
        finally:
            self.driver = None
            
            # Clean up temporary driver directory
            if self.driver_path and os.path.exists(self.driver_path):
                try:
                    driver_dir = os.path.dirname(self.driver_path)
                    if driver_dir.startswith(tempfile.gettempdir()):
                        shutil.rmtree(driver_dir, ignore_errors=True)
                        logging.debug(f"Cleaned up temp driver dir: {driver_dir}")
                except Exception as e:
                    logging.debug(f"Failed to clean up temp driver: {e}")

    def _direct_search_url(self, query: str) -> str:
        """
        Construct a direct Google search URL with appropriate parameters.
        
        Args:
            query (str): Search query string
            
        Returns:
            str: Complete Google search URL
        """
        params = {"q": query, "hl": self.lang.split("-")[0]}
        if "-" in self.lang:
            params["gl"] = self.lang.split("-")[-1]
        return f"https://www.google.com/search?{urlencode(params, quote_via=quote_plus)}"

    def search(self, query: str, max_results: int = 10):
        """
        Perform a Google search and extract results.
        
        Args:
            query (str): Search query
            max_results (int): Maximum number of results to extract
            
        Returns:
            list: List of SearchResult objects
        """
        url = self._direct_search_url(query)
        logging.info(f"Searching for: {query}")
        logging.debug(f"URL: {url}")
        
        self.driver.get(url)
        
        # Wait for search results to load
        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso, div#main"))
            )
            logging.info("Search results loaded")
        except TimeoutException:
            logging.warning("Timeout waiting for results, allowing extra time")
            # Allow a short extra wait for slower page loads
            time.sleep(1.5)
        
        return self.extract_results(max_results=max_results)

    def extract_results(self, max_results: int = 10):
        """
        Extract search results from the current page.
        
        Args:
            max_results (int): Maximum number of results to extract
            
        Returns:
            list: List of SearchResult objects
        """
        html = self.driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        search_root = soup.find("div", id="search") or soup

        # Use common result containers; include fallback to generic .g blocks
        candidates = search_root.select("div.MjjYud, div.g")
        logging.debug(f"Found {len(candidates)} candidate result containers")
        
        results = []
        rank = 1
        
        for cand in candidates:
            if rank > max_results:
                break
                
            a = cand.select_one("a")
            h3 = cand.select_one("h3")
            
            if not a or not h3:
                # Sometimes link/h3 are nested differently; try a more targeted approach
                main = cand.select_one("div.yuRUbf a")
                if main:
                    a = main
                    h3 = main.select_one("h3")
                    
            if not a or not h3:
                continue
                
            href = a.get("href", "")
            title = h3.get_text(strip=True)
            
            # Extract snippet: common classes used by Google
            sn = cand.select_one(".IsZvec, .VwiC3b, span.aCOpRe, .s3v9rd, .st")
            snippet = sn.get_text(" ", strip=True) if sn else ""
            
            domain = urlparse(href).netloc
            
            results.append(SearchResult(
                rank=rank,
                title=title,
                snippet=snippet,
                url=href,
                domain=domain
            ))
            rank += 1
        
        logging.info(f"Extracted {len(results)} search results")
        return results


def configure_logging(debug: bool = False):
    """
    Configure logging with appropriate level.
    
    Args:
        debug (bool): Enable debug logging
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def main():
    """
    Main entry point for the scraper CLI.
    """
    parser = argparse.ArgumentParser(
        description="Minimal Google scraper with headless support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search in normal mode
  python scrape_google.py --query "python tutorial" --max 5
  
  # Search in headless mode
  python scrape_google.py --query "python tutorial" --headless --max 5
  
  # Debug mode with detailed logging
  python scrape_google.py --query "python tutorial" --headless --debug
        """
    )
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--max", type=int, default=10, help="Maximum results to extract (default: 10)")
    parser.add_argument("--lang", type=str, default="en-US", help="Preferred language (e.g. en-US)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    configure_logging(debug=args.debug)
    
    logging.info(f"Starting Google scraper (headless={args.headless})")
    scraper = SimpleGoogleScraper(headless=args.headless, timeout=10, lang=args.lang)
    
    try:
        scraper.start()
        results = scraper.search(args.query, max_results=args.max)
        
        # Output results as JSON
        out = {"results": [asdict(r) for r in results]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        
        logging.info(f"Search completed successfully ({len(results)} results)")
    except Exception as e:
        logging.error(f"Search failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        raise
    finally:
        scraper.stop()


if __name__ == "__main__":
    main()
