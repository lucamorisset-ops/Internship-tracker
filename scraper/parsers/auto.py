"""Auto — a company added from the site (kind "auto"): find its official catalogue, then read it.

1. params.ats already set (found on an earlier run): read that public job-board
   API directly (Greenhouse, Lever, Recruitee, Workday), no detection.
2. catalog_url / params.url is an intermediary job board (JobTeaser, LinkedIn,
   Indeed, WTTJ...) -> "a_configurer": the robot only reads official career
   sites (Luca's rule).
3. a URL is given: the ATS is recognised from the URL itself, otherwise the
   page is fetched and recognised from its links / scripts:
     SmartRecruiters, Oracle HCM, Talentsoft, Sainoo, TalentBrew -> the dedicated
       parser of the registry reads the source now, and res.source_updates
       switches the source to that kind for the next runs;
     Greenhouse, Lever, Recruitee, Workday (no dedicated parser) -> read here
       from their public APIs; the source stays "auto" with params {"ats": ...}.
   Nothing recognised -> generic reading of the page (links that look like offers).
4. no URL: public APIs are tried with slugs derived from the company name
   (SmartRecruiters, Greenhouse, Lever); the first board whose company name
   fits is used. Nothing found -> "a_configurer" with what Luca can do.

Every request goes through the fetcher (robots.txt, delays); a 404 on a
guessed slug only means "not this one".
"""
from __future__ import annotations

import html as html_module
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..http import FetchError, RobotsDisallowed
from ..models import Offer, SourceResult, fold
from . import REGISTRY, get_parser
from .base import BaseParser, clean_text, iso_to_date, parse_relative_age
from .generic import INTERMEDIARY_FIX, INTERMEDIARY_REASON, is_intermediary
from .generic import Parser as GenericParser

LABELS = {
    "smartrecruiters": "SmartRecruiters", "oracle_hcm": "Oracle Recruiting Cloud", "talentsoft": "Talentsoft",
    "sainoo": "Sainoo", "talentbrew": "TalentBrew", "greenhouse": "Greenhouse", "lever": "Lever",
    "recruitee": "Recruitee", "workday": "Workday",
}
# kinds read inside this module (not in the registry): source stays "auto" with params {"ats": kind, ...}
LOCAL_ATS = ("greenhouse", "lever", "recruitee", "workday")
KEEP_PARAMS = ("internships_only",)          # carried over when the params are replaced
JSON = {"Accept": "application/json"}
WORKDAY_SEARCHES = ["intern", "stage"]
WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 3
NOT_FOUND_REASON = "Je n'ai pas trouvé de catalogue officiel à partir du nom seul."
NOT_FOUND_FIX = ("Ajoute le lien de la page carrières officielle (champ « Lien du catalogue ») : "
                 "le robot la lira au prochain passage.")

# ------------------------------------------------------------------ detection
_SR = re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9][A-Za-z0-9_\-]*)")
_SR_API = re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_\-]+)")
_SR_WIDGET = re.compile(r"company_code['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_\-]+)")
_SR_RESERVED = {"oneclick-ui", "static", "sr-jobs", "embed", "widget", "api", "search", "jobs", "careers",
                "company", "companies", "privacy-policy", "cookie-policy", "terms-of-use"}
_ORACLE = re.compile(r"(https://[A-Za-z0-9.\-]+)/hcmUI/CandidateExperience/[A-Za-z_\-]+/sites/([A-Za-z0-9_\-]+)")
_WORKDAY = re.compile(r"https?://([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/"
                      r"(?:wday/cxs/[a-z0-9\-]+/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_\-]+)")
_GH_API = re.compile(r"boards-api(\.eu)?\.greenhouse\.io/v1/boards/([A-Za-z0-9_\-]+)")
_GH = re.compile(r"(?:boards|job-boards)(\.eu)?\.greenhouse\.io/"
                 r"(?:embed/job_board(?:/js)?\?(?:[^\"'\s<>]*?&(?:amp;)?)?for=)?([A-Za-z0-9_\-]+)")
_LEVER = re.compile(r"(?:jobs|api)\.(eu\.)?lever\.co/(?:v0/postings/)?([A-Za-z0-9_\-]+)")
_RECRUITEE = re.compile(r"https?://([a-z0-9\-]+)\.recruitee\.com")
_SAINOO = re.compile(r"https?://([a-z0-9\-]+)\.sainoo\.com")
_TS_LIST = re.compile(r"https?://[^\s\"'<>]+?/offre-de-emploi/liste-offres\.aspx[^\s\"'<>]*", re.I)
_TS_HOST = re.compile(r"https?://[a-z0-9\-]+\.talent-soft\.com", re.I)
_TB_CATEGORY = re.compile(r"https?://(?:careers|jobs)\.[a-z0-9.\-]+/(?:[^\s\"'<>]*/)?category/[^\s\"'<>]+", re.I)
_TB_MARK = re.compile(r"tbcdn\.talentbrew\.com|talentbrew", re.I)
_STUDENT = re.compile(r"student|graduate|intern|campus|stage|early|etudiant|jeune|alternan")
_SUBDOMAIN_RESERVED = {"www", "app", "api", "cdn", "static", "assets", "help", "blog", "support", "careers",
                       "docs", "status", "mail", "go", "info"}


def _detect(s: str, talentbrew: bool = False) -> tuple[str, dict] | None:
    """First known ATS whose URL pattern appears in `s` (a URL or a whole page)."""
    for m in _SR.finditer(s):
        if m.group(1).lower() not in _SR_RESERVED:
            return "smartrecruiters", {"company": m.group(1)}
    m = _SR_API.search(s) or ("smartrecruiters" in s and _SR_WIDGET.search(s)) or None
    if m:
        return "smartrecruiters", {"company": m.group(1)}
    m = _ORACLE.search(s)
    if m:
        return "oracle_hcm", {"host": m.group(1), "site": m.group(2)}
    for m in _WORKDAY.finditer(s):
        if m.group(3).lower() not in ("wday", "login", "assets"):
            return "workday", {"host": f"{m.group(1)}.{m.group(2)}.myworkdayjobs.com",
                               "tenant": m.group(1), "site": m.group(3)}
    for rx in (_GH_API, _GH):
        for m in rx.finditer(s):
            if m.group(2).lower() not in ("embed", "v1"):
                return "greenhouse", {"slug": m.group(2), **({"region": "eu"} if m.group(1) else {})}
    for m in _LEVER.finditer(s):
        if m.group(2).lower() != "v0":
            return "lever", {"slug": m.group(2), **({"region": "eu"} if m.group(1) else {})}
    for m in _RECRUITEE.finditer(s):
        if m.group(1) not in _SUBDOMAIN_RESERVED:
            return "recruitee", {"slug": m.group(1)}
    m = _TS_LIST.search(s)
    if m:
        return "talentsoft", {"urls": [html_module.unescape(m.group(0))], "max_pages": 4}
    m = _TS_HOST.search(s)
    if m:
        return "talentsoft", {"urls": [m.group(0) + "/offre-de-emploi/liste-offres.aspx"], "max_pages": 4}
    for m in _SAINOO.finditer(s):
        if m.group(1) not in _SUBDOMAIN_RESERVED:
            return "sainoo", {"url": f"https://{m.group(1)}.sainoo.com/careers"}
    if talentbrew:
        m = _TB_CATEGORY.search(s)
        if m:
            return "talentbrew", {"url": m.group(0), "max_pages": 4}
    return None


def _with_url_details(url: str, kind: str, params: dict) -> tuple[str, dict]:
    """Oracle portal link: keep the filters of the official link (facets, keyword)."""
    if kind == "oracle_hcm" and _ORACLE.search(url):
        q = parse_qsl(urlsplit(url).query)
        facets = {k: v for k, v in q if k.startswith("selected") and k.endswith(("Facet", "Facets")) and v}
        keywords = [v for k, v in q if k == "keyword" and v]
        if facets:
            params["facets"] = facets
        if keywords:
            params["keywords"] = keywords
    return kind, params


def detect_ats(url: str, html: str | None = None) -> tuple[str, dict] | None:
    """(kind, params) from the URL itself, then from the page's links, then from its raw HTML."""
    hit = _detect(url, talentbrew=True)
    if hit:
        return _with_url_details(url, *hit)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for tag in soup.find_all(["a", "iframe", "script", "link", "form", "embed", "source"]):
        for attr in ("href", "src", "data-src", "data-url", "action"):
            v = tag.get(attr)
            if isinstance(v, str) and v.strip() and not v.strip().startswith(("#", "mailto:", "javascript:")):
                links.append(urljoin(url, v.strip()))
    for link in links:
        if is_intermediary(link):
            continue
        hit = _detect(link)
        if hit:
            return _with_url_details(link, *hit)
    hit = _detect(html_module.unescape(html).replace("\\/", "/"))
    if hit:
        return hit
    if _TB_MARK.search(html):
        host = urlsplit(url).netloc
        cats = [l for l in links if "/category/" in l and urlsplit(l).netloc == host]
        cats.sort(key=lambda u: 0 if _STUDENT.search(fold(u)) else 1)
        return "talentbrew", {"url": cats[0] if cats else url, "max_pages": 4}
    return None


# ------------------------------------------------------------------ name guessing
_LEGAL = {"sa", "sas", "sasu", "se", "inc", "ltd", "llc", "plc", "gmbh", "ag", "nv", "bv", "spa", "sca"}
_GENERIC_WORDS = _LEGAL | {
    "am", "asset", "assets", "management", "managers", "group", "groupe", "capital", "partners", "gestion",
    "investment", "investments", "investissement", "investissements", "bank", "banque", "finance", "financial",
    "the", "de", "la", "le", "les", "et", "and", "of", "du", "des", "co", "company", "holding", "holdings",
    "france", "paris", "international", "global", "securities", "privee", "private"}


def name_slugs(company: str) -> list[str]:
    """'Sycomore AM' -> ['sycomoream', 'sycomore-am', 'SycomoreAM', 'sycomore']."""
    t = unicodedata.normalize("NFKD", company or "").encode("ascii", "ignore").decode().replace("&", " and ")
    words = re.findall(r"[A-Za-z0-9]+", t)
    words = [w for w in words if w.lower() not in _LEGAL] or words
    if not words:
        return []
    cands = ["".join(words).lower(), "-".join(words).lower(), "".join(words),
             words[0].lower() if len(words) > 1 and len(words[0]) >= 4 else ""]
    out: list[str] = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


def same_company(ours: str, theirs: str | None) -> bool:
    """True when the board's company name shares a distinctive word with ours (or gives no name)."""
    if not theirs:
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", fold(ours)) if w not in _GENERIC_WORDS and len(w) >= 3]
    if not words:
        return True
    compact = re.sub(r"[^a-z0-9]", "", fold(theirs))
    return any(w in compact for w in words)


# ------------------------------------------------------------------ parser
class Parser(BaseParser):
    name = "auto"
    method = "détection"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._delegate: BaseParser | None = None   # parser that read the source this run

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        if p.get("ats"):
            return self._read_local(source, p, res)
        url = str(p.get("url") or source.get("catalog_url") or "").strip()
        if not url:
            return self._guess_from_name(source, res)
        if is_intermediary(url):
            return _intermediary(res)
        found = detect_ats(url)
        page = None
        if found is None:
            page = self.get(url, res)
            final = page.url or url
            if is_intermediary(final):
                return _intermediary(res)
            found = detect_ats(final, page.text)
        if found:
            return self._use(source, found[0], found[1], res, via=f"sur {urlsplit(url).netloc}")
        return self._generic(source, page.url or url, page.text, res)

    # -------------------------------------------------------------- outcomes
    def _use(self, source: dict, kind: str, params: dict, res: SourceResult, via: str,
             data=None) -> SourceResult:
        label = LABELS.get(kind, kind)
        keep = {k: v for k, v in self.params(source).items() if k in KEEP_PARAMS}
        if kind in LOCAL_ATS:
            new_params = {**keep, "ats": kind, **params}
            res.source_updates = {"kind": "auto", "params": new_params}
            self._read_local(source, new_params, res, data=data)
            res.method = f"détection puis {res.method}"
            res.reason = f"Catalogue {label} détecté {via} : le robot lit son API publique."
            return res
        new_params = {**keep, **params}
        try:
            if kind not in REGISTRY:
                raise KeyError(kind)
            sub_parser = get_parser(kind, self.ctx)
        except (ImportError, KeyError) as e:
            res.status = "a_configurer"
            res.complete = False
            res.reason = f"Catalogue {label} détecté {via}, mais son lecteur n'est pas encore installé."
            res.fix = "Le lecteur doit être ajouté dans scraper/parsers."
            res.error = f"{type(e).__name__}: {e}"
            return res
        sub = sub_parser.read(dict(source, kind=kind, params=new_params))
        self._delegate = sub_parser
        res.ok, res.status = sub.ok, sub.status
        res.method = f"détection puis {sub.method}"
        res.urls_read += sub.urls_read
        res.details_read += sub.details_read
        res.offers = sub.offers
        res.complete = sub.complete
        note = f"Catalogue {label} détecté {via} : le robot utilisera désormais son lecteur dédié."
        res.reason = note + (" " + sub.reason if sub.reason else "")
        res.fix, res.error = sub.fix, sub.error
        res.blocked_by_robots += sub.blocked_by_robots
        res.closed_urls += sub.closed_urls
        res.page_hash = sub.page_hash or res.page_hash
        res.source_updates = {**sub.source_updates, "kind": kind, "params": new_params}
        return res

    def _generic(self, source: dict, url: str, html: str, res: SourceResult) -> SourceResult:
        gen = GenericParser(self.ctx)
        self._delegate = gen
        res.offers = gen.extract_offers(source, url, html)
        res.method = f"détection puis {gen.method}"
        gen.finish(res, prefix="Aucun logiciel de recrutement connu n'a été détecté sur cette page. ")
        return res

    def _guess_from_name(self, source: dict, res: SourceResult) -> SourceResult:
        company = source.get("company") or ""
        slugs = name_slugs(company)
        lower: list[str] = []
        for s in slugs:
            if s.lower() not in lower:
                lower.append(s.lower())

        for slug in slugs:
            data = self._probe(f"https://api.smartrecruiters.com/v1/companies/{quote(slug)}/postings?limit=1", res)
            if isinstance(data, dict) and _int(data.get("totalFound")) > 0:
                first = (data.get("content") or [{}])[0] or {}
                comp = first.get("company") or {}
                if same_company(company, comp.get("name")):
                    ident = comp.get("identifier") or slug
                    return self._found(source, "smartrecruiters", {"company": ident}, res,
                                       f"https://careers.smartrecruiters.com/{ident}")
        for slug in lower:
            data = self._probe(_gh_api(slug), res)
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if isinstance(jobs, list):
                name = next((j.get("company_name") for j in jobs if isinstance(j, dict) and j.get("company_name")), None)
                if same_company(company, name):
                    return self._found(source, "greenhouse", {"slug": slug}, res,
                                       f"https://job-boards.greenhouse.io/{slug}", data)
        for slug in lower:
            data = self._probe(_lever_api(slug), res)
            if isinstance(data, list) and data:
                return self._found(source, "lever", {"slug": slug}, res, f"https://jobs.lever.co/{slug}", data)

        res.status = "a_configurer"
        res.complete = False
        res.reason, res.fix = NOT_FOUND_REASON, NOT_FOUND_FIX
        return res

    def _found(self, source, kind, params, res, catalog, data=None) -> SourceResult:
        self._use(source, kind, params, res, via="à partir du nom de l'entreprise", data=data)
        if res.status in ("ok", "partiel"):
            res.reason += " Vérifie qu'il s'agit bien de la bonne entreprise (bouton « Ouvrir » de la source)."
        if res.source_updates and not source.get("catalog_url"):
            res.source_updates["catalog_url"] = catalog
        return res

    def _probe(self, url: str, res: SourceResult):
        """JSON of a guessed board, or None (404, robots, error, not JSON)."""
        try:
            r = self.get(url, res, headers=JSON, accept_status=(200, 404), retries=0)
        except (FetchError, RobotsDisallowed):
            return None
        if r.status != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    # -------------------------------------------------------------- public job-board APIs
    def _read_local(self, source: dict, params: dict, res: SourceResult, data=None) -> SourceResult:
        ats = params.get("ats")
        reader = {"greenhouse": self._greenhouse, "lever": self._lever,
                  "recruitee": self._recruitee, "workday": self._workday}.get(ats)
        if reader is None:
            res.ok, res.status, res.complete = False, "erreur", False
            res.reason = f"Lecteur inconnu pour ce site ({ats})."
            res.fix = "Vide le paramètre « ats » de la source : le robot refera la détection."
            return res
        res.method = f"api {LABELS[ats]}"
        reader(source, params, res, data)
        return res

    def _greenhouse(self, source, params, res, data=None) -> None:
        slug = params["slug"]
        url = _gh_api(slug, params.get("region"))
        if data is None:
            data = self.json(url, res)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            raise FetchError(url, 200, "réponse inattendue de Greenhouse")
        for j in jobs:
            if not isinstance(j, dict) or not j.get("id"):
                continue
            contract = ""
            for m in j.get("metadata") or []:
                if isinstance(m, dict) and re.search(r"employment|contract|contrat", str(m.get("name")), re.I):
                    v = m.get("value")
                    contract = ", ".join(map(str, v)) if isinstance(v, list) else str(v or "")
                    break
            res.offers.append(self.offer(
                source, ext_id=str(j["id"]), title=j.get("title") or "",
                url=j.get("absolute_url") or f"https://job-boards.greenhouse.io/{slug}/jobs/{j['id']}",
                location=(j.get("location") or {}).get("name") or "",
                contract=contract,
                published=iso_to_date(j.get("first_published")),     # updated_at is not a publication date
                description=clean_text(html_module.unescape(j.get("content") or ""))[:4000],
                extra={"ats": "greenhouse"},
            ))
        res.complete = True

    def _lever(self, source, params, res, data=None) -> None:
        slug = params["slug"]
        url = _lever_api(slug, params.get("region"))
        if data is None:
            data = self.json(url, res)
        if not isinstance(data, list):
            raise FetchError(url, 200, "réponse inattendue de Lever")
        for p in data:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            cats = p.get("categories") or {}
            location = cats.get("location") or ", ".join(cats.get("allLocations") or [])
            created = p.get("createdAt")
            published = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date()
                         if isinstance(created, (int, float)) else None)
            lists = " ".join(f"{l.get('text', '')} {clean_text(l.get('content'))}"
                             for l in (p.get("lists") or []) if isinstance(l, dict))
            desc = " ".join(x for x in (p.get("descriptionPlain") or clean_text(p.get("description")),
                                        lists, p.get("additionalPlain") or "") if x)
            res.offers.append(self.offer(
                source, ext_id=str(p["id"]), title=p.get("text") or "",
                url=p.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{p['id']}",
                location=location, country=(p.get("country") or "").upper(),
                contract=cats.get("commitment") or "", published=published,
                description=clean_text(desc)[:4000], extra={"ats": "lever"},
            ))
        res.complete = True

    def _recruitee(self, source, params, res, data=None) -> None:
        slug = params["slug"]
        url = f"https://{slug}.recruitee.com/api/offers/"
        if data is None:
            data = self.json(url, res)
        offers = data.get("offers") if isinstance(data, dict) else None
        if not isinstance(offers, list):
            raise FetchError(url, 200, "réponse inattendue de Recruitee")
        for o in offers:
            if not isinstance(o, dict) or not o.get("id"):
                continue
            location = o.get("location") or ", ".join(x for x in (o.get("city"), o.get("country")) if x)
            res.offers.append(self.offer(
                source, ext_id=str(o["id"]), title=o.get("title") or "",
                url=o.get("careers_url") or f"https://{slug}.recruitee.com/o/{o.get('slug') or o['id']}",
                location=location, country=(o.get("country_code") or "").upper(),
                contract=str(o.get("employment_type_code") or "").replace("_", " "),
                published=iso_to_date(o.get("published_at") or o.get("created_at")),
                description=clean_text(f"{o.get('description') or ''} {o.get('requirements') or ''}")[:4000],
                extra={"ats": "recruitee"},
            ))
        res.complete = True

    def _workday(self, source, params, res, data=None) -> None:
        host = str(params["host"]).replace("https://", "").replace("http://", "").strip("/")
        tenant, site = params["tenant"], params["site"]
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        found: dict[str, Offer] = {}
        res.urls_read.append(api)
        for q in params.get("searches") or WORKDAY_SEARCHES:
            offset, total = 0, None
            for _ in range(WORKDAY_MAX_PAGES):
                r = self.ctx.fetcher.request(
                    "POST", api, headers={**JSON, "Content-Type": "application/json"},
                    json_body={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": q})
                try:
                    d = r.json()
                except ValueError:
                    raise FetchError(api, r.status, "réponse qui n'est pas du JSON") from None
                posts = [x for x in (d.get("jobPostings") or []) if isinstance(x, dict)] if isinstance(d, dict) else []
                if total is None:                       # Workday gives the total on the first page only
                    total = _int(d.get("total") if isinstance(d, dict) else 0)
                for jp in posts:
                    path = jp.get("externalPath") or ""
                    if not path:
                        continue
                    bullets = [b for b in (jp.get("bulletFields") or []) if isinstance(b, str)]
                    ext = bullets[0] if bullets else path.rstrip("/").rsplit("/", 1)[-1]
                    label = jp.get("postedOn") or ""
                    found.setdefault(ext, self.offer(
                        source, ext_id=ext, title=jp.get("title") or "",
                        url=f"https://{host}/{site}{path}",
                        location=jp.get("locationsText") or "",
                        published=_workday_posted(label, self.ctx.today), published_label=label,
                        extra={"ats": "workday", "detail_api": f"https://{host}/wday/cxs/{tenant}/{site}{path}"},
                    ))
                offset += len(posts)
                if not posts or offset >= total:
                    break
        res.offers = list(found.values())
        res.complete = False                            # keyword searches only, not the whole catalogue

    # -------------------------------------------------------------- details
    def enrich(self, offer: Offer, res: SourceResult) -> None:
        if self._delegate is not None:
            return self._delegate.enrich(offer, res)
        ats = offer.extra.get("ats")
        if ats == "workday":
            api = offer.extra.get("detail_api")
            if not api:
                return
            r = self.detail_get(api, res, headers=JSON, retries=1)
            try:
                info = (r.json() or {}).get("jobPostingInfo") or {}
            except (ValueError, AttributeError):
                return
            if not offer.description and info.get("jobDescription"):
                offer.description = clean_text(info["jobDescription"])[:4000]
            if not offer.published:
                offer.published = iso_to_date(info.get("startDate"))
            if not offer.location and isinstance(info.get("location"), str):
                offer.location = clean_text(info["location"])
            return
        if ats in LOCAL_ATS and offer.description:
            return                                      # the API already gave the full text
        super().enrich(offer, res)


# ------------------------------------------------------------------ helpers
def _intermediary(res: SourceResult) -> SourceResult:
    res.status = "a_configurer"
    res.complete = False
    res.reason, res.fix = INTERMEDIARY_REASON, INTERMEDIARY_FIX
    return res


def _gh_api(slug: str, region: str | None = None) -> str:
    host = "boards-api.eu.greenhouse.io" if region == "eu" else "boards-api.greenhouse.io"
    return f"https://{host}/v1/boards/{quote(slug)}/jobs?content=true"


def _lever_api(slug: str, region: str | None = None) -> str:
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    return f"https://{host}/v0/postings/{quote(slug)}?mode=json"


def _workday_posted(label: str, today):
    t = fold(label).replace("posted", "").replace("+", "").strip()
    return parse_relative_age(t, today) if t else None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0
