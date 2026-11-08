"""Contract shared by every parser.

A parser is a class named `Parser` in its own module of scraper/parsers/,
registered in scraper/parsers/__init__.py under the name stored in
`sources.kind`. It reads ONE source and returns a SourceResult:

    class Parser(BaseParser):
        name = "talentsoft"
        method = "html"            # api / html / navigateur / veille
        def read(self, source):    # source = row of the `sources` table (dict)
            res = self.result(source)
            soup = self.soup(url, res)          # records url in res.urls_read
            res.offers.append(self.offer(source, ext_id=..., title=..., url=...))
            return res

Rules for parsers:
  * read only the official catalogue URLs (source["catalog_url"] and
    source["params"]), through self.get / self.soup / self.json / self.render,
    which obey robots.txt and delays; never call requests directly;
  * fill what the list page gives (title, url, location, contract, published
    date, short description); the runner enriches new offers from their detail
    page afterwards (JSON-LD JobPosting, publication date, start date);
  * set res.complete = False when only part of the catalogue is read (e.g. the
    15 newest offers), so that missing offers are not marked as closed;
  * raise nothing for "no offer": an empty list with ok=True is a valid result;
    RobotsDisallowed / FetchError may propagate, the runner turns them into a
    "site qui résiste" with a French explanation.
"""
from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Fetcher, FetchError, Response, looks_like_challenge
from ..models import Offer, SourceResult, slugify


@dataclass
class Context:
    fetcher: Fetcher
    browser: Any = None          # scraper.browser.LazyBrowser (or None in tests)
    today: date = field(default_factory=date.today)


class BaseParser:
    name = "base"
    method = "html"
    detail_pages = True          # runner may open offer pages to enrich new offers

    def __init__(self, ctx: Context):
        self.ctx = ctx

    # ------------------------------------------------------------ helpers
    def result(self, source: dict) -> SourceResult:
        return SourceResult(source_id=source["id"], ok=True, method=self.method)

    def params(self, source: dict) -> dict:
        p = source.get("params") or {}
        if isinstance(p, str):
            p = json.loads(p or "{}")
        return p

    def get(self, url: str, res: SourceResult, **kw) -> Response:
        r = self.ctx.fetcher.get(url, **kw)
        res.urls_read.append(_shown_url(url, kw.get("params")))
        return r

    def soup(self, url: str, res: SourceResult, **kw) -> BeautifulSoup:
        r = self.get(url, res, **kw)
        return BeautifulSoup(r.text, "lxml")

    def json(self, url: str, res: SourceResult, **kw) -> Any:
        headers = {"Accept": "application/json", **(kw.pop("headers", None) or {})}
        r = self.get(url, res, headers=headers, **kw)
        try:
            return r.json()
        except ValueError:
            detail = "page anti-robot" if looks_like_challenge(r.text, r.status) else "réponse qui n'est pas du JSON"
            raise FetchError(url, r.status, detail) from None

    def detail_get(self, url: str, res: SourceResult, **kw) -> Response:
        """GET an offer page for enrich(): records it in res.details_read."""
        r = self.ctx.fetcher.get(url, **kw)
        res.details_read.append(url)
        return r

    def render(self, url: str, res: SourceResult, **kw) -> tuple[str, Any]:
        if self.ctx.browser is None:
            raise RuntimeError("navigateur indisponible")
        out = self.ctx.browser.render(url, **kw)
        res.urls_read.append(url)
        return out

    def offer(self, source: dict, **kw) -> Offer:
        kw.setdefault("company", source.get("company", ""))
        if not kw.get("ext_id"):
            kw["ext_id"] = slugify(kw.get("url") or kw.get("title", ""))
        kw["ext_id"] = str(kw["ext_id"])
        kw["title"] = clean_text(kw.get("title", ""))
        for k in ("location", "contract", "description", "published_label"):
            if kw.get(k):
                kw[k] = clean_text(kw[k])
        return Offer(source_id=source["id"], **kw)

    def read(self, source: dict) -> SourceResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def enrich(self, offer: Offer, res: SourceResult) -> None:
        """Complete a NEW offer from its detail page (generic: JSON-LD, then page text).

        Parsers whose detail pages need JavaScript or have an API override this.
        Fills only what is missing: published date, description, contract, location.
        """
        if not self.detail_pages or not offer.url:
            return
        r = self.detail_get(offer.url, res, retries=1)
        fill_from_detail_html(offer, r.text)


def fill_from_detail_html(offer: Offer, html: str) -> None:
    jobs = jsonld_jobpostings(html)
    if jobs:
        j = jobs[0]
        if not offer.published:
            offer.published = iso_to_date(j.get("datePosted"))
        if not offer.description and j.get("description"):
            offer.description = clean_text(j["description"])[:4000]
        et = j.get("employmentType")
        if not offer.contract and et:
            offer.contract = clean_text(", ".join(et) if isinstance(et, list) else str(et))
        if not offer.location:
            loc = j.get("jobLocation")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            if isinstance(loc, dict):
                a = loc.get("address") or {}
                if isinstance(a, dict):
                    offer.location = clean_text(", ".join(
                        str(a.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")
                        if a.get(k) and isinstance(a.get(k), str)))
        if offer.description:
            return
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "svg"]):
        t.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = clean_text(main.get_text(" "))
    if not offer.published:
        m = re.search(r"(publi\w*|posted|mise en ligne|date de publication)\D{0,25}"
                      r"(\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2}|20\d{2}-\d{2}-\d{2})", text, re.I)
        if m:
            offer.published = parse_date(m.group(2))
    if not offer.description:
        offer.description = text[:4000]


# ------------------------------------------------------------ text utils
def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = _html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def absolute(base: str, href: str) -> str:
    return urljoin(base, href)


_FR_DATE = re.compile(r"\b([0-3]?\d)[/.\-]([01]?\d)[/.\-](20\d{2})\b")
_ISO_DATE = re.compile(r"\b(20\d{2})-([01]\d)-([0-3]\d)")


def parse_date(text: str | None) -> date | None:
    """Accepts 2026-11-06, 2026-11-06T17:10:14, 06/11/2026, 6.11.2026."""
    if not text:
        return None
    m = _ISO_DATE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _FR_DATE.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def parse_relative_age(label: str, today: date) -> date | None:
    """'3d', '2 days ago', 'il y a 5 jours', '1w', 'today' -> date."""
    from datetime import timedelta

    t = (label or "").strip().lower()
    if t in ("today", "aujourd'hui", "0d", "new"):
        return today
    if t in ("yesterday", "hier"):
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\s*(d|day|days|j|jour|jours|w|week|weeks|sem|semaine|semaines|m|mo|month|months|mois)\b", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit.startswith(("d", "j")):
        return today - timedelta(days=n)
    if unit.startswith(("w", "s")):
        return today - timedelta(weeks=n)
    return today - timedelta(days=30 * n)


def _shown_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    from urllib.parse import urlencode

    return url + ("&" if "?" in url else "?") + urlencode(params)


def jsonld_jobpostings(html: str) -> list[dict]:
    """All schema.org JobPosting objects found in JSON-LD scripts."""
    out: list[dict] = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, json.JSONDecodeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if d.get("@type") == "JobPosting" or (isinstance(d.get("@type"), list) and "JobPosting" in d["@type"]):
                    out.append(d)
                for k in ("@graph", "itemListElement", "item"):
                    v = d.get(k)
                    if isinstance(v, list):
                        stack.extend(v)
                    elif isinstance(v, dict):
                        stack.append(v)
            elif isinstance(d, list):
                stack.extend(d)
    return out


def iso_to_date(v: Any) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        return parse_date(str(v))
