"""Discover individual offer pages from a site's sitemap or RSS/Atom feed (brief §5).

Some official sites list their offers only on the careers page via JavaScript, but
expose each offer as its own URL in `sitemap.xml` (declared in robots.txt) or in an
RSS/Atom feed. This module finds those offer URLs so the generic reader can open them
and read their structured data (JSON-LD JobPosting).

Pure parsing (sitemap index, urlset, RSS, Atom, URL filtering) is unit-tested; the
`collect_offer_pages` driver fetches through the polite client (robots.txt, delays)
and is bounded (a handful of sitemaps, a capped number of offer URLs).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from .parsers.generic import is_intermediary

_SITEMAP_LINE = re.compile(r"(?im)^\s*Sitemap:\s*(\S+)\s*$")
# an offer-page URL: an offer word in the path (singular or plural, FR/EN)
_OFFER_PATH = re.compile(
    r"/(jobs?|offres?|offers?|postes?|positions?|stages?|stagiaire|intern(?:ship)?|careers?|"
    r"carrieres?|emplois?|vacanc\w*|opportunit\w*|recrutement|job-offer|job-posting)([/_-]|$)", re.I)
_ASSET = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|css|js|pdf|zip|mp4|xml|rss)$", re.I)
_LIST_TAIL = re.compile(r"/(jobs?|offres?|offers?|careers?|carrieres?|emplois?|stages?|recrutement|"
                        r"opportunit\w*|positions?|vacancies)/?$", re.I)
MAX_SITEMAPS = 5
MAX_OFFER_URLS = 20


def sitemaps_in_robots(text: str) -> list[str]:
    """The `Sitemap:` URLs declared in a robots.txt body."""
    return [m.strip() for m in _SITEMAP_LINE.findall(text or "")]


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """(child_sitemaps, page_urls) from a sitemap index or a urlset."""
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError:
        return [], []
    sitemaps: list[str] = []
    pages: list[str] = []
    root_name = _localname(root.tag)
    for el in root.iter():
        if _localname(el.tag) != "loc" or not (el.text and el.text.strip()):
            continue
        loc = el.text.strip()
        # inside <sitemapindex> every <loc> is a child sitemap; inside <urlset> it is a page
        parent_is_index = root_name == "sitemapindex"
        (sitemaps if parent_is_index else pages).append(loc)
    return sitemaps, pages


def parse_feed(xml: str) -> list[str]:
    """Item/entry links from an RSS or Atom feed."""
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError:
        return []
    out: list[str] = []
    for el in root.iter():
        name = _localname(el.tag)
        if name == "link":
            href = el.get("href")                 # Atom
            if href:
                out.append(href.strip())
            elif el.text and el.text.strip():     # RSS
                out.append(el.text.strip())
        elif name == "loc" and el.text and el.text.strip():
            out.append(el.text.strip())
    return out


def is_offer_url(url: str) -> bool:
    """True for a single offer page (offer word in the path, a specific tail, not an asset/list/intermediary)."""
    if not url or is_intermediary(url) or _ASSET.search(urlsplit(url).path):
        return False
    path = urlsplit(url).path
    if not _OFFER_PATH.search(path):
        return False
    if _LIST_TAIL.search(path):                   # the list page itself, not one offer
        return False
    return len([s for s in path.split("/") if s]) >= 2


def filter_offer_urls(urls: list[str], limit: int = MAX_OFFER_URLS) -> list[str]:
    out: list[str] = []
    for u in urls:
        if is_offer_url(u) and u not in out:
            out.append(u)
            if len(out) >= limit:
                break
    return out


def collect_offer_pages(fetcher, base_url: str, *, limit: int = MAX_OFFER_URLS,
                        max_sitemaps: int = MAX_SITEMAPS) -> list[str]:
    """Offer-page URLs found via robots.txt sitemaps (or /sitemap.xml), through the polite client.

    Best-effort and bounded: never raises, obeys robots.txt and delays (the fetcher does),
    reads at most `max_sitemaps` sitemaps and returns at most `limit` offer URLs.
    """
    root = "{0.scheme}://{0.netloc}".format(urlsplit(base_url))
    seeds: list[str] = []
    try:
        robots = fetcher.get(root + "/robots.txt", accept_status=(200, 404), retries=0)
        seeds = sitemaps_in_robots(robots.text) if robots.status == 200 else []
    except Exception:  # noqa: BLE001
        seeds = []
    if not seeds:
        seeds = [root + "/sitemap.xml"]

    offer_urls: list[str] = []
    queue = list(dict.fromkeys(seeds))
    seen_sitemaps: set[str] = set()
    read = 0
    while queue and read < max_sitemaps and len(offer_urls) < limit:
        sm = queue.pop(0)
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)
        try:
            r = fetcher.get(sm, accept_status=(200, 404), retries=0)
        except Exception:  # noqa: BLE001
            continue
        read += 1
        if r.status != 200:
            continue
        children, pages = parse_sitemap(r.text)
        if not children and not pages:
            pages = parse_feed(r.text)            # not a sitemap: maybe an RSS/Atom feed
        for u in filter_offer_urls(pages, limit - len(offer_urls)):
            if u not in offer_urls:
                offer_urls.append(u)
        # prefer child sitemaps whose name hints at jobs
        children.sort(key=lambda u: 0 if _OFFER_PATH.search(u) else 1)
        queue.extend(children)
    return offer_urls[:limit]
