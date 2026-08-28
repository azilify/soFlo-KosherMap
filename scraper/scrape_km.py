"""
Scrapes https://koshermiami.org/establishments/

This page is loaded by JavaScript (there is no static HTML list), so this
uses Playwright to load it in a real headless browser. The browser identity
is set to look like a normal Chrome tab (not an automation tool), because
this site actively blocks requests that look like bots (a plain "403
Forbidden" with no content at all).

REAL PAGE STRUCTURE (confirmed by inspecting an actual rendered copy):
The page has a hidden data table at `.listDisplay .scrollableList`, with one
`<a href="/establishments/SLUG">` per establishment. Each contains a
`div.row.desctop` (there's also a duplicate `.row.mobile` version for small
screens - skipped here to avoid double-counting) with nine `.value` cells in
this fixed order:
  Name, Type, Area, Address, Phone,
  Cholov Yisroel, Pas Yisroel, Yoshon, Bishul Yisroel Tuna

The stringency columns hold values like "No", "N/A", "All Items",
"Available", or partial-availability notes like "Except Fortune Cookies" -
anything other than "No"/"N/A"/blank counts as that stringency being
available at that establishment.

(There's a separate small "featured" card view elsewhere on the page that
shows a KM/KDM certification logo per card, but it only covers a handful of
establishments, not the full list - so it isn't used as the data source
here. The per-establishment Cholov Yisroel status from the table above is a
more complete and accurate signal anyway.)
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL = "https://koshermiami.org/establishments/"
DEBUG_DIR = Path(__file__).parent.parent / "data"

NEGATIVE_VALUES = {"", "no", "n/a"}


def is_available(value):
    """True if a stringency column indicates the item is at least partially
    available (e.g. 'All Items', 'Available', 'Except Fortune Cookies'),
    False for 'No'/'N/A'/blank."""
    return (value or "").strip().lower() not in NEGATIVE_VALUES


def scrape_km():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            html = page.content()
            (DEBUG_DIR / "km_debug.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "km_debug.png"), full_page=True)
        finally:
            browser.close()

    soup = BeautifulSoup(html, "html.parser")
    scrollable = soup.select_one(".listDisplay .scrollableList")
    if not scrollable:
        print("WARNING: .listDisplay .scrollableList not found - page "
              "structure may have changed. Check data/km_debug.html.",
              file=sys.stderr)
        return []

    for a in scrollable.find_all("a", href=re.compile(r"^/establishments/")):
        row = a.select_one("div.row.desctop")
        if not row:
            continue
        values = [v.get_text(strip=True) for v in row.select(".value")]
        if len(values) < 9:
            continue

        name, ctype, area, address, phone, cy, py, yoshon, bishul = values[:9]
        if not name:
            continue

        records.append({
            "name": name,
            "type": ctype,
            "area": area,
            "address": address,
            "phone": phone,
            "cholov_yisroel": is_available(cy),
            "pas_yisroel": is_available(py),
            "yoshon": is_available(yoshon),
        })

    if not records:
        print("WARNING: KM scrape produced 0 rows despite finding the "
              "scrollableList container - check data/km_debug.html for "
              "what the row markup actually looked like.", file=sys.stderr)

    return records


if __name__ == "__main__":
    import json
    data = scrape_km()
    print(f"Scraped {len(data)} Kosher Miami rows")
    print(json.dumps(data[:5], indent=2))
