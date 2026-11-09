"""Page watch — companies without a readable list of offers (Moneta, Eleva).

The official careers page (params.url) is read and its main text hashed
(sha256). The text is normalised so that only real changes count: scripts,
styles, navigation, page header/footer and cookie banners are removed,
whitespace is collapsed, and tokens made only of digits and punctuation
(dates, counters, years) are dropped, together with month/day names next
to them ("8 novembre 2026", "Mon 9").

  * first run (no source["page_hash"]): the hash is stored, nothing emitted;
  * hash changed: one offer "La page carrières de X a changé" (ext_id
    "page-YYYYMMDD", relevance fixed to "proche") so that Luca is notified;
  * params.url is null (e.g. Eleva, only on JobTeaser): nothing is fetched.

status "sans_catalogue", complete=False (never closes anything).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from bs4 import BeautifulSoup

from ..models import SourceResult, fold
from .base import BaseParser
from .generic import is_intermediary

NO_URL_REASON = "Pas de page carrières officielle lisible pour cette entreprise."
NO_URL_FIX = "Crée une alerte e-mail (ou un suivi LinkedIn) pour être prévenu de ses offres."
REASON = "Pas de liste d'offres : le robot surveille la page et te prévient quand elle change."
EMPTY_NOTE = (" Attention : la page ne contient presque pas de texte sans JavaScript, "
              "certains changements peuvent passer inaperçus.")

_DROP_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "nav", "header", "footer",
              "object", "embed", "canvas"]
_COOKIE = re.compile(r"cookie|consent|gdpr|rgpd|didomi|onetrust|tarteaucitron|axeptio|cookiebot", re.I)
_NUMERIC = re.compile(r"[\W_]*\d[\d\W_]*")        # 08/11/2026, 2026, (3), 12:30, ©2026
_ORDINAL = re.compile(r"\W*\d+(er|re|e|eme|ème|st|nd|rd|th)\W*", re.I)    # 1er, 3rd, 2e
_CALENDAR = {
    # French and English months / days, folded, with common abbreviations
    "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
    "novembre", "decembre", "janv", "fevr", "fev", "avr", "juil", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun", "le", "on", "du", "au", "the",
}


def _is_number(tok: str) -> bool:
    return bool(_NUMERIC.fullmatch(tok) or _ORDINAL.fullmatch(tok))


def page_text(html: str) -> str:
    """Normalised main text of a page (see module docstring)."""
    soup = BeautifulSoup(html or "", "lxml")
    for t in soup(_DROP_TAGS):
        t.decompose()
    noise = [el for el in soup.find_all(True)
             if el.name not in ("html", "body", "main")
             and (_COOKIE.search(" ".join(el.get("class") or []) + " " + (el.get("id") or ""))
                  or (el.get("role") or "") in ("navigation", "banner", "contentinfo"))]
    for el in noise:
        if not el.decomposed:
            el.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = unicodedata.normalize("NFKC", main.get_text(" ")).replace("\xa0", " ")
    toks = text.split()
    num = [_is_number(t) for t in toks]
    out: list[str] = []
    for i, tok in enumerate(toks):
        if num[i]:
            continue
        near_num = (i > 0 and num[i - 1]) or (i + 1 < len(toks) and num[i + 1])
        if near_num and fold(tok).strip(".,;:()") in _CALENDAR:
            continue
        out.append(tok)
    return " ".join(out)


def page_hash(html: str) -> str:
    return hashlib.sha256(page_text(html).encode("utf-8")).hexdigest()


class Parser(BaseParser):
    name = "page_watch"
    method = "veille de page"
    detail_pages = False

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        res.complete = False
        res.status = "sans_catalogue"
        p = self.params(source)
        if "url" in p:
            url = p.get("url")
        else:                                  # no explicit url: the official catalogue link, if any
            url = source.get("catalog_url")
            url = None if is_intermediary(url) else url
        if not url:
            res.reason, res.fix = NO_URL_REASON, NO_URL_FIX
            return res

        r = self.get(url, res)
        text = page_text(r.text)
        res.page_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        res.reason = REASON + (EMPTY_NOTE if len(text) < 80 else "")

        previous = source.get("page_hash")
        if previous and previous != res.page_hash:
            company = source.get("company") or "l'entreprise"
            res.offers.append(self.offer(
                source,
                ext_id=f"page-{self.ctx.today:%Y%m%d}",
                title=f"La page carrières de {company} a changé",
                url=url,
                published=self.ctx.today,
                description=text[:500],
                relevance="proche",
                reasons="page modifiée depuis le dernier passage",
                start_label="Non précisé",
                extra={"fixed": True},
            ))
        return res
