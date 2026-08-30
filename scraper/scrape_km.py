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
screens - skipped here) with nine `.value` cells in this fixed order:
  Name, Type, Area, Address, Phone,
  Cholov Yisroel, Pas Yisroel, Yoshon, Bishul Yisroel Tuna

WEBSITE ENRICHMENT:
Each establishment's own detail page (the href above) has a "Find Us" panel
with a Website row - but ONLY when the establishment actually has one on
file (confirmed by inspecting a real detail page: koshermiami.org/
establishments/NewTimeTakeOutCatering). That row looks like:
    <div class="row">
      <div class="col col-lg-4 label">Website</div>
      <div class="col col-lg-8"><a href="http://example.com">example.com</a></div>
    </div>
This means getting websites requires visiting every individual detail page,
not just the one summary table - a much bigger crawl (roughly one page load
per establishment). To keep this reasonable on a DAILY schedule, results
are cached in data/km_website_cache.json keyed by the detail page URL, so
only establishments we haven't checked yet get a fresh page visit each run.
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL = "https://koshermiami.org/establishments/"
BASE_URL = "https://koshermiami.org"
DEBUG_DIR = Path(__file__).parent.parent / "data"
WEBSITE_CACHE_PATH = DEBUG_DIR / "km_website_cache.json"

NEGATIVE_VALUES = {"", "no", "n/a"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def is_available(value):
    """True if a stringency column indicates the item is at least partially
    available (e.g. 'All Items', 'Available', 'Except Fortune Cookies'),
    False for 'No'/'N/A'/blank."""
    return (value or "").strip().lower() not in NEGATIVE_VALUES


def load_website_cache():
    if WEBSITE_CACHE_PATH.exists():
        try:
            return json.loads(WEBSITE_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_website_cache(cache):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    WEBSITE_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def new_stealth_page(browser):
    page = browser.new_page(
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 900},
        locale="en-US",
    )
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return page


def fetch_website(page, detail_url):
    """Visits one establishment's detail page and pulls its Website link,
    if it has one. Returns '' if there's no Website row at all."""
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(500)
        soup = BeautifulSoup(page.content(), "html.parser")
        for row in soup.select(".contactInfo .row"):
            label = row.select_one(".label")
            if label and label.get_text(strip=True).lower() == "website":
                link = row.find("a", href=True)
                if link:
                    return link["href"]
        return ""
    except Exception as e:
        print(f"  Website fetch failed for {detail_url}: {e}", file=sys.stderr)
        return ""


def scrape_km():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = new_stealth_page(browser)

            # "networkidle" waits for ALL background network activity to stop,
            # which can hang or time out on pages with persistent polling
            # (this page embeds Google Maps, analytics, etc. that never fully
            # go quiet). "domcontentloaded" plus an explicit wait for the
            # actual list content is faster and far less prone to this.
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector(".listDisplay .scrollableList a", timeout=30000)
            except Exception:
                pass  # fall through - we'll detect the missing content below anyway
            page.wait_for_timeout(2000)

            html = page.content()
            (DEBUG_DIR / "km_debug.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "km_debug.png"), full_page=True)

            soup = BeautifulSoup(html, "html.parser")
            scrollable = soup.select_one(".listDisplay .scrollableList")
            if not scrollable:
                print("WARNING: .listDisplay .scrollableList not found - page "
                      "structure may have changed. Check data/km_debug.html.",
                      file=sys.stderr)
                browser.close()
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
                    "detail_href": a["href"],
                    "website": "",
                })

            if not records:
                print("WARNING: KM scrape produced 0 rows despite finding the "
                      "scrollableList container - check data/km_debug.html for "
                      "what the row markup actually looked like.", file=sys.stderr)
                browser.close()
                return []

            # Website enrichment: one extra page visit per establishment we
            # haven't already checked. Cached by detail URL so this shrinks to
            # near-zero extra work on every run after the first. If an
            # individual detail page fails, fetch_website() already catches
            # that internally and just returns "" - it won't abort the run.
            cache = load_website_cache()
            new_lookups = 0
            for rec in records:
                detail_url = BASE_URL + rec["detail_href"]
                if detail_url in cache:
                    rec["website"] = cache[detail_url]
                    continue
                website = fetch_website(page, detail_url)
                cache[detail_url] = website
                rec["website"] = website
                new_lookups += 1
                time.sleep(0.4)  # be polite between requests

            if new_lookups:
                save_website_cache(cache)
            print(f"Website lookups: {new_lookups} new, "
                  f"{len(records) - new_lookups} from cache")

            browser.close()

    except Exception as e:
        # Whatever goes wrong here (a slow/blocked page, a Playwright
        # timeout, a changed site structure) - never let it crash the whole
        # pipeline. Returning [] lets build_data.py's resilience logic fall
        # back to yesterday's Kosher Miami data instead of losing everything
        # (including whatever ORB/Sunshine already successfully scraped this
        # same run).
        print(f"WARNING: Kosher Miami scrape failed entirely: {e}", file=sys.stderr)
        return records if records else []

    return records


if __name__ == "__main__":
    data = scrape_km()
    print(f"Scraped {len(data)} Kosher Miami rows")
    with_website = [r for r in data if r.get("website")]
    print(f"{len(with_website)} have a website on file")
    print(json.dumps(data[:3], indent=2))
