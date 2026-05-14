# CLAUDE.md - Static Website Cloner

## Project Overview
Python-based static website cloner with a FastAPI web UI. Users provide a URL, the tool crawls and downloads the full site, rewrites URLs for offline use, and serves the result for browsing or ZIP download.

## Tech Stack
- **Backend**: Python 3.10+, FastAPI, uvicorn
- **Async HTTP**: aiohttp
- **Parsing**: BeautifulSoup4 + lxml (HTML), cssutils + regex (CSS)
- **Frontend**: Vanilla HTML/CSS/JS, SSE for real-time progress
- **No frameworks** on the frontend — keep it simple

## Project Structure
```
copy_site/
├── app.py                  # Entry point (FastAPI + uvicorn)
├── config.py               # CloneConfig dataclass
├── requirements.txt
├── cloner/                 # Core cloning engine
│   ├── models.py           # Data classes (CloneJob, Asset, etc.)
│   ├── url_utils.py        # URL normalization & path mapping
│   ├── downloader.py       # Async HTTP client
│   ├── parser.py           # HTML/CSS link & asset extraction
│   ├── rewriter.py         # URL rewriting for offline use
│   └── engine.py           # BFS crawl orchestrator
├── web/                    # Web layer
│   ├── schemas.py          # Pydantic models
│   ├── job_manager.py      # Job lifecycle & SSE management
│   └── routes.py           # API endpoints
├── static/                 # Web UI files
│   ├── index.html
│   ├── style.css
│   └── app.js
└── output/                 # Cloned sites stored here (gitignored)
```

## Commands
- **Run server**: `python app.py` (starts on http://localhost:8000)
- **Install deps**: `pip install -r requirements.txt`

## Architecture Conventions
- All HTTP fetching is async via aiohttp — never use synchronous requests
- BFS crawl pattern — breadth-first, depth-limited
- URL rewriting happens AFTER all downloads complete (needs full url_map)
- SSE (Server-Sent Events) for progress — not WebSocket
- Jobs run as asyncio background tasks
- Cloned sites go in `output/<domain>_<timestamp>/`

## Code Style
- Python type hints everywhere
- Dataclasses for data structures, Pydantic for API schemas
- Async/await for all I/O operations
- Keep modules focused — one responsibility per file
- No unnecessary abstractions or over-engineering

## Key Design Rules
- `url_map` (dict[str, str]) maps absolute URL → local file path — shared across engine, parser, rewriter
- `normalize_url()` must be used consistently everywhere to avoid duplicate crawling
- External URLs are always left absolute — only internal URLs get rewritten
- CSS files must be parsed after download for secondary assets (fonts, bg images)
- Path traversal protection required when serving cloned files via browse endpoint
- Graceful error handling — 404s, timeouts logged but never crash the job
