"""Roles watch — Goldman Sachs (higher.gs.com).

robots.txt of higher.gs.com allows /roles/ and disallows everything else, so
the search page (and the API behind it) cannot be read: new offers cannot be
discovered. The robot only re-checks the offer pages it already knows
(source["known_offers"], given by the runner): an offer whose page answers
404/410, says it is no longer available, or redirects away from the role,
goes to res.closed_urls. Offers are NOT re-emitted (the runner would treat
them as new or touch them); complete=False so nothing is closed by absence.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..http import FetchError, RobotsDisallowed
from ..models import SourceResult, fold, url_key
from .base import BaseParser

MAX_CHECKS = 60
# phrases that mean "closed" anywhere in the visible text (folded: no accents, lower case)
_CLOSED = re.compile(r"no longer available|this role is closed|role (is|has been) closed"
                     r"|no longer accepting applications|position has been filled|job (posting )?has expired"
                     r"|n.?est plus disponible|offre (n.?est plus en ligne|a ete pourvue)")
# weaker phrases: only in the title / headings, or on a short page
_NOT_FOUND = re.compile(r"\bnot found\b|\b404\b|page introuvable|page not found")


def looks_closed(html: str) -> bool:
    soup = BeautifulSoup(html or "", "lxml")
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    title = fold(soup.title.get_text(" ") if soup.title else "")
    heads = fold(" ".join(h.get_text(" ") for h in soup.find_all(["h1", "h2"])))
    body = fold((soup.body or soup).get_text(" "))
    if _CLOSED.search(body) or _CLOSED.search(title):
        return True
    return bool(_NOT_FOUND.search(title) or _NOT_FOUND.search(heads)
                or (len(body.split()) < 250 and _NOT_FOUND.search(body)))


def _redirected_away(asked: str, final: str) -> bool:
    """The offer page redirected elsewhere (search page, home): the role id is gone from the URL."""
    if not final or url_key(final) == url_key(asked):
        return False
    ids = re.findall(r"\d{4,}", urlsplit(asked).path)
    return bool(ids) and ids[-1] not in final


class Parser(BaseParser):
    name = "roles_watch"
    method = "veille des fiches"
    detail_pages = False

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        res.complete = False
        res.status = "partiel"
        company = source.get("company") or "ce site"
        p = self.params(source)

        urls: list[str] = []
        for o in source.get("known_offers") or []:
            u = (o.get("url") or "").strip() if isinstance(o, dict) else ""
            if u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)
        urls = urls[:MAX_CHECKS]

        alert_host = (p.get("alert_host") or urlsplit(source.get("catalog_url") or "").netloc
                      or (urlsplit(urls[0]).netloc if urls else "") or "le site carrières")
        res.fix = f"Crée une alerte sur {alert_host} (Job alerts)."

        errors: list[Exception] = []
        still_open = 0
        for u in urls:
            try:
                r = self.get(u, res, accept_status=(200, 404, 410), retries=1)
            except RobotsDisallowed as e:
                res.blocked_by_robots.append(e.url)
                errors.append(e)
                continue
            except FetchError as e:            # 403, 5xx...: unknown, the offer stays open
                errors.append(e)
                continue
            if r.status in (404, 410) or _redirected_away(u, r.url) or looks_closed(r.text):
                res.closed_urls.append(u)
            else:
                still_open += 1

        if urls and len(errors) == len(urls):
            raise errors[0]                    # nothing could be checked: the runner explains why
        if errors:
            res.error = " ; ".join(str(e) for e in errors)[:500]

        res.reason = (f"Le robots.txt de {company} n'autorise que les fiches d'offres : le robot vérifie "
                      "les offres connues mais ne peut pas découvrir les nouvelles.")
        if urls:
            res.reason += (f" {len(urls)} fiche(s) vérifiée(s) : {still_open} toujours en ligne, "
                           f"{len(res.closed_urls)} fermée(s).")
        return res
