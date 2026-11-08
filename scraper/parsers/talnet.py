"""Oleeo tal.net job boards — Morgan Stanley campus (morganstanley.tal.net).

The job board is a server-rendered table, 50 rows per page:
`tr.search_res[data-oppid][data-title]` with `a.subject` (title + offer link)
in the first cell and the city in the second. Next pages are
url + "?start=50", "?start=100"... read only while a page brings new ids and
looks like it has a next page (full page or a start= link), at most
`max_pages`. The host asks for Crawl-delay 10: the fetcher obeys it.

params: {"url": job board URL, "max_pages": 3}
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..http import FetchError, RobotsDisallowed
from ..models import SourceResult
from .base import BaseParser, absolute, clean_text

STEP = 50                                   # rows per page (probes 08/11/2026)
OPP_HREF = re.compile(r"/opp/(\d+)")
START = re.compile(r"[?&]start=(\d+)")


def page_url(url: str, start: int) -> str:
    return url if start == 0 else f"{url}{'&' if '?' in url else '?'}start={start}"


def _partial(res: SourceResult, reason: str, fix: str = "", error: str = "") -> None:
    res.complete = False
    res.status = "partiel"
    if reason not in res.reason:
        res.reason = f"{res.reason} {reason}".strip()
    if fix and fix not in res.fix:
        res.fix = f"{res.fix} {fix}".strip()
    if error:
        res.error = f"{res.error} | {error}".strip(" |")


class Parser(BaseParser):
    name = "talnet"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        url = p.get("url") or source["catalog_url"]
        max_pages = max(1, int(p.get("max_pages") or 3))
        seen: set[str] = set()
        start = 0
        soup = self.soup(url, res)               # page 1: errors propagate
        for n in range(1, max_pages + 1):
            if n > 1:
                try:
                    soup = self.soup(page_url(url, start), res)
                except FetchError as e:
                    if e.status == 404:
                        return res
                    _partial(res, f"La page {n} de la liste n'a pas pu être lue : la lecture est incomplète.",
                             error=f"FetchError: {e}")
                    return res
                except RobotsDisallowed as e:
                    res.blocked_by_robots.append(e.url)
                    _partial(res, f"robots.txt interdit la page {n} de la liste : seule la première partie est lue.")
                    return res
            rows, new = self._add_rows(source, soup, url, res, seen)
            nxt = _next_start(soup, start, rows)
            if not new or nxt is None:
                return res                       # natural end of the list
            start = nxt
        _partial(res, f"Le robot s'est arrêté après {max_pages} pages (limite max_pages) : "
                      "il reste peut-être des offres non lues.",
                 "Augmente max_pages dans les paramètres de la source.")
        return res

    def _add_rows(self, source: dict, soup: BeautifulSoup, base: str, res: SourceResult,
                  seen: set[str]) -> tuple[int, int]:
        """Add the offers of one page; returns (rows on the page, new offers)."""
        rows = _rows(soup)
        added = 0
        for row, link in rows:
            href = link.get("href", "") if link is not None else ""
            m = OPP_HREF.search(href)
            ext_id = clean_text(row.get("data-oppid")) or (m.group(1) if m else "")
            if not ext_id or ext_id in seen:
                continue
            title = clean_text(link.get_text(" ")) if link is not None else ""
            title = title or clean_text(row.get("data-title"))
            if not title or not href:
                continue
            seen.add(ext_id)
            added += 1
            tds = row.find_all("td") if row.name == "tr" else []
            location = clean_text(tds[1].get_text(" ")) if len(tds) >= 2 else ""
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=absolute(base, href), location=location))
        return len(rows), added


def _rows(soup: BeautifulSoup) -> list[tuple[Tag, Tag | None]]:
    """(row, offer link) pairs."""
    rows = soup.select("tr.search_res") or soup.select("tr[data-oppid]")
    out = [(r, r.select_one("a.subject") or r.find("a", href=OPP_HREF)) for r in rows]
    if out:
        return out
    # tolerant fallback (table redesigned): any link to an offer page
    for a in soup.find_all("a", href=OPP_HREF):
        out.append((a.find_parent("tr") or a, a))
    return out


def _next_start(soup: BeautifulSoup, start: int, rows: int) -> int | None:
    """Offset of the next page, or None when this page is the last one."""
    later = sorted({int(m.group(1)) for a in soup.find_all("a", href=START)
                    if (m := START.search(a["href"])) and int(m.group(1)) > start})
    if later:
        return later[0]
    if rows >= STEP:
        return start + STEP
    return None
