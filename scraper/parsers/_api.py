"""Small helpers shared by the JSON-API parsers (oracle_hcm, smartrecruiters, wp_job).

Not a parser (no `Parser` class, not in the registry).
"""
from __future__ import annotations

import html
import re
from typing import Any, Mapping

from ..http import FetchError, Response, looks_like_challenge

JSON_HEADERS = {"Accept": "application/json"}


def decode_json(r: Response) -> Any:
    """r.json(), but an HTML / anti-bot body becomes a FetchError the runner can explain."""
    try:
        return r.json()
    except ValueError:
        detail = "page anti-robot" if looks_like_challenge(r.text, r.status) else "réponse non JSON"
        raise FetchError(r.url, r.status, detail) from None


def html_to_text(s: Any) -> str:
    """HTML fragment -> one line of plain text (tags removed, every entity decoded)."""
    if not s:
        return ""
    t = re.sub(r"<[^>]+>", " ", str(s))
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def header(headers: Mapping[str, str] | None, name: str) -> str | None:
    """Case-insensitive header lookup (Response.headers is a plain dict)."""
    if not headers:
        return None
    low = name.lower()
    for k, v in headers.items():
        if k.lower() == low:
            return v
    return None
