# South Florida Kosher Restaurant Map — auto-updating

A free, self-updating pipeline: a daily scraper (GitHub Actions) refreshes
restaurant data from ORB and Kosher Miami, and a static map (GitHub Pages)
displays it with your filters (food category, certifying agency, dairy
standard). No server to pay for or maintain.

## What's in this folder

```
index.html                        the map itself (open this in a browser)
data/restaurants.json             the data the map reads (auto-generated)
data/geocode_cache.json           cached address -> lat/lon lookups
scraper/scrape_orb.py             pulls ORB's restaurant list (static HTML)
scraper/scrape_km.py              pulls Kosher Miami's list (JS-rendered, uses a headless browser)
scraper/scrape_sunshine.py        pulls Sunshine State Kosher's two PDF lists (finds fresh signed links + parses PDF tables)
scraper/geocode.py                turns addresses into map coordinates
scraper/build_data.py             runs all three scrapers + applies your tagging rules, writes data/restaurants.json
.github/workflows/daily-update.yml   the daily scheduled job
```

## One-time setup (about 10 minutes)

1. **Create a free GitHub account** at github.com if you don't have one.
2. **Create a new repository** (e.g. `kosher-map`), and upload every file in
   this folder to it, keeping the same folder structure.
3. **Turn on GitHub Pages**: repo → Settings → Pages → under "Build and
   deployment," set Source to "Deploy from a branch," branch `main`,
   folder `/ (root)`. Save. GitHub will give you a URL like
   `https://yourusername.github.io/kosher-map/` — that's your live map.
4. **Turn on Actions permissions**: repo → Settings → Actions → General →
   under "Workflow permissions," select "Read and write permissions." This
   lets the daily job commit updated data back to the repo.
5. **Run it once manually** to populate real data instead of waiting for the
   schedule: repo → Actions tab → "Daily kosher restaurant data update" →
   "Run workflow." It takes a few minutes (installing a headless browser +
   geocoding every address the first time).
6. Refresh your map URL — it should now show pins.

After that, it runs automatically every day at 9:00 AM UTC (edit the `cron`
line in `.github/workflows/daily-update.yml` to change the time —
crontab.guru is helpful for that).

## Known limitation: Kosher Miami's scraper is a best guess

ORB's page is plain HTML, so `scrape_orb.py` is straightforward and reliable.

Kosher Miami's page loads its list via JavaScript that I could not directly
inspect from this chat (I can only fetch raw HTML, not run a browser). I
wrote `scrape_km.py` to load the page with a real headless browser and parse
the rendered text using the same row pattern as the PDF export you provided
("Name / Type / Area / Address / Phone"). This is a reasonable bet since
that PDF was itself a printout of the site's List View — but it **may need
adjustment** once it runs against the live site for real.

**If the Kosher Miami side comes back empty:**
1. Go to the Actions tab → the failed/empty run → download the `km-debug`
   artifact. It contains a screenshot and full HTML of what the scraper
   actually saw.
2. Compare that to `ROW_PATTERN` and the "List View" click logic near the
   top of `scraper/scrape_km.py`, and adjust the pattern or selector to
   match what's really there.
3. Feel free to paste that debug HTML back into a chat with Claude and ask
   for a fix — that's a case where I can actually see the real structure
   and correct the scraper properly.

## Sunshine State Kosher's scraper

Their facilities page (`sunshinestatekosher.org/facilities`) is plain HTML,
but it links to two PDFs behind **signed, expiring URLs** (CloudFront-style
`Expires`/`Signature`/`Key-Pair-Id` query parameters). `scrape_sunshine.py`
re-loads the facilities page on every run to grab a **fresh** link (since
yesterday's signed URL will have expired) before downloading each PDF, then
parses the real 3-column table layout inside them (logo / name+address /
category+contact), including the county-header banner rows in the Playa
Bowls list.

Unlike the Kosher Miami scraper, this one was tested directly against real
copies of both PDFs before being shipped, so it's on solid footing rather
than a guess. If the agency changes their PDF's layout in the future and
rows start coming back empty or garbled, the same debugging path applies:
Actions tab → the run → download the `scraper-debug` artifact →
`data/sunshine_debug.txt` has the raw table cells the script extracted, which
you can compare against the parsing logic in `scrape_sunshine.py`.

## Adding more certifying agencies later

Add a new `scrape_<agency>.py` following the same pattern (return a list of
dicts with name/address/phone/type/area), import it in `build_data.py`, and
add its tagging rules there (agency name, any Cholov Yisroel/Stam logic
specific to that agency).

## Costs

$0. GitHub Actions gives free minutes to public repos (and a generous free
tier for private ones too), GitHub Pages hosting is free, and Nominatim
geocoding is free for this volume of daily requests since results are
cached and only new/changed addresses get re-geocoded.
