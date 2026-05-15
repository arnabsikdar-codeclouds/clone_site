# Product Requirements Document: Static Website Cloner

## Overview
A Python-based tool that clones static and JavaScript-rendered websites for offline browsing. Users provide a URL through a web interface, and the tool crawls the entire site — downloading HTML, CSS, JavaScript, images, and fonts — then rewrites all URLs to work locally. Includes job management, real-time progress, in-app preview, and production-ready features like retry logic, rate limiting, robots.txt compliance, and cancellation.

## Problem Statement
Developers, designers, and researchers often need offline copies of websites for reference, analysis, or archival purposes. Existing tools are either CLI-only, lack real-time progress feedback, fail to properly rewrite asset URLs for offline use, or cannot handle modern JavaScript-rendered sites.

## Goals
- Clone any website — public or authenticated — with a single URL input
- Download all pages and assets (CSS, JS, images, fonts) within the same domain
- Rewrite all URLs so the cloned site works fully offline
- Provide real-time progress feedback during cloning
- Allow browsing the cloned site directly, previewing in-app, or downloading as ZIP
- Handle errors gracefully with categorized error reporting
- Support cancellation of in-progress jobs
- Respect robots.txt and rate limits for polite crawling
- Optionally render JavaScript-heavy pages via headless browser

## Non-Goals
- Cloning dynamic server-side functionality (forms, APIs)
- Scheduled/automated cloning
- CDN or cloud hosting of cloned sites

## Target Users
- Web developers needing offline references
- Designers studying site layouts
- Researchers archiving web content
- Students learning from existing websites
- QA teams needing static snapshots of sites

---

## Functional Requirements

### FR-1: URL Input & Job Creation
- User provides a target URL via the web UI
- System validates the URL format and adds scheme if missing
- System creates a clone job with timestamps and begins processing
- Multiple jobs can run concurrently
- Duplicate URL detection warns users if the URL was already cloned

### FR-2: Site Crawling
- Breadth-first crawl of all internal pages (same domain)
- Configurable max depth (default: 10 levels)
- Configurable max pages (default: 500 pages)
- Respect for standard link patterns (`<a href>`)
- Detection and handling of `<base>` tags
- Skip external domain links (leave as absolute URLs)
- Avoid infinite loops via visited URL tracking
- robots.txt compliance (configurable, enabled by default)
- Optional sitemap.xml URL discovery
- Crawl delay from robots.txt integrated with rate limiter

### FR-3: Asset Downloading
- Download all referenced assets:
  - CSS stylesheets (`<link rel="stylesheet">`)
  - JavaScript files (`<script src>`)
  - Images (`<img src>`, `<img srcset>`, CSS `background-image`)
  - Fonts (CSS `@font-face`)
  - Favicons (`<link rel="icon">`)
  - Videos (`<video src>`, `<source src>`)
- Priority download queue: CSS files first, then everything else + secondary assets
- Parse CSS files for secondary assets (fonts, background images)
- Skip data URIs (leave inline)
- Configurable max file size (default: 50MB per file)
- Parallel downloads with concurrency limit (default: 10)
- Support for gzip, deflate, and Brotli compression

### FR-4: URL Rewriting
- Rewrite all internal URLs in HTML to relative local paths
- Rewrite all `url()` references in CSS to relative local paths
- Handle `srcset` attribute with multiple URLs
- Handle inline `style` attributes with `url()` references
- Leave external URLs unchanged (absolute)
- Remove or update `<base>` tags

### FR-5: File Organization
- Store cloned sites in `output/<domain>_<timestamp>/`
- Preserve original directory structure where possible
- Pages without extensions saved as `<path>/index.html`
- Handle query string URLs with hash-based filenames
- Async file I/O with concurrency limit (20 simultaneous writes)
- Compute and store total site size after save

### FR-6: Real-Time Progress
- Server-Sent Events (SSE) streaming to the browser
- Show: pages found/downloaded, assets found/downloaded, errors
- Live event log showing current activity
- Visual progress indicators (counters/bars)
- Categorized error details (clickable error panel)

### FR-7: Browse Cloned Site
- Dedicated `/site/{job_id}/` URL for browsing in a new tab
- Correct MIME types for all file types
- SPA-compatible: `history.replaceState` + `<base>` tag for React/Vue/Angular routing
- Path traversal protection

### FR-8: In-App Site Preview
- Modal overlay with sandboxed iframe
- Frame-busting protection (neutralizes top/parent navigation)
- X-Frame-Options and CSP headers for embed mode
- "Open in Tab" button and Escape key to close

### FR-9: ZIP Download
- Generate ZIP archive of the cloned site on demand
- Show download size on the ZIP button (e.g. "ZIP (4.2 MB)")
- Cache ZIP file for repeated downloads
- Stream download to browser

### FR-10: Job Management
- List all past clone jobs with status
- Show job metadata: URL, domain, page/asset counts, errors, size
- Cancel in-progress jobs (3 checkpoint cancellation)
- Delete jobs and their output files
- Retry failed/cancelled jobs with one click
- Job history search by domain and filter by status
- Automatic cleanup of expired jobs (configurable TTL, default: 1 hour)

### FR-11: Authentication Support
- Custom cookies passed to the session cookie jar
- Custom HTTP headers merged into requests
- Exposed via API request body

### FR-12: Browser-Based Login Flow
- "Login First" button in the clone form launches a real browser (Playwright)
- User manually logs into the target site in the opened browser
- System captures all cookies from the authenticated browser session
- Discovered navigation links from the authenticated page are collected as seed URLs
- Seed URLs are injected into the BFS crawl queue, enabling cloning of member-only areas
- Login sessions have a 10-minute timeout with automatic cleanup
- Runs Playwright in a dedicated thread to avoid blocking the async event loop
- Thread-safe flag synchronization between main and browser threads
- Polling-based status tracking: pending → browser_open → done → expired/failed

### FR-13: SPA / JavaScript Rendering (Optional)
- Optional Playwright integration (opt-in checkbox)
- ThreadedPlaywrightRenderer runs headless Chromium in a separate thread with its own event loop
- Pre-loads authentication cookies from the login flow
- Intercepts network requests during page rendering for asset discovery
- Graceful fallback to raw HTML fetch if rendering fails
- Automatically enabled when auth_cookies are present (from login flow)
- "JS Render" checkbox with descriptive tooltip

---

## Non-Functional Requirements

### Performance
- Concurrent downloads (default 10 simultaneous connections)
- Per-domain rate limiter with configurable delay
- Async file I/O via aiofiles
- Request timeout (default 30 seconds)
- Priority queue: CSS first, then other assets + secondaries
- Brotli/gzip/deflate compression support

### Security
- Path traversal protection on all file-serving endpoints
- SSL certificate verification (configurable, enabled by default)
- User-Agent identification (`SiteCloner/1.0`)
- No execution of downloaded JavaScript on the server
- Input URL validation
- API rate limiting per IP (sliding window, default: 10 requests/minute)
- Sandboxed iframe for in-app preview
- Frame-busting neutralization in embed mode

### Reliability
- Exponential backoff retry with jitter (configurable, default: 3 attempts)
- Categorized error reporting (TIMEOUT, DNS_FAILURE, HTTP_ERROR, SSL_ERROR, TOO_LARGE, PARSE_ERROR, UNKNOWN)
- 3-point cancellation (BFS loop, asset download, rewrite phase)
- Jobs continue despite individual page/asset failures
- Errors logged and reported to UI without crashing
- Automatic cleanup of expired jobs

### Encoding & Compatibility
- Charset detection from Content-Type header, HTML meta tag, XML declaration
- Fallback to UTF-8 with replacement on decode errors

### Limits & Safety
- Max 500 pages per job (configurable)
- Max 50MB per individual file (configurable)
- Max crawl depth of 10 (configurable)
- robots.txt compliance (configurable)

---

## Tech Stack

| Component       | Technology                              |
|-----------------|-----------------------------------------|
| Backend         | Python 3.10+, FastAPI, uvicorn          |
| HTTP Client     | aiohttp (async)                         |
| HTML Parsing    | BeautifulSoup4 + lxml                   |
| CSS Parsing     | cssutils + regex                        |
| File I/O        | aiofiles (async)                        |
| Compression     | Brotli                                  |
| SPA Rendering   | Playwright (optional)                   |
| Progress Stream | Server-Sent Events (SSE)                |
| Frontend        | Vanilla HTML/CSS/JS                     |
| Packaging       | ZIP via Python zipfile module            |
| Testing         | pytest + pytest-asyncio                 |

---

## API Endpoints

| Method | Path                           | Description                      |
|--------|--------------------------------|----------------------------------|
| POST   | `/api/clone`                   | Start a new clone job            |
| GET    | `/api/jobs`                    | List all jobs                    |
| GET    | `/api/jobs/{id}`               | Get job status with error details|
| POST   | `/api/jobs/{id}/cancel`        | Cancel a running job             |
| DELETE | `/api/jobs/{id}`               | Delete job and output files      |
| GET    | `/api/jobs/{id}/events`        | SSE progress stream              |
| GET    | `/api/jobs/{id}/download`      | Download cloned site as ZIP      |
| GET    | `/site/{id}/{path}`            | Browse cloned site (new tab)     |
| GET    | `/api/jobs/{id}/browse/{path}` | Browse/embed cloned site files   |
| POST   | `/api/auth/login`              | Start a browser login session    |
| GET    | `/api/auth/login/{id}`         | Check login session status       |
| POST   | `/api/auth/login/{id}/done`    | Signal login completion          |

---

## Clone Request Schema

```json
{
  "url": "https://example.com",
  "max_depth": 10,
  "max_pages": 500,
  "verify_ssl": true,
  "request_delay": 0.0,
  "respect_robots": true,
  "use_sitemap": false,
  "user_agent": "StaticSiteCloner/1.0",
  "auth_cookies": {"session": "abc123"},
  "auth_headers": {"Authorization": "Bearer token"},
  "use_playwright": false,
  "seed_urls": ["https://example.com/dashboard", "https://example.com/profile"]
}
```

---

## UI Features

### Clone Form
- URL input with validation
- Max depth and max pages controls
- Verify SSL checkbox (with tooltip explaining when to disable)
- JS Render checkbox (with tooltip explaining SPA rendering)
- **Login First** button — opens a real browser for authenticated session capture
- Login status display showing browser state, captured cookies, and discovered URLs

### Progress Section
- Real-time stats grid: Pages, Assets, Errors (clickable for detail panel)
- Animated progress bar with percentage
- Cancel button for in-progress jobs
- Activity log with timestamped entries
- Categorized error detail panel

### Job History
- Search by domain text input
- Filter by status dropdown (Done, Failed, Cancelled, Crawling, Downloading)
- Job cards with: URL, status badge, page/asset/error counts, site size
- Action buttons: Preview, Browse, ZIP (with size), Retry, Delete

### In-App Preview
- Modal overlay with sandboxed iframe
- Open in Tab and Close buttons
- Escape key to close
- Overlay click to close

---

## Success Criteria
1. Can clone a multi-page static site with all assets rendering correctly offline
2. Can clone a React/Vue/Angular SPA using JS Render mode
3. Can clone authenticated/member-only sites using the browser login flow
4. Progress updates stream in real-time during cloning
5. ZIP download contains complete, working site with accurate size display
6. Handles errors gracefully with categorized reporting (404s, timeouts, SSL, DNS)
7. Job cancellation stops the clone within seconds
8. robots.txt is respected by default
9. Rate limiting prevents abuse of the clone API
10. In-app preview works for both static and SPA sites
