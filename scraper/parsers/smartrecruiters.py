"""SmartRecruiters public careers page — Sycomore AM.

    GET https://careers.smartrecruiters.com/{company}
    <ul class="opening-jobs ..."><li class="opening-job job ...">
      <a href="https://jobs.smartrecruiters.com/{company}/{id}-{slug}" class="... js-job-ad-link">
        <h4 class="details-title job-title ...">Title</h4>
        <ul class="job-list"><li class="job-desc">Paris, France</li><li class="job-desc">Full-time</li></ul>

The SmartRecruiters Posting API (api.smartrecruiters.com) would be easier, but its
robots.txt forbids it to every robot except LinkedInBot (checked 09/11/2026), so the
robot reads the careers page that the company links to. Offer pages
(jobs.smartrecruiters.com) carry JSON-LD: the generic enrich fills date and description.

params: company (SmartRecruiters company identifier, e.g. "SycomoreAssetManagement").
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import SourceResult
from .base import BaseParser

CAREERS = "https://careers.smartrecruiters.com/{company}"
_JOB = re.compile(r"jobs\.smartrecruiters\.com/([^/?#]+)/(\d{6,})")


def _country(location: str) -> str:
    loc = location.lower()
    if "france" in loc:
        return "FR"
    if "united kingdom" in loc or "royaume-uni" in loc or "england" in loc:
        return "GB"
    return ""


class Parser(BaseParser):
    name = "smartrecruiters"
    method = "html"

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        company = str(self.params(source)["company"]).strip()
        url = CAREERS.format(company=quote(company, safe=""))
        soup = self.soup(url, res)

        seen: set[str] = set()
        for a in soup.select("a[href*='jobs.smartrecruiters.com/']"):
            m = _JOB.search(a.get("href", ""))
            if not m or m.group(2) in seen:
                continue
            seen.add(m.group(2))
            card = a.find_parent("li", class_=re.compile(r"opening-job")) or a
            title_el = a.select_one(".job-title, .details-title, h4, h3")
            descs = [li.get_text(" ", strip=True) for li in card.select("li.job-desc")]
            location = descs[0] if descs else ""
            res.offers.append(self.offer(
                source,
                ext_id=m.group(2),
                title=(title_el or a).get_text(" ", strip=True),
                url=a["href"].split("?")[0],
                location=location,
                country=_country(location),
                contract=" ".join(descs[1:]),
            ))
        # big companies paginate with a "show more" button: then this read is partial
        if soup.select_one(".js-more-jobs, .load-more, [data-load-more]"):
            res.complete = False
        return res
