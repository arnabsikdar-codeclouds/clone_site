import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LoginSession:
    session_id: str
    target_url: str
    status: str = "pending"  # pending | browser_open | done | failed | expired
    cookies: dict[str, str] = field(default_factory=dict)
    discovered_urls: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    error: str = ""
    # Thread-safe event — signalled from main thread, awaited in browser thread
    _done_flag: threading.Event = field(default_factory=threading.Event)


class LoginManager:
    def __init__(self) -> None:
        self._sessions: dict[str, LoginSession] = {}

    def create_session(self, url: str) -> LoginSession:
        session = LoginSession(
            session_id=uuid.uuid4().hex[:12],
            target_url=url,
        )
        self._sessions[session.session_id] = session
        # Run Playwright in a dedicated thread with its own event loop
        # to avoid Windows subprocess_exec NotImplementedError
        t = threading.Thread(
            target=self._run_browser_thread,
            args=(session,),
            daemon=True,
        )
        t.start()
        return session

    def _run_browser_thread(self, session: LoginSession) -> None:
        """Runs in a dedicated thread with a fresh event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._browser_session(session))
        finally:
            loop.close()

    async def _browser_session(self, session: LoginSession) -> None:
        from cloner.renderer import is_playwright_available

        if not is_playwright_available():
            session.status = "failed"
            session.error = (
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
            logger.warning("Login session %s: Playwright not available", session.session_id)
            return

        playwright = None
        browser = None
        try:
            from playwright.async_api import async_playwright

            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(session.target_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as nav_err:
                # Navigation errors are non-fatal — browser is open,
                # user can navigate manually.
                logger.warning("Login session %s: navigation error: %s", session.session_id, nav_err)
            session.status = "browser_open"
            logger.info("Login session %s: browser open at %s", session.session_id, session.target_url)

            # Wait for user to signal done (thread-safe event, polled with timeout)
            signalled = session._done_flag.wait(timeout=600)
            if not signalled:
                session.status = "expired"
                session.error = "Login session timed out after 10 minutes"
                logger.warning("Login session %s: timed out", session.session_id)
                return

            # Extract cookies
            raw_cookies = await context.cookies()
            session.cookies = {c["name"]: c["value"] for c in raw_cookies}

            # Extract all same-origin navigation links from the authenticated page.
            # This captures sidebar/menu links that are JS-rendered and invisible
            # to the raw HTML parser used by the crawler.
            try:
                current_origin = await page.evaluate("window.location.origin")
                links = await page.evaluate("""(origin) => {
                    const anchors = document.querySelectorAll('a[href]');
                    const urls = new Set();
                    for (const a of anchors) {
                        try {
                            const url = new URL(a.href, origin);
                            if (url.origin === origin
                                && !url.href.startsWith('javascript:')
                                && url.pathname !== '/'
                                && !url.hash) {
                                urls.add(url.href.split('#')[0]);
                            }
                        } catch {}
                    }
                    return [...urls];
                }""", current_origin)
                session.discovered_urls = links
                logger.info(
                    "Login session %s: discovered %d navigation links",
                    session.session_id, len(links),
                )
            except Exception as e:
                logger.warning("Login session %s: link extraction failed: %s", session.session_id, e)

            session.status = "done"
            logger.info(
                "Login session %s: captured %d cookies",
                session.session_id, len(session.cookies),
            )
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            logger.error("Login session %s: %s", session.session_id, exc, exc_info=True)
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()

    def get_session(self, session_id: str) -> LoginSession | None:
        return self._sessions.get(session_id)

    def finish_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session or session.status != "browser_open":
            return False
        session._done_flag.set()
        return True

    def cleanup_expired(self, max_age: float = 900) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.created_at > max_age
        ]
        for sid in expired:
            del self._sessions[sid]
