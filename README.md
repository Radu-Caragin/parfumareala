# Perfume Price Tracker

A personal, local web application for monitoring perfume prices across multiple
online perfume stores. Runs entirely on your machine: no external services,
no authentication, no scheduled/background scraping - every price check is
something you trigger yourself.

**Supported stores:** Fragranza.ro, Parfimo.ro, EsenteDeLux.ro, Vivantis.ro,
Notino.ro, Parfumat.ro, Brasty.ro, Koku.ro. Additional stores are added one
at a time, each as its own isolated scraper module, as they're provided.

Note: Vivantis.ro's and Notino.ro's Cloudflare configuration fingerprints
the TLS/HTTP handshake itself, not just headers - plain httpx gets
challenged on every request there, so those two scrapers use `curl_cffi`
(Chrome TLS-fingerprint impersonation) instead, via a shared
`CurlCffiScraper` base class (`app/scrapers/curl_base.py`). Every other
store still uses plain httpx.

## What it does

- You maintain a list of perfumes you care about (brand + name only).
- "Check prices" searches every enabled store and discovers every distinct
  variant (concentration, volume, tester status) actually sold - you never
  enter bottle sizes yourself.
- Each exact variant (e.g. "Xerjoff Erba Gold EDP 100 ml") is compared only
  against the same exact variant at other stores - concentrations, volumes,
  and tester/normal bottles are never mixed.
- The cheapest currently **in-stock** offer is highlighted per variant.
- A simple price-history table (no charts) shows how a price has moved over
  time, per store and variant.
- Local price alerts: set a target price on an exact variant and the app
  highlights it on the perfume's page when an in-stock offer drops to or
  below that price. There are no email/push/Telegram notifications - alerts
  only ever show up inside this app.
- Gift sets, samples, miniatures, refills, and bundles are filtered out
  automatically; normal bottles and testers are kept as separate products.

## Setup

```bash
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # optional, defaults work out of the box
```

Requires Python 3.9+ (64-bit). A 32-bit interpreter will fail to install
`uvicorn[standard]`'s compiled dependencies.

## Running

```bash
python run.py
```

Then open http://127.0.0.1:8000 in your browser. The SQLite database and
`logs/` directory are created automatically on first run.

## Using it

- **Add a perfume**: Dashboard → "Add perfume" → enter brand and name.
- **Check prices for one perfume**: open the perfume's page → "Check prices".
  This searches every enabled store, matches results against this perfume,
  and shows every variant found with its price and stock status per store.
- **Check all perfumes**: Dashboard → "Check all perfumes" - runs the same
  process for every monitored perfume. This is a synchronous request; with
  several perfumes and stores it can take a while (the button disables
  itself with a "Checking..." label while it runs).
- **Store status**: if a store didn't have a matching product, it shows
  "Not available"; if the scraper itself failed, it shows "Scraping error" -
  these are deliberately kept distinct so you know whether the store was
  actually checked.
- **Price history**: on a perfume's page, each store offer has a "History"
  link showing its price/stock changes over time. A new row is only added
  when the price or stock status actually changed.
- **Price alerts**: on a perfume's page, each variant has a small "Alert if
  price ≤ ..." form. When triggered, a banner appears at the top of the
  page - this is computed live from the current stored prices, so it's
  accurate even without running a fresh check.
- **Enable/disable a store**: Stores page → toggle. Disabling only stops
  future checks for that store - it never deletes its price history or
  previously discovered products.

## Database

SQLite, stored at `data/perfume_tracker.db` (path configurable via
`DATABASE_PATH` in `.env`). Created and initialized automatically on first
run via `Base.metadata.create_all()` - no separate database server, no
migrations tool for this project's current stage.

Main entities: `Perfume` (what you monitor) → `PerfumeVariant` (an exact
concentration+volume+tester combination) → `StoreProduct` (that variant's
current price/stock at one store) → `PriceHistory` (append-only, on change
only). `ScrapeRun`/`ScrapeResult` record each check and its per-store
outcome. `PriceAlert` belongs to one exact `PerfumeVariant`.

## Project architecture

```text
app/
├── main.py                 # FastAPI app: lifespan, static files, routes, error page
├── config/                 # Settings, loaded from .env
├── database/
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # engine/session, init_db()
│   ├── seed.py               # initial Store rows (currently: Fragranza.ro)
│   └── repositories/        # one module per entity - all DB access goes through these
├── normalization/           # pure functions: brand/name/concentration/volume/
│                             # tester/price parsing, exclusion filters
├── scrapers/
│   ├── base.py               # BaseScraper: HTTP client, retries, rate limiting
│   ├── registry.py           # @register_scraper - no if/elif dispatch by store
│   ├── exceptions.py         # RequestError, ParsingError, StoreUnavailable, ...
│   └── stores/               # one module per store (e.g. fragranza.py)
├── services/
│   ├── scraping_service.py   # orchestrates a price check end to end
│   ├── matching_service.py   # validates a scraped candidate against a monitored perfume
│   ├── comparison_service.py # best-price selection per variant
│   ├── alert_service.py      # price alert evaluation
│   └── perfume_service.py    # perfume CRUD + normalization
├── routes/                  # FastAPI routers (thin - delegate to services/repos)
├── templates/                # Jinja2 templates
└── static/css/               # stylesheet

data/            # SQLite database (gitignored)
logs/            # application logs (gitignored)
tests/           # mirrors the app/ structure; fixtures under tests/fixtures/
```

## Adding a new store

1. Investigate the site first (structured data? server-rendered HTML? does
   `robots.txt` disallow anything relevant?) before writing any selectors.
2. Create `app/scrapers/stores/<store>.py` implementing `BaseScraper`
   (`search_perfume`, `fetch_product`, `parse_product`), decorated with
   `@register_scraper`.
3. Import it in `app/scrapers/stores/__init__.py`.
4. Add its row to `app/database/seed.py`.
5. Add fixture-based tests under `tests/scrapers/stores/` (no live requests
   in the default test run - see below).

Nothing else needs to change: the dashboard, database schema, matching,
comparison, history, and alerts are all store-agnostic already.

## Running tests

```bash
python -m pytest -q
```

This never touches the real `data/perfume_tracker.db` (an isolated
in-memory SQLite database is used) and never makes real network requests
(scrapers are tested against saved HTML fixtures via `httpx.MockTransport`).

A small number of optional tests hit the real Fragranza.ro website, to
catch when its markup has drifted from the fixtures. They're excluded by
default (`pytest.ini`: `-m "not live"`) and run explicitly with:

```bash
python -m pytest -m live -q
```

## Configuration

All settings live in `.env` (copy from `.env.example`); every value has a
sensible default in `app/config/settings.py` if omitted.

| Variable | Purpose |
|---|---|
| `DATABASE_PATH` | SQLite file location |
| `REQUEST_TIMEOUT`, `REQUEST_DELAY`, `MAX_RETRIES`, `USER_AGENT` | scraper HTTP behavior |
| `MATCH_NAME_HIGH_CONFIDENCE_THRESHOLD`, `MATCH_NAME_AMBIGUOUS_THRESHOLD` | fuzzy name-matching cutoffs (brand/concentration/volume/tester always stay exact) |
| `DEBUG` | verbose logging + auto-reload |
| `HOST`, `PORT` | local server binding |
