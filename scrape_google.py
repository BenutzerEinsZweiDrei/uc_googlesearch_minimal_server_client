#!/usr/bin/env python3
"""
Minimal Google scraper using undetected-chromedriver + BeautifulSoup.

Usage:
  python scrape_google.py --query "zumba" --headless --max 5

Notes:
- This is intentionally minimal: it always uses the direct /search URL.
- headless mode does not work.
- Requires: pip install setuptools undetected-chromedriver selenium beautifulsoup4
"""
from dataclasses import dataclass, asdict
from urllib.parse import urlencode, quote_plus, urlparse
import argparse
import json
import logging
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
    def __init__(self, headless: bool = True, timeout: int = 10, lang: str = "en-US"):
        self.headless = headless
        self.timeout = timeout
        self.lang = lang
        self.driver = None
        opts = uc.ChromeOptions()
        opts.add_argument(f"--lang={self.lang}")
        if self.headless:
            # Use new headless where available, fallback to legacy
            try:
                opts.add_argument("--headless=new")
            except Exception:
                opts.add_argument("--headless")
            opts.add_argument("--disable-gpu")
        # Common tweaks to reduce automation fingerprint
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        self.options = opts

    def start(self):
        self.driver = uc.Chrome(options=self.options)

    def stop(self):
        try:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
        finally:
            self.driver = None

    def _direct_search_url(self, query: str) -> str:
        params = {"q": query, "hl": self.lang.split("-")[0]}
        if "-" in self.lang:
            params["gl"] = self.lang.split("-")[-1]
        return f"https://www.google.com/search?{urlencode(params, quote_via=quote_plus)}"

    def search(self, query: str, max_results: int = 10):
        url = self._direct_search_url(query)
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso, div#main"))
            )
        except TimeoutException:
            # allow a short extra wait
            time.sleep(1.5)
        return self.extract_results(max_results=max_results)

    def extract_results(self, max_results: int = 10):
        html = self.driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        search_root = soup.find("div", id="search") or soup

        # Use common result containers; include fallback to generic .g blocks
        candidates = search_root.select("div.MjjYud, div.g")
        results = []
        rank = 1
        for cand in candidates:
            if rank > max_results:
                break
            a = cand.select_one("a")
            h3 = cand.select_one("h3")
            if not a or not h3:
                # sometimes link/h3 are nested differently; try a more targeted approach
                main = cand.select_one("div.yuRUbf a")
                if main:
                    a = main
                    h3 = main.select_one("h3")
            if not a or not h3:
                continue
            href = a.get("href", "")
            title = h3.get_text(strip=True)
            # snippet: common classes used by Google
            sn = cand.select_one(".IsZvec, .VwiC3b, span.aCOpRe, .s3v9rd, .st")
            snippet = sn.get_text(" ", strip=True) if sn else ""
            domain = urlparse(href).netloc
            results.append(SearchResult(rank=rank, title=title, snippet=snippet, url=href, domain=domain))
            rank += 1
        return results


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Minimal Google scraper")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--max", type=int, default=10, help="Maximum results")
    parser.add_argument("--lang", type=str, default="en-US", help="Preferred language (e.g. en-US)")
    args = parser.parse_args()

    configure_logging()
    scraper = SimpleGoogleScraper(headless=args.headless, timeout=10, lang=args.lang)
    try:
        scraper.start()
        results = scraper.search(args.query, max_results=args.max)
        out = {"results": [asdict(r) for r in results]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        scraper.stop()


if __name__ == "__main__":
    main()
