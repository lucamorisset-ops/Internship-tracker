"""Sainoo careers page — Amiral Gestion.

https://amiralgestion.sainoo.com/careers is server-rendered and lists every
offer (6 in November 2026) as

    <a class="job-item" data-id="10279" href=".../jobs/10279?from_careers_page=true&standalone=true">
      .title · .location · .employment ("Full-time | Internship") · .deadline · .start-date ("Length: 6 months")

No publication date on the list. The offer URL is /jobs/{id} without the
query string; offer pages are server-rendered (generic enrich).

params: {"url": careers page URL}
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import Tag

from ..models import SourceResult
from .base import BaseParser, absolute, clean_text

JOB_PATH = re.compile(r"/jobs/(\d+)")


def _text(el: Tag | None) -> str:
    return clean_text(el.get_text(" ")) if el is not None else ""


class Parser(BaseParser):
    name = "sainoo"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        url = self.params(source).get("url") or source["catalog_url"]
        soup = self.soup(url, res)
        cards = soup.select("a.job-item[data-id]")
        if not cards:
            # tolerant fallback (page redesigned): any link to /jobs/<id>
            cards = [a for a in soup.select("a[href]") if JOB_PATH.search(a["href"])]
        seen: set[str] = set()
        for a in cards:
            href = absolute(url, a.get("href") or "")
            m = JOB_PATH.search(urlsplit(href).path)
            ext_id = (a.get("data-id") or "").strip() or (m.group(1) if m else "")
            title = _text(a.select_one(".title")) or _text(a)
            if not ext_id or ext_id in seen or not title:
                continue
            seen.add(ext_id)
            base = urlsplit(href if m else url)
            infos = [_text(a.select_one(sel)) for sel in (".deadline", ".start-date")]
            res.offers.append(self.offer(
                source, ext_id=ext_id, title=title,
                url=urlunsplit((base.scheme or "https", base.netloc, f"/jobs/{ext_id}", "", "")),
                location=_text(a.select_one(".location")),
                contract=_text(a.select_one(".employment")),
                description=" · ".join(x for x in infos if x)))
        return res
