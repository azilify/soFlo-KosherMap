"""
Scrapes https://koshermiami.org/establishments/

IMPORTANT CAVEAT: Kosher Miami's establishment list is loaded client-side by
JavaScript after the page loads (there is no static HTML list to parse).
This script uses Playwright to actually load the page in a headless browser,
switch to "List View", and read the rendered text.

Because the live DOM structure could not be inspected in advance (it's only
visible to a real browser), this script is written defensively:
  1. It waits for network activity to settle.
  2. It tries clicking a "List View" toggle if one exists.
  3. It falls back to reading the full rendered page text and parsing it with
     the same row pattern used for the Kosher Miami PDF export
     (Name / Type / Area / Address / Phone), since that PDF was itself a
     print of this List View.
  4. On any failure, it saves a screenshot + full HTML to data/km_debug.*
     so a human can inspect what changed and update the selectors below.

If this breaks after a site redesign: open data/km_debug.png and
data/km_debug.html (uploaded as a workflow artifact - see the GitHub Actions
log) to see what the page actually looked like, and adjust SELECTORS below.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://koshermiami.org/establishments/"
DEBUG_DIR = Path(__file__).parent.parent / "data"

# Areas and Types as seen on the site's filter UI - used to help split
# lines when the rendered text doesn't have clean delimiters.
KNOWN_AREAS = [
    "Miami Beach", "North Miami Beach", "Surfside", "Aventura",
    "Broward County", "Palm Beach County", "Boca Raton", "Hollywood",
    "Sunny Isles", "Bal Harbour", "Miami", "Other",
]

ROW_PATTERN = re.compile(
    r"(?P<name>.+?)\s+(?P<type>Meat|Dairy|Bakery|Take Out|Commercial|"
    r"Wholesale Only|Catering|Misc|Butcher|Grocery|Pareve"
    r"(?:,\s*(?:Meat|Dairy|Bakery|Take Out|Commercial|Wholesale Only|"
    r"Catering|Misc|Butcher|Grocery|Pareve))*)\s+"
    r"(?P<area>" + "|".join(KNOWN_AREAS) + r")\s*"
    r"(?P<address>.*?)\s*(?P<phone>\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})?$"
)


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
        # Some bot-protection checks look for the automation flag Playwright/
        # Selenium set on the page - hide it so the page looks like a normal
        # browser tab rather than an automated one.
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            # Try to switch to List View if such a control exists
            for label in ["List View", "List"]:
                try:
                    loc = page.get_by_text(label, exact=False)
                    if loc.count() > 0:
                        loc.first.click(timeout=3000)
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue

            page.wait_for_timeout(3000)
            full_text = page.inner_text("body")

            # Save debug artifacts every run - cheap insurance
            (DEBUG_DIR / "km_debug.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "km_debug.png"), full_page=True)

        finally:
            browser.close()

    # Parse rendered text line by line. Real listing rows contain one of the
    # KNOWN_AREAS; use that as an anchor.
    for line in full_text.splitlines():
        line = line.strip()
        if not line or len(line) < 5:
            continue
        if not any(area in line for area in KNOWN_AREAS):
            continue
        m = ROW_PATTERN.match(line)
        if not m:
            continue
        records.append({
            "name": m.group("name").strip(),
            "type": m.group("type").strip(),
            "area": m.group("area").strip(),
            "address": (m.group("address") or "").strip(),
            "phone": (m.group("phone") or "").strip(),
            "source": "Kosher Miami",
        })

    if not records:
        print("WARNING: KM scrape produced 0 rows. Check data/km_debug.html "
              "and data/km_debug.png (uploaded as a workflow artifact) to "
              "see what the live page looked like, and fix ROW_PATTERN / "
              "the List View toggle logic above.", file=sys.stderr)

    return records


if __name__ == "__main__":
    import json
    data = scrape_km()
    print(f"Scraped {len(data)} Kosher Miami rows")
    print(json.dumps(data[:5], indent=2))
