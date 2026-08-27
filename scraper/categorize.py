"""
Turns messy, inconsistent category text from any of the three certifying
agencies into four clean, orthogonal tag groups:

  food_type   - Dairy / Meat / Parve  (what animal products are involved -
                per kosher law, every dish is one of these three)
  food_service- Restaurant / Bakery / Take Out / Drinks and Snacks
                (how you consume it)
  commercial  - Catering / Commercial / Wholesale Only / Wholesale
                Distribution / Food Additives / Manufacturing / Grocery /
                Butcher / Misc  (not a place you walk into and eat)
  stringency  - Cholov Yisroel / Pas Yisroel / Yoshon
                (stricter standards some people specifically look for -
                Cholov Stam is deliberately NOT surfaced as its own tag:
                it's the unmarked default, so anyone who cares just
                selects Cholov Yisroel instead)

This is intentionally keyword-based (not a fixed lookup table) so it
handles free-text variations like "Bakery (pareve, pas Yisroel)",
"Cholov Yisroel Dairy Take-Out", or "Meat Catering" correctly by pulling
every relevant signal out of the string, rather than needing an exact
match.
"""
import re

COMMERCIAL_KEYWORDS = {
    "wholesale distribution": "Wholesale Distribution",
    "wholesale only": "Wholesale Only",
    "food additives": "Food Additives",
    "manufacturing": "Manufacturing",
    "grocery": "Grocery",
    "butcher": "Butcher",
    "commercial": "Commercial",
    "misc": "Misc",
}

HANDLE_RE = re.compile(r"^@\w+$")


def normalize(raw_text):
    """
    raw_text: any free-text category/description string (categories can be
    comma-separated, parenthetical, etc. - all handled the same way).
    Returns a dict of four sets: food_type, food_service, commercial, stringency.
    """
    text = raw_text or ""
    tl = text.lower()

    food_type = set()
    food_service = set()
    commercial = set()
    stringency = set()

    # --- Food type (Dairy / Meat / Parve) ---
    if "pareve and dairy" in tl:
        food_type.update(["Parve", "Dairy"])
    else:
        if re.search(r"\bpareve\b", tl) or re.search(r"\bparve\b", tl):
            food_type.add("Parve")
        if re.search(r"\bdairy\b", tl):
            food_type.add("Dairy")
        if re.search(r"\bmeat\b", tl):
            food_type.add("Meat")

    # --- Stringencies ---
    if "cholov yisroel" in tl:
        stringency.add("Cholov Yisroel")
        food_type.add("Dairy")  # "Cholov Yisroel X" always implies dairy
    # Cholov Stam is intentionally not surfaced - it's the unmarked default.
    if "non pas yisroel" not in tl and "pas yisroel" in tl:
        stringency.add("Pas Yisroel")
    if "yoshon" in tl:
        stringency.add("Yoshon")

    # --- Food service (how it's consumed) ---
    if "bakery" in tl:
        food_service.add("Bakery")
    if re.search(r"take[\s-]?out", tl):
        food_service.add("Take Out")
    if "snack foods" in tl or "healthy drinks" in tl or "drinks/snacks" in tl \
       or "drinks and snacks" in tl:
        food_service.add("Drinks and Snacks")

    # --- Commercial & wholesale ---
    if "catering" in tl:
        commercial.add("Catering")
    for kw, label in COMMERCIAL_KEYWORDS.items():
        if kw in tl:
            commercial.add(label)

    # If nothing else categorized it (no bakery/take-out/catering/commercial
    # signal at all) but it does have a food type, it's a plain sit-down
    # restaurant - the common case for most ORB/Kosher Miami listings.
    if food_type and not food_service and not commercial:
        food_service.add("Restaurant")

    return {
        "food_type": sorted(food_type),
        "food_service": sorted(food_service),
        "commercial": sorted(commercial),
        "stringency": sorted(stringency),
    }


def strip_handles(lines):
    """Remove social-media-handle-only lines (e.g. '@thebassarboard') from
    a list of text lines - these aren't categories or contact info worth
    keeping."""
    return [l for l in lines if not HANDLE_RE.match(l.strip())]
