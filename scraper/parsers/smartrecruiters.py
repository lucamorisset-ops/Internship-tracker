"""SmartRecruiters public Posting API — Sycomore AM.

    GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
    -> {"offset", "limit", "totalFound", "content": [posting, ...]}

params: company (SmartRecruiters company identifier, e.g. "SycomoreAssetManagement").
Offer URL: https://jobs.smartrecruiters.com/{company}/{id}-{slug of name}.
enrich: GET the posting `ref` (JSON) -> jobAd.sections texts and the official postingUrl.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import Offer, SourceResult, slugify
from ._api import JSON_HEADERS, decode_json, html_to_text
from .base import BaseParser, iso_to_date

API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
JOBS = "https://jobs.smartrecruiters.com/{company}/{id}-{slug}"
LIMIT = 100
MAX_PAGES = 10
SECTIONS = ("jobDescription", "qualifications", "additionalInformation")
_JOBS_URL = re.compile(r"^https://jobs\.smartrecruiters\.com/([^/?#]+)/")


class Parser(BaseParser):
    name = "smartrecruiters"
    method = "api"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        company = str(self.params(source)["company"]).strip()
        base = API.format(company=quote(company, safe=""))

        found: dict[str, Offer] = {}
        offset = 0
        for page in range(1, MAX_PAGES + 1):
            data = decode_json(self.get(f"{base}?limit={LIMIT}&offset={offset}", res, headers=JSON_HEADERS))
            data = data if isinstance(data, dict) else {}
            content = [p for p in (data.get("content") or []) if isinstance(p, dict)]
            for p in content:
                off = self._offer(source, company, p)
                if off is not None:
                    found.setdefault(off.ext_id, off)
            offset += len(content)
            total = data.get("totalFound")
            more = offset < int(total) if total is not None else len(content) >= LIMIT
            if not content or not more:
                break
            if page == MAX_PAGES:
                res.complete = False
        res.offers = list(found.values())
        return res

    def _offer(self, source: dict, company: str, p: dict) -> Offer | None:
        pid = p.get("id")
        if pid in (None, ""):
            return None
        name = p.get("name") or ""
        loc = p.get("location") or {}
        typ = p.get("typeOfEmployment") or {}
        return self.offer(
            source,
            ext_id=str(pid),
            title=name,
            url=JOBS.format(company=company, id=pid, slug=slugify(name, max_len=300)),
            location=loc.get("fullLocation") or loc.get("city") or "",
            country=(loc.get("country") or "").upper(),
            contract=typ.get("label") or "",
            published=iso_to_date(p.get("releasedDate")),
            extra={"ref": p.get("ref") or f"{API.format(company=quote(company, safe=''))}/{pid}"},
        )

    def enrich(self, offer: Offer, res: SourceResult) -> None:
        """Description from the posting detail API; official postingUrl if given."""
        ref = offer.extra.get("ref")
        if not ref:
            m = _JOBS_URL.match(offer.url or "")
            if not m:
                return
            ref = f"{API.format(company=m.group(1))}/{offer.ext_id}"
        if not str(ref).startswith("https://api.smartrecruiters.com/"):
            return                      # only the official API, never an arbitrary URL
        r = self.ctx.fetcher.get(ref, headers=JSON_HEADERS, retries=1)
        res.details_read.append(ref)
        d = decode_json(r)
        if not isinstance(d, dict):
            return
        sections = ((d.get("jobAd") or {}).get("sections") or {})
        text = " ".join(t for t in (html_to_text((sections.get(k) or {}).get("text")) for k in SECTIONS) if t)
        if text:
            offer.description = text[:4000]
        if d.get("postingUrl"):
            offer.url = str(d["postingUrl"])      # ext_id is kept: the runner also matches on it
        if not offer.published:
            offer.published = iso_to_date(d.get("releasedDate"))
        if not offer.contract:
            offer.contract = html_to_text((d.get("typeOfEmployment") or {}).get("label"))
        if not offer.location:
            loc = d.get("location") or {}
            offer.location = html_to_text(loc.get("fullLocation") or loc.get("city"))
            if not offer.country and loc.get("country"):
                offer.country = str(loc["country"]).upper()
