"""
Runs both scrapers, geocodes the results, applies the agreed tagging rules,
and writes the final data/restaurants.json consumed by the map (docs/index.html).

Tagging rules (as specified):
  - ORB entries: Agency = "ORB". Cholov Yisroel / Cholov Stam come directly
    from which ORB subcategory the restaurant was listed under.
  - Kosher Miami entries:
      * If explicitly flagged "KDM" -> Agency = "KDM", add "Cholov Yisroel".
      * Else if the restaurant's Type includes "Dairy" -> Agency = "KM",
        add "Cholov Stam" (KM dairy without the KDM mark implies the
        commercially-available/Cholov Stam standard).
      * Else -> Agency = "KM", no Cholov Yisroel/Stam tag.
"""
import json
import re
from pathlib import Path
from collections import defaultdict

from scrape_orb import scrape_orb
from scrape_km import scrape_km
from scrape_sunshine import scrape_sunshine
from geocode import geocode_all

OUT_PATH = Path(__file__).parent.parent / "data" / "restaurants.json"
KDM_PATTERN = re.compile(r"\bKDM\b", re.IGNORECASE)


def process_orb(raw):
    """Collapse ORB's per-subcategory rows into one row per restaurant."""
    grouped = defaultdict(lambda: {
        "categories": set(), "cholov_yisroel": False, "cholov_stam": False,
    })
    meta = {}

    for row in raw:
        key = (row["name"], row["address"])
        cat = row["category"]
        g = grouped[key]
        meta[key] = row

        if cat.lower() == "cholov yisroel":
            g["cholov_yisroel"] = True
        elif cat.lower() == "cholov stam":
            g["cholov_stam"] = True
        elif cat.lower() == "pas yisroel":
            g["categories"].add("Pas Yisroel")
        else:
            g["categories"].add(cat)

    out = []
    for key, g in grouped.items():
        base = meta[key]
        out.append({
            "name": base["name"],
            "address": base["address"],
            "area": "",
            "phone": base["phone"],
            "category": ", ".join(sorted(g["categories"])),
            "agency": "ORB",
            "cholov_yisroel": g["cholov_yisroel"],
            "cholov_stam": g["cholov_stam"],
            "cert_link": base.get("cert_link", ""),
            "source": "ORB",
        })
    return out


def process_km(raw):
    out = []
    for row in raw:
        name = row["name"]
        ctype = row["type"]
        is_kdm = bool(KDM_PATTERN.search(name))
        is_dairy = "dairy" in ctype.lower()

        categories = ctype
        cholov_yisroel = False
        cholov_stam = False

        if is_kdm:
            agency = "KDM"
            cholov_yisroel = True
            if "cholov yisroel" not in categories.lower():
                categories += ", Cholov Yisroel"
        else:
            agency = "KM"
            if is_dairy:
                cholov_stam = True
                if "cholov stam" not in categories.lower():
                    categories += ", Cholov Stam"

        out.append({
            "name": name,
            "address": row.get("address", ""),
            "area": row.get("area", ""),
            "phone": row.get("phone", ""),
            "category": categories,
            "agency": agency,
            "cholov_yisroel": cholov_yisroel,
            "cholov_stam": cholov_stam,
            "cert_link": "",
            "source": "Kosher Miami",
        })
    return out


def process_sunshine(raw):
    """
    Sunshine State Kosher (agency code: SSK - not an official abbreviation
    the agency uses on their site, just a short code for this dataset).
    No Cholov Yisroel/Cholov Stam distinction is published on their site,
    so those flags are left False here unless you learn otherwise.
    """
    out = []
    for row in raw:
        category = row.get("category", "")
        is_cy = "cholov yisroel" in category.lower()
        out.append({
            "name": row["name"],
            "address": row.get("address", ""),
            "area": row.get("area", ""),
            "phone": row.get("phone", ""),
            "email": row.get("email", ""),
            "category": category,
            "agency": "SSK",
            "cholov_yisroel": is_cy,
            "cholov_stam": False,
            "cert_link": "",
            "source": "Sunshine State Kosher",
        })
    return out


def main():
    print("Scraping ORB...")
    orb_raw = scrape_orb()
    print(f"  {len(orb_raw)} raw ORB rows")
    orb_records = process_orb(orb_raw)
    print(f"  {len(orb_records)} unique ORB restaurants")

    print("Scraping Kosher Miami...")
    km_raw = scrape_km()
    print(f"  {len(km_raw)} raw Kosher Miami rows")
    km_records = process_km(km_raw)

    print("Scraping Sunshine State Kosher...")
    sunshine_raw = scrape_sunshine()
    print(f"  {len(sunshine_raw)} raw Sunshine State Kosher rows")
    sunshine_records = process_sunshine(sunshine_raw)

    all_records = orb_records + km_records + sunshine_records

    print("Geocoding...")
    all_records = geocode_all(all_records)
    geocoded = sum(1 for r in all_records if r.get("lat"))
    print(f"  {geocoded}/{len(all_records)} geocoded successfully")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(all_records, indent=2))
    print(f"Wrote {len(all_records)} records to {OUT_PATH}")


if __name__ == "__main__":
    main()
