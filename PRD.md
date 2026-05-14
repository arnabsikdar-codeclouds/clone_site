# Product Requirements Document: Static Website Cloner

## Overview
A Python-based tool that clones static websites for offline browsing. Users provide a URL through a web interface, and the tool crawls the entire site — downloading HTML, CSS, JavaScript, images, and fonts — then rewrites all URLs to work locally.

## Problem Statement
Developers, designers, and researchers often need offline copies of websites for reference, analysis, or archival purposes. Existing tools are either CLI-only, lack real-time progress feedback, or fail to properly rewrite asset URLs for offline use.

## Goals
- Clone any public static website with a single URL input
- Download all pages and assets (CSS, JS, images, fonts) within the same domain
- Rewrite all URLs so the cloned site works fully offline
- Provide real-time progress feedback during cloning
- Allow browsing the cloned site directly or downloading as ZIP

## Non-Goals
- Cloning JavaScript-rendered SPAs (no headless browser)
- Bypassing authentication or paywalls
- Cloning dynamic server-side functionality (forms, APIs)
- Scheduled/automated cloning
- CDN or cloud hosting of cloned sites

## Target Users
- Web developers needing offline references
- Designers studying site layouts
- Researchers archiving web content
- Students learning from existing websites

---

## Functional Requirements

### FR-1: URL Input & Job Creation
- User provides a target URL via the web UI
- System validates the URL format
- System creates a clone job and begins processing immediately
- Multiple jobs can run concurrently

### FR-2: Site Crawling
- Breadth-first crawl of all internal pages (same domain)
- Configurable max depth (default: 10 levels)
- Configurable max pages (default: 500 pages)
- Respect for standard link patterns (`<a href>`)
- Detection and handling of `<base>` tags
- Skip external domain links (leave as absolute URLs)
- Avoid infinite loops via visited URL tracking

### FR-3: Asset Downloading
- Download all referenced assets:
  - CSS stylesheets (`<link rel="stylesheet">`)
  - JavaScript files (`<script src>`)
  - Images (`<img src>`, `<img srcset>`, CSS `background-image`)
  - Fonts (CSS `@font-face`)
  - Favicons (`<link rel="icon">`)
  - Videos (`<video src>`, `<source src>`)
- Parse CSS files for secondary assets (fonts, background images)
- Skip data URIs (leave inline)
- Configurable max file size (default: 50MB per file)
- Parallel downloads with concurrency limit (default: 10)

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

### FR-6: Real-Time Progress
- Server-Sent Events (SSE) streaming to the browser
- Show: pages found/downloaded, assets found/downloaded, errors
- Live event log showing current activity
- Visual progress indicators (counters/bars)

### FR-7: Browse Cloned Site
- Serve cloned files directly from the output directory
- User can browse the cloned site in a new browser tab
- Correct MIME types for all file types

### FR-8: ZIP Download
- Generate ZIP archive of the cloned site on demand
- Cache ZIP file for repeated downloads
- Stream download to browser

### FR-9: Job History
- List all past clone jobs with status
- Show job metadata: URL, start time, page/asset counts, errors
- Persist history across server restarts (JSON file)

---

## Non-Functional Requirements

### Performance
- Concurrent downloads (default 10 simultaneous connections)
- Politeness delay between requests (default 100ms)
- Request timeout (default 30 seconds)
- Single retry on transient failures (5xx, timeout)

### Security
- Path traversal protection when serving cloned files
- User-Agent identification (`SiteCloner/1.0`)
- No execution of downloaded JavaScript on the server
- Input URL validation

### Reliability
- Graceful handling of 404s, timeouts, and malformed HTML
- Jobs continue despite individual page/asset failures
- Errors logged and reported to UI without crashing

### Limits & Safety
- Max 500 pages per job (configurable)
- Max 2000 assets per job (configurable)
- Max 50MB per individual file (configurable)
- Max crawl depth of 10 (configurable)

---

## Tech Stack

| Component       | Technology                          |
|-----------------|-------------------------------------|
| Backend         | Python 3.10+, FastAPI, uvicorn      |
| HTTP Client     | aiohttp (async)                     |
| HTML Parsing    | BeautifulSoup4 + lxml               |
| CSS Parsing     | cssutils + regex                    |
| Progress Stream | Server-Sent Events (SSE)            |
| Frontend        | Vanilla HTML/CSS/JS                 |
| Packaging       | ZIP via Python zipfile module        |

---

## API Endpoints

| Method | Path                           | Description                |
|--------|--------------------------------|----------------------------|
| POST   | `/api/clone`                   | Start a new clone job      |
| GET    | `/api/jobs`                    | List all jobs              |
| GET    | `/api/jobs/{id}`               | Get job status             |
| GET    | `/api/jobs/{id}/events`        | SSE progress stream        |
| GET    | `/api/jobs/{id}/download`      | Download cloned site as ZIP|
| GET    | `/api/jobs/{id}/browse/{path}` | Browse cloned site files   |

---

## UI Wireframe (Text)

```
┌─────────────────────────────────────────────┐
│            🌐 Site Cloner                    │
├─────────────────────────────────────────────┤
│                                             │
│  URL: [https://example.com        ] [Clone] │
│                                             │
├─────────────────────────────────────────────┤
│  Progress:                                  │
│  Pages:  12 / 45    ████████░░░░░░  27%     │
│  Assets: 34 / 120   ████░░░░░░░░░░  28%     │
│  Errors: 2                                  │
│                                             │
│  ┌─ Event Log ────────────────────────────┐ │
│  │ [14:32:01] Crawling /about/team        │ │
│  │ [14:32:02] Downloaded css/main.css     │ │
│  │ [14:32:02] Downloaded images/logo.png  │ │
│  │ [14:32:03] Error: /old-page (404)      │ │
│  └────────────────────────────────────────┘ │
│                                             │
├─────────────────────────────────────────────┤
│  History:                                   │
│  ┌────────────────────────────────────────┐ │
│  │ ✅ example.com — 45 pages, 120 assets  │ │
│  │    May 14, 2026    [Browse] [Download] │ │
│  ├────────────────────────────────────────┤ │
│  │ ✅ docs.python.org — 12 pages, 30 assets│ │
│  │    May 13, 2026    [Browse] [Download] │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## Success Criteria
1. Can clone a multi-page static site (e.g., a documentation site) with all assets
2. Cloned site renders correctly when browsed offline (CSS, images, fonts load)
3. Progress updates stream in real-time during cloning
4. ZIP download contains complete, working site
5. Handles errors gracefully without crashing (404s, timeouts, large files)
