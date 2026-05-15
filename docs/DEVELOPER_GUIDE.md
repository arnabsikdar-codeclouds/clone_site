# Developer Guide

This document is for developers working on the SiteCloner codebase. It covers architecture, module responsibilities, data flows, extension points, and common gotchas.

---

## Table of Contents

- [Quick Setup](#quick-setup)
- [Architecture Overview](#architecture-overview)
- [Module Reference](#module-reference)
  - [Entry Point — app.py](#entry-point--apppy)
  - [Configuration — config.py](#configuration--configpy)
  - [Data Models — cloner/models.py](#data-models--clonermodelspy)
  - [URL Utilities — cloner/url_utils.py](#url-utilities--clonerurl_utilspy)
  - [HTTP Client — cloner/downloader.py](#http-client--clonerdownloaderpy)
  - [HTML/CSS Parser — cloner/parser.py](#htmlcss-parser--clonerparserpy)
  - [URL Rewriter — cloner/rewriter.py](#url-rewriter--clonerrewriterpy)
  - [Clone Engine — cloner/engine.py](#clone-engine--clonerenginepy)
  - [Encoding Detection — cloner/encoding.py](#encoding-detection--clonerencodingpy)
  - [Robots.txt — cloner/robots.py](#robotstxt--clonerrobotspy)
  - [Playwright Renderer — cloner/renderer.py](#playwright-renderer--clonerrendererpy)
  - [API Schemas — web/schemas.py](#api-schemas--webschemaspy)
  - [Job Manager — web/job_manager.py](#job-manager--webjob_managerpy)
  - [Login Manager — web/login_manager.py](#login-manager--weblogin_managerpy)
  - [API Routes — web/routes.py](#api-routes--webroutespy)
  - [Rate Limiting — web/middleware.py](#rate-limiting--webmiddlewarepy)
  - [Frontend — static/](#frontend--static)
- [Data Flow: Clone Pipeline](#data-flow-clone-pipeline)
- [Data Flow: Browser Login](#data-flow-browser-login)
- [Key Data Structures](#key-data-structures)
- [Adding a New Feature](#adding-a-new-feature)
- [Common Gotchas](#common-gotchas)
- [Testing](#testing)

---

## Quick Setup

```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Install Playwright for JS rendering / browser login
pip install playwright
playwright install chromium

# Run the server
python app.py
# -> http://localhost:8000
```

---

## Architecture Overview

```
                    +-----------+
  User Browser ---->|  FastAPI   |----> SSE (real-time progress)
                    |  Web UI    |
                    +-----+-----+
                          |
                    +-----v------+
                    | Middleware  |  API rate limiting (per IP)
                    +-----+------+
                          |
               +----------+----------+
               |                     |
        +------v-------+     +------v--------+
        |  JobManager  |     | LoginManager  |
        | lifecycle,   |     | browser login,|
        | SSE, cleanup |     | cookie capture|
        +------+-------+     +---------------+
               |
        +------v-------+
        | CloneEngine  |  BFS orchestrator (4 phases)
        +------+-------+
               |
    +------+---+----+--------+
    |      |        |        |
Downloader Parser Rewriter Renderer
(aiohttp) (BS4)  (BS4)    (ThreadedPlaywright)
    |
+---+--------+
|            |
RateLimiter RobotsChecker
```

**Layer summary:**

| Layer | Files | Role |
|-------|-------|------|
| Entry Point | `app.py` | FastAPI init, lifespan, background tasks |
| Config | `config.py` | All settings as a dataclass |
| Models | `cloner/models.py` | Job, Asset, Error enums and dataclasses |
| URL Handling | `cloner/url_utils.py` | Normalization, path mapping, classification |
| HTTP | `cloner/downloader.py` | Async fetching, retries, rate limiting |
| Parsing | `cloner/parser.py` | HTML/CSS link extraction |
| Rewriting | `cloner/rewriter.py` | URL rewriting for offline use |
| Orchestration | `cloner/engine.py` | 4-phase clone pipeline |
| Encoding | `cloner/encoding.py` | Charset detection |
| Compliance | `cloner/robots.py` | robots.txt, sitemap parsing |
| Rendering | `cloner/renderer.py` | Playwright headless browser |
| Schemas | `web/schemas.py` | Pydantic request/response models |
| Job Mgmt | `web/job_manager.py` | Job CRUD, SSE broadcasting, ZIP, cleanup |
| Auth | `web/login_manager.py` | Browser-based login sessions |
| Routes | `web/routes.py` | API endpoints, file serving |
| Middleware | `web/middleware.py` | Rate limiting |
| Frontend | `static/` | Vanilla HTML/CSS/JS |

---

## Module Reference

### Entry Point — `app.py`

Initializes FastAPI with a lifespan context manager that starts two background loops:
- **Job cleanup** — every 60s, deletes jobs older than `job_ttl` (default 1 hour)
- **Login cleanup** — every 60s, removes expired login sessions (10 min max)

Creates singleton instances of `CloneConfig`, `JobManager`, and `LoginManager`. Mounts static files and registers all routes.

Runs on `0.0.0.0:8000` with hot reload enabled via uvicorn.

---

### Configuration — `config.py`

A single `@dataclass` with all tunable parameters:

| Parameter | Default | What it controls |
|-----------|---------|------------------|
| `max_depth` | 10 | BFS crawl depth limit |
| `max_pages` | 500 | Max HTML pages to crawl |
| `concurrency` | 10 | Parallel download connections |
| `timeout` | 30 | HTTP request timeout (seconds) |
| `max_file_size` | 50 MB | Skip files larger than this |
| `max_retries` | 3 | Retry attempts on failure |
| `retry_base_delay` | 1.0 | Exponential backoff base (seconds) |
| `verify_ssl` | true | SSL certificate validation |
| `request_delay` | 0.0 | Per-domain delay between requests |
| `respect_robots` | true | Obey robots.txt |
| `use_sitemap` | false | Parse sitemap.xml for URLs |
| `auth_cookies` | `{}` | Cookies for authenticated requests |
| `auth_headers` | `{}` | Custom HTTP headers |
| `job_ttl` | 3600 | Auto-cleanup after N seconds |
| `api_rate_limit` | 10 | Max clone requests per IP per window |
| `api_rate_window` | 60 | Rate limit window (seconds) |
| `use_playwright` | false | Enable JS rendering |
| `user_agent` | `StaticSiteCloner/1.0` | HTTP User-Agent |
| `output_dir` | `output` | Base directory for cloned sites |

Config is cloned per job in `job_manager.start_clone()`, so per-job overrides don't affect the global instance.

---

### Data Models — `cloner/models.py`

**Enums:**
- `AssetType` — HTML, CSS, JS, IMAGE, FONT, VIDEO, OTHER
- `JobStatus` — PENDING, CRAWLING, DOWNLOADING, REWRITING, DONE, FAILED, CANCELLED
- `ErrorCategory` — TIMEOUT, DNS_FAILURE, HTTP_ERROR, SSL_ERROR, TOO_LARGE, PARSE_ERROR, UNKNOWN

**Dataclasses:**
- `ErrorDetail` — URL, category, message, HTTP status code
- `Asset` — URL, local path, content bytes, status, content-type, errors
- `CrawlResult` — URL, depth, discovered links/assets, parse errors
- `CloneJob` — Full job state machine (ID, URL, status, counts, timestamps, output path, errors list)

**Progress callback type:** `Callable[[dict[str, Any]], Awaitable[None]]` — async function receiving event dicts.

> **Note:** `Asset.content` is `None` until downloaded. `CloneJob.cancel_requested` is polled by the engine at 3 checkpoints.

---

### URL Utilities — `cloner/url_utils.py`

**Critical module.** Every URL in the system must go through `normalize_url()` to prevent duplicate crawling.

| Function | Purpose |
|----------|---------|
| `normalize_url(url, base_url)` | Resolve relative URLs, lowercase scheme+host, strip fragments, canonicalize ports |
| `is_same_domain(url, domain)` | Domain match check (includes subdomains) |
| `url_to_local_path(url, domain)` | Convert URL to safe filesystem path |
| `make_relative_path(from_file, to_file)` | Compute relative path between two local files |
| `classify_url(url, content_type)` | Guess AssetType from extension or MIME type |

**Path safety:**
- Replaces `..` and `:` with `_` (traversal protection)
- Truncates long filenames using MD5 hash suffix
- Caps total path at ~200 chars for Windows compatibility
- Query strings appended as `_key-val` to distinguish cache-busted URLs
- Directories and path-less URLs get `/index.html` appended

---

### HTTP Client — `cloner/downloader.py`

**RateLimiter** — Per-domain delay enforcement using `asyncio.Lock`. Tracks last request time per domain.

**Downloader** — Wraps `aiohttp.ClientSession` with:
- Connection pooling
- Auth cookies/headers injection
- Concurrency semaphore (default 10)
- Retry with exponential backoff + jitter
- Size limit enforcement (Content-Length header + body check)
- gzip/deflate/Brotli decompression

Key methods:
```python
await downloader.start(target_url)     # Init session, load cookies
status, body, ctype, err = await downloader.fetch(url)
status, body, ctype, final_url, err = await downloader.fetch_with_final_url(url)
await downloader.close()
```

**Retry logic:**
- Retries on 5xx and transient errors (DNS, connection, timeout)
- Does NOT retry on 4xx (client errors) or SSL errors
- Delay: `base_delay * 2^attempt + random(0, 0.5)`

---

### HTML/CSS Parser — `cloner/parser.py`

Extracts URLs from HTML using BeautifulSoup (lxml backend) and from CSS using regex.

**HTML elements parsed:**
`<a href>`, `<link href>` (stylesheets, icons), `<script src>`, `<img src/srcset>`, `<source src/srcset>`, `<video src/poster>`, `<audio src>`, `<style>` blocks, inline `style=""` attributes, `<meta og:image>`, `<base href>`

**CSS regex patterns:**
```
url(\s*(['"]?)(.*?)\1\s*\)
@import\s+(?:url\(...\)|['"]...['"]))
```

Returns: `(page_links: list[str], asset_urls: list[str])`
- `page_links` — URLs to crawl (HTML pages)
- `asset_urls` — URLs to download (CSS, JS, images, fonts, etc.)

> Data URIs (`data:`) are skipped. External URLs are included but filtered by `is_same_domain()` in the engine.

---

### URL Rewriter — `cloner/rewriter.py`

Runs **after** all downloads complete (needs the full `url_map`).

```python
rewritten_html = rewrite_html(html, page_url, url_map, page_local_path)
rewritten_css  = rewrite_css(css_text, css_url, url_map, css_local_path)
```

**Logic per URL:**
1. Normalize against the base URL (page URL or CSS URL)
2. Look up in `url_map` (absolute URL -> local path)
3. If found: compute relative path from current file to target
4. If not found: leave as-is (external or undownloaded)
5. Skip special protocols: `#`, `mailto:`, `tel:`, `javascript:`, `data:`

**HTML-specific:** Removes `<base>` tags (all paths become relative). Uses posixpath (forward slashes) even on Windows.

---

### Clone Engine — `cloner/engine.py`

The heart of the system. Orchestrates 4 sequential phases:

#### Phase 1: CRAWLING (BFS)
```
queue = deque([(start_url, 0)] + [(seed, 1) for seed in seed_urls])
while queue and pages < max_pages:
    url, depth = queue.popleft()
    if depth > max_depth: skip
    if url in visited: skip
    if robots blocked: skip
    fetch page (aiohttp or Playwright)
    parse HTML -> page_links + asset_urls
    add page_links to queue at depth+1
    collect asset_urls for download
```

#### Phase 2: DOWNLOADING (two waves)
1. **Wave 1:** Download all CSS files first
2. Parse CSS files for secondary assets (fonts, background images)
3. **Wave 2:** Download remaining assets + secondary assets

#### Phase 3: REWRITING
Rewrite all HTML and CSS files using the complete `url_map`.

#### Phase 4: SAVING
Write all files to disk via aiofiles with semaphore (20 concurrent writes). Compute total site size.

**Cancellation checkpoints:** 3 points — BFS loop start, before downloads, before rewrite. Engine polls `job.cancel_requested`.

**Key data structures:**
```python
url_map: dict[str, str]        # absolute URL -> local file path
html_assets: dict[str, Asset]  # pages (for rewriting)
css_assets: dict[str, Asset]   # CSS (for parsing + rewriting)
all_assets: dict[str, Asset]   # everything else (for writing)
visited: set[str]              # dedup crawled URLs
pending_assets: set[str]       # URLs queued for download
secondary_urls: set[str]       # discovered in CSS
```

**Playwright integration:**
- Uses `ThreadedPlaywrightRenderer` (not `PlaywrightRenderer`) to avoid Windows event loop issues
- Auto-enabled when `auth_cookies` are present
- Intercepts network requests during page load for asset discovery
- Falls back to raw HTTP fetch on any Playwright error

---

### Encoding Detection — `cloner/encoding.py`

```python
text = decode_content(raw_bytes, content_type="text/html; charset=utf-8")
```

Detection order:
1. `charset=` in Content-Type header
2. `<meta charset="...">` in first 4KB of HTML
3. `<?xml encoding="..."?>` declaration
4. Fallback: UTF-8 with `errors="replace"`

---

### Robots.txt — `cloner/robots.py`

```python
checker = RobotsChecker(user_agent="StaticSiteCloner/1.0")
await checker.load(base_url, downloader.fetch)
if checker.can_fetch(url):
    crawl(url)
delay = checker.crawl_delay(url)  # may update rate limiter
sitemap_urls = await checker.get_sitemap_urls(base_url, downloader.fetch)
```

Uses stdlib `urllib.robotparser.RobotFileParser`. Caches parsed rules per origin. Missing robots.txt allows all URLs.

Sitemap parsing extracts `<loc>` tags via regex from sitemap.xml files referenced in robots.txt (or falls back to `/sitemap.xml`).

---

### Playwright Renderer — `cloner/renderer.py`

Two implementations:

**`PlaywrightRenderer`** — Basic async renderer. Not used in production (Windows `subprocess_exec` issue).

**`ThreadedPlaywrightRenderer`** — Production renderer:
- Runs Playwright in a dedicated background thread with its own event loop
- Bridges async calls via `asyncio.run_coroutine_threadsafe()`
- Persistent browser context (reused across pages)
- Pre-injects auth cookies at context creation
- Intercepts asset network requests (stylesheet, image, font, media, script)

```python
renderer = ThreadedPlaywrightRenderer(
    user_agent="...",
    cookies={"session": "abc123"},
    target_url="https://example.com"  # for cookie domain
)
await renderer.start()
html, asset_urls = await renderer.render("https://example.com/page")
await renderer.close()
```

Each `render()` creates a new page and closes it after use. Page timeout is 30s with graceful fallback on timeout (uses partial HTML).

> **Requires:** `pip install playwright && playwright install chromium`

---

### API Schemas — `web/schemas.py`

Pydantic models for request validation and response serialization:

| Schema | Used by |
|--------|---------|
| `CloneRequest` | POST /api/clone |
| `CloneResponse` | POST /api/clone response |
| `JobResponse` | GET /api/jobs/{id} |
| `ErrorDetailResponse` | Nested in JobResponse |
| `LoginRequest` | POST /api/auth/login |
| `LoginStartResponse` | POST /api/auth/login response |
| `LoginSessionResponse` | GET /api/auth/login/{id} |

Optional fields use `Type | None` with default `None`. Enum values serialized via `.value`.

---

### Job Manager — `web/job_manager.py`

Manages the full lifecycle of clone jobs:

| Method | What it does |
|--------|--------------|
| `create_job(url, ...)` | Create job with UUID, parse domain |
| `start_clone(job, config)` | Launch engine as async background task |
| `subscribe(job_id)` | Create asyncio.Queue for SSE |
| `unsubscribe(job_id, queue)` | Remove SSE subscriber |
| `cancel_job(job_id)` | Set `job.cancel_requested = True` |
| `delete_job(job_id)` | Remove output dir, ZIP cache, job record |
| `find_recent_clone(url)` | Duplicate detection (same URL, DONE status) |
| `get_zip_path(job)` | Generate or return cached ZIP |
| `start_cleanup_loop()` | Background TTL cleanup every 60s |

**SSE broadcasting:** `_broadcast(job_id, data)` pushes events to all subscriber queues. Non-blocking — errors are silently ignored.

**ZIP generation:** On-demand, cached on disk, uses ZIP_DEFLATED compression.

**Job IDs:** 12-char hex (truncated UUID).

---

### Login Manager — `web/login_manager.py`

Manages Playwright-based browser login sessions for authenticated cloning.

**Flow:**
1. User clicks "Login First" → `create_session(url)` spawns a background thread
2. Thread launches visible Chromium browser, navigates to the target URL
3. Status becomes `browser_open` — user logs in manually in the real browser
4. User clicks "Done" in the UI → `finish_session(session_id)` sets a `threading.Event`
5. Thread captures cookies via `context.cookies()` and navigation links via DOM query
6. Status becomes `done` with cookies and discovered URLs available

**Link discovery:** Runs `document.querySelectorAll('a[href]')` in the browser, filters to same-origin, non-JS, non-root, non-hash-only links. Returned as `discovered_urls` for seed URL injection.

**Timeouts:**
- Browser wait: 10 minutes (600s) for user to log in
- Session cleanup: every 60s in app.py lifespan

> Thread uses `asyncio.new_event_loop()` to avoid Windows subprocess issues. Browser is non-headless (visible to user).

---

### API Routes — `web/routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/clone` | Start clone job |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Get job details |
| POST | `/api/jobs/{id}/cancel` | Cancel job |
| DELETE | `/api/jobs/{id}` | Delete job |
| GET | `/api/jobs/{id}/events` | SSE progress stream |
| GET | `/api/jobs/{id}/download` | Download ZIP |
| GET | `/site/{id}/{path}` | Browse cloned site (new tab) |
| GET | `/api/jobs/{id}/browse/{path}` | Browse/embed cloned site |
| POST | `/api/auth/login` | Start login session |
| GET | `/api/auth/login/{id}` | Check login status |
| POST | `/api/auth/login/{id}/done` | Finish login |

**File serving details:**
- Path traversal protection via `os.path.normpath()`
- Directories redirect to `index.html`
- HTML files get `<base>` tag and `history.replaceState` injected for SPA routing
- Embed mode (`?embed=1`) adds frame-busting neutralization and CSP headers
- MIME types guessed via `mimetypes.guess_type()`

**SSE stream:** 30s keepalive timeout, closes on `"type": "end"` event.

---

### Rate Limiting — `web/middleware.py`

Sliding window rate limiter. Only applies to `POST /api/clone`.

- Tracks request timestamps per IP in an in-memory dict
- Prunes timestamps older than the window (default 60s)
- Returns HTTP 429 if count >= limit (default 10)
- Resets on server restart (no persistence)

---

### Frontend — `static/`

Vanilla HTML/CSS/JS — no frameworks.

**`index.html`** — UI structure: clone form, auth section, progress section, job history, preview modal.

**`style.css`** — Styling with CSS Grid layout, animations (counter bump, progress bar, toast notifications).

**`app.js`** — All UI logic:

| Function | Purpose |
|----------|---------|
| `startClone()` | Validate input, call POST /api/clone |
| `subscribeToEvents(jobId)` | Open SSE stream, update UI on events |
| `cancelCurrentJob()` | POST cancel |
| `refreshJobs()` | Fetch and render job list |
| `previewJob(jobId)` | Open iframe preview modal |
| `browseJob(jobId)` | Open /site/{id}/ in new tab |
| `startLoginSession()` | POST /api/auth/login, start polling |
| `finishLoginSession()` | POST done, capture cookies/URLs |
| `clearLoginSession()` | Reset login state |

**SSE event types handled:** `status`, `page_crawled`, `crawl_complete`, `asset_downloaded`, `secondary_assets_found`, `error`, `done`, `end`

---

## Data Flow: Clone Pipeline

```
User clicks "Clone"
  |
  v
POST /api/clone
  -> job_manager.create_job()
  -> job_manager.start_clone() [background task]
       |
       v
     CloneEngine.run()
       |
       +-- Phase 1: BFS Crawl
       |     for each page:
       |       downloader.fetch() or renderer.render()
       |       parser.parse_html() -> page_links + asset_urls
       |       queue page_links, collect asset_urls
       |       broadcast "page_crawled" event
       |
       +-- Phase 2: Download Assets
       |     Wave 1: download CSS files
       |     parser.parse_css() -> secondary_urls
       |     Wave 2: download remaining + secondary
       |     broadcast "asset_downloaded" events
       |
       +-- Phase 3: Rewrite URLs
       |     rewriter.rewrite_html() for each HTML file
       |     rewriter.rewrite_css() for each CSS file
       |
       +-- Phase 4: Save to Disk
       |     aiofiles.write() with semaphore(20)
       |     compute total site size
       |
       v
     broadcast "done" event
     job.status = DONE
```

---

## Data Flow: Browser Login

```
User clicks "Login First"
  |
  v
POST /api/auth/login {url}
  -> login_manager.create_session(url)
  -> spawn background thread
       |
       v
     Launch visible Chromium browser
     Navigate to target URL
     status = "browser_open"
       |
       v
     [User logs in manually in the browser]
       |
       v
User clicks "Done" in UI
  -> POST /api/auth/login/{id}/done
  -> sets threading.Event flag
       |
       v
     Thread captures:
       - context.cookies() -> all cookies
       - document.querySelectorAll('a[href]') -> navigation links
     status = "done"
       |
       v
User clicks "Clone"
  -> cookies injected into CloneConfig.auth_cookies
  -> discovered_urls sent as seed_urls
  -> ThreadedPlaywrightRenderer auto-enabled
  -> Clone starts with authenticated session
```

---

## Key Data Structures

### `url_map` — The Core Mapping

```python
url_map: dict[str, str]
# Example:
{
    "https://example.com/":           "index.html",
    "https://example.com/about":      "about/index.html",
    "https://example.com/style.css":  "style.css",
    "https://example.com/logo.png":   "logo.png",
}
```

Built during crawl + download phases. Used by the rewriter to convert absolute URLs to relative local paths. **Must be complete before rewriting starts.**

### `CloneJob` — Job State Machine

```
PENDING -> CRAWLING -> DOWNLOADING -> REWRITING -> DONE
                                                -> FAILED
                                                -> CANCELLED (at any checkpoint)
```

### Progress Event Types

| Event | Key Fields |
|-------|------------|
| `status` | `status` (crawling, downloading, rewriting, done) |
| `page_crawled` | `url`, `depth`, `pages_crawled` |
| `crawl_complete` | `pages_crawled`, `assets_found` |
| `asset_downloaded` | `url`, `asset_type`, `assets_downloaded`, `assets_total` |
| `secondary_assets_found` | `count`, `assets_total` |
| `error` | `url`, `error`, `category` |
| `done` | `pages_crawled`, `assets_downloaded`, `errors`, `site_size_bytes` |
| `end` | `status` (done, failed, cancelled) |

---

## Adding a New Feature

### Adding a new config parameter

1. Add field to `CloneConfig` in `config.py` with a default value
2. Add it to `CloneRequest` in `web/schemas.py` (optional field)
3. Pass it through in `routes.py` POST /api/clone handler
4. Use it in the relevant module (engine, downloader, etc.)

### Adding a new API endpoint

1. Define request/response Pydantic models in `web/schemas.py`
2. Add the route function in `web/routes.py`
3. Register the route in `register_routes()` at the bottom of routes.py
4. Add frontend handler in `static/app.js`

### Adding a new HTML element to parse

1. Add extraction logic in `cloner/parser.py` `parse_html()`
2. Add rewriting logic in `cloner/rewriter.py` `rewrite_html()`
3. Add test cases in `tests/test_parser.py` and `tests/test_rewriter.py`

### Adding a new SSE event type

1. Emit the event in `cloner/engine.py` via `await progress_callback({...})`
2. Handle it in `web/job_manager.py` `_broadcast()` (usually automatic)
3. Handle it in `static/app.js` `subscribeToEvents()` switch case

---

## Common Gotchas

### URL Normalization
**Always** use `normalize_url()` on any URL before adding it to `visited`, `url_map`, or any set/dict. Failing to do this causes duplicate downloads and broken rewrites.

### Windows Long Paths
Windows has a 260-char path limit. `url_to_local_path()` truncates to ~200 chars. Engine adds `\\?\` prefix for long paths during file write. Use forward slashes in `<base>` tags (routes.py does `rel.replace("\\", "/")`).

### Playwright Threading
Windows uvicorn uses `ProactorEventLoop` which doesn't support `subprocess_exec`. That's why we use `ThreadedPlaywrightRenderer` (runs Playwright in its own thread with a fresh event loop) instead of `PlaywrightRenderer` (which uses the main loop).

### Rewriting Requires Complete url_map
The rewriter **must** run after all downloads finish. It needs the full `url_map` to compute relative paths. Running it incrementally would produce broken links for not-yet-downloaded assets.

### CSS Priority Download
CSS files are downloaded first (Wave 1) because they may reference fonts and background images that we also need to download. These "secondary assets" are discovered by parsing CSS, then downloaded in Wave 2.

### SSE Keepalive
The SSE stream sends `: keepalive\n\n` every 30s to prevent browser/proxy timeout. The frontend EventSource reconnects automatically on disconnect.

### Job Cancellation
Cancellation is cooperative — the engine checks `job.cancel_requested` at 3 checkpoints. Between checkpoints, work continues. Cancellation is not instant.

### Auth Cookie Domain
When injecting cookies from the login flow into the Playwright renderer, cookies are scoped to the domain parsed from `target_url`. Make sure the login URL and clone URL share the same domain.

### Error Handling Philosophy
Individual page/asset failures are logged and reported but never crash the job. The clone continues with whatever it can get. Errors are accumulated in `job.errors` and categorized for the UI.

---

## Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio aioresponses

# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_engine.py -v

# Run a specific test
pytest tests/test_parser.py::test_parse_html_extracts_links -v
```

Test files mirror source modules:
- `tests/test_url_utils.py` — URL normalization, path mapping
- `tests/test_parser.py` — HTML/CSS extraction
- `tests/test_rewriter.py` — URL rewriting
- `tests/test_downloader.py` — HTTP client, retries
- `tests/test_engine.py` — Pipeline integration
- `tests/test_routes.py` — API endpoints
- `tests/test_job_manager.py` — Job lifecycle
- `tests/test_encoding.py` — Charset detection

Use `aioresponses` to mock aiohttp requests in async tests.
