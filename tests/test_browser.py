"""Headless browser: robots.txt also applies to the pages it is sent to (fake Playwright, no Chromium)."""
from types import SimpleNamespace

import pytest

from conftest import FakeFetcher
from scraper.browser import Browser
from scraper.http import FetchError, RobotsDisallowed

CARMIGNAC = "https://www.carmignac.com/en-fr/about-us/careers"
ROBOTS = {"https://www.carmignac.com": "User-agent: *\nDisallow: /redirect_X/\n"}


class Route:
    def __init__(self, url, frame, nav=True):
        self.request = SimpleNamespace(url=url, frame=frame, is_navigation_request=lambda: nav)
        self.done = None

    def abort(self):
        self.done = "abort"

    def continue_(self):
        self.done = "continue"


class Page:
    """goto() lands on `final` (HTTP redirect) then the page script asks for `js_navigations`."""

    def __init__(self, final=None, js_navigations=(), found=True, goto_error=None, requests=()):
        self.main_frame = object()
        self.final, self.js, self.found, self.goto_error = final, list(js_navigations), found, goto_error
        self.requests = list(requests) or ["https://cdn.example.net/app.js"]
        self.url, self.handler, self.routes = "", None, []

    def route(self, pattern, handler):
        self.handler = handler

    def _ask(self, url, nav=True):
        r = Route(url, self.main_frame, nav)
        self.handler(r)
        self.routes.append((url, r.done))
        return r.done == "continue"

    def goto(self, url, timeout, wait_until):
        if self.goto_error:
            raise self.goto_error
        assert self._ask(url)
        self.url = self.final or url
        for sub in self.requests:                                    # scripts, images, data...
            self._ask(sub, nav=False)
        for nav in self.js:
            self.url = nav if self._ask(nav) else "chrome-error://chromewebdata/"   # what Chromium does
        return SimpleNamespace(status=200)

    def wait_for_selector(self, selector, timeout):
        if not self.found:
            raise TimeoutError(selector)

    def content(self):
        return "<html><body><table><tr><th>Job Title</th></tr></table></body></html>"

    def evaluate(self, js):
        return None

    def close(self):
        pass


def _browser(page):
    b = Browser(FakeFetcher({}, ROBOTS))
    b._context = SimpleNamespace(new_page=lambda: page)      # Chromium is never started
    return b


def test_allowed_page_is_rendered():
    page = Page(requests=["https://cdn.example.net/app.js", "https://www.carmignac.com/redirect_X/pixel.png"])
    html, _ = _browser(page).render(CARMIGNAC, wait_for="table")
    assert "Job Title" in html
    assert ("https://cdn.example.net/app.js", "continue") in page.routes                 # another host
    assert ("https://www.carmignac.com/redirect_X/pixel.png", "abort") in page.routes    # forbidden on the site


def test_data_request_forbidden_by_robots_is_not_made():
    page = Page(requests=["https://www.carmignac.com/redirect_X/api/jobs"], found=False)
    with pytest.raises(RobotsDisallowed) as e:
        _browser(page).render(CARMIGNAC, wait_for="table")
    assert e.value.url == "https://www.carmignac.com/redirect_X/api/jobs"


def test_javascript_redirect_to_a_forbidden_page_is_not_followed():
    page = Page(js_navigations=["https://www.carmignac.com/redirect_X/en-fr/about-us/careers"], found=False)
    with pytest.raises(RobotsDisallowed) as e:
        _browser(page).render(CARMIGNAC, wait_for="table")
    assert e.value.url == "https://www.carmignac.com/redirect_X/en-fr/about-us/careers"
    assert ("https://www.carmignac.com/redirect_X/en-fr/about-us/careers", "abort") in page.routes


def test_http_redirect_to_a_forbidden_page_is_not_used():
    page = Page(final="https://www.carmignac.com/redirect_X/careers")
    b = _browser(page)
    with pytest.raises(RobotsDisallowed) as e:
        b.render(CARMIGNAC, wait_for="table")
    assert e.value.url == "https://www.carmignac.com/redirect_X/careers"
    assert {"url": "https://www.carmignac.com/redirect_X/careers", "status": "robots", "via": "navigateur"} \
        in b.fetcher.log


def test_navigation_failure_is_a_fetch_error():
    page = Page(goto_error=TimeoutError("Timeout 30000ms exceeded"))
    with pytest.raises(FetchError) as e:
        _browser(page).render(CARMIGNAC, wait_for="table")
    assert e.value.url == CARMIGNAC and e.value.status is None and "navigateur" in e.value.detail
