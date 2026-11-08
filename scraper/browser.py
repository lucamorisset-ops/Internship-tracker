"""Headless Chromium for the few official sites that only show offers with JavaScript.

Same rules as http.Fetcher: robots.txt first, honest user agent, no login,
no form submission, no CAPTCHA solving. If the page shows an anti-robot
challenge, we stop and report the source as resisting.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .http import Fetcher, RobotsDisallowed, FetchError, USER_AGENT, looks_like_challenge

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
            user_agent=USER_AGENT, locale="fr-FR", java_script_enabled=True
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
        try:
            resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            status = resp.status if resp else 0
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=timeout_ms)
                except Exception:  # noqa: BLE001 - reported below
                    html = page.content()
                    self.fetcher._capture(url, status, html)
                    self.fetcher.log.append({"url": url, "status": status, "via": "navigateur"})
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

    def close(self) -> None:
        if self._b:
            self._b.close()
