"""
Runs all three scrapers, geocodes the results, applies clean category
tagging (see categorize.py), and writes data/restaurants.json.

RESILIENCE: if any one source's scrape returns 0 rows (site down, layout
changed, temporary network issue), this script keeps that source's
previous entries from the last successful run instead of wiping them out.
A day where Kosher Miami's JS-rendering fails shouldn't delete every
Kosher Miami restaurant from the map - it should just skip updating them
until the next successful run.
"""
import json
import re
from pathlib import Path
from collections import defaultdict

from scrape_orb import scrape_orb
from scrape_km import scrape_km
from scrape_sunshine import scrape_sunshine
from geocode import geocode_all
from categorize import normalize

OUT_PATH = Path(__file__).parent.parent / "data" / "restaurants.json"
KDM_PATTERN = re.compile(r"\bKDM\b", re.IGNORECASE)

AGENCY_NAMES = {
    "ORB": "ORB",
    "KM": "KM",
    "KDM": "KDM",
    "SSK": "Sunshine State Kosher",
}


def tag_record(base, extra_text_for_tagging):
    """Runs categorize.normalize() and attaches the four tag arrays plus a
    combined display string (used in map popups)."""
    tags = normalize(extra_text_for_tagging)
    base.update(tags)
    all_tags = tags["food_type"] + tags["food_service"] + tags["commercial"] + tags["stringency"]
    base["category"] = ", ".join(all_tags)
    return base


def process_orb(raw):
    """Collapse ORB's per-subcategory rows into one row per restaurant."""
    grouped = defaultdict(lambda: {"raw_tags": set()})
    meta = {}

    for row in raw:
        key = (row["name"], row["address"])
        meta[key] = row
        grouped[key]["raw_tags"].add(row["category"])

    out = []
    for key, g in grouped.items():
        base = meta[key]
        combined_text = ", ".join(g["raw_tags"])
        rec = tag_record({
            "name": base["name"],
            "address": base["address"],
            "area": "",
            "phone": base["phone"],
            "agency": "ORB",
            "cert_link": base.get("cert_link", ""),
            "source": "ORB",
        }, combined_text)
        out.append(rec)
    return out


def process_km(raw):
    out = []
    for row in raw:
        name = row["name"]
        ctype = row["type"]
        is_kdm = bool(KDM_PATTERN.search(name))
        agency = "KDM" if is_kdm else "KM"

        # KM (not KDM) dairy listings are Cholov Stam by definition, but per
        # the agreed rule, Cholov Stam isn't surfaced as its own filter tag -
        # so no extra text needs adding here for that case. KDM listings do
        # need "Cholov Yisroel" added explicitly since KM's raw Type field
        # never says it.
        text_for_tagging = ctype + (", Cholov Yisroel" if is_kdm else "")

        rec = tag_record({
            "name": name,
            "address": row.get("address", ""),
            "area": row.get("area", ""),
            "phone": row.get("phone", ""),
            "agency": agency,
            "cert_link": "",
            "source": "Kosher Miami",
        }, text_for_tagging)
        out.append(rec)
    return out


def process_sunshine(raw):
    out = []
    for row in raw:
        rec = tag_record({
            "name": row["name"],
            "address": row.get("address", ""),
            "area": row.get("area", ""),
            "phone": row.get("phone", ""),
            "agency": "SSK",
            "cert_link": "",
            "source": "Sunshine State Kosher",
        }, row.get("category", ""))
        out.append(rec)
    return out


def load_previous():
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text())
        except Exception:
            return []
    return []


def main():
    previous = load_previous()
    previous_by_source = defaultdict(list)
    for r in previous:
        previous_by_source[r.get("source")].append(r)

    print("Scraping ORB...")
    orb_raw = scrape_orb()
    orb_records = process_orb(orb_raw) if orb_raw else previous_by_source.get("ORB", [])
    if not orb_raw:
        print(f"  ORB scrape returned nothing - keeping {len(orb_records)} previous entries")
    else:
        print(f"  {len(orb_records)} ORB restaurants")

    print("Scraping Kosher Miami...")
    km_raw = scrape_km()
    km_records = process_km(km_raw) if km_raw else previous_by_source.get("Kosher Miami", [])
    if not km_raw:
        print(f"  Kosher Miami scrape returned nothing - keeping {len(km_records)} previous entries")
    else:
        print(f"  {len(km_records)} Kosher Miami restaurants")

    print("Scraping Sunshine State Kosher...")
    sunshine_raw = scrape_sunshine()
    sunshine_records = process_sunshine(sunshine_raw) if sunshine_raw else previous_by_source.get("Sunshine State Kosher", [])
    if not sunshine_raw:
        print(f"  Sunshine State Kosher scrape returned nothing - keeping {len(sunshine_records)} previous entries")
    else:
        print(f"  {len(sunshine_records)} Sunshine State Kosher restaurants")

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
