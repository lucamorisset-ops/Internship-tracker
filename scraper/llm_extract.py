"""(d) step 5 — LLM extraction of offers from page text, as a last resort. Stub.

When no ATS API, no discovered JSON endpoint and no structured/link extraction found
anything, a language model could read the page text and return JobPosting-shaped
rows. This module is the *interface* for that step; it is deliberately a stub:

  * disabled by default — maybe_llm_offers() returns [] and makes no network/LLM call,
    so there is no key to manage and no cost;
  * enabling it (SCRAPER_LLM=1) with a real `client` is where an implementation would
    go: send `text` to the model, parse its JSON, and return normalized dicts with the
    common offer fields (title, url, location, contract, published, description).

Keeping it a stub honours the brief ("prévois l'interface ; l'implémentation peut
rester un stub") without adding a dependency or a hidden cost.
"""
from __future__ import annotations

import os
from typing import Any, Callable

# the common, schema.org JobPosting-aligned shape every extraction method returns
OFFER_FIELDS = ("title", "url", "location", "contract", "published", "description", "ext_id")

# a real extractor would be injected here (tests may set it); None keeps the stub inert
EXTRACTOR: Callable[[str, dict], list[dict]] | None = None


def llm_enabled() -> bool:
    return os.environ.get("SCRAPER_LLM", "").strip().lower() in ("1", "true", "yes", "on")


def maybe_llm_offers(source: dict, text: str, *, max_chars: int = 20000) -> list[dict]:
    """Normalized offer dicts extracted by an LLM, or [] when the step is disabled.

    Never raises: the LLM step must never break a pass. Returns only well-formed rows
    (a non-empty title), truncated to the common offer fields.
    """
    if not llm_enabled() or not text or EXTRACTOR is None:
        return []
    try:
        rows = EXTRACTOR(text[:max_chars], source) or []
    except Exception:  # noqa: BLE001 - last resort, best-effort only
        return []
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict) and str(r.get("title") or "").strip():
            out.append({k: r.get(k) for k in OFFER_FIELDS if r.get(k) not in (None, "")})
    return out
