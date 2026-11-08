"""Shared data types for the robot.

A parser turns one source (a company's official careers catalogue) into a
list of `Offer` objects. Everything else (matching, storage, notifications)
works on these objects only, so parsers stay small and testable.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


@dataclass
class Offer:
    """One job/internship posting as read on the official site."""

    source_id: str              # e.g. "amundi"
    ext_id: str                 # stable id on the site (requisition id, slug...)
    title: str
    url: str                    # link to the official offer page
    company: str = ""
    location: str = ""          # free text as shown by the site ("Paris 15 éme")
    country: str = ""           # ISO code when the site gives it ("FR", "GB")
    contract: str = ""          # free text ("Stage", "Internship", "CDI"...)
    published: date | None = None   # publication date when the site gives it
    published_label: str = ""   # human label when no exact date ("3d", "Non affichée")
    description: str = ""       # short text used for start-date / métier detection
    start_label: str = ""       # filled by matching ("Janvier 2027")
    relevance: str = ""         # filled by matching: cible / proche / exclue
    reasons: str = ""           # filled by matching: why
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source_id}:{self.ext_id}"

    @property
    def url_key(self) -> str:
        return url_key(self.url)

    def text(self) -> str:
        """All text useful for matching, in one string."""
        return " \n".join(
            x for x in (self.title, self.contract, self.location, self.description) if x
        )

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("extra", None)
        d["id"] = self.id
        d["url_key"] = self.url_key
        d["published"] = self.published.isoformat() if self.published else None
        return d


@dataclass
class SourceResult:
    """What happened when one source was read."""

    source_id: str
    ok: bool = False
    status: str = "ok"          # ok / partiel / resiste / sans_catalogue / erreur
    method: str = ""            # "api", "html", "navigateur", "veille de page"...
    urls_read: list[str] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    complete: bool = True       # False when only part of the catalogue is read
    reason: str = ""            # why it resists / what went wrong (French, for Luca)
    fix: str = ""               # what Luca can do about it (French)
    error: str = ""             # technical detail
    blocked_by_robots: list[str] = field(default_factory=list)
    page_hash: str = ""         # for page-watch sources
    closed_urls: list[str] = field(default_factory=list)  # known offers confirmed gone
    details_read: list[str] = field(default_factory=list)  # offer pages opened for details
    source_updates: dict[str, Any] = field(default_factory=dict)  # e.g. kind/params found by "auto"

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source_id,
            "ok": self.ok,
            "status": self.status,
            "method": self.method,
            "urls": self.urls_read,
            "details": self.details_read,
            "found": len(self.offers),
            "complete": self.complete,
            "reason": self.reason,
            "error": self.error[:500],
            "robots": self.blocked_by_robots,
        }


_TRACKING = re.compile(r"^(utm_|from_|standalone$|source$|ref$|src$|lcid$|locale$)", re.I)


def url_key(url: str) -> str:
    """Normalise a URL so that the same offer always gets the same key.

    Lower-case host, drop fragment, trailing slash and tracking parameters,
    keep meaningful query parameters (e.g. ?annonce=116845, ?id=10128-97).
    """
    if not url:
        return ""
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not _TRACKING.match(k)]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower(), path, urlencode(sorted(q)), ""))


def slugify(text: str, max_len: int = 60) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:max_len] or hashlib.sha1(text.encode()).hexdigest()[:10]


def fold(text: str) -> str:
    """Lower-case and strip accents, for keyword matching."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).lower()
