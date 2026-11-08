"""Radancy TalentBrew career sites — BlackRock (careers.blackrock.com).

Category pages are server-rendered, 10 offers per page:
`li.section3__search-results-li > a[data-job-id]` with the title in
h2.section3__job-title and labelled info spans ("Location:", "Additional
Locations:", "Team:"). Pages: url, url + "/2", url + "/3"... until a page
brings no new job id (or 404), at most `max_pages`. robots.txt only forbids
/search-jobs/, which is never read. Offer pages carry JSON-LD (generic enrich).

params: {"url": category URL, "max_pages": 4}
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..http import FetchError, RobotsDisallowed
from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text

JOB_HREF = re.compile(r"/job/[^\"'#?]*?/(\d{6,})/?$")


def page_url(url: str, n: int) -> str:
    return url if n == 1 else f"{url.rstrip('/')}/{n}"


def _partial(res: SourceResult, reason: str, fix: str = "", error: str = "") -> None:
    res.complete = False
    res.status = "partiel"
    if reason not in res.reason:
        res.reason = f"{res.reason} {reason}".strip()
    if fix and fix not in res.fix:
        res.fix = f"{res.fix} {fix}".strip()
    if error:
        res.error = f"{res.error} | {error}".strip(" |")


def _country(location: str) -> str:
    t = fold(location)
    if re.search(r"england|scotland|united kingdom|\buk\b", t):
        return "GB"
    if re.search(r"\bfrance\b|ile[- ]de[- ]france", t):
        return "FR"
    return ""


class Parser(BaseParser):
    name = "talentbrew"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        url = p.get("url") or source["catalog_url"]
        max_pages = max(1, int(p.get("max_pages") or 4))
        seen: set[str] = set()
        soup = self.soup(url, res)               # page 1: errors propagate
        new = self._add_cards(source, soup, url, res, seen)
        for n in range(2, max_pages + 1):
            if not new:
                return res                       # natural end
            purl = page_url(url, n)
            try:
                soup = self.soup(purl, res)
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
            new = self._add_cards(source, soup, url, res, seen)
        if new:
            _partial(res, f"Le robot s'est arrêté après {max_pages} pages (limite max_pages) : "
                          "il reste peut-être des offres non lues.",
                     "Augmente max_pages dans les paramètres de la source.")
        return res

    def _add_cards(self, source: dict, soup: BeautifulSoup, base: str, res: SourceResult,
                   seen: set[str]) -> int:
        """Add the offers of one page; returns how many were new."""
        added = 0
        for a in _job_links(soup):
            href = a.get("href", "")
            m = JOB_HREF.search(href.split("?")[0])
            ext_id = clean_text(a.get("data-job-id")) or (m.group(1) if m else "")
            if not ext_id or ext_id in seen or not href:
                continue
            h = a.select_one("h2.section3__job-title") or a.find(["h2", "h3"])
            title = clean_text((h or a).get_text(" "))
            if not title:
                continue
            seen.add(ext_id)
            added += 1
            card = a.find_parent("li") or a
            locations, team = _infos(card)
            location = ", ".join(locations)
            extra = {"team": team} if team else {}
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=absolute(base, href),
                location=location, country=_country(locations[0] if locations else ""),
                extra=extra))
        return added


def _job_links(soup: BeautifulSoup) -> list[Tag]:
    links = [a for a in soup.select("li.section3__search-results-li a[data-job-id]") if a.get("href")]
    if links:
        return links
    # tolerant fallback (page redesigned): job links with an id, or any /job/.../<id> link
    links = [a for a in soup.select("a[data-job-id][href]")]
    if links:
        return links
    return [a for a in soup.find_all("a", href=True) if JOB_HREF.search(a["href"].split("?")[0])]


def _infos(card: Tag) -> tuple[list[str], str]:
    """(locations, team) read from the labelled spans of a card."""
    locations: list[str] = []
    team = ""
    for val in card.select(".section3__job-info"):
        lab = val.find_previous_sibling("span")
        label = fold(lab.get_text(" ")) if lab else ""
        text = clean_text(val.get_text(" "))
        if not text:
            continue
        if "location" in label or "lieu" in label:
            if text not in locations:
                locations.append(text)
        elif "team" in label or "categor" in label:
            team = text
    if not locations:
        # fallback: span.job-location without its "Location:" label
        for span in card.select(".job-location"):
            text = clean_text(span.get_text(" "))
            text = re.sub(r"^(additional\s+)?locations?\s*:\s*", "", text, flags=re.I)
            if text and text not in locations:
                locations.append(text)
    return locations, team
