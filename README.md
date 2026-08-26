# phx-scraper

Async scraper and FastAPI backend for the [Getro](https://getro.com) job collection behind
[jobs.phxfwd.org](https://jobs.phxfwd.org). It paginates the upstream search API in
concurrent batches, normalizes every posting into one consistent shape, streams results
to CSV, and renders human-readable PDFs.

- **136 postings** across 33 companies in the collection, every job function
- **~0.9s** for a full scrape (8 pages, 7 of them concurrent)
- **47 tests**, no network access required

---

## Contents

- [Quick start](#quick-start)
- [Command-line tools](#command-line-tools)
- [HTTP API](#http-api)
- [Project structure](#project-structure)
- [Module reference](#module-reference)
- [Configuration](#configuration)
- [How the scrape works](#how-the-scrape-works)
- [Upstream quirks](#upstream-quirks)
- [Testing](#testing)

---

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

uv run python scrape_to_csv.py -v     # every job -> jobs.csv
uv run python stale_jobs.py           # 90-day metrics in the terminal
uv run python make_pdf.py             # jobs.pdf + metrics.pdf
uv run fastapi dev main.py            # HTTP API on :8000, docs at /docs
uv run pytest                         # 47 tests
```

The three CLIs form a pipeline. Each step reads the previous step's output, so only the
first one touches the network:

```
Getro API  ──scrape_to_csv.py──>  jobs.csv  ──┬──stale_jobs.py──>  terminal metrics
                                              └──make_pdf.py────>  jobs.pdf + metrics.pdf
```

---

## Command-line tools

### `scrape_to_csv.py` — scrape into a CSV

Rows are flushed to disk as each batch lands, so an interrupted or partially failed run
still leaves a usable file.

```bash
uv run python scrape_to_csv.py                       # all jobs -> jobs.csv
uv run python scrape_to_csv.py -o out/jobs.csv -v    # custom path, progress logging
uv run python scrape_to_csv.py -q engineer -q sales  # repeatable, deduped across queries
uv run python scrape_to_csv.py --max-pages 3         # cap the walk
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `-q`, `--query` | none (all jobs) | Search term. Repeatable; results are deduped against one shared seen-set. |
| `-o`, `--out` | `jobs.csv` | Output path. Parent directories are created. |
| `--max-pages` | `100` | Hard ceiling on pages per query. |
| `-v`, `--verbose` | off | Log each batch as it is fetched. |

| Exit code | Meaning |
| --- | --- |
| `0` | Complete run |
| `1` | Scrape error (upstream unreachable, retries exhausted) |
| `2` | Partial run — some pages failed, CSV holds the rest |
| `130` | Interrupted with Ctrl-C, partial CSV kept |

### `stale_jobs.py` — 90-day metrics

```bash
uv run python stale_jobs.py                  # jobs.csv, 90-day window
uv run python stale_jobs.py out/jobs.csv -d 30
```

```
jobs older than 90 days: 71 of 136 (52.21%)
```

The boundary is exclusive — exactly 90 days old is not stale, 91 is. Rows with no posting
date are excluded from the stale count and reported on a separate line rather than
silently counted as fresh.

### `make_pdf.py` — human-readable PDFs

Reads the CSV, so it never re-hits the network.

```bash
uv run python make_pdf.py                                 # jobs.pdf + metrics.pdf
uv run python make_pdf.py out/jobs.csv --jobs-only
uv run python make_pdf.py --metrics-only --metrics-pdf q3.pdf
```

- **`metrics.pdf`** — one page covering the 90-day window only: headline percentage, a
  stale/fresh proportion bar, and four figures (total, older than 90d, within 90d, share).
- **`jobs.pdf`** — every posting newest-first, one block each: title, company, location,
  work mode, seniority, pay, skills, clickable URL, and an age badge that turns amber past
  90 days. Blocks never split across a page boundary.

| Flag | Default | Purpose |
| --- | --- | --- |
| `csv_path` | `jobs.csv` | Source CSV. |
| `--jobs-pdf` | `jobs.pdf` | Listing output path. |
| `--metrics-pdf` | `metrics.pdf` | Metrics output path. |
| `-d`, `--days` | `90` | Staleness window. |
| `--jobs-only` / `--metrics-only` | off | Render one document. Mutually exclusive (exit `2`). |

---

## HTTP API

```bash
uv run fastapi dev main.py     # docs at http://127.0.0.1:8000/docs
```

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe. |
| `POST` | `/scrape` | Paginate upstream in batches, normalize, store. Body: `query`, `max_pages`, `store`. |
| `POST` | `/normalize` | Normalize a raw payload without fetching or storing. |
| `GET` | `/jobs` | List stored jobs. Query: `q`, `company`, `work_mode`, `seniority`, `page`, `per_page`. |
| `GET` | `/jobs/{job_id}` | One job, or `404`. |
| `DELETE` | `/jobs/{job_id}` | Remove a job, or `404`. |

```bash
curl -X POST localhost:8000/scrape -H 'content-type: application/json' \
  -d '{"query": "", "max_pages": 5}'
```

Every list endpoint returns the same envelope:
`{ items, count, total, page, per_page, has_more }`. Note `count` is the size of this
response while `total` is the size of the full match set.

Storage is an in-memory dict held on `app.state` — it resets when the process restarts.

---

## Project structure

```
phx-scraper/
├── config.py            Settings and env-var loading
├── errors.py            Exception hierarchy
├── schemas.py           Public response models (the shape everything else emits)
├── getro.py             Raw upstream payload -> Job models
├── getro_client.py      Async HTTP client: retries, backoff, concurrency cap
├── scraper.py           Batched page navigation
├── sinks.py             JobSink protocol, streaming CSV writer, CSV reader
├── store.py             In-memory job store and filtering
├── main.py              FastAPI routes
├── pdf_styles.py        Shared PDF palette and paragraph styles
├── pdf_reports.py       PDF builders (listing + metrics)
├── scrape_to_csv.py     CLI: scrape -> CSV
├── stale_jobs.py        CLI: 90-day metrics
├── make_pdf.py          CLI: CSV -> PDFs
├── pytest.ini           Test config (asyncio auto mode)
└── tests/
    ├── conftest.py          Shared fixtures (fast-retry Settings)
    ├── test_client.py       HTTP client: retries, 429, transport errors  (10)
    ├── test_scraper.py      Batching, dedup, failure isolation, cancel    (9)
    ├── test_csv_sink.py     CSV flattening, streaming, partial runs       (6)
    ├── test_stale_jobs.py   Age maths and CLI                             (7)
    ├── test_pdf_reports.py  PDF content, escaping, pagination            (10)
    └── test_make_pdf.py     PDF CLI wiring                                (5)
```

**Dependency direction.** Modules only import downward, so nothing circular:

```
CLIs / main.py
      ↓
scraper.py ──> getro_client.py ──> config.py, errors.py
      ↓                ↓
   sinks.py        getro.py
      ↓                ↓
          schemas.py
```

`getro.py` is the only module that knows upstream field names. `schemas.py` defines the
shape everything downstream consumes, and imports nothing from the project.

---

## Module reference

### `config.py`

| Symbol | Purpose |
| --- | --- |
| `Settings` | Pydantic settings model holding every tunable: base URL, collection id, batching, timeouts, retry policy. Reads `PHX_`-prefixed env vars and `.env`. |
| `get_settings()` | `lru_cache`d accessor so one `Settings` instance is shared process-wide. |

### `errors.py`

| Symbol | Purpose |
| --- | --- |
| `ScraperError` | Base class — catching this catches everything the package raises. |
| `TransientError` | Retryable failure (5xx, timeouts). Also raised once retries are exhausted, with the original error as `__cause__`. |
| `RateLimitError` | HTTP 429. Carries `retry_after` seconds when upstream sends the header. Subclasses `TransientError`. |
| `UpstreamError` | Non-retryable 4xx. Carries `status_code`. |
| `PayloadError` | Response was not JSON, or was missing `results` / `results.jobs`. |

### `schemas.py` — the public contract

| Symbol | Purpose |
| --- | --- |
| `_Lenient` | `StrEnum` base whose `_missing_` maps unknown upstream values to `unknown` instead of raising, so a new upstream enum value can never 500 the API. |
| `WorkMode` | `on_site` / `hybrid` / `remote` / `unknown`. |
| `Seniority` | `internship` … `executive` / `unknown`. |
| `Company` | Employer: id, name, slug, logo, funding stage, head count, industries. |
| `Location` | One place: name, area type, latitude, longitude. |
| `Compensation` | Pay in whole currency units (upstream sends cents), plus currency, period, equity flag. |
| `Compensation.text` | Computed display string, e.g. `$170,000 - $190,000/yr + equity`. Returns `None` when no amount is known. |
| `Job` | One normalized posting — the central model. |
| `Job.location_text` | Computed primary location for a card, e.g. `Phoenix, AZ, USA +1 more`; falls back to `Remote` / `Not specified`. |
| `Job.work_mode_label` | Computed human label, e.g. `On-site`. |
| `Job.seniority_label` | Computed human label, e.g. `Mid-Senior level`. |
| `JobPage` | List envelope: `items`, `count`, `total`, `page`, `per_page`. |
| `JobPage.has_more` | Computed — whether another page exists. |
| `JobPage.of()` | Constructor that derives `count` from `items` so the two can never disagree. |
| `epoch_to_datetime()` | Unix seconds -> timezone-aware UTC datetime, passing `None` through. |

### `getro.py` — upstream adapter

| Symbol | Purpose |
| --- | --- |
| `normalize_keys()` | Recursively rewrites dict keys to snake_case, letting one parser handle both the snake_case REST API and the camelCase server-rendered payload. |
| `parse_job()` | Normalizes one raw job into a `Job`. Returns `None` for placeholder or malformed entries rather than raising, so one bad record cannot fail a page. |
| `parse_payload()` | Normalizes a whole document — either API shape or embedded page state — returning `(jobs, reported_total)`. |
| `extract_jobs_state()` | Digs `initialState.jobs` out of a Next.js `__NEXT_DATA__` document, accepting several nesting depths. |
| `_snake()` | camelCase -> snake_case for a single key. |
| `_cents_to_units()` | Integer cents -> whole currency units, tolerating `None` and junk. |
| `_parse_point()` | `POINT (lon lat)` WKT -> `(latitude, longitude)`, swapping to the conventional order. |
| `_strings()` | Filters a value down to a list of strings, guarding against nulls in upstream arrays. |
| `_locations()` | Builds `Location` models, preferring `location_details` and falling back to the flat `locations` list. |
| `_company()` | Builds the `Company` model, defaulting the name to `Unknown`. |
| `_compensation()` | Builds `Compensation`, returning `None` when pay is private or absent, and nulling the `period_not_defined` sentinel. |

### `getro_client.py` — HTTP layer

| Symbol | Purpose |
| --- | --- |
| `RETRYABLE_STATUS` | The status codes worth retrying: 408, 425, 429, 500, 502, 503, 504. |
| `SearchPage` | Frozen result of one request: page number, raw job dicts, reported total. |
| `SearchPage.is_empty` | Whether the page returned no jobs — the walk's stop signal. |
| `GetroClient` | Async client for the Getro search API. Owns retry policy and the concurrency cap. |
| `GetroClient.__aenter__` | Builds the pooled `httpx.AsyncClient` with timeouts, connection limits, and headers. Injecting a client instead skips this, which is how tests use a mock transport. |
| `GetroClient.__aexit__` / `aclose()` | Closes the client, but only if this instance created it. |
| `GetroClient.search_jobs()` | Public call: POST one search page and return a `SearchPage`. |
| `GetroClient._post_with_retry()` | Retry loop — exponential backoff with jitter, `Retry-After` honoured on 429, raises `TransientError` once attempts are spent. |
| `GetroClient._post()` | One attempt: acquires the semaphore, sends, and maps the status code onto the exception hierarchy. |
| `GetroClient._backoff()` | Capped exponential delay with random jitter, so parallel retries do not resynchronize. |
| `_retry_after_seconds()` | Parses the `Retry-After` header, tolerating a missing or malformed value. |
| `_to_search_page()` | Validates the response envelope and builds a `SearchPage`, raising `PayloadError` on anything unexpected. |

### `scraper.py` — orchestration

| Symbol | Purpose |
| --- | --- |
| `PageFailure` | Records one page that could not be fetched, and why. |
| `ScrapeResult` | Outcome of a run: jobs, upstream's reported total, pages fetched, failures. |
| `ScrapeResult.total` | Jobs actually retrieved — the honest count, as distinct from `reported_total`. |
| `ScrapeResult.is_partial` | Whether any page failed. |
| `_BatchOutcome` | Internal per-batch verdict: did it add anything, did it hit the end of the result set. |
| `JobScraper` | Walks the paginated search endpoint in concurrent batches. |
| `JobScraper.scrape()` | Fetches page 1 to learn the page size, then walks the rest in windows until exhausted. Accepts an optional `sink` for streaming and an external `seen` set for cross-query dedup. |
| `JobScraper._next_window()` | Picks the next block of page numbers, trimmed to the estimate while it is still ahead and to the hard cap always. |
| `JobScraper._run_batch()` | Fires one window concurrently with `return_exceptions=True`, records failures per page, and re-raises `CancelledError` rather than logging it as a failure. |
| `JobScraper._collect()` | Parses a page, drops duplicates and unparseable records, and returns only the newly seen jobs. |
| `JobScraper._emit()` | Hands a batch to the sink when one is configured. |
| `scrape_jobs()` | Convenience wrapper that owns a client for a single one-shot scrape. |

### `sinks.py` — output

| Symbol | Purpose |
| --- | --- |
| `CSV_COLUMNS` | The 28-column CSV schema, and the single source of truth for column order. |
| `JobSink` | `Protocol` with one `write()` coroutine, so the scraper depends on an interface rather than on CSV specifically. |
| `job_to_row()` | Flattens a nested `Job` into one CSV row, joining multi-values with `" | "`. |
| `CsvJobSink` | Async context manager that opens the file, writes the header, and appends batches. |
| `CsvJobSink.write()` | Serializes rows and flushes them, guarded by a lock so concurrent batches cannot interleave. |
| `CsvJobSink._flush_rows()` | The blocking write, run in a worker thread via `asyncio.to_thread` so the event loop keeps moving. |
| `CsvJobSink.aclose()` | Closes the handle. |
| `read_rows()` | Reads a CSV back into row dicts, for the PDF and metrics tools. |

### `store.py`

| Symbol | Purpose |
| --- | --- |
| `JobStore` | In-memory store keyed by job id. The seam to swap for a database. |
| `JobStore.upsert_many()` | Inserts or replaces jobs, returning how many were new. |
| `JobStore.get()` / `delete()` / `__len__` | Single-job lookup, removal, and size. |
| `JobStore.search()` | Sorts newest-first, applies the text/company/work-mode/seniority filters, paginates, and returns a `JobPage`. |
| `_matches_text()` | Case-insensitive match across title, company, and skills. |

### `main.py` — FastAPI app

| Symbol | Purpose |
| --- | --- |
| `lifespan()` | Opens one shared `GetroClient` and `JobStore` for the app's lifetime, so connections are pooled across requests. |
| `get_scraper()` / `get_store()` | Dependency providers, overridable in tests. |
| `ScrapeRequest` | Request body: `query`, `max_pages`, `store`. |
| `ScrapeReport` | Response body: counts, pages fetched, failed pages, partial flag, jobs. |
| `ScrapeReport.of()` | Builds the response from a `ScrapeResult`. |
| `health()` | Liveness probe. |
| `scrape()` | Runs a scrape, maps `UpstreamError` to `502` and other scraper errors to `504`, and optionally stores results. |
| `normalize()` | Normalizes a posted raw payload without fetching. |
| `list_jobs()` / `get_job()` / `delete_job()` | Read and remove stored jobs. |

### `pdf_styles.py`

| Symbol | Purpose |
| --- | --- |
| Colour constants | `INK`, `MUTED`, `RULE`, `ACCENT`, `FRESH`, `STALE`, `UNDATED` — one palette shared by both documents. |
| `PAGE_MARGIN` | 16mm margin used for the frame and the footer baseline. |
| `build_styles()` | Returns the named `ParagraphStyle` set (title, subtitle, job title, meta, pay, metric value, headline). |

### `pdf_reports.py`

| Symbol | Purpose |
| --- | --- |
| `build_metrics_pdf()` | Renders the one-page staleness report: headline percentage, proportion bar, four figures, and an undated-rows note when relevant. |
| `build_jobs_pdf()` | Renders every posting newest-first with a summary header. |
| `ProportionBar` | Custom flowable whose `draw()` paints the stale/fresh/undated split as one stacked bar, skipping zero-width segments. |
| `Rule` | Custom flowable whose `draw()` paints a hairline separator. |
| `_job_block()` | Builds one posting's flowables wrapped in `KeepTogether` so a listing never splits across pages. |
| `_metric_cards()` | Lays out a row of big-number/label pairs as a borderless table. |
| `_document()` | Builds the `BaseDocTemplate` with margins, metadata, and the footer callback. |
| `_footer()` | Draws the footer label and page number on every page. |
| `_escape()` | Escapes `&`, `<`, `>` for ReportLab's mini-markup. Must be applied per field, before joining with entities like `&middot;`. |
| `_parse_timestamp()` | ISO-8601 string -> aware datetime, assuming UTC when no offset is present. |
| `_age_days()` | Age of a row in whole days, or `None` when undated. |

### `scrape_to_csv.py`

| Symbol | Purpose |
| --- | --- |
| `RunSummary` | Totals across every query in one run: rows written, pages fetched, failures. |
| `scrape_to_csv()` | Opens the sink and client once, then scrapes each query in sequence against a shared seen-set so a job found twice is written once. |
| `parse_args()` | Defines the CLI surface. |
| `main()` | Entry point — runs the coroutine and maps outcomes to exit codes. |

### `stale_jobs.py`

| Symbol | Purpose |
| --- | --- |
| `DEFAULT_MAX_AGE_DAYS` | The 90-day window. |
| `StaleReport` | Frozen result: total, stale, undated, window. |
| `StaleReport.percentage` | Stale share rounded to two decimals, returning `0.0` on an empty file rather than dividing by zero. |
| `analyze()` | Streams the CSV and counts rows past the cutoff. Takes an injectable `now` so tests are deterministic. |
| `parse_args()` / `main()` | CLI surface and entry point. |

### `make_pdf.py`

| Symbol | Purpose |
| --- | --- |
| `parse_args()` | Defines the CLI surface. |
| `main()` | Validates flags and source, then renders whichever documents were requested. |

---

## Configuration

Every field on `Settings` is overridable with a `PHX_`-prefixed env var or a `.env` file.

| Setting | Default | Purpose |
| --- | --- | --- |
| `getro_base_url` | `https://api.getro.com/api/v2` | Upstream API root. |
| `collection_id` | `10289` | The Phoenix Forward job collection. |
| `hits_per_page` | `20` | Requested page size (upstream currently ignores this — see below). |
| `batch_size` | `20` | Pages fetched per concurrent window. |
| `max_concurrency` | `20` | Hard ceiling on in-flight requests. |
| `max_pages` | `100` | Runaway-walk backstop. |
| `connect_timeout` | `5.0` | Seconds to establish a connection. |
| `read_timeout` | `20.0` | Seconds to read a response. |
| `max_retries` | `3` | Retries after the first attempt. |
| `backoff_base` | `0.5` | Base delay, doubled per attempt. |
| `backoff_max` | `8.0` | Backoff ceiling before jitter. |
| `user_agent` | `phx-scraper/0.1 …` | Sent on every request. |

```bash
PHX_BATCH_SIZE=5 PHX_MAX_PAGES=10 uv run python scrape_to_csv.py -v
```

---

## How the scrape works

One shared `httpx.AsyncClient` gives pooled keep-alive connections. An
`asyncio.Semaphore(max_concurrency)` caps in-flight requests, and each batch runs under
`asyncio.gather(..., return_exceptions=True)` so a single bad page degrades to a recorded
failure instead of killing the run.

1. **Page 1 alone**, to learn the real page size and upstream's reported total.
2. **Windows of `batch_size` pages** go out concurrently. The window is trimmed to the
   estimate while the estimate is still ahead, and to `max_pages` always.
3. **Stop** when a window adds no new jobs, or contains a short page — a page holding
   fewer than `page_size` results means the result set ended there.
4. **Dedup** by job id throughout, since `scrape()` accepts a shared `seen` set across
   queries.
5. **Stream** each batch to the sink before the next window is requested.

Retries cover `RETRYABLE_STATUS` and transport errors with exponential backoff plus
jitter, honouring `Retry-After` on 429. Other 4xx fail fast — retrying a `400` just wastes
requests. `asyncio.CancelledError` is re-raised rather than swallowed as a page failure,
so Ctrl-C stops promptly.

---

## Upstream quirks

Three behaviours worth knowing, each verified against the live API:

**`hitsPerPage` is ignored.** Requesting 2 returns 20. Page size is fixed server-side, so
the walk derives it from `len(page_1.jobs)` rather than trusting the request.

**`results.count` is not the paginated size.** It is a fuzzy pre-filter total, inflated by
exactly one page in every query tested — `"software engineer"` reports 84 but paginates
64; the empty query reports 156 but paginates 136. Bounding the walk on
`ceil(count / page_size)` would be wrong, so termination is driven by short and empty
pages. The value is kept as a window hint and surfaced as `reported_total`.

**Two payload shapes, two key styles.** The REST API returns snake_case; the server-rendered
page state embedded in `jobs.phxfwd.org` returns camelCase. `normalize_keys()` reconciles
both so one parser serves either source.

### Normalization

| Upstream | Normalized |
| --- | --- |
| snake_case (API) / camelCase (SSR) | keys reconciled, one parser |
| `compensation_amount_min_cents: 17000000` | `compensation.min_amount: 170000.0` + `text` |
| `compensation_period: "period_not_defined"` | `null` |
| `created_at: 1785839127` | `posted_at`, UTC ISO-8601 |
| `POINT (-111.92 33.49)` | `latitude` / `longitude` floats |
| `searchable_locations` (city → … → continent) | dropped; `location_details` wins |
| `work_mode` / `seniority` / `null` | enums plus display labels |
| padded `{}` entries | skipped |
| unknown enum values | `unknown`, never a 500 |

`searchable_locations` is a widening hierarchy meant for search indexing — rendering it
would put "North America" on a Scottsdale job.

---

## Testing

```bash
uv run pytest              # 47 tests
uv run pytest -v           # per-test names
uv run pytest tests/test_scraper.py
```

No network access: every HTTP test drives `httpx.MockTransport`, and `conftest.py` supplies
a `Settings` fixture with millisecond backoff so retry paths run instantly. PDF assertions
extract text back out with `pypdf` rather than trusting that the build did not raise.

Coverage worth knowing about:

| Area | Examples |
| --- | --- |
| Retries | Succeeds after 503s, exhausts cleanly, `Retry-After` honoured, 4xx not retried |
| Batching | Never exceeds `batch_size` in flight, stops on short page, respects `--max-pages` |
| Resilience | One failing page leaves the rest intact, `CancelledError` propagates |
| Streaming | Rows are on disk before later pages are requested, partial runs keep their rows |
| Metrics | Exclusive boundary, undated rows, empty file does not divide by zero |
| PDFs | Markup escaping, separator entities, sort order, pagination, empty datasets |
