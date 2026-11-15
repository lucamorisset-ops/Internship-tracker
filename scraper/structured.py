"""Structured-data extraction of schema.org JobPosting from a careers page.

Reads JobPosting objects across syntaxes and returns normalized dicts:

    {"title", "url", "location", "contract", "published", "description", "syntax"}

Priority on duplicates (same URL): JSON-LD > Microdata > RDFa > Microformats.
OpenGraph never creates an offer; it only fills a missing title or description.

Works with pure lxml/bs4 (JSON-LD, Microdata, OpenGraph). When `extruct` is
installed, RDFa and Microformats are added too — it stays optional so the robot
never breaks if extruct cannot be built on the host.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .parsers.base import clean_text, iso_to_date, jsonld_jobpostings

_JOBPOSTING_TYPE = re.compile(r"(?:^|/)JobPosting$", re.I)


# ------------------------------------------------------------------ normalization
def _employment(et: Any) -> str:
    if isinstance(et, list):
        return ", ".join(clean_text(str(x)) for x in et if x)
    return clean_text(str(et or ""))


def _address_text(addr: Any) -> str:
    if isinstance(addr, str):
        return clean_text(addr)
    if not isinstance(addr, dict):
        return ""
    parts = [addr.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
    return clean_text(", ".join(str(p) for p in parts if p and isinstance(p, str)))


def _location_of(j: dict) -> str:
    loc = j.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc]
    out: list[str] = []
    for l in locs:
        if isinstance(l, dict):
            txt = _address_text(l.get("address") or l)
        elif isinstance(l, str):
            txt = clean_text(l)
        else:
            txt = ""
        if txt and txt not in out:
            out.append(txt)
    return " ; ".join(out)


def _posting(j: dict, base_url: str, syntax: str) -> dict | None:
    title = clean_text(j.get("title") or j.get("name") or "")
    if not title:
        return None
    u = j.get("url") or j.get("sameAs") or ""
    url = urljoin(base_url, u) if isinstance(u, str) and u else base_url
    return {
        "title": title,
        "url": url,
        "location": _location_of(j),
        "contract": _employment(j.get("employmentType")),
        "published": iso_to_date(j.get("datePosted")),
        "description": clean_text(j.get("description") or "")[:4000],
        "syntax": syntax,
    }


# ------------------------------------------------------------------ microdata (pure lxml)
def microdata_jobpostings(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    out: list[dict] = []
    for scope in soup.find_all(attrs={"itemtype": _JOBPOSTING_TYPE}):
        props: dict[str, Any] = {}
        for el in scope.find_all(attrs={"itemprop": True}):
            name = el.get("itemprop")
            if name in props:
                continue
            if el.get("content"):
                val: Any = el["content"]
            elif el.get("datetime"):
                val = el["datetime"]
            elif el.name in ("a", "link") and el.get("href"):
                val = urljoin(base_url, el["href"])
            elif el.name in ("img", "meta") and el.get("src"):
                val = el["src"]
            else:
                val = clean_text(el.get_text(" "))
            props[name] = val
        j = {
            "title": props.get("title") or props.get("name"),
            "url": props.get("url"),
            "employmentType": props.get("employmentType"),
            "datePosted": props.get("datePosted"),
            "description": props.get("description"),
            "jobLocation": props.get("jobLocation") or props.get("addressLocality"),
        }
        p = _posting(j, base_url, "microdata")
        if p:
            out.append(p)
    return out


# ------------------------------------------------------------------ opengraph (fallback only)
def opengraph(html: str) -> dict:
    soup = BeautifulSoup(html or "", "lxml")
    out: dict[str, str] = {}
    for tag in soup.find_all("meta", property=re.compile(r"^og:(title|description)$")):
        key = tag.get("property").split(":", 1)[1]
        if tag.get("content") and key not in out:
            out[key] = clean_text(tag["content"])
    return out


# ------------------------------------------------------------------ extruct (optional: RDFa, Microformats)
def _extruct_jobpostings(html: str, base_url: str) -> list[dict]:
    try:
        import extruct
    except Exception:  # noqa: BLE001 - optional dependency
        return []
    try:
        data = extruct.extract(html, base_url=base_url, uniform=True,
                               syntaxes=["rdfa", "microformat"])
    except Exception:  # noqa: BLE001 - never break a read because extruct choked
        return []
    out: list[dict] = []
    for syntax in ("rdfa", "microformat"):
        for obj in data.get(syntax) or []:
            if not isinstance(obj, dict):
                continue
            t = obj.get("@type") or obj.get("type")
            types = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and _JOBPOSTING_TYPE.search(x) for x in types):
                p = _posting(obj, base_url, syntax)
                if p:
                    out.append(p)
    return out


# ------------------------------------------------------------------ public API
def structured_jobpostings(html: str, base_url: str) -> list[dict]:
    """All JobPosting found on the page, deduplicated by URL in priority order.

    JSON-LD wins over Microdata over RDFa/Microformats; OpenGraph then fills a
    missing title or description on the page-level, never creating a new offer.
    """
    found: dict[str, dict] = {}
    for items in (
        [p for j in jsonld_jobpostings(html) if (p := _posting(j, base_url, "json-ld"))],
        microdata_jobpostings(html, base_url),
        _extruct_jobpostings(html, base_url),
    ):
        for it in items:
            found.setdefault(it["url"], it)
    postings = list(found.values())
    og = opengraph(html)
    for p in postings:
        if not p["description"] and og.get("description"):
            p["description"] = og["description"]
    return postings


def extra_structured_jobpostings(html: str, base_url: str) -> list[dict]:
    """JobPosting from Microdata and (optionally) RDFa/Microformats only.

    Used by the generic reader, which already has its own JSON-LD pass: this adds
    the other syntaxes without duplicating it.
    """
    found: dict[str, dict] = {}
    for items in (microdata_jobpostings(html, base_url), _extruct_jobpostings(html, base_url)):
        for it in items:
            found.setdefault(it["url"], it)
    return list(found.values())
