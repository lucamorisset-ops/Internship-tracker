"""Blocked — Pictet (SuccessFactors): robots.txt forbids every catalogue page.

No page is fetched: each run only asks the fetcher whether robots.txt allows
params.url. Still forbidden -> status "resiste" (ok=True: this is the expected
state, explained to Luca); allowed -> "a_configurer" so that a real reader can
be written. complete=False: nothing is ever closed by this source.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..models import SourceResult
from .base import BaseParser


class Parser(BaseParser):
    name = "blocked"
    method = "aucune (robots.txt)"
    detail_pages = False

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        res.complete = False
        url = self.params(source).get("url") or source.get("catalog_url")
        company = source.get("company") or "l'entreprise"
        if not url:
            res.status = "a_configurer"
            res.reason = "Aucun lien de catalogue à vérifier pour cette entreprise."
            res.fix = "Ajoute le lien du catalogue officiel dans l'onglet Sources."
            return res

        parts = urlsplit(url)
        host = parts.netloc
        fetcher = self.ctx.fetcher
        res.urls_read.append(f"{parts.scheme}://{host}/robots.txt")
        if fetcher.allowed(url):
            res.status = "a_configurer"
            res.reason = "Le robots.txt autorise maintenant la lecture : le lecteur de ce site peut être écrit."
            res.fix = "Le lecteur de ce site doit être écrit dans scraper/parsers (le robot ne lit encore rien)."
            return res

        res.status = "resiste"
        res.blocked_by_robots = [url]
        res.fix = (f"Crée une alerte e-mail sur le site carrières de {company} : "
                   "c'est la seule façon d'être prévenu.")
        unreachable = getattr(fetcher, "robots_unreachable", None)
        if callable(unreachable) and unreachable(url):
            res.reason = (f"Le fichier robots.txt de {host} est injoignable : par prudence, le robot "
                          "ne lit pas le catalogue. Il réessaiera au prochain passage.")
        elif not fetcher.allowed(f"{parts.scheme}://{host}/"):
            res.reason = (f"Le fichier robots.txt de {host} interdit aux robots toutes les pages du "
                          "catalogue (Disallow: /). Le robot respecte cette règle.")
        else:
            res.reason = (f"Le fichier robots.txt de {host} interdit aux robots la page du catalogue "
                          f"({parts.path or '/'}). Le robot respecte cette règle.")
        return res
