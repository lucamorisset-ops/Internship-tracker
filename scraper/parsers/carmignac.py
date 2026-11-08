"""Carmignac careers page (needs a browser).

https://www.carmignac.com/en-fr/about-us/careers: a plain GET returns a
244-byte JavaScript redirect ("This website requires JS enabled and cookies"),
so the page is opened directly in the headless browser (no stealth trick: if
the browser is refused too, the FetchError propagates and the runner reports
the source as resisting).

The rendered page has one table "Open Positions":

    <table><thead>Job Title | Contract | Location</thead>
      <tbody><tr><td>Equity Product Specialist</td><td>Permanent</td><td>London</td></tr></tbody></table>

No link per row (applications by e-mail): url = the careers page,
ext_id = slug(title + "-" + location). Nothing more to read: detail_pages = False.

params: {"url": careers page URL}
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..models import SourceResult, slugify
from .base import BaseParser, absolute, clean_text

TITLE_HEAD = re.compile(r"job title|intitul|^\s*(poste|position|title)\s*$", re.I)
CONTRACT_HEAD = re.compile(r"contract|contrat|type", re.I)
LOCATION_HEAD = re.compile(r"location|lieu|localisation|city|ville|office", re.I)


def _text(el: Tag | None) -> str:
    return clean_text(el.get_text(" ")) if el is not None else ""


def _headers(table: Tag) -> list[str]:
    cells = table.select("thead th") or table.select("thead td")
    if not cells:
        first = table.find("tr")
        cells = first.find_all(["th", "td"]) if first is not None else []
    return [_text(c) for c in cells]


def _offer_table(soup: BeautifulSoup) -> tuple[Tag | None, dict[str, int]]:
    """The table whose header contains "Job Title", with its column indexes."""
    for table in soup.find_all("table"):
        heads = _headers(table)
        if not any(TITLE_HEAD.search(h) for h in heads):
            continue
        cols = {"title": 0, "contract": 1, "location": 2}
        for key, rx in (("title", TITLE_HEAD), ("contract", CONTRACT_HEAD), ("location", LOCATION_HEAD)):
            idx = next((i for i, h in enumerate(heads) if rx.search(h)), None)
            if idx is not None:
                cols[key] = idx
        return table, cols
    return None, {}


class Parser(BaseParser):
    name = "carmignac"
    method = "navigateur"
    detail_pages = False          # no offer page: the table is all there is

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        url = self.params(source).get("url") or source["catalog_url"]
        html, _ = self.render(url, res, wait_for="table")   # FetchError propagates (résiste)
        soup = BeautifulSoup(html, "lxml")
        table, cols = _offer_table(soup)
        if table is None:
            res.complete = False
            res.status = "partiel"
            res.reason = ("La page carrières de Carmignac s'est affichée mais sans le tableau des postes "
                          "(colonne « Job Title ») : soit aucun poste n'est ouvert, soit la page a changé. "
                          "Aucune offre n'est marquée comme fermée.")
            res.fix = "À vérifier : ouvre la page carrières avec le bouton de la source."
            return res
        rows = table.select("tbody tr") or table.find_all("tr")[1:]
        seen: set[str] = set()
        for tr in rows:
            cells = tr.find_all("td")
            if not cells:
                continue

            def cell(key: str) -> str:
                i = cols[key]
                return _text(cells[i]) if i < len(cells) else ""

            title, location = cell("title"), cell("location")
            ext_id = slugify(f"{title}-{location}")
            if not title or ext_id in seen:
                continue
            seen.add(ext_id)
            link = next((a["href"] for a in tr.find_all("a", href=True)
                         if not a["href"].lower().startswith(("mailto:", "tel:", "#", "javascript:"))), None)
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title, url=absolute(url, link) if link else url,
                location=location, contract=cell("contract")))
        return res
