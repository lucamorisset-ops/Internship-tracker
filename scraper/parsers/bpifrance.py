"""Bpifrance Talents (talents.bpifrance.fr), offers shown with JavaScript.

List pages: /nos-opportunites/?criteres=stage,finances and
?criteres=stage,capital-investissement. Offer links look like
https://talents.bpifrance.fr/opportunites/<slug>/?id=9986-81 (ext_id = the
number before the dash: "9986").

For each list URL:
  1. plain GET; a maintenance page (seen on 08/11/2026: "Maintenance page",
     200, 2 KB, no offer link) -> status "erreur" with a French explanation;
  2. offer links already in the raw HTML -> read them, no browser needed;
  3. otherwise render the page (wait for a[href*="/opportunites/"]).
Both lists are merged (an offer may appear in both).

The card markup is not known yet (site in maintenance during the capture):
title = the heading of the link / card, or the link text; location, contract
and date are taken from the card when it shows them (class names such as
"location"/"contract", "Lieu : ..." labels, or short texts like "Stage").

params: {"urls": [list URL, ...], "internships_only": true}
(internships_only is read by the runner for matching; nothing is filtered here.)
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, Tag

from ..http import FetchError
from ..models import Offer, SourceResult, fold
from .base import (BaseParser, absolute, clean_text, fill_from_detail_html, iso_to_date,
                   jsonld_jobpostings, parse_date, parse_relative_age)

OFFER_SEL = 'a[href*="/opportunites/"]'
MAINTENANCE_REASON = "Le site Bpifrance Talents est en maintenance : aucune offre lisible pour l'instant."
MAINTENANCE_FIX = "Rien à faire : le robot réessaiera au prochain passage."

HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
TITLE_CLASS = '[class*="title"], [class*="titre"], [class*="name"], [class*="intitule"]'
GENERIC_LINK = re.compile(r"^(voir|consulter|d[ée]couvrir|en savoir plus|postuler|candidater|lire la suite|"
                          r"plus de d[ée]tails|d[ée]tails?|j'y vais|acc[ée]der|>|→|›)", re.I)
STOP_TAGS = {"ul", "ol", "main", "body", "html", "section", "form", "nav", "header", "footer",
             "table", "tbody", "[document]"}
LOCATION_CLASS = ("location", "localisation", "lieu", "city", "ville")
CONTRACT_CLASS = ("contract", "contrat")
DATE_CLASS = ("date", "published", "publication")
LABELLED = re.compile(r"^\s*(lieu|localisation|ville|site|contrat|type de contrat|type)\s*:\s*(.+)$", re.I)
CONTRACT_WORD = re.compile(r"^(stage\b.{0,40}|stagiaire|cdi|cdd\b.{0,20}|alternance\b.{0,20}|apprentissage|"
                           r"v\.?i\.?e\.?|int[ée]rim|internship)$", re.I)
PLACE_WORD = re.compile(r"^(paris\b.{0,20}|maisons[- ]alfort.{0,10}|.{0,40}\(\d{2,3}\)|\d{5}\s.{1,40}|"
                        r"(lyon|lille|marseille|bordeaux|nantes|toulouse|strasbourg|rennes|nice|"
                        r"montpellier|grenoble|rouen|dijon|orl[ée]ans|tours|metz|nancy|amiens|caen|"
                        r"poitiers|limoges|clermont-ferrand|besan[çc]on|reims|ajaccio)\b.{0,20})$", re.I)
PUBLISHED_TEXT = re.compile(r"(publi\w*|mise en ligne|post[ée]e?)\D{0,20}(\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2})", re.I)
RELATIVE_AGE = re.compile(r"il y a\s+\d+\s*(jours?|semaines?|mois|j|sem)\b|aujourd'hui|\bhier\b", re.I)
MORE_PAGES = re.compile(r"(voir|charger|afficher) plus d'(offres|opportunites|resultats)|load more|"
                        r"page suivante|next page", re.I)
TOTAL = re.compile(r"\b(\d{1,4})\s+(opportunites|offres|resultats)\b", re.I)


# ------------------------------------------------------------------ page helpers
def _visible_text(soup: BeautifulSoup | Tag) -> str:
    parts = [s for s in soup.find_all(string=True)
             if not isinstance(s, Comment) and s.parent is not None
             and s.parent.name not in ("script", "style", "noscript", "template", "title")]
    return clean_text(" ".join(parts))


def _offer_id(href: str) -> str:
    """'9986-81' from .../opportunites/<slug>/?id=9986-81 ('' when absent)."""
    v = (parse_qs(urlsplit(href).query).get("id") or [""])[0].strip()
    return v if re.match(r"\d+", v) else ""


def _ext_id(href: str) -> str:
    oid = _offer_id(href)
    return oid.split("-", 1)[0] if oid else ""


def offer_links(soup: BeautifulSoup) -> list[Tag]:
    return [a for a in soup.select(OFFER_SEL) if a.get("href") and _ext_id(a["href"])]


def is_maintenance(soup: BeautifulSoup) -> bool:
    """Maintenance page: no offer link and "maintenance" in the title, a heading or a short page."""
    if offer_links(soup):
        return False
    title = fold(soup.title.get_text(" ")) if soup.title else ""
    if "maintenance" in title:
        return True
    if any("maintenance" in fold(h.get_text(" ")) for h in soup.find_all(HEADINGS)):
        return True
    text = fold(_visible_text(soup))
    return "maintenance" in text and len(text) < 1500


def _more_pages(soup: BeautifulSoup, shown: int) -> bool:
    """True when the list says it has more offers than it shows (load more, next page, total)."""
    text = fold(_visible_text(soup))
    if MORE_PAGES.search(text) or soup.select_one('a[rel="next"], link[rel="next"]'):
        return True
    m = TOTAL.search(text)
    return bool(m and int(m.group(1)) > shown)


# ------------------------------------------------------------------ card helpers
def _card(a: Tag, ext_id: str) -> Tag:
    """The largest ancestor of the link that only shows this offer (stops at its heading)."""
    node = a
    for _ in range(5):
        if node.find(HEADINGS) is not None and node is not a:
            break
        parent = node.parent
        if parent is None or parent.name in STOP_TAGS:
            break
        if {_ext_id(x["href"]) for x in parent.select(OFFER_SEL) if x.get("href")} - {ext_id, ""}:
            break
        if len(_visible_text(parent)) > 800:
            break
        node = parent
    return node


def _first(card: Tag, selector: str) -> str:
    for el in card.select(selector):
        t = clean_text(el.get_text(" "))
        if t:
            return t
    return ""


def _title(anchors: list[Tag], card: Tag) -> str:
    for a in anchors:
        t = _first(a, ", ".join(HEADINGS) + ", " + TITLE_CLASS)
        if t:
            return t
    for a in anchors:
        t = clean_text(a.get_text(" "))
        if t and len(t) <= 160 and not GENERIC_LINK.match(t) and a.find(["div", "p", "ul", "li"]) is None:
            return t
    t = _first(card, ", ".join(HEADINGS)) or _first(card, TITLE_CLASS)
    if t:
        return t
    for a in anchors:
        t = clean_text(a.get("title") or a.get("aria-label") or "")
        if t and not GENERIC_LINK.match(t):
            return t
    return ""


def _title_from_url(href: str) -> str:
    slug = urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-f-h$|-h-f$", " F/H", slug)
    return slug.replace("-", " ").strip().capitalize()


def _leaves(card: Tag) -> list[tuple[Tag, str]]:
    """Innermost elements of the card that hold text, with that text."""
    out = []
    for el in card.find_all(True):
        if el.name in ("script", "style", "svg", "noscript"):
            continue
        if el.find(lambda x: x.name not in ("br", "i", "svg", "strong", "em", "b") and
                   clean_text(x.get_text(" "))) is not None:
            continue
        t = clean_text(el.get_text(" "))
        if t:
            out.append((el, t))
    return out


def _has_class(el: Tag, keys: tuple[str, ...]) -> bool:
    node: Tag | None = el
    for _ in range(2):   # the element or its direct parent (e.g. <li class="tag--location"><span>)
        if node is None:
            break
        cls = " ".join(node.get("class") or []).lower()
        if any(k in cls for k in keys):
            return True
        node = node.parent
    return False


def _describe(card: Tag, title: str) -> dict:
    out = {"location": "", "contract": "", "published": None, "published_label": "", "rest": []}
    time_el = card.find("time")
    if time_el is not None:
        out["published"] = iso_to_date(time_el.get("datetime")) or parse_date(time_el.get_text(" "))
    for el, t in _leaves(card):
        if t == title or GENERIC_LINK.match(t) or el.find_parent(HEADINGS) is not None:
            continue
        m = LABELLED.match(t)
        if m:
            key = "location" if fold(m.group(1)) in ("lieu", "localisation", "ville", "site") else "contract"
            out[key] = out[key] or m.group(2)
            continue
        if _has_class(el, DATE_CLASS) or PUBLISHED_TEXT.search(t) or RELATIVE_AGE.search(t):
            if not out["published"]:
                pm = PUBLISHED_TEXT.search(t)
                rm = RELATIVE_AGE.search(t)
                out["published"] = (parse_date(pm.group(2)) if pm else None) or parse_date(t) or \
                    (parse_relative_age(rm.group(0), date_today()) if rm else None)
                if not out["published"] and rm:
                    out["published_label"] = t
            continue
        if not out["contract"] and (_has_class(el, CONTRACT_CLASS) or CONTRACT_WORD.match(t)):
            out["contract"] = t
        elif not out["location"] and (_has_class(el, LOCATION_CLASS) or PLACE_WORD.match(t)):
            out["location"] = t
        elif len(t) < 200:
            out["rest"].append(t)
    return out


_TODAY = None


def date_today():
    """Today's date of the current run (set by Parser.read; date.today() otherwise)."""
    from datetime import date

    return _TODAY or date.today()


# ------------------------------------------------------------------ parser
class Parser(BaseParser):
    name = "bpifrance"
    method = "navigateur"

    def read(self, source: dict) -> SourceResult:
        global _TODAY
        _TODAY = self.ctx.today
        res = self.result(source)
        p = self.params(source)
        urls = [u for u in (p.get("urls") or [p.get("url") or source["catalog_url"]]) if u]
        found: dict[str, Offer] = {}
        failed: list[tuple[str, FetchError]] = []
        empty: list[str] = []
        for url in urls:
            soup = self._plain(url, res)
            if soup is not None and is_maintenance(soup):
                return self._maintenance(res)
            if soup is None or not offer_links(soup):
                try:
                    html, _ = self.render(url, res, wait_for=OFFER_SEL)
                except FetchError as e:
                    if e.status in (401, 403, 429) or "anti-robot" in (e.detail or ""):
                        raise                       # the runner reports "site qui résiste"
                    (empty if "introuvable" in (e.detail or "") else failed).append(
                        url if "introuvable" in (e.detail or "") else (url, e))
                    continue
                soup = BeautifulSoup(html, "lxml")
                if is_maintenance(soup):
                    return self._maintenance(res)
            offers = self._offers(source, soup, url)
            if not offers:
                empty.append(url)
            for off in offers:
                prev = found.get(off.ext_id)
                if prev is None:
                    found[off.ext_id] = off
                    continue
                for k in ("location", "contract", "published", "published_label", "description"):
                    if not getattr(prev, k) and getattr(off, k):
                        setattr(prev, k, getattr(off, k))
            if _more_pages(soup, len(offers)):
                res.complete = False
        res.offers = list(found.values())

        if failed and len(failed) + len(empty) == len(urls) and not res.offers:
            raise failed[0][1]
        for u, e in failed:
            res.complete = False
            res.status = "partiel"
            res.reason = (f"{res.reason} La page {u} n'a pas pu être lue ({e.status or 'erreur réseau'}) : "
                          "seules les offres des autres pages sont affichées.").strip()
            res.fix = "Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage."
            res.error = f"{res.error} | {e}".strip(" |")
        if empty:
            # an empty list may be real (no internship in this filter) or a page change:
            # never close known offers on that basis
            res.complete = False
            if not res.offers:
                res.status = "partiel"
                res.reason = ("Aucune offre n'est apparue sur les pages Bpifrance Talents après chargement : "
                              "soit il n'y a aucun stage dans ces filtres en ce moment, soit la page a changé. "
                              "Aucune offre n'est marquée comme fermée.")
                res.fix = ("À vérifier : ouvre le catalogue avec le bouton de la source. S'il montre des offres, "
                           "le lecteur doit être corrigé (dossier scraper/parsers).")
        return res

    # -------------------------------------------------------------- steps
    def _plain(self, url: str, res: SourceResult) -> BeautifulSoup | None:
        """Raw HTML of the list (None when the plain GET fails: the browser will try)."""
        try:
            r = self.get(url, res, accept_status=(200, 503))
        except FetchError:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        if r.status != 200 and not is_maintenance(soup):
            return None
        return soup

    def _maintenance(self, res: SourceResult) -> SourceResult:
        res.ok = False
        res.status = "erreur"
        res.offers = []
        res.reason = MAINTENANCE_REASON
        res.fix = MAINTENANCE_FIX
        res.error = "page de maintenance"
        return res

    def _offers(self, source: dict, soup: BeautifulSoup, page_url: str) -> list[Offer]:
        groups: dict[str, tuple[str, list[Tag]]] = {}
        for a in offer_links(soup):
            href = absolute(page_url, a["href"])
            groups.setdefault(_ext_id(href), (href, []))[1].append(a)
        out = []
        for ext_id, (href, anchors) in groups.items():
            parts = urlsplit(href)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, f"id={_offer_id(href)}", ""))
            card = _card(anchors[0], ext_id)
            title = _title(anchors, card) or _title_from_url(href)
            d = _describe(card, title) if card is not anchors[0] or card.find(True) else _describe(card, title)
            out.append(self.offer(
                source, ext_id=ext_id, title=title, url=url,
                location=d["location"], contract=d["contract"], published=d["published"],
                published_label=d["published_label"], description=" · ".join(d["rest"])[:500]))
        return out

    # -------------------------------------------------------------- details
    def enrich(self, offer: Offer, res: SourceResult) -> None:
        """Offer pages may also need JavaScript: only use a page that really shows the offer.

        Plain GET first; if it does not show the offer (no JobPosting JSON-LD and
        no title in the text), render it in the browser. A page that still does
        not show the offer is ignored, so no menu/footer text becomes the description.
        """
        if not offer.url:
            return
        html = None
        try:
            html = self.ctx.fetcher.get(offer.url, retries=1).text
            res.details_read.append(offer.url)
        except FetchError:
            html = None
        if (html is None or not _shows_offer(html, offer)) and self.ctx.browser is not None:
            html, _ = self.ctx.browser.render(offer.url)
            res.details_read.append(offer.url)
        if html and _shows_offer(html, offer):
            fill_from_detail_html(offer, html)


def _shows_offer(html: str, offer: Offer) -> bool:
    if jsonld_jobpostings(html):
        return True
    soup = BeautifulSoup(html, "lxml")
    if is_maintenance(soup):
        return False
    key = fold(offer.title)[:40].strip()
    return bool(key) and key in fold(_visible_text(soup))
