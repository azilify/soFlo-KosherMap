"""
Scrapes https://www.sunshinestatekosher.org/facilities

The site links to two PDFs behind signed, expiring CloudFront-style URLs
(Expires/Signature/Key-Pair-Id query params) that regenerate on each page
load. This script re-loads the facilities page every run to grab a FRESH
link before downloading each PDF, then parses the PDF's real layout:

Each business is one ROW of a bordered 3-COLUMN table:
  Column 1: logo/image (no useful text)
  Column 2: business name (first line) + address lines (remaining lines)
  Column 3: category/description line(s), then phone and/or email

The Playa Bowls PDF additionally has full-width banner rows that name a
county ("Palm Beach County", "Broward County", "Miami-Dade County") - these
apply to every business row that follows until the next banner, and are
tracked as `area` rather than emitted as their own restaurant.

Because pdfplumber's table detection depends on the PDF actually having
ruled borders (which these do, based on visual inspection of the source
files), `page.extract_tables()` is used directly rather than falling back
to fragile whitespace-based text parsing.
"""
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

from categorize import strip_handles

PAGE_URL = "https://www.sunshinestatekosher.org/facilities"
DEBUG_DIR = Path(__file__).parent.parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KosherMapBot/1.0)"}

PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\d{3}-HOT-DOGS", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
COUNTY_RE = re.compile(r"^[A-Za-z .-]+County$")
SKIP_NAME_RE = re.compile(r"^(please click|see )", re.I)


def find_pdf_links():
    resp = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" in href.lower() and "Facilities" in href:
            full_url = urljoin(PAGE_URL, href)
            label = a.get_text(strip=True) or (a.img.get("alt", "") if a.img else "") or href
            links.append((label, full_url))
    return links


def parse_pdf_tables(pdf_bytes, source_label):
    records = []
    debug_rows = []
    current_area = ""

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    debug_rows.append(" || ".join(cells))

                    joined = " ".join(cells).strip()
                    if not joined or "list of sunshine state" in joined.lower() or "updated" in joined.lower():
                        continue

                    non_empty = [c for c in cells if c]
                    if len(non_empty) == 1 and COUNTY_RE.match(non_empty[0]):
                        current_area = non_empty[0]
                        continue

                    if len(cells) < 3:
                        continue

                    name_block = cells[1]
                    detail_block = cells[2]
                    if not name_block:
                        continue

                    name_lines = [l.strip().rstrip(",") for l in name_block.split("\n") if l.strip()]
                    if not name_lines:
                        continue
                    name = name_lines[0]

                    if SKIP_NAME_RE.match(name) or "please click" in joined.lower():
                        continue

                    # Some names wrap onto a second line before the address
                    # begins (e.g. "Jeremiah's Italian Ice" / "of South
                    # Savannah" / "7400 Abercorn St" / "Savannah, GA").
                    # If any remaining line contains a digit (a real street
                    # address), merge any digit-free lines before it into
                    # the name. If NO remaining line has a digit (e.g. just
                    # a city name like "Boca Raton"), leave it as address.
                    remaining = name_lines[1:]
                    if any(re.search(r"\d", l) for l in remaining):
                        i = 0
                        while i < len(remaining) and not re.search(r"\d", remaining[i]):
                            name += " " + remaining[i]
                            i += 1
                        address = ", ".join(remaining[i:])
                    else:
                        address = ", ".join(remaining)

                    detail_lines = [l.strip() for l in detail_block.split("\n") if l.strip()]
                    detail_lines = strip_handles(detail_lines)
                    phone_match, email_match = "", ""
                    category_lines = []
                    for line in detail_lines:
                        pm = PHONE_RE.search(line)
                        em = EMAIL_RE.search(line)
                        if pm:
                            phone_match = pm.group(0)
                        elif em:
                            email_match = em.group(0)
                        else:
                            category_lines.append(line)
                    category = ", ".join(category_lines)

                    records.append({
                        "name": name,
                        "address": address,
                        "area": current_area,
                        "phone": phone_match,
                        "email": email_match,
                        "category": category,
                        "source": source_label,
                    })

    return records, debug_rows


def scrape_sunshine():
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    all_records = []
    all_debug = []

    links = find_pdf_links()
    if not links:
        print("WARNING: No PDF links found on the Sunshine State Kosher "
              "facilities page - the site's HTML structure may have changed.",
              file=sys.stderr)
        return []

    for label, url in links:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            records, debug_rows = parse_pdf_tables(resp.content, label)
            all_records.extend(records)
            all_debug.append(f"=== {label} ({url}) ===")
            all_debug.extend(debug_rows)
        except Exception as e:
            print(f"Failed to fetch/parse '{label}' at {url}: {e}", file=sys.stderr)

    (DEBUG_DIR / "sunshine_debug.txt").write_text("\n".join(all_debug), encoding="utf-8")

    if not all_records:
        print("WARNING: Sunshine State Kosher scrape produced 0 rows. Check "
              "data/sunshine_debug.txt (uploaded as a workflow artifact) - if "
              "PDF table extraction found no ruled tables, the fallback in "
              "this script may need a text-based parser instead.", file=sys.stderr)

    return all_records


if __name__ == "__main__":
    import json
    data = scrape_sunshine()
    print(f"Scraped {len(data)} Sunshine State Kosher rows")
    print(json.dumps(data, indent=2))
