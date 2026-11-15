"""Headless Chromium for the few official sites that only show offers with JavaScript.

Same rules as http.Fetcher: robots.txt first, honest user agent, no login,
no form submission, no CAPTCHA solving. If the page shows an anti-robot
challenge, we stop and report the source as resisting.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .http import Fetcher, RobotsDisallowed, FetchError, looks_like_challenge

log = logging.getLogger(__name__)


class Browser:
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self._pw = None
        self._browser = None
        self._context = None

    def _start(self) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright  # imported lazily: heavy

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._context = self._browser.new_context(
            user_agent=self.fetcher.user_agent, locale="fr-FR", java_script_enabled=True
        )

    def render(self, url: str, *, wait_for: str | None = None, timeout_ms: int = 30000,
               evaluate: str | None = None) -> tuple[str, Any]:
        """Open url, wait for `wait_for` (CSS selector) and return (html, evaluate result)."""
        if not self.fetcher.allowed(url):
            self.fetcher.log.append({"url": url, "status": "robots"})
            raise RobotsDisallowed(url, unreachable=self.fetcher.robots_unreachable(url))
        self._start()
        host = self.fetcher._host(url)
        self.fetcher._wait(host, self.fetcher._crawl_delay(url))
        page = self._context.new_page()
        blocked: list[str] = []          # URLs the page asked for that robots.txt forbids (never loaded)
        page.route("**/*", self._robots_guard(page, host, blocked))
        try:
            try:
                resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001 - timeout, network: the runner explains it
                self.fetcher.log.append({"url": url, "status": "erreur", "via": "navigateur"})
                raise FetchError(url, None, f"navigateur : {type(e).__name__}") from None
            status = resp.status if resp else 0
            final = page.url or url        # chrome-error://... after a navigation stopped by the guard
            if final != url and final.startswith(("http://", "https://")) and not self.fetcher.allowed(final):
                # HTTP redirect (Playwright cannot stop it): the forbidden page is not used
                self.fetcher.log.append({"url": final, "status": "robots", "via": "navigateur"})
                raise RobotsDisallowed(final, unreachable=self.fetcher.robots_unreachable(final))
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=timeout_ms)
                except Exception:  # noqa: BLE001 - reported below
                    html = page.content()
                    self.fetcher._capture(url, status, html)
                    self.fetcher.log.append({"url": url, "status": status, "via": "navigateur"})
                    if blocked:     # the content needed a page robots.txt forbids (JavaScript redirect, data)
                        self.fetcher.log.append({"url": blocked[0], "status": "robots", "via": "navigateur"})
                        raise RobotsDisallowed(blocked[0], unreachable=self.fetcher.robots_unreachable(blocked[0]))
                    detail = "page anti-robot" if looks_like_challenge(html, status) else \
                        f"élément « {wait_for} » introuvable"
                    raise FetchError(url, status, detail)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            html = page.content()
            self.fetcher._capture(url, status, html)
            self.fetcher.log.append({"url": url, "status": status, "via": "navigateur"})
            if looks_like_challenge(html, status):
                raise FetchError(url, status, "page anti-robot")
            result = page.evaluate(evaluate) if evaluate else None
            return html, result
        finally:
            page.close()

    def sniff_endpoints(self, url: str, *, max_actions: int = 6, timeout_ms: int = 45000):
        """Open url, capture JSON responses and return (candidates, cookies, html).

        Reuses this browser's single Playwright context (never starts a second one),
        obeys robots.txt and the per-host delay, and aborts requests robots.txt forbids.
        """
        from . import discover

        if not self.fetcher.allowed(url):
            self.fetcher.log.append({"url": url, "status": "robots"})
            raise RobotsDisallowed(url, unreachable=self.fetcher.robots_unreachable(url))
        self._start()
        host = self.fetcher._host(url)
        self.fetcher._wait(host, self.fetcher._crawl_delay(url))
        candidates: list = []
        page = self._context.new_page()
        blocked: list[str] = []
        page.route("**/*", self._robots_guard(page, host, blocked))

        def on_response(resp) -> None:
            if "json" not in (resp.headers.get("content-type") or "").lower():
                return
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                return
            req = resp.request
            candidates.extend(discover.best_candidates(body, {
                "method": req.method, "url": resp.url, "post_data": req.post_data,
                "headers": dict(req.headers)}))

        page.on("response", on_response)
        try:
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
            discover._explore(page, candidates, max_actions, timeout_ms)
            cookies = self._context.cookies()
            html = page.content()
            self.fetcher.log.append({"url": url, "status": 200, "via": "navigateur"})
        finally:
            page.close()
        best: dict = {}
        for c in sorted(candidates, key=lambda c: -c.score):
            best.setdefault((c.method, c.url.split("?")[0], c.json_path), c)
        return list(best.values()), cookies, html

    def _robots_guard(self, page, host: str, blocked: list[str]) -> Callable:
        """Route handler: neither a navigation of the page (JavaScript redirect...) nor a request
        to the site itself (data loaded by its scripts) goes to a URL that robots.txt forbids;
        such URLs are not loaded and are recorded in `blocked`."""
        def handler(route) -> None:
            u = route.request.url
            checked = u.startswith(("http://", "https://")) and (
                self.fetcher._host(u) == host or _main_navigation(route.request, page))
            if checked and not self.fetcher.allowed(u):
                blocked.append(u)
                route.abort()
            else:
                route.continue_()
        return handler

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:  # noqa: BLE001
            log.debug("browser close: %s", e)
        self._pw = self._browser = self._context = None


def _main_navigation(request, page) -> bool:
    try:
        return request.is_navigation_request() and request.frame == page.main_frame
    except Exception:  # noqa: BLE001 - e.g. service worker request without frame
        return False


class LazyBrowser:
    """Starts Chromium only if a parser actually needs it."""

    def __init__(self, fetcher: Fetcher, factory: Callable[[Fetcher], Browser] = Browser):
        self._fetcher = fetcher
        self._factory = factory
        self._b: Browser | None = None

    def render(self, *a, **kw):
        if self._b is None:
            self._b = self._factory(self._fetcher)
        return self._b.render(*a, **kw)

    def sniff_endpoints(self, *a, **kw):
        if self._b is None:
            self._b = self._factory(self._fetcher)
        return self._b.sniff_endpoints(*a, **kw)

    def close(self) -> None:
        if self._b:
            self._b.close()
