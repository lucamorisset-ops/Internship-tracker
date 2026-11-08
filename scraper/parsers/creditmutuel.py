"""Crédit Mutuel group recruitment site — La Française / Crédit Mutuel AM.

recrutement.creditmutuel.fr/fr/nos_offres.html?socs=... is server-rendered
and shows only the 15 most recent offers of the selected entities, so the
read is always partial (complete=False: missing offers are not closed).
robots.txt forbids the paging parameters (_tabi=, _pid=, _fid=): page 1 only.

Card: li.item > a[href*="offre.html?annonce="] (title) and
ul.ei_listdescription li = [location, contract, "Date de publication : dd/mm/yyyy"].

params: {"url": list URL}
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text, parse_date

ANNONCE_HREF = re.compile(r"offre\.html\?(?:[^\"'#]*&)?annonce=\d+", re.I)
CONTRACT = re.compile(r"\b(stage|stagiaire|cdi|cdd|alternance|alternant|apprenti\w*|interim|"
                      r"v\.?i\.?e|internship|freelance|contrat)\b", re.I)
DEPARTMENT = re.compile(r"\(\s*(\d{2}|2[ab]|97\d)\s*\)", re.I)


def _annonce(href: str) -> str:
    q = parse_qs(urlsplit(href).query)
    v = (q.get("annonce") or [""])[0]
    m = re.match(r"\d+", v)
    return m.group(0) if m else ""


class Parser(BaseParser):
    name = "creditmutuel"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        url = p.get("url") or source["catalog_url"]
        soup = self.soup(url, res)
        seen: set[str] = set()
        for link, card in _cards(soup):
            ext_id = _annonce(link["href"])
            title = clean_text(link.get_text(" "))
            if not ext_id or ext_id in seen or not title:
                continue
            seen.add(ext_id)
            location, contract, published = _describe(card)
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=absolute(url, link["href"]),
                location=location, contract=contract, published=published,
                country="FR" if DEPARTMENT.search(location) else ""))
        # the site only lists the 15 most recent offers: never close the others
        res.complete = False
        return res


def _cards(soup: BeautifulSoup) -> list[tuple[Tag, Tag]]:
    """(title link, card) pairs."""
    out: list[tuple[Tag, Tag]] = []
    for li in soup.select("li.item"):
        a = li.find("a", href=ANNONCE_HREF)
        if a is not None:
            out.append((a, li))
    if out:
        return out
    # tolerant fallback (page redesigned): any link to an offer page
    for a in soup.find_all("a", href=ANNONCE_HREF):
        card = a.find_parent("li", class_="item") or a.find_parent(["li", "article", "div"]) or a
        out.append((a, card))
    return out


def _describe(card: Tag):
    """(location, contract, published date) from the card's description list."""
    ul = card.select_one("ul.ei_listdescription")
    items = ul.find_all("li", recursive=False) if ul else []
    if not items and card.name != "a":
        items = [li for li in card.find_all("li") if li.find("a", href=ANNONCE_HREF) is None]
    location = contract = ""
    published = None
    for li in items:
        text = clean_text(li.get_text(" "))
        if not text:
            continue
        if re.search(r"publi", fold(text)):
            published = published or parse_date(text)
        elif not contract and CONTRACT.search(fold(text)):
            contract = text
        elif not location:
            location = text
    return location, contract, published
