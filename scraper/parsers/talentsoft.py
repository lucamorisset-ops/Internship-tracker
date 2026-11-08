"""Talentsoft (Cegid) career sites — Amundi (jobs.amundi.com).

The list page is server-rendered: one `li.ts-offer-list-item` per offer, with
the title link and a description list [contract, entity, country, city].
There is no publication date on the list (the offer page has it: generic
enrich). Pages 2, 3... are read with `&page=N` until a page brings no new
offer (or the site answers 404), at most `max_pages` pages per list.

params: {"urls": [list URL, ...], "max_pages": 4}
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..http import FetchError, RobotsDisallowed
from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text

OFFER_HREF = re.compile(r"_(\d+)\.aspx", re.I)
PAGE_SIZE = 50          # offers per list page seen on jobs.amundi.com (probes 08/11/2026)

COUNTRIES = {
    "france": "FR",
    "royaume-uni": "GB", "royaume uni": "GB", "united kingdom": "GB", "uk": "GB",
    "angleterre": "GB", "england": "GB",
}


def country_code(text: str) -> str:
    return COUNTRIES.get(fold(text).strip(), "")


def page_url(url: str, n: int) -> str:
    return f"{url}{'&' if '?' in url else '?'}page={n}"


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
    name = "talentsoft"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        urls = p.get("urls") or ([p["url"]] if p.get("url") else [source["catalog_url"]])
        max_pages = max(1, int(p.get("max_pages") or 4))
        seen: set[str] = set()
        failures: list[Exception] = []
        for url in urls:
            try:
                self._read_list(source, url, max_pages, res, seen)
            except (FetchError, RobotsDisallowed) as e:
                failures.append(e)
                if isinstance(e, RobotsDisallowed):
                    res.blocked_by_robots.append(e.url)
                _partial(res, f"Une des listes d'offres n'a pas pu être lue ({e}) : les offres "
                              "qui en viennent ne sont pas marquées comme fermées.",
                         "Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage.",
                         f"{type(e).__name__}: {e}")
        if failures and len(failures) == len(urls):
            raise failures[0]
        return res

    # ------------------------------------------------------------------
    def _read_list(self, source: dict, url: str, max_pages: int, res: SourceResult,
                   seen: set[str]) -> None:
        soup = self.soup(url, res)          # page 1: errors propagate
        first_ids = self._add_cards(source, soup, url, res, seen)
        prev_ids = first_ids
        for n in range(2, max_pages + 1):
            purl = page_url(url, n)
            try:
                soup = self.soup(purl, res)
            except FetchError as e:
                if e.status == 404:          # no such page: end of the list
                    return
                _partial(res, f"La page {n} de la liste n'a pas pu être lue : la lecture est incomplète.",
                         error=f"FetchError: {e}")
                return
            except RobotsDisallowed as e:
                res.blocked_by_robots.append(e.url)
                _partial(res, f"robots.txt interdit la page {n} de la liste : seule la première partie est lue.")
                return
            before = len(seen)
            page_ids = self._add_cards(source, soup, url, res, seen)
            if len(seen) == before:
                if n == 2 and page_ids and page_ids == first_ids and len(first_ids) >= PAGE_SIZE:
                    # a full page served again for page=2: the site ignored the page number
                    _partial(res, "La page 2 de la liste renvoie les mêmes offres que la page 1 : "
                                  "la pagination du site n'a pas été reconnue, la lecture est sans doute incomplète.",
                             "Le lecteur doit être corrigé dans le code (dossier scraper/parsers).")
                return                        # natural end of the list
            prev_ids = page_ids
        if prev_ids:
            _partial(res, f"Le robot s'est arrêté après {max_pages} pages (limite max_pages) : "
                          "il reste peut-être des offres non lues.",
                     "Augmente max_pages dans les paramètres de la source.")

    def _add_cards(self, source: dict, soup: BeautifulSoup, base: str, res: SourceResult,
                   seen: set[str]) -> list[str]:
        """Add the offers of one page; returns the ext_ids found on it (in order)."""
        ids: list[str] = []
        for link, parts, ref in _cards(soup):
            m = OFFER_HREF.search(link.get("href", ""))
            if not m:
                continue
            ext_id = m.group(1)
            if ext_id in ids:
                continue
            ids.append(ext_id)
            if ext_id in seen:
                continue
            title = clean_text(link.get_text(" ")) or clean_text(link.get("title"))
            if not title:
                continue
            seen.add(ext_id)
            contract, entity, country_txt, city = _describe(parts)
            location = ", ".join(x for x in (city, country_txt) if x)
            extra = {k: v for k, v in (("entity", entity), ("reference", ref)) if v}
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=absolute(base, link["href"]),
                contract=contract, location=location, country=country_code(country_txt),
                extra=extra))
        return ids


def _cards(soup: BeautifulSoup) -> list[tuple[Tag, list[str], str]]:
    """(title link, description texts, reference) for each offer card."""
    out: list[tuple[Tag, list[str], str]] = []
    items = soup.select("li.ts-offer-list-item")
    for li in items:
        a = li.select_one("a.ts-offer-list-item__title-link")
        if a is None or not OFFER_HREF.search(a.get("href", "")):
            a = next((x for x in li.find_all("a", href=OFFER_HREF)
                      if "liste-offres" not in x["href"]), None)
        if a is None:
            continue
        ul = li.select_one("ul.ts-offer-list-item__description")
        parts = [clean_text(x.get_text(" ")) for x in ul.find_all("li")] if ul else []
        fav = li.select_one("[data-reference]")
        ref = clean_text(fav.get("data-reference")) if fav else clean_text(a.get("title"))
        out.append((a, parts, ref))
    if out:
        return out
    # tolerant fallback (page redesigned): any link to an offer page
    for a in soup.find_all("a", href=OFFER_HREF):
        if "liste-offres" in a["href"]:
            continue
        li = a.find_parent("li")
        ul = li.find("ul") if li else None
        parts = [clean_text(x.get_text(" ")) for x in ul.find_all("li")] if ul else []
        out.append((a, parts, clean_text(a.get("title"))))
    return out


def _describe(parts: list[str]) -> tuple[str, str, str, str]:
    """[contract, entity, country, city] -> (contract, entity, country, city), tolerant."""
    parts = [x for x in parts if x]
    if len(parts) >= 4:
        return parts[0], parts[1], parts[2], parts[3]
    country = next((x for x in parts if country_code(x)), "")
    rest = [x for x in parts if x != country]
    contract = rest[0] if rest else ""
    city = rest[-1] if len(rest) >= 2 else ""
    entity = rest[1] if len(rest) >= 3 else ""
    return contract, entity, country, city
