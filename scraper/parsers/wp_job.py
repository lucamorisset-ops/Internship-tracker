"""WordPress REST `job` endpoint — Mirova on recrutement.natixis.com.

    GET {api}?search=stage&per_page=100&page=1&_fields=id,date,title,link,class_list
    headers X-WP-Total / X-WP-TotalPages

params:
    api       "https://recrutement.natixis.com/app/wp-json/wp/v2/job"
    searches  ["stage", "internship"]  one query each, merged by WP id
    brands    ["tax_brands-mirova", "tax_brands-mirova-us"]  class_list entries to keep
              (empty -> keep every item)

robots.txt of the site allows /app/wp-json/ and /job/ (offer pages, read by the
generic enrich of BaseParser).
"""
from __future__ import annotations

import html
from urllib.parse import quote

from ..models import Offer, SourceResult
from ._api import JSON_HEADERS, decode_json, header
from .base import BaseParser, clean_text, iso_to_date

PER_PAGE = 100
MAX_PAGES = 10
FIELDS = "id,date,title,link,class_list"

CONTRACTS = {"stage": "Stage", "cdi": "CDI", "cdd": "CDD", "vie": "VIE", "vi": "VI",
             "alternance": "Alternance", "apprentissage": "Apprentissage", "internship": "Internship",
             "interim": "Intérim", "freelance": "Freelance"}
COUNTRIES = {"france": "FR", "royaume-uni": "GB", "united-kingdom": "GB", "uk": "GB",
             "etats-unis": "US", "united-states": "US", "usa": "US", "luxembourg": "LU",
             "allemagne": "DE", "germany": "DE", "belgique": "BE", "suisse": "CH", "espagne": "ES",
             "italie": "IT", "pays-bas": "NL", "irlande": "IE", "portugal": "PT", "singapour": "SG",
             "hong-kong": "HK", "japon": "JP", "australie": "AU", "canada": "CA",
             "emirats-arabes-unis": "AE", "chine": "CN", "inde": "IN"}
_SMALL = {"le", "la", "les", "de", "du", "des", "d", "l", "sur", "sous", "en", "et", "aux", "au"}


def _terms(class_list: list[str], prefix: str) -> list[str]:
    return [c[len(prefix):] for c in class_list if c.startswith(prefix) and len(c) > len(prefix)]


def _place(slug: str) -> str:
    """'paris' -> 'Paris', 'charenton-le-pont' -> 'Charenton-le-Pont'."""
    parts = slug.split("-")
    return "-".join(w if (i and w in _SMALL) else w.capitalize() for i, w in enumerate(parts))


def _contract(slug: str) -> str:
    return CONTRACTS.get(slug) or slug.replace("-", " ").capitalize()


class Parser(BaseParser):
    name = "wp_job"
    method = "api"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        api = str(p["api"])
        sep = "&" if "?" in api else "?"
        searches = [s for s in (p.get("searches") or []) if s is not None] or [""]
        brands = [b for b in (p.get("brands") or []) if b]

        found: dict[str, Offer] = {}
        for search in searches:
            page = 1
            while True:
                q = f"search={quote(str(search))}&" if search else ""
                url = f"{api}{sep}{q}per_page={PER_PAGE}&page={page}&_fields={FIELDS}"
                r = self.get(url, res, headers=JSON_HEADERS)
                items = decode_json(r)
                if not isinstance(items, list) or not items:
                    break
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    cl = [str(c) for c in (it.get("class_list") or [])]
                    if isinstance(it.get("class_list"), dict):      # older WP: {"0": "post-1", ...}
                        cl = [str(c) for c in it["class_list"].values()]
                    if brands and not any(b in cl for b in brands):
                        continue
                    off = self._offer(source, it, cl)
                    if off is not None:
                        found.setdefault(off.ext_id, off)
                try:
                    total_pages = int(header(r.headers, "X-WP-TotalPages") or 1)
                except ValueError:
                    total_pages = 1
                if page >= total_pages:
                    break
                if page >= MAX_PAGES:
                    res.complete = False
                    break
                page += 1

        res.offers = list(found.values())
        return res

    def _offer(self, source: dict, it: dict, cl: list[str]) -> Offer | None:
        wp_id = it.get("id")
        link = it.get("link") or ""
        if wp_id in (None, "") or not link:
            return None
        t = it.get("title")
        raw = t.get("rendered") if isinstance(t, dict) else t
        title = html.unescape(clean_text(raw or ""))
        cities = [_place(c) for c in _terms(cl, "tax_city-")] or [_place(c) for c in _terms(cl, "tax_place-")]
        countries = [COUNTRIES.get(c, "") for c in _terms(cl, "tax_country-")]
        return self.offer(
            source,
            ext_id=str(wp_id),
            title=title,
            url=link,
            published=iso_to_date(it.get("date")),
            contract=", ".join(_contract(c) for c in _terms(cl, "tax_contract-")),
            location=", ".join(cities),
            country=next((c for c in countries if c), ""),
            extra={"brands": _terms(cl, "tax_brands-")},
        )
