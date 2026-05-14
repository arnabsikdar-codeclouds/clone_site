# SiteCloner

A Python-based static website cloner with a real-time web UI. Provide a URL, and SiteCloner will crawl the entire site, download all pages and assets, rewrite URLs for offline use, and package everything for local browsing or ZIP download.

## Features

- **Full site cloning** -- crawls HTML pages, CSS, JavaScript, images, fonts, and videos
- **Offline-ready** -- all internal URLs are rewritten to relative paths so the cloned site works without a server
- **Real-time progress** -- live updates via Server-Sent Events (SSE) with page count, asset count, and activity log
- **In-browser preview** -- browse the cloned site directly through the web UI
- **ZIP download** -- download the entire cloned site as a single ZIP file
- **Configurable** -- control crawl depth, max pages, concurrency, timeout, and file size limits
- **Async throughout** -- built on aiohttp and asyncio for fast, concurrent downloads

## How It Works

SiteCloner operates in four sequential phases:

### Phase 1: Crawl (BFS)

The engine starts from the given URL and performs a **breadth-first search** across the site. For each HTML page it downloads:

1. The page content is fetched via aiohttp
2. BeautifulSoup parses the HTML to extract two things:
   - **Page links** (`<a href>`) -- queued for further crawling (if within depth limit)
   - **Asset URLs** (CSS, JS, images, fonts, videos from `<link>`, `<script>`, `<img>`, `<video>`, `<audio>`, `<source>`, inline styles, etc.)
3. Only same-domain links are followed; external URLs are left as-is

Crawling stops when either `max_depth` or `max_pages` is reached.

### Phase 2: Download Assets

All discovered asset URLs (CSS, JS, images, fonts) are downloaded concurrently using an asyncio semaphore to limit parallelism (default: 10 concurrent requests).

After the initial asset download, **CSS files are parsed** for secondary references -- `url()` values pointing to fonts, background images, and other resources. These secondary assets are then downloaded in a second batch.

### Phase 3: Rewrite URLs

Once all files are downloaded and a complete `url_map` (absolute URL -> local file path) is built, the engine rewrites every internal URL:

- **HTML files**: rewrites `href`, `src`, `srcset`, `poster`, inline `style` attributes, `<style>` blocks, and `<meta>` image tags. Removes `<base>` tags since all paths become relative.
- **CSS files**: rewrites all `url()` references (backgrounds, fonts, imports)

External URLs (different domain) are left as absolute URLs.

### Phase 4: Save to Disk

All rewritten files are written to `output/<domain>_<timestamp>/`, preserving the original site's directory structure. The output directory is immediately available for browsing or ZIP download.

## Architecture

```
                    +-----------+
  User Browser ---->|  FastAPI   |----> SSE (real-time progress)
                    |  Web UI    |
                    +-----+-----+
                          |
                    +-----v-----+
                    | JobManager |  manages job lifecycle & SSE queues
                    +-----+-----+
                          |
                    +-----v-----+
                    |CloneEngine |  BFS orchestrator
                    +-----+-----+
                          |
            +-------------+-------------+
            |             |             |
       Downloader     Parser       Rewriter
       (aiohttp)    (BS4/lxml)   (BS4/regex)
```

## Quick Start

### Prerequisites

- Python 3.10 or higher

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd copy_site

# Install dependencies
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

The server starts at **http://localhost:8000**. Open it in your browser, enter a URL, and hit Clone.

## API Reference

### Start a Clone

```
POST /api/clone
```

**Request body:**
```json
{
  "url": "https://example.com",
  "max_depth": 10,
  "max_pages": 500
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | *required* | The URL to clone |
| `max_depth` | int | 10 | Maximum BFS crawl depth |
| `max_pages` | int | 500 | Maximum number of HTML pages to crawl |

**Response:**
```json
{
  "job_id": "abc123",
  "message": "Clone started"
}
```

### List All Jobs

```
GET /api/jobs
```

Returns an array of all clone jobs with their current status.

### Get Job Status

```
GET /api/jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "abc123",
  "url": "https://example.com",
  "domain": "example.com",
  "status": "done",
  "pages_crawled": 42,
  "assets_downloaded": 156,
  "errors_count": 3,
  "error_message": ""
}
```

**Job statuses:** `pending` -> `crawling` -> `downloading` -> `rewriting` -> `done` (or `failed`)

### Stream Progress Events (SSE)

```
GET /api/jobs/{job_id}/events
```

Returns a Server-Sent Events stream. Event types:

| Event Type | Description |
|------------|-------------|
| `status` | Job status changed (crawling, downloading, rewriting, saving) |
| `page_crawled` | An HTML page was downloaded and parsed |
| `asset_downloaded` | An asset (CSS/JS/image/font) was downloaded |
| `crawl_complete` | BFS crawl phase finished |
| `secondary_assets_found` | Additional assets discovered in CSS files |
| `error` | A non-fatal error occurred |
| `done` | Clone completed successfully |
| `end` | Stream is closing |

### Download as ZIP

```
GET /api/jobs/{job_id}/download
```

Returns the cloned site as a `.zip` file. Only available after the job completes.

### Browse Cloned Site

```
GET /api/jobs/{job_id}/browse/{path}
```

Serves individual files from the cloned site. Includes path traversal protection.

## Configuration

Default settings are defined in `config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_depth` | 10 | Maximum crawl depth from the start URL |
| `max_pages` | 500 | Maximum HTML pages to crawl |
| `concurrency` | 10 | Simultaneous download connections |
| `timeout` | 30s | HTTP request timeout per URL |
| `max_file_size` | 50 MB | Skip files larger than this |
| `user_agent` | `StaticSiteCloner/1.0` | HTTP User-Agent header |
| `output_dir` | `output` | Directory for cloned sites |

## Project Structure

```
copy_site/
├── app.py                  # Entry point (FastAPI + uvicorn)
├── config.py               # CloneConfig dataclass
├── requirements.txt
├── cloner/                 # Core cloning engine
│   ├── models.py           # Data classes (CloneJob, Asset, AssetType, JobStatus)
│   ├── url_utils.py        # URL normalization, path mapping, domain checks
│   ├── downloader.py       # Async HTTP client with retry and size limits
│   ├── parser.py           # HTML/CSS link & asset extraction
│   ├── rewriter.py         # URL rewriting for offline use
│   └── engine.py           # BFS crawl orchestrator (4-phase pipeline)
├── web/                    # Web layer
│   ├── schemas.py          # Pydantic request/response models
│   ├── job_manager.py      # Job lifecycle, SSE pub/sub, ZIP generation
│   └── routes.py           # FastAPI API endpoints
├── static/                 # Web UI (vanilla HTML/CSS/JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
└── output/                 # Cloned sites stored here (gitignored)
```

## Tech Stack

- **FastAPI** + **uvicorn** -- async web server
- **aiohttp** -- async HTTP client for downloading
- **BeautifulSoup4** + **lxml** -- HTML parsing and rewriting
- **cssutils** + regex -- CSS parsing for `url()` references
- **Vanilla JS** -- frontend with SSE for real-time updates

## Limitations

- Only clones static content -- JavaScript-rendered (SPA) content won't be captured
- Stays within the same domain -- cross-domain pages are not followed
- Large sites may take significant time depending on page count and asset volume
- Some dynamically loaded resources (lazy-loaded images, AJAX content) may be missed

## License

This project is for educational and personal use. Always respect website terms of service and `robots.txt` when cloning sites.
