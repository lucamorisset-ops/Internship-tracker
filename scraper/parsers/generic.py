"""Generic reader for an official careers page that has no dedicated parser.

The page is read once (plain GET, no JavaScript). Offers are:
  * links that look like individual job offers: the URL or the link text matches
    offer words (job, offre, poste, stage, intern...) AND the link points to a
    detail page (id, code or long slug at the end of the URL), outside the
    site navigation (nav, page header/footer, menus, social links, mailto...);
  * schema.org JobPosting objects in JSON-LD, when the page has some.

Titles come from the link text, or from the card heading when the link only
says "Voir l'offre" / "Apply". ext_id is a slug of the normalised URL.
Only part of the details is known (contract, date...), so the result is
always "partiel" and complete=False (nothing is closed by absence).

params: {"url": careers page} or {"urls": [...]}; default source["catalog_url"].

Also exposes `is_intermediary(url)`: intermediary job boards (JobTeaser,
LinkedIn, Indeed...) are never read — Luca's rule: official career sites only.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from ..models import Offer, SourceResult, fold, slugify, url_key
from .base import BaseParser, clean_text, iso_to_date, jsonld_jobpostings, parse_date

REASON = ("Lecture générique : le robot repère les liens qui ressemblent à des offres. "
          "Les détails (contrat, date) peuvent manquer.")
NO_LINK = (" Aucun lien d'offre n'a été trouvé sur la page : elle est peut-être affichée "
           "par JavaScript, ou les offres sont publiées ailleurs.")
INTERMEDIARY_REASON = "Ce lien est un site intermédiaire : le robot lit uniquement les sites carrières officiels."
INTERMEDIARY_FIX = "Donne le lien de la page carrières officielle de l'entreprise."
MAX_OFFERS = 200

# intermediary job boards (host label match): never read, never followed
INTERMEDIARIES = ("jobteaser", "linkedin", "indeed", "welcometothejungle", "wttj", "glassdoor",
                  "hellowork", "monster", "apec", "efinancialcareers")
_SOCIAL = {"facebook", "twitter", "x", "instagram", "youtube", "youtu", "tiktok", "vimeo", "pinterest",
           "threads", "medium", "spotify", "deezer", "flickr", "snapchat", "whatsapp", "t", "lnkd",
           "bsky", "mastodon", "xing", "viadeo"}
_ASSET_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|css|js|zip|mp4|mp3|webm|xml|rss|json|woff2?|ttf)$", re.I)

# offer words in the URL (path + query), lower-case
OFFER_HREF = re.compile(
    r"(jobs?\b|jobs?[-_/]|offres?|offers?|postes?\b|position|vacanc|careers?/[\w-]+|carrieres?/[\w-]+"
    r"|stages?\b|stagiaire|intern(?!ation)|/opportunit|emplois?|annonce|requisition|recrutement/)")
# offer words in the link text (accent-free, lower case)
OFFER_TEXT = re.compile(
    r"\b(stage|stagiaire|intern|internship|alternance|alternant\w*|apprenti\w*|analyste?|analyst"
    r"|assistant\w*|associate|trainee|graduate|off[- ]cycle|cdi|cdd|v\.?i\.?e"
    r"|h ?/ ?f|f ?/ ?h|m ?/ ?f|f ?/ ?m|m ?/ ?w ?/ ?d|specialist|specialiste|charge\w* d\w*|consultant"
    r"|developpeur|developer|engineer|ingenieur|controleur|juriste|auditeur|offre|job|poste|position|vacancy)\b")
STRONG_TEXT = re.compile(r"\b(stage|stagiaire|internship|intern|off[- ]cycle|alternance|apprenti\w*"
                         r"|h ?/ ?f|f ?/ ?h|m ?/ ?f|f ?/ ?m|m ?/ ?w ?/ ?d)\b")
# whole link texts that are navigation to a list, not an offer
LISTING_TEXT = re.compile(
    r"^(nos |toutes? (les |nos )?|voir (toutes |tous )?(les |nos )?|all |search |browse |rechercher (les |une )?"
    r"|see all |view all |our |current |decouvrez (nos |les )?|consulter (nos |les )?)?"
    r"(offres?|offres? d'?emplois?|offres? de stages?|offres? d'?alternance|jobs?|job offers?|emplois?|postes?"
    r"|careers?|carrieres?|opportunit\w+|stages?|internships?|vacancies|positions?|open positions"
    r"|alternances?|recrutement|metiers)( (en cours|disponibles|ouvert\w*|open|a pourvoir))?$")
SPONTANEOUS = re.compile(r"candidature spontan|spontaneous application|unsolicited|open application")
# link texts that say "open the offer" without naming it: title taken from the card
CTA_TEXT = re.compile(r"^(voir|lire|en savoir|decouvrir|postuler|candidater|apply|view|read|learn|see"
                      r"|details?|more|plus|consulter|acceder)\b")
_ID_KEYS = re.compile(r"^(annonce|id|jobid|job_id|jobId|offerid|offer_id|offreid|reqid|req_id|requisitionid"
                      r"|gh_jid|oppid|ref|reference|code|vacancyid|posting_id)$", re.I)
_NAV_CLASSES = {"menu", "navbar", "nav", "navigation", "breadcrumb", "breadcrumbs", "pagination", "pager",
                "social", "socials", "share", "sharing", "footer", "site-footer", "site-header",
                "main-menu", "mega-menu", "skip-link", "language-switcher", "lang-switcher"}
_NAV_ROLES = {"navigation", "banner", "contentinfo", "menu", "menubar"}
_CARD_TAGS = ("article", "li", "section", "main", "tr", "td")
_PUBLISHED = re.compile(r"(publi\w*|posted|mise en ligne|date de publication)\D{0,25}"
                        r"(\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2}|20\d{2}-\d{2}-\d{2})", re.I)


# ------------------------------------------------------------------ helpers
def _labels(url: str) -> list[str]:
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    return host.split(".")[:-1]          # without the TLD


def is_intermediary(url: str | None) -> bool:
    """True for intermediary job boards (JobTeaser, LinkedIn, Indeed, WTTJ...)."""
    if not url:
        return False
    return any(lab in INTERMEDIARIES for lab in _labels(url))


def intermediary_name(url: str) -> str:
    for lab in _labels(url):
        if lab in INTERMEDIARIES:
            return {"jobteaser": "JobTeaser", "linkedin": "LinkedIn", "indeed": "Indeed",
                    "welcometothejungle": "Welcome to the Jungle", "wttj": "Welcome to the Jungle",
                    "glassdoor": "Glassdoor", "hellowork": "HelloWork", "monster": "Monster",
                    "apec": "Apec", "efinancialcareers": "eFinancialCareers"}.get(lab, lab)
    return ""


def ext_id_for(url: str) -> str:
    """Stable slug of the normalised URL (host + path + query), at most 60 characters."""
    k = url_key(url)
    p = urlsplit(k)
    s = slugify(p.netloc + p.path + ("-" + p.query if p.query else ""), max_len=1000)
    if len(s) <= 60:
        return s
    h = hashlib.sha1(k.encode()).hexdigest()[:8]
    return s[-51:].strip("-") + "-" + h


def _is_social(url: str) -> bool:
    return any(lab in _SOCIAL for lab in _labels(url))


def _in_navigation(a: Tag) -> bool:
    for parent in a.parents:
        if not isinstance(parent, Tag) or parent.name in ("body", "html", "[document]"):
            break
        if parent.name == "nav":
            return True
        if (parent.get("role") or "").lower() in _NAV_ROLES:
            return True
        if parent.name in ("header", "footer") and not parent.find_parent(_CARD_TAGS):
            return True                       # page header/footer, not a card's <header>
        tokens = set((" ".join(parent.get("class") or []) + " " + (parent.get("id") or "")).lower().split())
        if tokens & _NAV_CLASSES:
            return True
    return False


def _detail_like(abs_url: str) -> bool:
    """URL points to one item: an id/code in the query or at the end of the path, or a long slug."""
    p = urlsplit(abs_url)
    if any(_ID_KEYS.match(k) and v for k, v in parse_qsl(p.query)):
        return True
    segs = [s for s in p.path.split("/") if s]
    if not segs:
        return False
    last = re.sub(r"\.(aspx?|html?|php|jsp|pdf|docx?)$", "", segs[-1], flags=re.I)
    if re.search(r"\d{3,}", last):
        return True
    if len(last) >= 6 and re.fullmatch(r"[A-Za-z0-9]+", last) and re.search(r"\d", last) and re.search(r"[A-Za-z]", last):
        return True                           # codes like VBPXW547
    return len([w for w in re.split(r"[-_+]+", last) if w]) >= 3


def _same_or_parent(abs_url: str, page_url: str) -> bool:
    """Link to the page itself (or a filter/pagination of it), or to a parent page."""
    a, p = urlsplit(url_key(abs_url)), urlsplit(url_key(page_url))
    if a.netloc != p.netloc:
        return False
    if a.path == p.path:
        return not any(_ID_KEYS.match(k) for k, _ in parse_qsl(a.query))
    return p.path.startswith(a.path.rstrip("/") + "/")


def _heading_text(el: Tag) -> str:
    h = el.find(["h1", "h2", "h3", "h4", "h5"])
    if h is None:
        h = el.find(class_=re.compile(r"title|titre|intitule|job-name", re.I))
    return clean_text(h.get_text(" ")) if h is not None else ""


def _leaf_texts(el: Tag) -> list[str]:
    return [t for t in (clean_text(s) for s in el.find_all(string=True)) if t]


def _title_for(a: Tag) -> tuple[str, str]:
    """(title, full card text) for an offer link."""
    full = clean_text(a.get_text(" "))
    title = _heading_text(a)
    if not title:
        leaves = _leaf_texts(a)
        title = leaves[0] if len(leaves) > 1 and len(full) > 90 else full
    if not title or CTA_TEXT.match(fold(title)) and len(title.split()) <= 5:
        title = ""
        for attr in ("title", "aria-label"):
            v = clean_text(a.get(attr) or "")
            if v and not re.fullmatch(r"[\d\W_]+", v) and not CTA_TEXT.match(fold(v)) and len(v) > 3:
                title = v
                break
        if not title:                         # "Voir l'offre": heading of the enclosing card
            card = a.parent
            for _ in range(4):
                if not isinstance(card, Tag) or card.name in ("body", "main"):
                    break
                title = _heading_text(card)
                if title:
                    full = clean_text(card.get_text(" "))
                    break
                card = card.parent
    card = a.find_parent(["li", "article", "tr"])
    if card is not None:
        ctx = clean_text(card.get_text(" "))
        if len(full) < len(ctx) < 800:
            full = ctx                         # card text: place, contract, date around the link
    return title[:300], full


def _jsonld_location(j: dict) -> str:
    loc = j.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc]
    out: list[str] = []
    for l in locs:
        if not isinstance(l, dict):
            continue
        a = l.get("address") or {}
        if isinstance(a, dict):
            parts = [a.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
            parts = [p.get("name") if isinstance(p, dict) else p for p in parts]
            txt = ", ".join(str(p) for p in parts if p and isinstance(p, str))
            if txt and txt not in out:
                out.append(txt)
        elif isinstance(a, str) and a not in out:
            out.append(a)
    return " ; ".join(out)


# ------------------------------------------------------------------ parser
class Parser(BaseParser):
    name = "generic"
    method = "html, lecture générique"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.intermediary_links: list[str] = []   # links to job boards seen (and not followed)

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        res.complete = False
        p = self.params(source)
        urls = [u for u in (p.get("urls") or [p.get("url") or source.get("catalog_url")]) if u]
        if not urls:
            res.status = "a_configurer"
            res.reason = "Aucun lien de page carrières n'est configuré pour cette entreprise."
            res.fix = ("Ajoute le lien de la page carrières officielle (champ « Lien du catalogue ») : "
                       "le robot la lira au prochain passage.")
            return res
        official = [u for u in urls if not is_intermediary(u)]
        if not official:
            res.status, res.reason, res.fix = "a_configurer", INTERMEDIARY_REASON, INTERMEDIARY_FIX
            return res
        found: dict[str, Offer] = {}
        for u in official:
            r = self.get(u, res)
            for off in self.extract_offers(source, r.url or u, r.text):
                _merge_into(found, off)
        res.offers = list(found.values())[:MAX_OFFERS]
        self.finish(res)
        return res

    def finish(self, res: SourceResult, prefix: str = "") -> None:
        res.status = "partiel"
        res.complete = False
        res.reason = prefix + REASON
        if not res.offers:
            res.reason += NO_LINK
            boards = sorted({intermediary_name(u) for u in self.intermediary_links} - {""})
            if boards:
                res.reason += (f" La page renvoie vers {', '.join(boards)} (site intermédiaire), "
                               "que le robot ne lit pas.")
                res.fix = ("Crée une alerte e-mail sur le site carrières officiel de l'entreprise, "
                           "ou donne-moi le lien de son portail de recrutement officiel.")

    # -------------------------------------------------------------- page
    def extract_offers(self, source: dict, page_url: str, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "lxml")
        base_tag = soup.find("base", href=True)
        base = urljoin(page_url, base_tag["href"]) if base_tag else page_url
        found: dict[str, Offer] = {}

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue
            abs_url = urljoin(base, href).split("#")[0]
            if not abs_url.startswith(("http://", "https://")):
                continue
            if is_intermediary(abs_url):
                self.intermediary_links.append(abs_url)
                continue
            if _is_social(abs_url) or _ASSET_EXT.search(urlsplit(abs_url).path):
                continue
            if _same_or_parent(abs_url, page_url) or _in_navigation(a):
                continue
            title, full = _title_for(a)
            ft = fold(title)
            if not title or len(title) < 4 or LISTING_TEXT.match(ft) or SPONTANEOUS.search(ft):
                continue
            target = fold(urlsplit(abs_url).path + "?" + urlsplit(abs_url).query)
            href_hit = bool(OFFER_HREF.search(target))
            text_hit = bool(OFFER_TEXT.search(ft))
            detail = _detail_like(abs_url)
            if not ((detail and (href_hit or text_hit))
                    or (href_hit and STRONG_TEXT.search(ft) and len(title.split()) >= 3)):
                continue
            m = _PUBLISHED.search(full)
            off = self.offer(
                source, ext_id=ext_id_for(abs_url), title=title, url=abs_url,
                description=full if full != title else "",
                published=parse_date(m.group(2)) if m else None,
            )
            _merge_into(found, off)

        for j in jsonld_jobpostings(html):
            title = clean_text(j.get("title") or j.get("name") or "")
            if not title:
                continue
            u = j.get("url") or j.get("sameAs") or ""
            u = urljoin(base, u) if isinstance(u, str) and u else page_url
            et = j.get("employmentType")
            off = self.offer(
                source, ext_id=ext_id_for(u), title=title, url=u,
                location=_jsonld_location(j),
                contract=", ".join(et) if isinstance(et, list) else str(et or ""),
                published=iso_to_date(j.get("datePosted")),
                description=clean_text(j.get("description") or "")[:4000],
                extra={"jsonld": True},
            )
            _merge_into(found, off, from_jsonld=True)
        return list(found.values())


def _merge_into(found: dict[str, Offer], off: Offer, from_jsonld: bool = False) -> None:
    """Dedupe by normalised URL; complete the first offer with what the second one knows.

    JSON-LD (structured data of the site) wins for the title and a longer description.
    """
    k = off.url_key or off.id
    old = found.get(k)
    if old is None:
        found[k] = off
        return
    if from_jsonld and off.title:
        old.title = off.title
    if from_jsonld and len(off.description) > len(old.description):
        old.description = off.description
    for f in ("location", "country", "contract", "published", "description"):
        if not getattr(old, f) and getattr(off, f):
            setattr(old, f, getattr(off, f))
