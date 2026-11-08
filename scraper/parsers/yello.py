"""Yello (recsolu) job board — Deutsche Bank.

https://db.recsolu.com/job_boards/1?locale=en is server-rendered and shows the
25 newest offers of "74 Results" (all regions), so the read is partial
(complete=False) unless the page announces no more results than it shows.

    <li class="search-results__item">
      <a class="search-results__req_title" href="/jobs/wsSne9C62Ef0mymYhfNSyQ?job_board_id=...">title</a>
      <div><span>France</span><span>Paris</span></div>          (country, then city)
      <div class="search-results__post-time">3d</div>             (relative age)
    </li>

ext_id = the token after /jobs/; url = absolute offer URL without the query.

params: {"url": job board URL}
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import Tag

from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text, parse_relative_age

JOB_PATH = re.compile(r"/jobs/([^/?#]+)")
RESULTS = re.compile(r"\b(\d{1,5})\s+results?\b", re.I)
COUNTRIES = {
    "france": "FR", "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "royaume-uni": "GB", "germany": "DE", "luxembourg": "LU", "switzerland": "CH",
    "belgium": "BE", "ireland": "IE", "netherlands": "NL", "spain": "ES", "italy": "IT",
    "united states": "US", "united states of america": "US", "usa": "US", "india": "IN",
    "singapore": "SG", "hong kong": "HK", "japan": "JP",
}


def _text(el: Tag | None) -> str:
    return clean_text(el.get_text(" ")) if el is not None else ""


def _pairs(soup) -> list[tuple[Tag, Tag]]:
    """(card, title link) pairs."""
    out = []
    for li in soup.select("li.search-results__item"):
        a = li.select_one("a.search-results__req_title") or li.select_one('a[href*="/jobs/"]')
        if a is not None:
            out.append((li, a))
    if not out:
        # tolerant fallback (markup changed): any link to /jobs/<token>
        for a in soup.select('a[href*="/jobs/"]'):
            out.append((a.find_parent("li") or a.parent, a))
    return out


def _place(card: Tag) -> list[str]:
    spans = card.select(".search-results__jobinfo div span")
    if not spans:
        spans = [s for s in card.find_all("span")
                 if s.find_parent("a") is None and s.find("span") is None]
    return [t for t in (_text(s) for s in spans) if t]


class Parser(BaseParser):
    name = "yello"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        url = self.params(source).get("url") or source["catalog_url"]
        soup = self.soup(url, res)
        seen: set[str] = set()
        for card, a in _pairs(soup):
            href = absolute(url, a.get("href") or "")
            parts = urlsplit(href)
            m = JOB_PATH.search(parts.path)
            title = _text(a)
            if not m or m.group(1) in seen or not title:
                continue
            seen.add(m.group(1))
            place = _place(card)                      # [country, city] on this board
            label = _text(card.select_one(".search-results__post-time"))
            res.offers.append(self.offer(
                source, ext_id=m.group(1), title=title,
                url=urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                location=", ".join(reversed(place)),
                country=COUNTRIES.get(fold(place[0]).strip(), "") if place else "",
                published=parse_relative_age(label, self.ctx.today) if label else None,
                published_label=label))
        m = RESULTS.search(clean_text(soup.get_text(" ")))
        total = int(m.group(1)) if m else None
        # only the newest offers are listed: never close the others, unless the
        # board says it has no more results than the ones read
        res.complete = total is not None and total <= len(res.offers)
        return res
