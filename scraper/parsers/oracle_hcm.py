"""Oracle Recruiting Cloud (Candidate Experience) — Lazard, J.P. Morgan, Edmond de Rothschild.

Reads the public REST API that the official portal itself calls (see docs/probes.md):

    {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true
        &expand=requisitionList.secondaryLocations
        &finder=findReqs;siteNumber={site},facetsList=NONE,limit=25,offset=0,
                sortBy=POSTING_DATES_DESC[,keyword=%22...%22][,{facet}={value}]

params:
    host          "https://jpmc.fa.oraclecloud.com"
    site          "CX_1001"
    keywords      optional list: one query per keyword, results merged by requisition Id
    facets        optional {name: value}, appended to the finder as `,name=value`
                  with the value URL-encoded (";" -> %3B, '"' -> %22, "|" -> %7C, " " -> %20)
    partial_note  optional French sentence: the portal is read in full but the company
                  publishes other offers elsewhere -> status "partiel"

The offer page ({host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}) needs
JavaScript, so `enrich` reads the details API instead and never opens that page.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import Offer, SourceResult
from ._api import JSON_HEADERS, decode_json, html_to_text
from .base import BaseParser, iso_to_date

LIMIT = 25                 # page size used by the official portal
MAX_JOBS = 200             # per keyword
API = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAILS_API = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
PARTIAL_FIX = ("Active l'alerte e-mail de l'entreprise sur son site carrières "
               "pour les offres publiées ailleurs.")
_JOB_URL = re.compile(r"^(https?://[^/]+)/hcmUI/CandidateExperience/[^/]+/sites/([^/]+)/job/")


def _enc(value: object) -> str:
    if isinstance(value, (list, tuple)):
        value = ";".join(str(v) for v in value)
    return quote(str(value), safe="")


def list_url(host: str, site: str, offset: int = 0, keyword: str | None = None,
             facets: dict | None = None) -> str:
    finder = [f"findReqs;siteNumber={site}", "facetsList=NONE", f"limit={LIMIT}",
              f"offset={offset}", "sortBy=POSTING_DATES_DESC"]
    if keyword:
        finder.append("keyword=" + _enc(f'"{keyword}"'))
    for name, value in (facets or {}).items():
        if value not in (None, "", []):
            finder.append(f"{name}={_enc(value)}")
    return (f"{host}{API}?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder={','.join(finder)}")


def details_url(host: str, site: str, req_id: str) -> str:
    return (f"{host}{DETAILS_API}?expand=all&onlyData=true"
            f"&finder=ById;Id=%22{quote(str(req_id), safe='')}%22,siteNumber={site}")


def job_url(host: str, site: str, req_id: str) -> str:
    return f"{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"


class Parser(BaseParser):
    name = "oracle_hcm"
    method = "api"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        host = str(p["host"]).rstrip("/")
        site = str(p["site"])
        facets = p.get("facets") or {}
        keywords = [k for k in (p.get("keywords") or []) if k and str(k).strip()] or [None]

        found: dict[str, Offer] = {}
        for kw in keywords:
            offset = 0
            while True:
                url = list_url(host, site, offset, kw, facets)
                data = decode_json(self.get(url, res, headers=JSON_HEADERS))
                items = data.get("items") or [] if isinstance(data, dict) else []
                block = items[0] if items and isinstance(items[0], dict) else {}
                reqs = [r for r in (block.get("requisitionList") or []) if isinstance(r, dict)]
                total = block.get("TotalJobsCount")
                for r in reqs:
                    off = self._offer(source, host, site, r)
                    if off is None:
                        continue
                    if off.ext_id in found:
                        if kw:
                            found[off.ext_id].extra.setdefault("keywords", []).append(kw)
                        continue
                    if kw:
                        off.extra["keywords"] = [kw]
                    found[off.ext_id] = off
                offset += len(reqs)
                if not reqs:
                    break
                more = offset < int(total) if total is not None else len(reqs) >= LIMIT
                if not more:
                    break
                if offset >= MAX_JOBS:
                    res.complete = False      # only the MAX_JOBS newest were read
                    break

        res.offers = list(found.values())
        note = p.get("partial_note")
        if note:
            res.status = "partiel"
            res.reason = str(note)
            res.fix = PARTIAL_FIX
        return res

    def _offer(self, source: dict, host: str, site: str, r: dict) -> Offer | None:
        req_id = r.get("Id")
        if req_id in (None, ""):
            return None
        req_id = str(req_id)
        locs: list[str] = []
        for name in [r.get("PrimaryLocation")] + [
                (s or {}).get("Name") for s in (r.get("secondaryLocations") or []) if isinstance(s, dict)]:
            name = (name or "").strip()
            if name and name not in locs:
                locs.append(name)
        return self.offer(
            source,
            ext_id=req_id,
            title=r.get("Title") or "",
            url=job_url(host, site, req_id),
            location="; ".join(locs),
            country=(r.get("PrimaryLocationCountry") or "").upper(),
            published=iso_to_date(r.get("PostedDate")),
            description=html_to_text(r.get("ShortDescriptionStr")),
            extra={
                "oracle": {"host": host, "site": site},
                # kept for reference only: an intern may be labelled "Fixed term" and would
                # then be excluded as a CDD by matching, so they do not fill `contract`.
                "oracle_fields": {k: r.get(k) for k in ("JobFamily", "JobFunction", "ContractType",
                                                        "JobType", "WorkerType", "StudyLevel",
                                                        "PostingEndDate") if r.get(k)},
            },
        )

    def enrich(self, offer: Offer, res: SourceResult) -> None:
        """Full description from the details API (the job page itself needs JavaScript)."""
        o = offer.extra.get("oracle") or {}
        host, site = o.get("host"), o.get("site")
        if not (host and site):
            m = _JOB_URL.match(offer.url or "")
            if not m:
                return
            host, site = m.group(1), m.group(2)
        url = details_url(host, site, offer.ext_id)
        r = self.detail_get(url, res, headers=JSON_HEADERS, retries=1)
        data = decode_json(r)
        items = data.get("items") or [] if isinstance(data, dict) else []
        if not items or not isinstance(items[0], dict):
            return
        d = items[0]
        text = " ".join(t for t in (html_to_text(d.get(k)) for k in (
            "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")) if t)
        if text:
            offer.description = text[:4000]
        if not offer.published:
            offer.published = iso_to_date(d.get("ExternalPostedStartDate"))
        if not offer.location and d.get("PrimaryLocation"):
            offer.location = html_to_text(d["PrimaryLocation"])
        if not offer.country and d.get("PrimaryLocationCountry"):
            offer.country = str(d["PrimaryLocationCountry"]).upper()
