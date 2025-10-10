# server.py

from minimal_server import minimal_server

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import time
from bs4 import BeautifulSoup

class GetResults:
    def __init__(self):
        self.options = uc.ChromeOptions()
        self.options.add_argument("--no-first-run --no-service-autorun --password-store=basic")
        self.driver = uc.Chrome(options=self.options)
        self.driver.quit()

    def open_google(self):
        self.driver.get("https://www.google.com")
        time.sleep(5)
        self.accept_cookies()

    def accept_cookies(self):
        try:
            time.sleep(2)
            consent_button = self.driver.find_element(By.ID, "L2AGLb")
            consent_button.click()
        except:
            print("Consent button not found or already accepted.")

    def search_query(self, query="zumba"):
        search_box = self.driver.find_element(By.ID, "APjFqb")
        search_box.click()
        for char in query:
            search_box.send_keys(char)
            time.sleep(0.3)  # Simulate human typing

        time.sleep(1)
        try:
            search_button = self.driver.find_element(By.CLASS_NAME, "gNO89b")
            search_button.click()
        except:
            print("Search button not found.")

        time.sleep(3)

    def extract_results(self):
        html = self.driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        search_div = soup.find("div", id="search")

        if not search_div:
            print("Kein <div id='search'> gefunden.")
            return
            
        results_tab = []

        results = search_div.select(".MjjYud")
        for result in results:
            if result.find("div", class_="yuRUbf"):
                h3 = result.find("h3")
                span = result.find("span", class_=False, id=False)
                a = result.find("a")
                
                title = [h3.get_text(strip=True) if h3 else "—"]
                span = [span.get_text(strip=True) if span else "—"]
                a = [a["href"] if a and a.has_attr("href") else "—"]
                
                results_tab.append([title, span, a])
                
        return results_tab

    def run(self):
        self.driver = uc.Chrome()
        self.open_google()
        self.search_query("zumba")
        tab = self.extract_results()
        self.driver.quit()
        return tab

if __name__ == "__main__":
    obj = GetResults()
    # Starte den Server, der Methoden von obj über den Socket zugänglich macht
    minimal_server(obj, host="localhost", port=4444)
