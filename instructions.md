I want you to help me build a complete **local Python web application for monitoring perfume prices across multiple online perfume stores**.

This will be a personal tool used only by me, running locally on my computer.

The application must be designed as a **clean, modular, maintainable project**, not as one large Python file and not as a collection of unrelated scripts in one folder.

Do not rush into writing the entire project at once. We will build it incrementally.

---

# 1. Main purpose

I want to manually maintain a list of perfumes that I am interested in.

For each perfume I will provide:

* Brand
* Perfume/model name

Example:

```text
Brand: Xerjoff
Perfume: Erba Gold
```

When I run a price check, the application should search all currently supported and enabled perfume stores and find all relevant variants of that perfume.

For example:

```text
Xerjoff Erba Gold

50 ml EDP
100 ml EDP
100 ml EDP Tester
```

If applicable, different concentrations must be treated as different products:

```text
Dior Sauvage EDT 100 ml
Dior Sauvage EDP 100 ml
Dior Sauvage Parfum 100 ml
```

Tester versions must also be treated separately:

```text
Xerjoff Naxos EDP 100 ml
Xerjoff Naxos EDP 100 ml Tester
```

Do NOT combine these variants.

The purpose of the application is to make it easy for me to see the current price of each exact perfume variant across all supported stores.

---

# 2. Products that must be included

Normal retail bottles should be included.

Tester versions should also be included and treated as separate product variants.

Examples:

```text
100 ml EDP
100 ml EDP Tester
```

These are two different variants.

The same applies for different concentrations:

```text
100 ml EDT
100 ml EDP
100 ml Parfum
```

These are different variants.

---

# 3. Products that must be excluded

The scraper should exclude products such as:

* Gift sets
* Sets containing multiple products
* Refill bottles
* Refill-only products
* Miniature sets
* Discovery sets
* Samples
* Sample packs
* Multi-product bundles

Normal retail bottles and testers should remain included.

The exclusion logic should ideally be centralized in the normalization/filtering layer rather than duplicated inside every store scraper.

---

# 4. Store implementation strategy

The application must be architected from the beginning to support **multiple perfume stores**, but we will NOT implement all stores immediately.

Stores will be added progressively during development.

I will personally provide each new website/store that I want to add.

Do NOT:

* invent additional stores
* automatically add stores that I have not requested
* implement placeholder scrapers for future stores
* assume which websites will be supported later

The architecture should simply make it easy to add new store scrapers when I provide them.

Each new store must have its own isolated scraper module/class.

For example, over time the structure may become:

```text
app/
└── scrapers/
    ├── base.py
    ├── registry.py
    └── stores/
        ├── fragranza.py
        ├── future_store_1.py
        ├── future_store_2.py
        └── ...
```

However, only actual requested stores should exist in the project.

Do not generate dummy scraper files for future stores.

---

# 5. First and only store for initial development

We will begin with:

**Fragranza.ro**

Website:

https://fragranza.ro/

Fragranza.ro must be the ONLY real perfume store scraper implemented initially.

Do not implement:

* Notino
* Parfimo
* Douglas
* Vivantis
* Brasty
* Sephora
* or any other store

unless I explicitly provide that website later.

The development sequence should therefore be:

1. Build the general multi-store architecture.
2. Build the SQLite database and application logic.
3. Build the local web interface.
4. Build the scraper infrastructure.
5. Investigate Fragranza.ro.
6. Implement Fragranza.ro.
7. Connect Fragranza.ro to the complete application.
8. Test everything.
9. Add other stores later, one at a time, when I provide them.

---

# 6. Recommended technology stack

Use:

* Python 3
* FastAPI
* Jinja2 templates
* HTMX where useful for lightweight dynamic UI functionality
* SQLite
* SQLAlchemy
* Pydantic where appropriate
* httpx for HTTP requests
* BeautifulSoup or lxml for HTML parsing
* pytest for testing

Prefer normal HTTP scraping whenever possible.

If a website needs browser rendering or JavaScript interaction, use:

* Playwright

only when actually necessary.

Do NOT automatically use Playwright.

Do NOT use Selenium unless there is an exceptional technical reason and you explain that reason first.

Keep the application lightweight because it is a personal application running locally.

---

# 7. Project architecture

I want a professional folder structure.

Do NOT place everything in the root folder.

Do NOT create one giant `main.py`.

Use an architecture conceptually similar to:

```text
perfume-price-tracker/
│
├── app/
│   ├── main.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── perfumes.py
│   │       ├── stores.py
│   │       ├── prices.py
│   │       └── alerts.py
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── exceptions.py
│   │   └── stores/
│   │       ├── __init__.py
│   │       └── fragranza.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── perfume_service.py
│   │   ├── scraping_service.py
│   │   ├── matching_service.py
│   │   ├── normalization_service.py
│   │   ├── comparison_service.py
│   │   └── alert_service.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── perfume.py
│   │   ├── scraping.py
│   │   └── store.py
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── perfumes.py
│   │   ├── stores.py
│   │   └── settings.py
│   │
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── perfumes/
│   │   ├── stores/
│   │   └── components/
│   │
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       └── helpers.py
│
├── data/
│   └── perfume_tracker.db
│
├── logs/
│
├── tests/
│   ├── scrapers/
│   ├── services/
│   ├── normalization/
│   └── fixtures/
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── run.py
```

You may improve this architecture if you think there is a cleaner solution.

However, if you want to substantially change it, explain why before doing so.

Keep responsibilities clearly separated.

---

# 8. Local web interface

The application must have a clean local web interface.

I want to start the application with something simple such as:

```bash
python run.py
```

and then access it locally through something like:

```text
http://127.0.0.1:8000
```

The application does not need authentication because it will only be used locally by me.

The interface should be:

* clean
* modern
* simple
* easy to navigate
* functional rather than overly decorative

Do not build a frontend SPA with React/Vue unless there is a very strong reason.

FastAPI + Jinja2 + HTMX should be sufficient.

---

# 9. Dashboard

The main page should show all perfumes that I am monitoring.

Conceptually:

```text
------------------------------------------------------
PERFUME PRICE TRACKER
------------------------------------------------------

[ Add perfume ]             [ Check all perfumes ]

Xerjoff Erba Gold
Last checked: Today 14:30
Best available price: 799 RON

[ View prices ] [ Check now ] [ Edit ] [ Delete ]

------------------------------------------------------

Xerjoff Naxos
Last checked: Yesterday
Best available price: 849 RON

[ View prices ] [ Check now ] [ Edit ] [ Delete ]
```

The exact UI design can be improved during development.

---

# 10. Adding perfumes

I should be able to add a perfume through the web interface.

The required fields should initially be:

```text
Brand
Perfume name
```

Example:

```text
Brand: Xerjoff
Perfume name: Erba Gold
```

Do NOT require me to manually enter:

* volume
* concentration
* tester status

The scrapers should discover available variants automatically.

I should also be able to:

* edit a monitored perfume
* delete a monitored perfume
* see when it was last checked

---

# 11. Price checking

There must be two separate manual actions.

## Check one perfume

Each perfume should have a button such as:

```text
Check prices
```

This should check that perfume against every currently enabled store.

## Check all perfumes

There must also be a global button:

```text
Check all perfumes
```

This should check every saved perfume against every currently enabled store.

Scraping is manually triggered.

There is NO automatic scheduled scraping required.

Do not add cron jobs, Celery, Redis, background workers or external schedulers unless I specifically ask for them later.

---

# 12. Scraping progress

Because checking several perfumes across several stores may eventually take some time, the UI should be designed so it can show useful status information.

For example:

```text
Checking Xerjoff Erba Gold...

Fragranza.ro: completed
Future Store A: pending
Future Store B: pending
```

Do not overcomplicate this initially.

A simple loading/progress state through HTMX is sufficient.

The architecture should allow better progress reporting later if necessary.

---

# 13. Price comparison page

For each perfume, I want to see every discovered variant separately.

Example:

```text
Xerjoff Erba Gold
```

## EDP 50 ml

```text
Fragranza.ro      599 RON       In stock
Future Store A    649 RON       In stock
Future Store B    Not available
```

Best price:

```text
Fragranza.ro - 599 RON
```

## EDP 100 ml

```text
Fragranza.ro      799 RON       In stock
Future Store A    829 RON       In stock
Future Store B    910 RON       In stock
```

## EDP 100 ml Tester

```text
Fragranza.ro      719 RON       In stock
Future Store A    Not available
Future Store B    Not available
```

Each variant must be compared only against the exact same variant.

Never compare:

```text
50 ml against 100 ml
```

Never compare:

```text
EDT against EDP
```

Never compare:

```text
EDP against Parfum
```

Never compare:

```text
normal retail bottle against tester
```

---

# 14. Variant identity

A perfume variant should conceptually be identified by:

* Perfume
* Concentration
* Volume
* Tester status

For example:

```text
Xerjoff
Erba Gold
EDP
100 ml
Tester: False
```

is a different variant from:

```text
Xerjoff
Erba Gold
EDP
100 ml
Tester: True
```

and different from:

```text
Xerjoff
Erba Gold
EDP
50 ml
Tester: False
```

Variant identity is extremely important.

---

# 15. Store availability reporting

Stores where the perfume or variant was not found should still appear in the interface.

Do NOT simply hide missing results.

For example:

```text
Fragranza.ro       799 RON
Future Store A     Not available
Future Store B     Not available
```

This allows me to know that the store was actually checked.

Internally, distinguish between statuses such as:

```text
in_stock
out_of_stock
not_found
scraping_error
store_unavailable
```

The UI can convert these into readable labels:

```text
In stock
Out of stock
Not available
Scraping error
Store unavailable
```

---

# 16. Store management

Create a store management/settings page.

Each store should be enabled or disabled from the web interface.

Example:

```text
Stores

[x] Fragranza.ro
[ ] Future Store A
[x] Future Store B
```

Initially there will only be:

```text
[x] Fragranza.ro
```

Disabled stores should not be checked.

Disabling a store must NOT delete:

* historical prices
* previous products
* previous price checks
* stored URLs

It only disables future scraping for that store.

---

# 17. Store metadata

The database should maintain store information such as:

```text
name
slug
base_url
enabled
scraper_identifier
created_at
```

Potentially also:

```text
last_successful_check
last_error
```

if useful.

Do not hardcode store enable/disable logic directly in templates.

---

# 18. Data collected from each offer

For each scraped offer, collect as much of the following information as reliably possible:

```text
store
brand
perfume name
concentration
volume_ml
tester
price
old_price
currency
discount_percentage
availability
product_url
scraped_at
```

Example normalized result:

```python
{
    "store": "Fragranza.ro",
    "brand": "Xerjoff",
    "name": "Erba Gold",
    "concentration": "EDP",
    "volume_ml": 100,
    "tester": False,
    "price": 799.00,
    "old_price": 899.00,
    "currency": "RON",
    "availability": "in_stock",
    "product_url": "..."
}
```

Additional raw information may be stored if useful for debugging, but do not unnecessarily duplicate data.

---

# 19. Price handling

Prices should be stored numerically, not as raw strings.

For example:

```text
"799,99 Lei"
```

should become something like:

```python
Decimal("799.99")
```

Prefer `Decimal` rather than floating-point values for money.

Store currency separately.

Initially the main expected currency is:

```text
RON
```

Do not calculate price per ml.

I do NOT need price-per-ml information.

---

# 20. Old prices and discounts

If a store exposes:

* current price
* old/original price

store both where possible.

For example:

```text
Current price: 799 RON
Old price: 899 RON
```

Discount percentage may either be extracted or calculated if appropriate.

Do not invent an old price if the website does not provide one.

---

# 21. Normalization layer

Different stores may format products differently.

For example:

```text
Xerjoff Erba Gold Eau de Parfum 100 ml
Xerjoff Erba Gold EDP 100ml
ERBA GOLD Xerjoff 100 ML
Xerjoff Erba Gold 100 ml Apa de Parfum
```

These should ideally normalize to:

```text
Brand: Xerjoff
Name: Erba Gold
Concentration: EDP
Volume: 100
Tester: False
```

Create a dedicated normalization layer.

Do NOT mix normalization rules directly into:

* database code
* UI code
* routing code

Store-specific extraction may identify raw fields, but general normalization should be reusable.

---

# 22. Concentration normalization

Normalize common concentration names.

Examples:

```text
Eau de Parfum
EDP
E.D.P.
E.d.P.
Apa de parfum

=> EDP
```

```text
Eau de Toilette
EDT
E.D.T.
Apa de toaleta

=> EDT
```

Support where relevant:

```text
Parfum
Extrait de Parfum
Extrait
EDC
Eau de Cologne
Cologne
```

Be careful not to assume that every perfume has an EDP/EDT designation.

Some products may simply be marketed as:

```text
Parfum
Extrait
Cologne
```

---

# 23. Volume extraction

Bottle volume should be normalized as an integer or numeric number of milliliters.

Examples:

```text
100ml
100 ml
100 ML

=> 100
```

Handle typical perfume bottle sizes.

Do not mistake unrelated numbers in titles for bottle volume.

Use structured page information when available rather than relying only on title parsing.

---

# 24. Tester detection

Tester detection must be explicit.

For example:

```text
Tester
TESTER
tester perfume
100 ml tester
```

should set:

```python
tester = True
```

A product without a tester indication should normally be:

```python
tester = False
```

However, do not infer tester status incorrectly from unrelated text.

Tester status must participate in product matching.

---

# 25. Product exclusion filtering

Create reusable filtering rules that reject:

* refill
* refillable refill bottles when the item itself is a refill
* gift set
* set cadou
* coffret
* discovery set
* sample
* sample set
* miniatures
* miniature collections
* bundles with multiple products

Be careful with the word "refillable".

A normal perfume bottle that is refillable may still be a legitimate normal product.

What should be excluded is primarily a product sold as the refill itself.

The filtering system should be conservative enough to avoid incorrectly excluding valid perfume bottles.

---

# 26. Product matching

Product matching is extremely important.

The system should determine whether results from different websites refer to the same monitored perfume and the same perfume variant.

Matching should consider:

* normalized brand
* normalized perfume name
* concentration
* volume
* tester status

Example:

```text
Xerjoff Erba Gold EDP 100 ml
```

must NOT match:

```text
Xerjoff Erba Gold EDP 50 ml
```

or:

```text
Xerjoff Erba Gold EDP 100 ml Tester
```

or:

```text
Xerjoff Erba Gold EDT 100 ml
```

Do not rely only on crude string similarity.

Use structured normalization first.

Fuzzy matching can be used as an additional mechanism for perfume name matching where appropriate.

It should never override clear differences in:

* volume
* concentration
* tester status

---

# 27. Search candidate validation

When a store search returns results, do not blindly accept them.

Example monitored perfume:

```text
Brand: Xerjoff
Perfume: Erba Gold
```

The search may return:

```text
Xerjoff Erba Gold
Xerjoff Erba Pura
Xerjoff Gold Collection
Other unrelated Xerjoff products
```

Candidate search results must pass validation before being accepted.

Use:

1. brand matching
2. normalized perfume name matching
3. exclusion filters
4. structured product extraction
5. variant normalization

False positives should be rejected.

---

# 28. Confidence and ambiguous matches

If matching is ambiguous, prefer rejecting an uncertain result rather than displaying a completely unrelated perfume.

The architecture may optionally support a matching confidence score internally.

For example:

```text
exact
high_confidence
ambiguous
rejected
```

Do not expose this unnecessarily in the main UI initially.

It can be useful for debugging.

---

# 29. SQLite database

Use SQLite because I do not want to run a separate database server.

The database should automatically be created when the application starts for the first time.

Use SQLAlchemy.

Design a proper relational schema.

Likely entities include:

```text
Perfume
PerfumeVariant
Store
StoreProduct
ScrapeRun
ScrapeResult
PriceHistory
PriceAlert
```

You may modify the exact schema if you have a cleaner design.

Explain the final relationships before implementation.

Avoid unnecessary duplication.

---

# 30. Perfume entity

A monitored perfume should represent the perfume itself.

Example:

```text
Brand: Xerjoff
Name: Erba Gold
```

It should not initially require known bottle sizes.

Bottle variants should be discovered through scraping.

Potential fields:

```text
id
brand
name
normalized_brand
normalized_name
created_at
updated_at
last_checked_at
```

---

# 31. PerfumeVariant entity

Perfume variants should represent individual comparable variants.

For example:

```text
Xerjoff Erba Gold
EDP
100 ml
Tester: False
```

Potential fields:

```text
id
perfume_id
concentration
volume_ml
tester
created_at
```

The combination should be unique for a monitored perfume where appropriate.

---

# 32. StoreProduct entity

A StoreProduct should represent the relationship between a known perfume variant and a specific store product page.

Potential information:

```text
store_id
perfume_variant_id
product_url
store_product_identifier
product_title
last_seen_at
```

This may allow later checks to reuse a known product page instead of rediscovering the product every single time.

However, do not assume that product URLs will always remain valid.

The design should allow fallback to store search when necessary.

---

# 33. Scrape runs

It may be useful to model each manual scraping operation as a scrape run.

Examples:

```text
single perfume check
check all perfumes
```

A scrape run could contain:

```text
started_at
finished_at
status
number_of_perfumes
number_of_stores
errors
```

This should not be overengineered, but it could make debugging and status reporting easier.

---

# 34. Price history

Every successful price check should allow the system to preserve historical prices.

Example:

```text
Xerjoff Erba Gold
EDP
100 ml
Fragranza.ro

2026-08-20    849 RON
2026-08-22    819 RON
2026-08-24    799 RON
```

I DO NOT currently need graphs or charts.

A historical table is enough.

Do not build chart libraries unless I ask for them later.

---

# 35. Price history behavior

Think carefully about whether a new history row should be stored when the price has not changed.

Possible approaches:

A. Store every price observation.

B. Store only when the price or stock status changes.

For this personal application, recommend the approach that you think produces the most useful history while keeping the database simple.

Explain your choice before implementation.

---

# 36. Best price

For every exact perfume variant, automatically determine the cheapest currently available offer.

Example:

```text
Xerjoff Erba Gold EDP 100 ml

Fragranza.ro      799 RON
Future Store A    849 RON
Future Store B    829 RON

BEST PRICE:
Fragranza.ro - 799 RON
```

Only offers that are actually available/in stock should qualify as the best current price.

Do not use an out-of-stock offer as the best price.

Do not mix variants.

---

# 37. Price alerts

I want local price alerts.

I should be able to define something such as:

```text
Xerjoff Erba Gold
EDP
100 ml
Alert if price <= 750 RON
```

There should be NO:

* email alerts
* Telegram alerts
* push notifications
* SMS
* external notification services

The alert should only be shown inside the local web application.

When I manually check prices, the interface should highlight triggered alerts.

Example:

```text
PRICE ALERT

Xerjoff Erba Gold EDP 100 ml

Fragranza.ro
729 RON

Target: 750 RON
```

---

# 38. Alert behavior

Alerts should belong to an exact perfume variant.

For example:

```text
Xerjoff Erba Gold EDP 100 ml
```

not just:

```text
Xerjoff Erba Gold
```

unless we later explicitly add perfume-wide alerts.

The alert should trigger when at least one currently available store offer is equal to or below the threshold.

The UI should identify:

* store
* current price
* configured target price

---

# 39. Base scraper architecture

Create a reusable scraper abstraction.

For example conceptually:

```python
class BaseScraper:
    store_name: str
    store_slug: str
    base_url: str

    async def search_perfume(...):
        ...

    async def fetch_product(...):
        ...

    async def parse_product(...):
        ...
```

The exact interface is your design decision.

It should provide reusable functionality for:

* HTTP client/session
* timeout
* retries
* request headers
* User-Agent
* redirects
* configurable delay
* polite rate limiting
* response validation
* HTTP error handling
* logging

Do not duplicate these mechanics in every store scraper.

---

# 40. Scraper result model

All store scrapers should return data in a common normalized structure.

For example:

```python
ScrapedOffer(
    store="fragranza",
    raw_title="...",
    brand="Xerjoff",
    perfume_name="Erba Gold",
    concentration="EDP",
    volume_ml=100,
    tester=False,
    price=Decimal("799.00"),
    old_price=Decimal("899.00"),
    currency="RON",
    availability="in_stock",
    product_url="..."
)
```

Store-specific scrapers should not return arbitrary dictionaries with completely different fields.

Use a shared schema/model.

---

# 41. Scraper registry

I want the application to automatically know which scrapers exist.

Avoid logic such as:

```python
if store == "fragranza":
    ...
elif store == "store_b":
    ...
elif store == "store_c":
    ...
```

Prefer a registry/plugin-style architecture.

Conceptually:

```python
SCRAPER_REGISTRY = {
    "fragranza": FragranzaScraper,
}
```

or a decorator/automatic registration approach if it remains simple and readable.

Do not overengineer plugin discovery.

The goal is simply that adding another store later is easy.

---

# 42. Adding a future store

When I later provide another website, adding it should ideally require:

1. Create one new scraper under:

```text
app/scrapers/stores/
```

2. Register that scraper.

3. Add its Store database entry.

4. Add its tests/fixtures.

The following should NOT need to be redesigned:

* dashboard
* perfume database
* variant model
* normalization architecture
* price alerts
* comparison logic
* price history
* routes

This extensibility is one of the most important architectural goals.

---

# 43. Store scraping failures

Scrapers must fail independently.

If one store fails, the complete price check must NOT fail.

Later, with several stores, something like this must be possible:

```text
Fragranza.ro        799 RON
Future Store A      829 RON
Future Store B      Scraping error
Future Store C      Not available
```

One failing scraper must not prevent results from successful stores from being saved.

Errors should be logged.

The UI should indicate failures without crashing the application.

---

# 44. Scraper error types

Create sensible custom exceptions or error states where useful.

Examples:

```text
RequestError
ParsingError
ProductNotFound
StoreUnavailable
UnexpectedResponse
```

Do not create dozens of unnecessary exception classes.

Keep error handling clear and useful.

---

# 45. HTTP scraping behavior

The base scraping layer should include reusable support for:

* HTTP client
* connection timeout
* read timeout
* retry logic
* request headers
* configurable User-Agent
* rate limiting
* configurable delay
* redirects
* error handling
* logging
* response validation

Do not send excessive requests.

This is a manually triggered application used by one person, so aggressive scraping is unnecessary.

Use respectful delays and avoid unnecessary page requests.

---

# 46. Respect website behavior

Before implementing any scraper, investigate the website's actual behavior.

Where practical, respect:

* website Terms of Service
* robots.txt guidance
* reasonable request rates

Do not attempt to:

* bypass CAPTCHAs
* bypass authentication
* circumvent access controls
* defeat anti-bot protection aggressively
* impersonate logged-in users

If a site becomes inaccessible through reasonable scraping methods, explain the limitation instead of implementing aggressive bypass techniques.

---

# 47. New store investigation workflow

Whenever I provide a new perfume website, do NOT immediately start writing CSS selectors based on assumptions.

For every new store, first investigate how that particular website works.

Determine whether product search and product information are obtained through:

* normal server-rendered HTML
* search-result HTML
* internal JSON/API requests
* embedded JSON data
* JSON-LD
* JavaScript-rendered pages
* another mechanism

Prefer the simplest and most reliable approach.

Priority should generally be:

1. Reliable JSON/API request if available and appropriate.
2. Structured product data such as JSON-LD.
3. Server-rendered HTML using `httpx` + BeautifulSoup/lxml.
4. Playwright only when JavaScript rendering/browser interaction is genuinely required.

Do not assume HTML parsing is automatically the best option.

---

# 48. Fragranza.ro investigation

When we reach the Fragranza scraper phase, investigate:

https://fragranza.ro/

Before writing the scraper, explain:

* how the search functionality works
* what request is sent when searching
* whether results are server-rendered
* whether useful API/JSON endpoints exist
* whether product information is present as structured data
* whether individual product pages contain JSON-LD
* how product variants are represented
* how stock information is represented
* how prices are represented
* how testers are represented
* whether JavaScript rendering is necessary
* which implementation strategy is likely to be the most reliable

Do not implement Fragranza selectors before doing this analysis.

---

# 49. Fragranza.ro search behavior

For Fragranza.ro, the scraper must search using the monitored perfume's:

* brand
* perfume/model name

Example:

```text
Brand: Xerjoff
Perfume: Erba Gold
```

The goal is to discover all relevant variants available on Fragranza.ro.

Potential variants could include:

```text
50 ml EDP
100 ml EDP
100 ml EDP Tester
50 ml EDT
100 ml EDT
100 ml Parfum
```

depending on the perfume.

---

# 50. Fragranza result validation

Do not assume that every search result returned by Fragranza is relevant.

Every candidate must be validated.

For example, searching:

```text
Xerjoff Erba Gold
```

may potentially return unrelated Xerjoff products.

Use the common matching/normalization layer before associating results with the monitored perfume.

False positives should be rejected.

---

# 51. Fragranza product extraction

For relevant Fragranza products, extract where available:

* Brand
* Perfume name
* Concentration
* Bottle volume
* Tester status
* Current price
* Old price
* Discount
* Stock status
* Product URL
* Product title
* Store-specific product identifier if available

Use structured fields from the page whenever they are more reliable than title parsing.

---

# 52. Fragranza availability

Every perfume check should result in a Fragranza status.

Possible results:

```text
In stock
Out of stock
Not available
Scraping error
Store unavailable
```

If no matching product is found:

```text
Fragranza.ro — Not available
```

Do not silently omit the store.

---

# 53. Future stores

After Fragranza.ro is completely functional, I will provide another website.

At that point:

1. Analyze the new website.
2. Explain how it works.
3. Recommend a scraping strategy.
4. Create a dedicated scraper.
5. Register it with the existing scraper registry.
6. Add the store to the database/store-management interface.
7. Add tests.
8. Verify the new scraper independently.
9. Verify that Fragranza still works.
10. Verify that multi-store comparison works correctly.

Do not modify Fragranza-specific code unless genuinely necessary.

The architecture should make adding a second, third, fourth, etc. store straightforward.

---

# 54. Known product URL reuse

If a store product has already been matched successfully in a previous scrape, it may be useful to remember its product URL.

On future checks, the system may first attempt to check the known URL directly.

If:

* the URL no longer exists
* the product changes
* parsing fails
* the variant no longer matches

then fall back to a fresh store search.

This optimization should only be implemented if it keeps the architecture clean.

Do not make the first version unnecessarily complex.

---

# 55. Data freshness

The UI should distinguish current scrape results from historical information.

Current comparison should preferably reflect the most recent completed check.

Historical rows should not accidentally appear as current prices.

Think carefully about this in the schema.

---

# 56. Logging

Implement useful logging.

Logs should help diagnose:

* request failures
* parsing failures
* products not found
* unexpected HTML structures
* changes in website markup
* store scraper exceptions
* normalization failures
* ambiguous matches

Store log files under:

```text
logs/
```

Do not fill the logs with unnecessary debug spam during normal usage.

Allow a DEBUG configuration option for deeper logging.

---

# 57. Logging privacy

Do not unnecessarily log complete page HTML.

If HTML needs to be saved for debugging, prefer explicit debug fixtures or failure snapshots rather than dumping every response into normal log files.

Do not log secrets or sensitive configuration.

---

# 58. Configuration

Keep configuration separate from application logic.

Potential configuration values include:

```text
DATABASE_PATH
REQUEST_TIMEOUT
REQUEST_DELAY
MAX_RETRIES
USER_AGENT
DEBUG
HOST
PORT
```

Use `.env` where appropriate.

Also create:

```text
.env.example
```

Do not hardcode machine-specific absolute paths.

The project should work regardless of where I clone/store the folder.

---

# 59. SQLite location

The SQLite database can live somewhere similar to:

```text
data/perfume_tracker.db
```

Ensure the `data` directory is created automatically when necessary.

Do not require me to manually install or run SQLite as a server.

---

# 60. Local startup

Provide a simple startup command.

Ideally:

```bash
python run.py
```

The startup script should:

* initialize required directories
* ensure the database exists
* initialize database tables if necessary
* register initial stores when appropriate
* launch the FastAPI application

Avoid requiring a long startup command every time.

---

# 61. Database migrations

For the first version, decide whether to use:

* SQLAlchemy `create_all`
* Alembic

Because this is a local personal application, avoid unnecessary complexity.

However, consider that the schema may evolve while we build the project.

Recommend the most appropriate approach and explain why before implementation.

---

# 62. UI for perfume details

A perfume detail page should eventually contain:

* Brand
* Perfume name
* Last checked
* Check prices button
* Current variants
* Store prices for each variant
* Best current price
* Price alerts
* Price history table
* Status information

Do not add charts.

---

# 63. Variant display

Variants should have clear readable names.

For example:

```text
EDP — 50 ml
EDP — 100 ml
EDP — 100 ml — Tester
Parfum — 100 ml
```

Do not create confusing automatically generated labels.

---

# 64. Current offer display

For every variant and store, display useful information such as:

```text
Fragranza.ro
799 RON
In stock
View product
```

If discounted:

```text
799 RON
899 RON
-11%
```

The product URL should open the actual store page.

---

# 65. Not available display

If a store has no matching variant:

```text
Not available
```

If the store failed:

```text
Scraping error
```

These states must not be confused.

---

# 66. Manual check timestamps

Display when a perfume was last checked.

For example:

```text
Last checked: 24 Aug 2026, 20:15
```

Store timestamps properly in the database.

Use a consistent timezone strategy.

Since this application is local, displaying the local system timezone is acceptable.

---

# 67. Check all behavior

When I click:

```text
Check all perfumes
```

the system should conceptually do:

```text
for every saved perfume:
    for every enabled store:
        run the store scraper
        normalize candidate results
        validate perfume match
        discover variants
        persist current results
        persist price history
        evaluate alerts
```

One perfume/store failure must not cancel the entire operation.

At the end, the dashboard should display updated information.

---

# 68. Check one behavior

When I click:

```text
Check prices
```

for a single perfume:

1. Load that monitored perfume.
2. Load all enabled stores.
3. Run each store scraper independently.
4. Search using brand + perfume name.
5. Parse candidate products.
6. Exclude invalid product types.
7. Normalize candidate information.
8. Match candidates to the monitored perfume.
9. Identify exact variants.
10. Save/update StoreProduct records.
11. Save current availability and prices.
12. Save price history.
13. Determine best price per exact variant.
14. Evaluate configured price alerts.
15. Return the refreshed perfume page.

---

# 69. Concurrency

Because there may eventually be multiple stores, consider whether asynchronous HTTP requests could improve responsiveness.

FastAPI and httpx support async behavior.

However:

* do not make excessive parallel requests to the same store
* do not overcomplicate concurrency
* respect rate limits
* maintain independent error handling

Explain your strategy before implementing multi-store concurrency.

---

# 70. Tests

Create automated tests for important application logic.

Especially test:

* brand normalization
* perfume name normalization
* concentration normalization
* volume extraction
* tester detection
* gift set detection
* refill detection
* exclusion filters
* price parsing
* product matching
* variant identity
* best-price selection
* alert triggering

---

# 71. Scraper tests

Individual store scrapers should be testable without always requesting the live website.

Where practical, use saved HTML/JSON fixtures.

For Fragranza:

```text
tests/
└── fixtures/
    └── fragranza/
```

Possible fixtures:

```text
search_results.html
product_page.html
tester_product.html
out_of_stock_product.html
```

or JSON files depending on how Fragranza actually works.

Do not decide the fixture format until you investigate the website.

---

# 72. Live scraper tests

If we create optional tests that access the real Fragranza website, keep them separate from normal unit tests.

Normal:

```bash
pytest
```

should ideally not hammer real websites.

Live/integration tests should be explicitly triggered.

---

# 73. Code quality

Follow these rules:

* clean Python
* Python type hints
* meaningful variable names
* small focused functions
* focused classes
* separation of concerns
* reusable code
* avoid global mutable state
* proper exception handling
* useful docstrings
* comments only where they add value
* avoid duplicate logic
* follow consistent naming conventions

Do not generate giant service classes with hundreds of lines unless there is a genuine reason.

---

# 74. Avoid overengineering

This is a personal local application.

Do NOT introduce unnecessary infrastructure such as:

* Docker Compose unless actually useful
* Kubernetes
* Redis
* Celery
* RabbitMQ
* microservices
* separate frontend/backend repositories
* PostgreSQL server
* cloud services
* authentication systems
* GraphQL
* event buses

Keep the architecture clean but practical.

---

# 75. Dependency discipline

Only add libraries that have a clear purpose.

When adding a dependency, briefly explain why it is needed.

Do not install multiple libraries that solve the same problem without a reason.

---

# 76. README

Eventually create a good README explaining:

* what the project does
* supported stores
* current first store: Fragranza.ro
* installation
* virtual environment creation
* dependency installation
* starting the application
* database location
* project architecture
* adding perfumes
* checking prices
* enabling/disabling stores
* adding a new store scraper
* running tests

---

# 77. Git-friendly project

Create an appropriate `.gitignore`.

Do not commit:

* virtual environments
* caches
* logs
* `.env`
* local database if you recommend excluding it
* temporary scraper debug files
* Playwright/browser cache files if applicable

Decide whether the SQLite database should be ignored and explain your choice.

---

# 78. Development workflow

THIS IS VERY IMPORTANT.

Do NOT generate the entire project in one response.

We will work step by step.

For every major development stage:

1. Briefly explain what will be implemented.
2. Show the relevant project tree.
3. State exactly which files will be created.
4. State exactly which files will be modified.
5. Provide COMPLETE code for every created or modified file.
6. Do not omit sections of files.
7. Do not use placeholders such as:

```python
# existing code here
```

8. Explain important architectural decisions.
9. Give exact commands needed to run/test the current stage.
10. Tell me what behavior I should expect.
11. Stop at a logical checkpoint.

Do not continue automatically to several additional phases.

I want to be able to test each stage before moving forward.

---

# 79. Updating existing code

When modifying an existing file, provide the full updated content of that file unless I explicitly ask for only a patch/diff.

Do not silently remove previously implemented functionality.

Do not rename existing files or modules without explaining why.

---

# 80. Debugging workflow

When I report an error:

1. Analyze the actual error.
2. Identify the likely cause.
3. Tell me which file needs modification.
4. Provide the full corrected file when appropriate.
5. Do not rebuild unrelated parts of the application.
6. Preserve the existing architecture unless the architecture itself is the cause.

---

# 81. Do not guess project state

As development continues, base modifications on the latest code already created in this conversation.

Do not generate a completely different architecture later unless there is a strong technical reason.

If a previous decision becomes problematic, explain why before changing it.

---

# 82. Development stages

Use approximately this order.

## Phase 1 — Architecture and project initialization

Finalize:

* directory structure
* dependencies
* configuration
* FastAPI application skeleton
* logging
* basic startup

## Phase 2 — SQLite database

Implement:

* database initialization
* SQLAlchemy models
* repositories
* initial store data

Initially only:

```text
Fragranza.ro
```

## Phase 3 — Perfume and variant domain logic

Implement:

* monitored perfumes
* perfume variants
* normalization models
* concentration normalization
* volume parsing
* tester detection
* exclusion logic

## Phase 4 — Matching

Implement:

* brand matching
* perfume-name matching
* variant matching
* false-positive prevention
* tests

## Phase 5 — Base scraper architecture

Implement:

* BaseScraper
* common HTTP functionality
* shared result models
* scraper errors
* scraper registry

Do not implement random stores.

## Phase 6 — Basic local web UI

Implement:

* layout
* dashboard
* navigation
* basic styling

## Phase 7 — Perfume management

Implement:

* add perfume
* edit perfume
* delete perfume
* perfume detail page

## Phase 8 — Store management

Implement:

* store list
* enable/disable stores

Initially only:

```text
Fragranza.ro
```

## Phase 9 — Investigate Fragranza.ro

Analyze:

https://fragranza.ro/

Do NOT implement its scraper before this investigation.

## Phase 10 — Fragranza scraper

Implement the actual Fragranza scraper using the strategy discovered during Phase 9.

## Phase 11 — Price checking integration

Connect Fragranza to:

* Check prices
* Check all perfumes
* normalization
* matching
* database
* current offers
* availability status

## Phase 12 — Price comparison

Implement:

* exact variant grouping
* all-store comparison
* best current price

Initially there is only Fragranza, but the architecture must support future stores.

## Phase 13 — Price history

Implement historical price tracking and a simple historical table.

No charts.

## Phase 14 — Price alerts

Implement local UI alerts.

No external notifications.

## Phase 15 — Error handling and polish

Improve:

* scraper failure behavior
* UI feedback
* logging
* edge cases
* tests

## Phase 16+ — Additional stores

I will provide each additional website myself.

Implement stores one at a time.

---

# 83. Important first task

For your FIRST response, DO NOT write the application yet.

Do NOT implement Fragranza yet.

Instead:

1. Review all requirements above.
2. Propose the final project architecture.
3. Show the complete directory tree you recommend.
4. Explain the responsibility of each major package/module.
5. Propose the SQLite database schema.
6. Explain all important database relationships.
7. Explain the distinction between:

   * Perfume
   * PerfumeVariant
   * Store
   * StoreProduct
   * current offer/result
   * price history
8. Explain the BaseScraper interface.
9. Explain the scraper registry.
10. Explain the common scraper result model.
11. Explain how Fragranza will plug into the architecture.
12. Explain how future stores will plug into the architecture.
13. Explain the normalization pipeline.
14. Explain tester detection.
15. Explain concentration detection.
16. Explain bottle-volume detection.
17. Explain exclusion filtering.
18. Explain product matching.
19. Explain how uncertain matches should be handled.
20. Explain what happens internally when I click:

```text
Check prices
```

21. Explain what happens internally when I click:

```text
Check all perfumes
```

22. Explain how store failures are isolated.
23. Explain how price history should be stored.
24. Explain how local price alerts should work.
25. Recommend whether we should use Alembic or simpler database initialization for this project.
26. Recommend whether known store-product URLs should be reused on future checks.
27. Point out any architectural decisions or potential problems that should be solved before implementation.

After presenting this architecture proposal:

**STOP.**

Do not generate Phase 1 code yet.

Wait for my approval of the architecture before writing implementation code.

---

# 84. Final important constraints

Remember these throughout the entire project:

* This is a personal local application.
* Python is the main language.
* The interface runs locally in the browser.
* Use FastAPI + Jinja2 + HTMX.
* Use SQLite.
* No database server.
* Scraping is manually triggered.
* No scheduled scraping.
* No external alerts.
* No price-per-ml calculations.
* No price charts.
* Normal bottles and testers are separate variants.
* Different volumes are separate variants.
* Different concentrations are separate variants.
* Gift sets are excluded.
* Refills are excluded.
* Samples are excluded.
* Stores where a product is missing should show `Not available`.
* Scraper errors should be shown separately from `Not available`.
* Stores can be enabled or disabled.
* Store failures must not crash the complete operation.
* The architecture must support additional stores later.
* I will personally provide every additional store.
* Do not invent future stores.
* Do not implement future stores before I request them.
* The first and only initial store is Fragranza.ro.
* Website: https://fragranza.ro/
* Investigate every website before deciding how to scrape it.
* Prefer HTTP/API/structured data over browser automation.
* Use Playwright only if necessary.
* Do not use aggressive anti-bot bypass techniques.
* Keep the code modular.
* Keep the project folder organized.
* Do not put everything in one file.
* Do not overengineer.
* Work incrementally.
* Let me approve major architectural steps before continuing.
