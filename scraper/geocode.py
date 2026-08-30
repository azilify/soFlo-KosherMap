"""
Geocodes addresses using OpenStreetMap's free Nominatim API.

Caches results in data/geocode_cache.json so that re-running daily only
geocodes NEW or CHANGED addresses, not the whole list every time. This
respects Nominatim's usage policy (max ~1 request/second, must set a
descriptive User-Agent) and keeps the daily job fast.

If you'd rather use Google's Geocoding API (more accurate, but requires a
billing-enabled API key stored as a GitHub Actions secret), swap the
`geocode_one` function body for a call to
https://maps.googleapis.com/maps/api/geocode/json and set GOOGLE_MAPS_API_KEY
as a repo secret.
"""
import json
import re
import time
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent.parent / "data" / "geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "KosherRestaurantMap/1.0 (personal project; contact via GitHub)"}

ZIP_RE = re.compile(r"\b(\d{5})\b")


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _query_nominatim(query):
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "us"}
    try:
        r = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        results = r.json()
        if results:
            return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}
    except Exception as e:
        print(f"Geocode failed for '{query}': {e}")
    return None


def geocode_one(address, area_hint=""):
    if not address or not address.strip():
        return None

    # Avoid appending a redundant ", FL" onto addresses that already contain
    # the state (most do, since these are printed as "...City, FL 33312").
    # A duplicated state can confuse the geocoder on some queries.
    needs_state = "fl" not in address.lower()
    if area_hint:
        query = f"{address}, {area_hint}" + (", FL" if needs_state else "")
    else:
        query = address + (", FL" if needs_state else "")

    result = _query_nominatim(query)
    if result:
        return result

    # Fallback: some addresses list a city that doesn't officially match its
    # own zip code (e.g. a business calling itself "Fort Lauderdale" at a
    # zip code that's technically Hollywood's, or vice versa - common along
    # unincorporated county lines in South Florida). If the full address
    # fails, retry with just the street and zip, dropping the city name
    # entirely - that sidesteps the mismatch.
    zip_match = ZIP_RE.search(address)
    if zip_match:
        street = address.split(",")[0].strip()
        fallback_query = f"{street}, FL {zip_match.group(1)}"
        if fallback_query.lower() != query.lower():
            result = _query_nominatim(fallback_query)
            if result:
                return result

    return None


def geocode_all(records):
    """
    records: list of dicts each with 'address' and optionally 'area'.
    Adds 'lat'/'lon' keys in place. Returns the same list.

    IMPORTANT: only successful lookups are cached. A failed lookup (bad
    network blip, rate limit, temporary geocoder hiccup) is deliberately
    NOT cached, so it gets retried on the next run instead of being
    permanently stuck as "no coordinates" forever.
    """
    cache = load_cache()
    updated = False

    for rec in records:
        addr = rec.get("address", "")
        area = rec.get("area", "")
        key = f"{addr}|{area}".strip().lower()
        if not key.strip("|"):
            rec["lat"], rec["lon"] = None, None
            continue

        # Treat a cached null the same as "not cached at all" - this is what
        # actually lets old, already-stuck failures heal themselves on the
        # next run, rather than only preventing NEW failures from getting
        # stuck (which is all the previous version of this fix did).
        if key in cache and cache[key] is not None:
            coords = cache[key]
        else:
            coords = geocode_one(addr, area)
            if coords:
                cache[key] = coords
                updated = True
            time.sleep(1.1)  # respect Nominatim's ~1 req/sec limit

        if coords:
            rec["lat"], rec["lon"] = coords["lat"], coords["lon"]
        else:
            rec["lat"], rec["lon"] = None, None

    if updated:
        save_cache(cache)

    return records
