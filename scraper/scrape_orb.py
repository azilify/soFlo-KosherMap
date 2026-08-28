"""
Scrapes https://www.orbkosher.com/category/restaurants/

ORB's site is server-rendered (no JavaScript needed to see the data), so this
uses plain requests + BeautifulSoup. The page groups restaurants under
headers like "Restaurants » Dairy", "Restaurants » Meat", etc. Each restaurant
is a list item containing:
  - a link/name for the business
  - a tel: link for phone (optional)
  - a link to /view-map-address/... whose link text IS the street address
  - a link with text "View Kosher Certificate" (optional)

This structural approach (tag + href pattern based) is more resilient to
CSS/class-name changes than selecting by class name.
"""
import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.orbkosher.com/category/restaurants/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KosherMapBot/1.0; +https://github.com/)"}


def scrape_orb():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    records = []
    current_category = None

    # Walk the document in order; track the most recent "Restaurants » X" header,
    # and treat each subsequent <li> as belonging to that category until the
    # next header appears.
    for el in soup.find_all(["h1", "h2", "h3", "h4", "li"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(strip=True)
            m = re.search(r"Restaurants\s*»\s*(.+)", text)
            if m:
                current_category = m.group(1).strip()
            continue

        if el.name == "li" and current_category:
            li_text = el.get_text(" ", strip=True)
            if not li_text:
                continue

            # Name + Website: the first link that isn't a tel/address/PDF link
            # is the establishment's photo, wrapped in a link that points to
            # their own website - its title attribute is the display name,
            # and its href IS the website URL (confirmed against real
            # markup: <a title="X" href="https://their-site.com"><img .../></a>)
            name = None
            website = ""
            for a in el.find_all("a"):
                href = a.get("href", "")
                if href.startswith("tel:") or "view-map-address" in href or href.endswith(".pdf"):
                    continue
                candidate = a.get("title") or a.get_text(strip=True)
                if candidate:
                    name = candidate.strip()
                    website = href.strip()
                    break
            if not name:
                # fallback: plain text before first link
                name = li_text.split("(")[0].strip()[:80]

            # Phone
            phone = ""
            tel_a = el.find("a", href=re.compile(r"^tel:"))
            if tel_a:
                phone = tel_a.get_text(strip=True)

            # Address: link to /view-map-address/
            address = ""
            addr_a = el.find("a", href=re.compile(r"view-map-address"))
            if addr_a:
                address = addr_a.get_text(strip=True)

            # Certificate link
            cert_link = ""
            cert_a = el.find("a", string=re.compile("View Kosher Certificate", re.I))
            if cert_a:
                cert_link = cert_a.get("href", "")

            if name and (address or phone):
                records.append({
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "category": current_category,
                    "cert_link": cert_link,
                    "website": website,
                    "source": "ORB",
                })

    return records


if __name__ == "__main__":
    import json
    data = scrape_orb()
    print(f"Scraped {len(data)} ORB rows")
    print(json.dumps(data[:5], indent=2))
