"""Test helpers: a fake fetcher that serves fixture files instead of the network."""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.http import Fetcher, FetchError, Response  # noqa: E402
from scraper.robots import Robots as Protego  # noqa: E402
from scraper.parsers.base import Context  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher(Fetcher):
    """Serves `routes` {regex: fixture name | (status, text_or_fixture[, headers])}; robots {host: text}.

    Unknown URL -> FetchError 404. Every call is recorded in self.calls.
    """

    def __init__(self, routes: dict[str, object], robots: dict[str, str] | None = None):
        super().__init__(capture_dir=None, min_delay=0)
        self.routes = routes
        self.robots_txt = robots or {}
        self.calls: list[str] = []

    def robots_for(self, url: str):
        host = self._host(url)
        txt = self.robots_txt.get(host)
        return Protego.parse(txt) if txt else None

    def _crawl_delay(self, url: str) -> float:
        return 0

    def request(self, method, url, *, params=None, headers=None, data=None, json_body=None,
                accept_status=(200,), retries=2, check_robots=True):
        import requests

        full = requests.Request(method, url, params=params).prepare().url or url
        if check_robots and not self.allowed(full):
            from scraper.http import RobotsDisallowed
            raise RobotsDisallowed(full)
        self.calls.append(full)
        self.log.append({"url": full, "status": 200})
        for pat, target in self.routes.items():
            if re.search(pat, full):
                hdrs: dict = {}
                if isinstance(target, tuple):
                    status, text = target[0], target[1]
                    hdrs = target[2] if len(target) > 2 else {}
                    if text.endswith((".html", ".json", ".txt")) and (FIXTURES / text).exists():
                        text = fixture(text)
                else:
                    status, text = 200, fixture(str(target))
                if status not in accept_status:
                    raise FetchError(full, status)
                return Response(full, status, text, hdrs)
        raise FetchError(full, 404)


class FakeBrowser:
    """render(url) -> (html of the fixture, None)."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def render(self, url, wait_for=None, timeout_ms=30000, evaluate=None):
        self.calls.append(url)
        for pat, name in self.routes.items():
            if re.search(pat, url):
                return fixture(name), None
        raise FetchError(url, 404)

    def close(self):
        pass


@pytest.fixture
def make_ctx():
    def _make(routes: dict[str, object], robots: dict[str, str] | None = None,
              browser_routes: dict[str, str] | None = None, today: date = date(2026, 11, 8)):
        f = FakeFetcher(routes, robots)
        b = FakeBrowser(browser_routes) if browser_routes is not None else None
        return Context(fetcher=f, browser=b, today=today)
    return _make
