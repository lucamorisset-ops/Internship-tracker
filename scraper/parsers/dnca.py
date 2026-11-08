"""DNCA Finance careers (www.dnca-investments.com/carrieres, Next.js server-rendered).

The site's filter link /carrieres?contract=stage lists the internships as

    <li data-role="offer"><a href="/carrieres/VBPXW547">
      <span><span>title</span><span><span>contract</span><span>service</span></span></span>
      <span><span>city</span><span>Publiée le<!-- -->20/10/2026</span></span>
    </a></li>

ext_id = the code after /carrieres/. The service (e.g. "Contrôle des Risques")
goes into the description. Offer pages are server-rendered (generic enrich).

params: {"url": list URL, "internships_only": true}
(internships_only is read by the runner for matching; nothing is filtered here.)
"""
from __future__ import annotations

import re

from bs4 import Tag

from ..models import SourceResult, fold
from .base import BaseParser, absolute, clean_text, parse_date

OFFER_HREF = re.compile(r"^(?:https?://[^/]+)?/carrieres/([A-Za-z0-9]{4,})/?(?:[?#].*)?$")
PUBLISHED = re.compile(r"publi|mise en ligne", re.I)


def _leaves(el: Tag) -> list[str]:
    """Texts of the innermost <span>s, in document order (empty ones dropped)."""
    out = []
    for s in el.find_all("span"):
        if s.find("span") is None:
            t = clean_text(s.get_text(" "))
            if t:
                out.append(t)
    return out


def _is_date(text: str) -> bool:
    return bool(PUBLISHED.search(fold(text))) or (parse_date(text) is not None and len(text) < 30)


def _fields(a: Tag) -> dict:
    """title, contract, service, city, published from the card's spans."""
    leaves = _leaves(a)
    published = next((parse_date(t) for t in leaves if _is_date(t) and parse_date(t)), None)
    top = a.find_all("span", recursive=False)
    if len(top) >= 2:
        first = [t for t in _leaves(top[0]) or [clean_text(top[0].get_text(" "))] if t]
        second = [t for t in _leaves(top[1]) or [clean_text(top[1].get_text(" "))] if t and not _is_date(t)]
        first += [""] * 3
        return {"title": first[0], "contract": first[1], "service": first[2],
                "city": second[0] if second else "", "published": published}
    rest = [t for t in leaves if not _is_date(t)] or [clean_text(a.get_text(" "))]
    rest += [""] * 4
    return {"title": rest[0], "contract": rest[1], "service": rest[2], "city": rest[3],
            "published": published}


class Parser(BaseParser):
    name = "dnca"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        url = self.params(source).get("url") or source["catalog_url"]
        soup = self.soup(url, res)
        links = soup.select('li[data-role=offer] > a[href^="/carrieres/"]')
        if not links:
            # tolerant fallback (markup changed): any link to /carrieres/<code>
            links = [a for a in soup.select("a[href]") if OFFER_HREF.match(a["href"].strip())]
        seen: set[str] = set()
        for a in links:
            m = OFFER_HREF.match(a["href"].strip())
            if not m or m.group(1) in seen:
                continue
            f = _fields(a)
            if not f["title"]:
                continue
            seen.add(m.group(1))
            res.offers.append(self.offer(
                source, ext_id=m.group(1), title=f["title"],
                url=absolute(url, f"/carrieres/{m.group(1)}"),
                location=f["city"], contract=f["contract"], published=f["published"],
                description=f["service"]))
        return res
