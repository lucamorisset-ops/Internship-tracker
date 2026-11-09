"""BNP Paribas careers (group.bnpparibas) — one list page per entity.

Server-rendered: `article.card-offer` cards (title h3, contract div.offer-type,
location div.offer-location) linking to /emploi-carriere/offre-emploi/<slug>
(English site: /en/careers/job-offer/<slug>). No date on the list.

robots.txt forbids query strings (*?q, *?$, *?NumPage...): the robot never
adds one, so only the first page of each list is read. When the page
announces more offers ("N offres") than it shows, complete=False.

params: {"urls": [list URL, ...], "internships_only": true}
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..http import FetchError, RobotsDisallowed
from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text

OFFER_PATH = re.compile(r"/(?:offre-emploi|job-offer)/([^/?#]+)", re.I)
TOTAL = re.compile(
    r"\b(\d{1,3}(?:[  \xa0.]\d{3})+|\d+)\s+(?:offres?|(?:job\s+)?offers?|r[ée]sultats?|results?)\b"
    r"(?!\s+(?:par|per)\s+page)", re.I)

COUNTRIES = {
    "france": "FR",
    "royaume-uni": "GB", "royaume uni": "GB", "united kingdom": "GB", "uk": "GB",
    "angleterre": "GB", "england": "GB",
}


def _partial(res: SourceResult, reason: str, fix: str = "", error: str = "") -> None:
    res.complete = False
    res.status = "partiel"
    if reason not in res.reason:
        res.reason = f"{res.reason} {reason}".strip()
    if fix and fix not in res.fix:
        res.fix = f"{res.fix} {fix}".strip()
    if error:
        res.error = f"{res.error} | {error}".strip(" |")


def announced_total(soup: BeautifulSoup) -> int | None:
    """Number of offers the page says it has ("6 offres"), if shown.

    Looks first in elements whose class names a result count, then in <main>
    (outside the site menu), then in the whole page.
    """
    scopes = soup.find_all(class_=re.compile(r"result|count|total|\bnb", re.I))
    scopes += [soup.find("main"), soup.body or soup]
    for scope in scopes:
        if scope is None:
            continue
        m = TOTAL.search(clean_text(scope.get_text(" ")))
        if m:
            return int(re.sub(r"\D", "", m.group(1)))
    return None


def _no_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _country(location: str) -> str:
    last = location.rsplit(",", 1)[-1] if location else ""
    return COUNTRIES.get(fold(last).strip(), "")


class Parser(BaseParser):
    name = "bnp"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        urls = p.get("urls") or ([p["url"]] if p.get("url") else [source["catalog_url"]])
        if isinstance(urls, str):
            urls = [urls]
        seen: set[str] = set()
        failures: list[Exception] = []
        for url in urls:
            url = _no_query(url)            # robots.txt: no query string, ever
            try:
                soup = self.soup(url, res)
            except (FetchError, RobotsDisallowed) as e:
                failures.append(e)
                if isinstance(e, RobotsDisallowed):
                    res.blocked_by_robots.append(e.url)
                _partial(res, f"Une des listes d'offres n'a pas pu être lue ({e}) : les offres "
                              "qui en viennent ne sont pas marquées comme fermées.",
                         "Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage.",
                         f"{type(e).__name__}: {e}")
                continue
            on_page = self._add_cards(source, soup, url, res, seen)
            total = announced_total(soup)
            if total is not None and total > on_page:
                _partial(res, f"Une liste annonce {total} offres mais la page n'en affiche que {on_page} : "
                              "le robots.txt du site interdit de lire les pages suivantes (paramètres "
                              "d'adresse), les autres offres ne sont pas lues.",
                         "Crée une alerte e-mail sur le site carrières de BNP Paribas pour ne rien manquer.")
        if failures and len(failures) == len(urls):
            raise failures[0]
        return res

    def _add_cards(self, source: dict, soup: BeautifulSoup, base: str, res: SourceResult,
                   seen: set[str]) -> int:
        """Add the offers of one list page; returns how many distinct offers it shows."""
        on_page: set[str] = set()
        for link, card in _cards(soup):
            m = OFFER_PATH.search(link.get("href", ""))
            if not m:
                continue
            ext_id = m.group(1).strip("/").lower()
            h = card.find(["h3", "h2", "h4"])
            title = clean_text((h or link).get_text(" "))
            if not title:
                continue
            on_page.add(ext_id)
            if ext_id in seen:
                continue
            seen.add(ext_id)
            ctype = card.select_one(".offer-type")
            cloc = card.select_one(".offer-location")
            location = clean_text(cloc.get_text(" ")) if cloc else ""
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=_no_query(absolute(base, link["href"])),
                contract=clean_text(ctype.get_text(" ")) if ctype else "",
                location=location, country=_country(location)))
        return len(on_page)


def _cards(soup: BeautifulSoup) -> list[tuple[Tag, Tag]]:
    """(offer link, card element) pairs."""
    out: list[tuple[Tag, Tag]] = []
    for art in soup.select("article.card-offer"):
        a = art.find("a", href=OFFER_PATH)
        if a is not None:
            out.append((a, art))
    if out:
        return out
    # tolerant fallback (page redesigned): any link to an offer page
    for a in soup.find_all("a", href=OFFER_PATH):
        card = a.find_parent(["article", "li"]) or a
        out.append((a, card))
    return out
