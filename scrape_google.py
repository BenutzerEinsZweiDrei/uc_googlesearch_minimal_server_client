# Resilient Google scraper — enhanced parsing debug (serverless)
#
# Usage:
#   python scraper_resilient_fix3.py --query "zumba" --headless --debug
#
# This version adds extensive debugging for the result-parsing stage:
# - Saves the full page HTML and a prettified BeautifulSoup dump.
# - Records counts of elements found per candidate selector.
# - Saves each candidate block's HTML to a separate file for inspection.
# - Produces extraction_debug.json with per-candidate detailed parse attempts and any exceptions.
# - Keeps previous resilient search behavior (textarea/combobox support, direct /search fallback).
#
# Requirements:
#   pip install undetected-chromedriver selenium beautifulsoup4

import argparse
import json
import logging
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlencode, quote_plus, urlparse

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


@dataclass
class SearchResult:
    rank: int
    title: str
    snippet: str
    url: str
    domain: str


class SafeChromeQuitMixin:
    def _safe_quit(self, driver):
        if not driver:
            return
        try:
            try:
                driver.close()
            except Exception:
                pass
            try:
                driver.quit()
            except Exception as e:
                logging.debug("driver.quit() raised: %s", e, exc_info=True)
        finally:
            try:
                svc = getattr(driver, "service", None)
                if svc is not None:
                    proc = getattr(svc, "process", None)
                    if proc is not None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            except Exception:
                pass


class ResilientGoogleScraper(SafeChromeQuitMixin):
    def __init__(self, headless: bool = True, timeout: int = 10, preferred_lang: str = "en-US", debug: bool = False, debug_dir: Optional[Path] = None):
        self.headless = headless
        self.timeout = timeout
        self.preferred_lang = preferred_lang
        self.debug = debug
        self.debug_dir = debug_dir or (Path.cwd() / f"debug_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
        self.driver = None
        self._quit_called = False

        self.options = uc.ChromeOptions()
        self.options.add_argument(f"--lang={self.preferred_lang}")
        self.options.add_experimental_option("prefs", {"intl.accept_languages": self.preferred_lang})
        self.options.add_argument("--no-first-run")
        self.options.add_argument("--no-service-autorun")
        self.options.add_argument("--password-store=basic")
        if self.headless:
            try:
                self.options.add_argument("--headless=new")
            except Exception:
                self.options.add_argument("--headless")
            self.options.add_argument("--disable-gpu")
        self.options.add_argument("--disable-blink-features=AutomationControlled")
        self.options.add_argument("--disable-extensions")
        self.options.add_argument("--disable-dev-shm-usage")
        self.options.add_argument("--no-sandbox")

        # domain candidates to probe
        self.domain_candidates = [
            "https://www.google.com",
            "https://www.google.com/ncr",
            "https://www.google.co.uk",
            "https://www.google.de",
            "https://www.google.fr",
            "https://www.google.es",
            "https://www.google.nl",
            "https://www.google.it",
            "https://www.google.ca",
            "https://www.google.com.au",
        ]

        # expanded selectors: include textarea, combobox, and contenteditable cases
        self.search_input_selectors = [
            "input[name='q']",
            "input#APjFqb",
            "textarea#APjFqb",
            "textarea.gLFyf",
            "textarea[role='combobox']",
            "textarea[jsname]",
            "div[role='combobox']",
            "div[contenteditable='true']",
            "input[type='search']",
            "input[aria-label*='Search']",
            "input[title*='Search']",
            "form[action*='/search'] input",
            "input.gsfi",
        ]

        # XPath fallbacks kept
        self.search_input_xpaths = [
            "//textarea[contains(@aria-label,'Search')]",
            "//input[contains(@aria-label,'Search')]",
            "//div[@role='combobox' and @contenteditable='true']",
            "//input[contains(@name,'q')]",
            "//input[@type='search']",
            "//textarea[@role='combobox']",
        ]

        # cookie selectors (broad)
        self.cookie_selectors = [
            (By.ID, "L2AGLb"),
            (By.XPATH, "//button[contains(., 'I agree') or contains(., 'Accept all') or contains(., 'Alle akzeptieren')]"),
            (By.XPATH, "//button[contains(., 'Agree')]"),
            (By.XPATH, "//button[contains(., 'Accept')]"),
            (By.CSS_SELECTOR, "button[aria-label='Accept all']"),
            (By.CSS_SELECTOR, "form[action*='consent'] button"),
            (By.CSS_SELECTOR, "button[jsname='higCR']"),
        ]

        if self.debug:
            self.debug_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        logging.info("Starting undetected-chromedriver (headless=%s, lang=%s)", self.headless, self.preferred_lang)
        try:
            self.driver = uc.Chrome(options=self.options)
            time.sleep(0.2)
            logging.debug("Driver started")
        except WebDriverException as e:
            logging.exception("Failed to start driver")
            raise RuntimeError(f"Could not start driver: {e}")

    def stop(self):
        logging.info("Stopping driver...")
        if self._quit_called:
            logging.debug("Quit already called; skipping.")
            return
        self._quit_called = True
        try:
            self._safe_quit(self.driver)
        finally:
            self.driver = None
            logging.info("Driver stopped.")

    def _try_open_domain_variations(self, timeout_each: float = 6.0) -> Tuple[Optional[str], Optional[Exception]]:
        last_exc = None
        for base in self.domain_candidates:
            try:
                params = {"hl": self.preferred_lang.split("-")[0]}
                if "-" in self.preferred_lang:
                    params["gl"] = self.preferred_lang.split("-")[-1]
                url = base
                if params:
                    url = f"{base}/?{urlencode(params)}"
                logging.debug("Navigating to %s", url)
                self.driver.get(url)
                combined_css = ",".join(self.search_input_selectors)
                try:
                    WebDriverWait(self.driver, timeout_each).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, combined_css))
                    )
                    logging.debug("Detected search input on %s", base)
                    return base, None
                except TimeoutException:
                    time.sleep(1.0)
                    for sel in self.search_input_selectors:
                        try:
                            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                logging.debug("Found search input with selector %s on %s", sel, base)
                                return base, None
                        except Exception:
                            pass
                    raise TimeoutException(f"No search input on {base}")
            except Exception as exc:
                logging.debug("Domain attempt %s failed: %s", base, exc, exc_info=True)
                last_exc = exc
                continue
        return None, last_exc

    def _accept_cookies_resilient(self):
        logging.debug("Trying to accept cookies (broad).")
        for by, sel in self.cookie_selectors:
            try:
                elems = self.driver.find_elements(by, sel)
                for el in elems:
                    if el.is_displayed() and el.is_enabled():
                        try:
                            el.click()
                            logging.debug("Clicked consent element %s", sel)
                            time.sleep(0.5)
                            return True
                        except Exception:
                            logging.debug("Click failed for %s", sel, exc_info=True)
            except Exception:
                pass

        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for i, fr in enumerate(iframes):
                try:
                    self.driver.switch_to.frame(fr)
                except Exception:
                    continue
                for by, sel in self.cookie_selectors:
                    try:
                        elems = self.driver.find_elements(by, sel)
                        for el in elems:
                            if el.is_displayed() and el.is_enabled():
                                try:
                                    el.click()
                                    logging.debug("Clicked consent inside iframe %d selector %s", i, sel)
                                    self.driver.switch_to.default_content()
                                    time.sleep(0.5)
                                    return True
                                except Exception:
                                    logging.debug("Click in iframe failed", exc_info=True)
                    except Exception:
                        pass
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        except Exception:
            logging.debug("Error iterating iframes", exc_info=True)

        logging.debug("No cookie consent clicked.")
        return False

    def open_google_resilient(self) -> str:
        domain_used, err = self._try_open_domain_variations()
        if not domain_used:
            raise RuntimeError(f"Could not open a Google domain successfully: {err}")
        try:
            self._accept_cookies_resilient()
        except Exception:
            logging.debug("Cookie acceptance raised", exc_info=True)
        return domain_used

    def _locate_search_input(self):
        # CSS selectors (includes textarea variants)
        for sel in self.search_input_selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    for e in els:
                        try:
                            if e.is_displayed():
                                logging.debug("Search input located using CSS selector: %s", sel)
                                return e, sel
                        except Exception:
                            continue
            except Exception:
                continue
        # XPath fallbacks (also includes textarea role)
        for xp in self.search_input_xpaths:
            try:
                els = self.driver.find_elements(By.XPATH, xp)
                if els:
                    for e in els:
                        try:
                            if e.is_displayed():
                                logging.debug("Search input located using XPath: %s", xp)
                                return e, xp
                        except Exception:
                            continue
            except Exception:
                continue
        # Generic visible input/textarea fallback
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                try:
                    t = (inp.get_attribute("type") or "").lower()
                    if inp.is_displayed() and t in ("text", "search", ""):
                        logging.debug("Falling back to generic visible input")
                        return inp, "generic-input"
                except Exception:
                    continue
            textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
            for ta in textareas:
                try:
                    if ta.is_displayed():
                        logging.debug("Falling back to generic visible textarea")
                        return ta, "generic-textarea"
                except Exception:
                    continue
        except Exception:
            pass
        return None, None

    def _set_value_js(self, el, value: str) -> bool:
        try:
            tag = el.tag_name.lower()
            if tag in ("input", "textarea"):
                self.driver.execute_script(
                    "arguments[0].focus(); arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
                    el, value
                )
                return True
            # contenteditable/combobox: set textContent/innerText and dispatch events
            self.driver.execute_script("""
                arguments[0].focus();
                try { arguments[0].innerText = arguments[1]; } catch(e) { arguments[0].textContent = arguments[1]; }
                var ev = new Event('input', { bubbles: true });
                arguments[0].dispatchEvent(ev);
            """, el, value)
            return True
        except Exception:
            logging.debug("JS value set failed", exc_info=True)
            return False

    def _direct_search(self, query: str):
        params = {"q": query}
        params["hl"] = self.preferred_lang.split("-")[0]
        if "-" in self.preferred_lang:
            params["gl"] = self.preferred_lang.split("-")[-1]
        url = f"https://www.google.com/search?{urlencode(params, quote_via=quote_plus)}"
        logging.info("Falling back to direct search URL: %s", url)
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso, div#main"))
            )
        except TimeoutException:
            time.sleep(1.5)
        if self.debug:
            try:
                html = self.driver.page_source
                (self.debug_dir / "direct_search_page.html").write_text(html, encoding="utf-8")
                self.driver.save_screenshot(str(self.debug_dir / "direct_search.png"))
            except Exception:
                logging.debug("Could not save debug artifacts for direct search", exc_info=True)

    def search(self, query: str, human_type: bool = False, retries: int = 1):
        logging.info("Searching for query: %s", query)
        input_el, sel = self._locate_search_input()
        if not input_el:
            logging.warning("Search input not found with selectors. Falling back to direct-search.")
            if self.debug:
                try:
                    html = self.driver.page_source
                    (self.debug_dir / "no_input_page.html").write_text(html, encoding="utf-8")
                    self.driver.save_screenshot(str(self.debug_dir / "no_input_screenshot.png"))
                    logging.debug("Saved debug snapshot to %s", self.debug_dir)
                except Exception:
                    logging.debug("Failed to write debug snapshot", exc_info=True)
            self._direct_search(query)
            return

        tag = None
        try:
            tag = input_el.tag_name.lower()
        except Exception:
            pass

        try:
            try:
                input_el.click()
            except Exception:
                pass
            try:
                input_el.clear()
            except Exception:
                pass

            if tag in ("input", "textarea"):
                if human_type:
                    for ch in query:
                        input_el.send_keys(ch)
                        time.sleep(0.12)
                else:
                    input_el.send_keys(query)
                input_el.send_keys(Keys.ENTER)
            else:
                ok = self._set_value_js(input_el, query)
                if ok:
                    try:
                        self.driver.execute_script("var e = new KeyboardEvent('keydown', {key:'Enter',keyCode:13,which:13}); arguments[0].dispatchEvent(e);", input_el)
                        time.sleep(0.05)
                        self.driver.execute_script("var e = new KeyboardEvent('keypress', {key:'Enter',keyCode:13,which:13}); arguments[0].dispatchEvent(e);", input_el)
                        time.sleep(0.05)
                        self.driver.execute_script("var e = new KeyboardEvent('keyup', {key:'Enter',keyCode:13,which:13}); arguments[0].dispatchEvent(e);", input_el)
                    except Exception:
                        try:
                            input_el.send_keys(Keys.ENTER)
                        except Exception:
                            pass
                else:
                    try:
                        if human_type:
                            for ch in query:
                                input_el.send_keys(ch)
                                time.sleep(0.12)
                        else:
                            input_el.send_keys(query)
                        input_el.send_keys(Keys.ENTER)
                    except Exception:
                        logging.debug("Direct send_keys to non-input element failed", exc_info=True)
                        self._direct_search(query)
                        return

            try:
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso, div#main"))
                )
            except TimeoutException:
                logging.debug("Results container not found quickly; sleeping briefly")
                time.sleep(1.5)

        except Exception as e:
            logging.exception("Search interaction failed, falling back to direct search")
            if self.debug:
                (self.debug_dir / "search_interaction_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            self._direct_search(query)

    def extract_results(self, max_results: int = 10) -> List[SearchResult]:
        """
        Simplified, robust extraction logic based on live-tested selectors
        from server.py.
        """
        html = self.driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # Save debug files if enabled
        if self.debug:
            try:
                (self.debug_dir / "page.html").write_text(html, encoding="utf-8")
                (self.debug_dir / "page_pretty.html").write_text(soup.prettify(), encoding="utf-8")
            except Exception:
                logging.debug("Failed to write debug HTML files", exc_info=True)

        search_div = soup.find("div", id="search")
        if not search_div:
            logging.debug("No <div id='search'> found — fallback to full soup")
            search_div = soup

        # ✅ Primary Google result blocks
        results = search_div.select("div.MjjYud")

        parsed_results: List[SearchResult] = []
        rank = 1

        for result in results:
            if rank > max_results:
                break

            # Match classic result containers: <div class="yuRUbf"> <a><h3>Title</h3></a>
            main_link = result.select_one("div.yuRUbf a")
            h3 = result.select_one("h3")
            snippet_el = result.select_one(".IsZvec, .VwiC3b, span.aCOpRe, .s3v9rd, .st")

            if not main_link or not h3:
                continue  # skip blocks without a proper link and title

            href = main_link.get("href", "—")
            title = h3.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else "—"
            domain = urlparse(href).netloc

            parsed_results.append(
                SearchResult(rank=rank, title=title, snippet=snippet, url=href, domain=domain)
            )
            rank += 1

            # Save candidate HTML in debug mode
            if self.debug:
                try:
                    f = self.debug_dir / f"candidate_{rank}.html"
                    f.write_text(str(result), encoding="utf-8")
                except Exception:
                    logging.debug("Failed to save candidate HTML", exc_info=True)

        if not parsed_results:
            logging.warning("No results found with selector div.MjjYud → div.yuRUbf")

        return parsed_results


    def run_once(self, query: str, human_type: bool = False, max_results: int = 10, retries: int = 1):
        domain_used = None
        try:
            self.start()
            domain_used = self.open_google_resilient()
            time.sleep(0.4)
            self.search(query, human_type=human_type, retries=retries)
            time.sleep(0.4)
            results = self.extract_results(max_results=max_results)
            return results, domain_used
        finally:
            try:
                self.stop()
            except Exception:
                logging.debug("Exception during final stop", exc_info=True)


def configure_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def main():
    parser = argparse.ArgumentParser(description="Resilient Google scraper (parsing debug enabled).")
    parser.add_argument("--query", "-q", type=str, required=True, help="Search query")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--max", type=int, default=10, help="Maximum number of results to return")
    parser.add_argument("--human", action="store_true", help="Simulate human typing (slower)")
    parser.add_argument("--debug", action="store_true", help="Enable debug artifacts (saves page HTML, candidates, and extraction_debug.json)")
    parser.add_argument("--lang", type=str, default="en-US", help="Preferred language (e.g. en-US, de-DE)")
    parser.add_argument("--retries", type=int, default=1, help="Number of retries for search input if not found")
    args = parser.parse_args()

    configure_logging(args.debug)
    logging.info("Scraper starting (lang=%s)", args.lang)
    scraper = ResilientGoogleScraper(headless=args.headless, timeout=10, preferred_lang=args.lang, debug=args.debug)

    try:
        results, domain = scraper.run_once(query=args.query, human_type=args.human, max_results=args.max, retries=args.retries)
    except Exception as e:
        logging.exception("Scrape failed")
        payload = {"error": str(e)}
        if args.debug:
            payload["trace"] = traceback.format_exc()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    out = {"domain_used": domain, "results": [asdict(r) for r in results]}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()