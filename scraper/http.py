"""Polite HTTP access for the robot.

Rules applied to every request, whatever the parser:
  * robots.txt of the host is read first and obeyed (RFC 9309, with * and $),
    for our own user agent; a disallowed URL is never fetched;
  * Crawl-delay is obeyed, otherwise at least MIN_DELAY seconds between two
    requests to the same host;
  * the robot says who it is (USER_AGENT) and never logs in, submits forms or
    applies to anything: it only reads public pages and public APIs.

When CAPTURE_DIR is set, every response body is saved there so that parsers
can be fixed from real pages (the GitHub workflow uploads that folder).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from .robots import Robots as Protego

log = logging.getLogger(__name__)

BOT_NAME = "tracker-stages-bot"
REPO_URL = "https://github.com/lucamorisset-ops/internship-tracker"
USER_AGENT = f"Mozilla/5.0 (compatible; {BOT_NAME}/1.0; +{REPO_URL})"
MIN_DELAY = 2.0          # seconds between two requests to the same host
MAX_CRAWL_DELAY = 60.0   # Crawl-delay obeyed in full up to this value; a host asking for more is not read
TIMEOUT = 30


class RobotsDisallowed(Exception):
    def __init__(self, url: str, unreachable: bool = False, via: str = ""):
        msg = (f"robots.txt injoignable pour {url} : lecture suspendue par prudence" if unreachable
               else f"robots.txt interdit la lecture de {url}")
        super().__init__(msg)
        self.url = url
        self.unreachable = unreachable  # robots.txt could not be read (network / 5xx), RFC 9309 2.3.1.4
        self.via = via                  # allowed page (already requested) that redirected to url


class FetchError(Exception):
    def __init__(self, url: str, status: int | None, detail: str = ""):
        super().__init__(f"{url} -> {status or 'erreur réseau'} {detail}".strip())
        self.url = url
        self.status = status
        self.detail = detail


@dataclass
class Response:
    url: str
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.text)


def looks_like_challenge(text: str, status: int) -> bool:
    """True when the body is an anti-bot page rather than real content.

    We never try to get past such pages: the source is reported as resisting.
    """
    if status in (401, 403, 429, 503) and len(text) < 20000:
        return True
    t = text[:4000].lower()
    return any(
        s in t
        for s in (
            "captcha",
            "just a moment...",
            "cf-browser-verification",
            "requires js enabled and cookies",
            "access denied</title>",
            "/cdn-cgi/challenge-platform",
        )
    ) and len(text) < 50000


class Fetcher:
    """requests.Session wrapper with robots.txt, delays, capture and retries."""

    def __init__(self, capture_dir: str | None = None, min_delay: float = MIN_DELAY):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            }
        )
        self.min_delay = min_delay
        self._robots: dict[str, Protego | None] = {}
        self._robots_status: dict[str, int] = {}
        self._last: dict[str, float] = {}
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.log: list[dict[str, Any]] = []   # every URL read, for the run report

    # ---------- robots.txt ----------
    def _host(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def robots_for(self, url: str) -> Protego | None:
        host = self._host(url)
        if host in self._robots:
            return self._robots[host]
        rp: Protego | None = None
        status = 0
        try:
            self._wait(host, 0)
            r = self.session.get(host + "/robots.txt", timeout=TIMEOUT, allow_redirects=True)
            status = r.status_code
            if r.status_code == 200 and "text/html" not in r.headers.get("content-type", ""):
                rp = Protego.parse(r.text)
            elif r.status_code == 200 and not r.text.lstrip().startswith("<"):
                rp = Protego.parse(r.text)
            elif 500 <= r.status_code < 600:
                # RFC 9309 2.3.1.4: server error -> assume complete disallow
                rp = Protego.parse("User-agent: *\nDisallow: /")
            # 4xx (404, 403...) -> RFC 9309 2.3.1.3: robots "unavailable", crawling allowed
        except requests.RequestException as e:
            log.warning("robots.txt illisible pour %s: %s", host, e)
            rp = Protego.parse("User-agent: *\nDisallow: /")
            status = -1
        self._robots[host] = rp
        self._robots_status[host] = status
        return rp

    def robots_unreachable(self, url: str) -> bool:
        st = self._robots_status.get(self._host(url), 0)
        return st == -1 or st >= 500

    def allowed(self, url: str) -> bool:
        rp = self.robots_for(url)
        return True if rp is None else rp.can_fetch(url, BOT_NAME)

    def _crawl_delay(self, url: str) -> float:
        rp = self.robots_for(url)
        d = rp.crawl_delay(BOT_NAME) if rp else None
        if d and float(d) > MAX_CRAWL_DELAY:
            # waiting less than asked would break the site's rule: the host is not read
            raise FetchError(url, None, f"Crawl-delay de {float(d):g} s demandé par robots.txt")
        return float(d) if d else self.min_delay

    def _wait(self, host: str, delay: float) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < delay:
                time.sleep(delay - gap)
        self._last[host] = time.monotonic()

    # ---------- requests ----------
    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            accept_status: tuple[int, ...] = (200,), retries: int = 2,
            check_robots: bool = True) -> Response:
        return self.request("GET", url, params=params, headers=headers,
                            accept_status=accept_status, retries=retries,
                            check_robots=check_robots)

    def request(self, method: str, url: str, *, params: dict | None = None,
                headers: dict | None = None, data: Any = None, json_body: Any = None,
                accept_status: tuple[int, ...] = (200,), retries: int = 2,
                check_robots: bool = True) -> Response:
        full = requests.Request(method, url, params=params).prepare().url or url
        if check_robots and not self.allowed(full):
            self.log.append({"url": full, "status": "robots"})
            raise RobotsDisallowed(full, unreachable=self.robots_unreachable(full))
        host = self._host(full)
        delay = self._crawl_delay(full)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._wait(host, delay)
            try:
                r = self._follow(method, url, params=params, headers=headers, data=data,
                                 json_body=json_body, check_robots=check_robots)
            except RobotsDisallowed:
                raise
            except requests.RequestException as e:
                last_exc = e
                time.sleep(3 * (attempt + 1))
                continue
            text = r.text
            self._capture(full, r.status_code, text)
            self.log.append({"url": full, "status": r.status_code})
            if r.status_code in accept_status:
                return Response(r.url, r.status_code, text, dict(r.headers))
            if r.status_code >= 500 and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
            raise FetchError(full, r.status_code, "page anti-robot" if looks_like_challenge(text, r.status_code) else "")
        raise FetchError(full, None, str(last_exc or ""))

    def _follow(self, method: str, url: str, *, params, headers, data, json_body,
                check_robots: bool, max_hops: int = 5) -> requests.Response:
        """Send the request and follow redirects by hand, checking robots.txt at each hop."""
        r = self.session.request(method, url, params=params, headers=headers, data=data,
                                 json=json_body, timeout=TIMEOUT, allow_redirects=False)
        hops = 0
        while r.is_redirect and hops < max_hops:
            nxt = requests.compat.urljoin(r.url, r.headers.get("location", ""))
            if check_robots and not self.allowed(nxt):
                self.log.append({"url": r.url, "status": r.status_code})
                self.log.append({"url": nxt, "status": "robots"})
                raise RobotsDisallowed(nxt, unreachable=self.robots_unreachable(nxt), via=r.url)
            if r.status_code == 303 or (r.status_code in (301, 302) and method != "HEAD"):
                method, data, json_body = "GET", None, None
            self._wait(self._host(nxt), self._crawl_delay(nxt))
            r = self.session.request(method, nxt, headers=headers, data=data, json=json_body,
                                     timeout=TIMEOUT, allow_redirects=False)
            hops += 1
        return r

    def _capture(self, url: str, status: int, text: str) -> None:
        if not self.capture_dir:
            return
        try:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            p = urlsplit(url)
            name = re.sub(r"[^a-zA-Z0-9]+", "_", p.netloc + p.path)[:80]
            h = hashlib.sha1(url.encode()).hexdigest()[:8]
            (self.capture_dir / f"{name}_{h}_{status}.txt").write_text(
                f"URL: {url}\nSTATUS: {status}\n\n{text}", encoding="utf-8"
            )
        except OSError as e:
            log.debug("capture failed: %s", e)


def robots_status(fetcher: Fetcher, url: str) -> int:
    fetcher.robots_for(url)
    return fetcher._robots_status.get(fetcher._host(url), 0)


def env_capture_dir() -> str | None:
    return os.environ.get("CAPTURE_DIR") or None
