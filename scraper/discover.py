"""Automatic discovery of the JSON endpoint that loads a careers page's offers (e).

From the sole URL of a careers page, and without any human action:
  1. open the page in headless Chromium and capture every JSON response (sniff);
  2. score each list of objects by how much it looks like offers; keep the best;
  3. generalise the captured request (drop filters, find the pagination parameter);
  4. replay it directly with the polite HTTP client — no browser on the next passes.

Design choices (same guard-rails as the rest of the robot):
  * the heavy browser step runs only when ENABLE_BROWSER is true AND a browser is
    available; otherwise discovery is skipped and the generic reader takes over;
  * robots.txt and the per-host delay are obeyed before every navigation / request;
  * anonymous session cookies / CSRF tokens given to any visitor may be reused, but
    an anti-bot token (cf_clearance, datadome, _px...) is NEVER reproduced: the
    source is abandoned and logged. No CAPTCHA or login is ever solved.

Everything except the Playwright driver is pure and unit-tested on fixtures.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# words that make a JSON object look like a job offer, and list keys that hold offers
JOB_KEYS = {"title", "jobtitle", "name", "text", "postingtitle", "location", "locationstext",
            "postedon", "dateposted", "publishedat", "department", "externalpath", "applyurl",
            "hostedurl", "joburl", "url", "id", "jobid", "requisitionid", "slug"}
TITLE_KEYS = {"title", "jobtitle", "name", "text", "postingtitle"}
LIST_HINTS = {"jobs", "jobpostings", "postings", "results", "items", "content", "data", "offers",
              "positions", "openings", "vacancies", "hits", "elements"}
# request headers that must not be replayed (volatile or connection-specific)
VOLATILE_HEADERS = {"cookie", "content-length", "host", "connection", "accept-encoding",
                    "if-none-match", "if-modified-since"}
# cookies / headers minted by an anti-bot system: never reproduced -> abandon the source
ANTIBOT_MARKERS = ("cf_clearance", "__cf_bm", "datadome", "akamai", "_abck", "ak_bmsc",
                   "incap_ses", "visid_incap", "reese84", "_px", "px-", "perimeterx")
# request parameters that carry a filter / search term, cleared to get the whole catalogue
FILTER_KEYS = re.compile(r"^(q|query|keywords?|search|searchtext|term|text|facet|filters?|"
                         r"selected\w*facet\w*|location|city|contract|department)$", re.I)
# pagination parameters, in order of preference
PAGE_PARAMS = ("offset", "start", "from", "skip", "page", "pageindex", "pagenumber")
SIZE_PARAMS = ("limit", "size", "pagesize", "per_page", "perpage", "count")

SEARCH_INPUTS = ("input[type=search], input[name*=search i], input[name*=keyword i], "
                 "input[placeholder*=recherch i], input[placeholder*=search i]")
CLICK_TARGETS = ["Rechercher", "Search", "Voir les offres", "Toutes les offres", "Voir toutes",
                 "Load more", "Voir plus", "Afficher plus", "Suivant", "Next"]


# ------------------------------------------------------------------ candidate model
@dataclass
class Candidate:
    method: str
    url: str
    json_path: str
    post_data: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    n_items: int = 0
    score: float = 0.0
    page: dict[str, Any] | None = None     # pagination descriptor, set by generalize_request

    def as_params(self) -> dict:
        """What is stored in sources.params to replay this endpoint without a browser."""
        return {"method": self.method, "url": self.url, "json_path": self.json_path,
                "post_data": self.post_data, "headers": self.headers, "page": self.page}


# ------------------------------------------------------------------ list finding & scoring
def find_lists(obj: Any, path: str = "$") -> list[tuple[str, list]]:
    """Every list of dict objects in a JSON value, with its JSON path."""
    out: list[tuple[str, list]] = []
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj[:5]):
        out.append((path, obj))
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += find_lists(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            out += find_lists(v, f"{path}[{i}]")
    return out


def score_candidate(path: str, items: list) -> float:
    """How much a list looks like job offers: shared offer-ish keys + size + list name."""
    keys = {str(k).lower() for it in items[:10] if isinstance(it, dict) for k in it}
    s = 3 * len(keys & JOB_KEYS) + min(len(items), 50) / 10
    last = path.split(".")[-1].split("[")[0].lower()
    if last in LIST_HINTS:
        s += 3
    if not (keys & TITLE_KEYS):     # no title anywhere -> almost certainly not offers
        s -= 10
    return round(s, 2)


def best_candidates(body: Any, request: dict) -> list[Candidate]:
    """Scored candidates (score > 8) from one captured JSON response."""
    out: list[Candidate] = []
    for path, items in find_lists(body):
        sc = score_candidate(path, items)
        if sc > 8:
            out.append(Candidate(
                method=request.get("method", "GET"), url=request.get("url", ""),
                json_path=path, post_data=request.get("post_data"),
                headers=replayable_headers(request.get("headers") or {}),
                n_items=len(items), score=sc))
    return out


def replayable_headers(headers: dict) -> dict:
    """Keep only non-volatile headers (Content-Type, Accept, Referer, Origin, stable x-*)."""
    return {k: v for k, v in headers.items() if k.lower() not in VOLATILE_HEADERS}


# ------------------------------------------------------------------ anti-bot guard
def is_antibot(name: str) -> bool:
    n = (name or "").lower()
    return any(m in n for m in ANTIBOT_MARKERS)


def antibot_in(cookies: list[dict] | None = None, headers: dict | None = None) -> str | None:
    """Name of the first anti-bot cookie/header seen, or None. Its presence => abandon."""
    for c in cookies or []:
        if isinstance(c, dict) and is_antibot(c.get("name", "")):
            return c.get("name")
    for k in headers or {}:
        if is_antibot(k):
            return k
    return None


# ------------------------------------------------------------------ JSON path
def resolve_path(obj: Any, path: str) -> Any:
    """Follow a path produced by find_lists ('$.a.b[0].c') through a JSON value."""
    cur = obj
    for token in re.findall(r"\.([^.\[]+)|\[(\d+)\]", path):
        key, idx = token
        try:
            cur = cur[key] if key else cur[int(idx)]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


# ------------------------------------------------------------------ generalization
def _clear_query_filters(url: str) -> str:
    p = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not FILTER_KEYS.match(k)]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(kept), ""))


def _clear_body_filters(body: Any) -> Any:
    if isinstance(body, dict):
        out = {}
        for k, v in body.items():
            kl = k.lower()
            if kl in ("appliedfacets", "facets", "filters"):
                out[k] = {} if isinstance(v, dict) else []
            elif kl in ("searchtext", "q", "query", "keyword", "keywords", "term", "text"):
                out[k] = "" if isinstance(v, str) else v
            else:
                out[k] = v
        return out
    return body


def _find_page_params(keys) -> dict[str, Any] | None:
    lower = {str(k).lower(): k for k in keys}
    page_key = next((lower[p] for p in PAGE_PARAMS if p in lower), None)
    if not page_key:
        return None
    size_key = next((lower[s] for s in SIZE_PARAMS if s in lower), None)
    kind = "page" if page_key.lower() in ("page", "pageindex", "pagenumber") else "offset"
    return {"param": page_key, "size_param": size_key, "kind": kind}


def generalize_request(candidate: Candidate, page_size: int = 20) -> Candidate:
    """Return a copy with filters cleared and the pagination parameter detected.

    The captured request often carries the filter the user clicked; we never replay
    the click, we clear the filter directly and page through the whole catalogue.
    """
    method, url, post_data = candidate.method, candidate.url, candidate.post_data
    page: dict[str, Any] | None = None

    body: Any = None
    if post_data:
        try:
            body = json.loads(post_data)
        except (ValueError, TypeError):
            body = None

    if isinstance(body, dict):
        body = _clear_body_filters(body)
        pp = _find_page_params(body.keys())
        if pp:
            pp["where"] = "body"
            size = body.get(pp["size_param"]) if pp["size_param"] else None
            pp["size"] = int(size) if isinstance(size, int) else page_size
            page = pp
        post_data = json.dumps(body)
    else:
        url = _clear_query_filters(url)
        q = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        pp = _find_page_params(q.keys())
        if pp:
            pp["where"] = "query"
            size = q.get(pp["size_param"]) if pp["size_param"] else None
            pp["size"] = int(size) if (size and str(size).isdigit()) else page_size
            page = pp

    return Candidate(method=method, url=url, json_path=candidate.json_path, post_data=post_data,
                     headers=dict(candidate.headers), n_items=candidate.n_items,
                     score=candidate.score, page=page)


def apply_page(candidate: Candidate, index: int) -> tuple[str, str | None]:
    """(url, post_data) for page number `index` (0-based), given the pagination descriptor."""
    page = candidate.page
    if not page:
        return candidate.url, candidate.post_data
    size = page.get("size") or 20
    value = index if page["kind"] == "page" else index * size
    if page["where"] == "body":
        body = json.loads(candidate.post_data or "{}")
        body[page["param"]] = value
        return candidate.url, json.dumps(body)
    p = urlsplit(candidate.url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != page["param"]]
    q.append((page["param"], str(value)))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), "")), candidate.post_data


# ------------------------------------------------------------------ field mapping
FIELD_ALIASES = {
    "title": ("title", "jobtitle", "name", "text", "postingtitle", "job_title"),
    "ext_id": ("id", "jobid", "requisitionid", "slug", "externalpath", "reference", "ref"),
    "url": ("hostedurl", "joburl", "applyurl", "url", "absolute_url", "externalpath", "canonicalurl"),
    "location": ("locationstext", "location", "locationname", "primarylocation", "city", "place"),
    "contract": ("employmenttype", "contracttype", "type", "commitment", "worktype"),
    "published": ("dateposted", "postedon", "publishedat", "createdat", "posteddate", "firstpublished"),
    "description": ("descriptionplain", "description", "jobdescription", "content", "summary"),
}


def _lower_map(item: dict) -> dict:
    return {str(k).lower(): v for k, v in item.items()}


def _flat(v: Any) -> str:
    if isinstance(v, dict):
        for k in ("name", "label", "text", "value"):
            if isinstance(v.get(k), str):
                return v[k]
        return ""
    if isinstance(v, list):
        return ", ".join(_flat(x) for x in v if _flat(x))
    return str(v) if v not in (None, "") else ""


def map_offer_fields(item: dict, base_url: str) -> dict:
    """Heuristic mapping of one JSON object to the common offer fields."""
    low = _lower_map(item)
    out: dict[str, Any] = {}
    for field_name, aliases in FIELD_ALIASES.items():
        for a in aliases:
            if a in low and low[a] not in (None, ""):
                out[field_name] = _flat(low[a]) if field_name != "published" else low[a]
                break
    if out.get("url"):
        out["url"] = urljoin(base_url, str(out["url"]))
    return out


# ------------------------------------------------------------------ Playwright driver (gated)
def browser_enabled() -> bool:
    return (os.environ.get("ENABLE_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"))


def sniff_job_endpoints(url: str, user_agent: str, *, allowed=None, max_actions: int = 6,
                        timeout_ms: int = 45000, executable_path: str | None = None
                        ) -> tuple[list[Candidate], list[dict], str]:
    """Open `url` in headless Chromium, capture JSON responses, return (candidates, cookies, html).

    `allowed(u)` (optional) must return False for a URL robots.txt forbids: such a
    request is aborted and never loaded. `executable_path` (or PW_EXECUTABLE_PATH)
    points at a Chromium binary when the default download is not present. Requires
    Playwright + ENABLE_BROWSER; raises RuntimeError otherwise.
    """
    if not browser_enabled():
        raise RuntimeError("découverte navigateur désactivée (ENABLE_BROWSER)")
    from playwright.sync_api import sync_playwright  # heavy, imported lazily

    exe = executable_path or os.environ.get("PW_EXECUTABLE_PATH") or None
    captured: list[Candidate] = []

    def on_response(resp) -> None:
        if "json" not in (resp.headers.get("content-type") or "").lower():
            return
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            return
        req = resp.request
        captured.extend(best_candidates(body, {
            "method": req.method, "url": resp.url, "post_data": req.post_data,
            "headers": dict(req.headers)}))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({"executable_path": exe} if exe else {}))
        ctx = browser.new_context(user_agent=user_agent, locale="fr-FR")
        page = ctx.new_page()
        if allowed is not None:
            page.route("**/*", lambda route: (route.abort() if route.request.url.startswith("http")
                                              and not allowed(route.request.url) else route.continue_()))
        page.on("response", on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
            _explore(page, captured, max_actions, timeout_ms)   # 4.2: trigger filters if needed
            cookies = ctx.cookies()
            html = page.content()
        finally:
            browser.close()

    best: dict[tuple, Candidate] = {}
    for c in sorted(captured, key=lambda c: -c.score):
        best.setdefault((c.method, c.url.split("?")[0], c.json_path), c)
    return list(best.values()), cookies, html


def _explore(page, captured: list, max_actions: int, timeout_ms: int) -> None:
    """4.2 — bounded automatic interactions when nothing was captured on load."""
    actions = 0
    if not captured:
        box = page.locator(SEARCH_INPUTS).first
        if box.count() and box.is_visible():
            box.fill("stage")
            box.press("Enter")
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            actions += 1
    for label in CLICK_TARGETS:
        if captured or actions >= max_actions:
            break
        btn = page.get_by_role("button", name=label).or_(page.get_by_role("link", name=label)).first
        if btn.count() and btn.is_visible():
            btn.click()
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            page.wait_for_timeout(1200)
            actions += 1
    if not captured and actions < max_actions:
        cb = page.locator("[class*=filter i] input[type=checkbox], "
                          "[class*=facet i] input[type=checkbox]").first
        if cb.count() and cb.is_visible():
            cb.check()
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
