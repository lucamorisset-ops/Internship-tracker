"""JSON endpoint discovery (e): scoring, generalization, field mapping, paginated replay.

Pure functions and the browser-free replay path only; no network, no Playwright.
"""
import json

from datetime import date

from scraper import discover
from scraper.parsers import get_parser


# --------------------------------------------------------------------------- list finding & scoring
def test_find_lists_and_score_prefers_offers():
    body = {
        "jobPostings": [{"title": "Stage Analyste", "externalPath": "/x", "location": "Paris"},
                        {"title": "Stage Crédit", "externalPath": "/y", "location": "Paris"}],
        "facets": [{"id": 1, "count": 3}, {"id": 2, "count": 4}],
    }
    paths = dict(discover.find_lists(body))
    assert "$.jobPostings" in paths and "$.facets" in paths
    jobs = discover.score_candidate("$.jobPostings", body["jobPostings"])
    facets = discover.score_candidate("$.facets", body["facets"])
    assert jobs > 8 > facets          # facets have no title -> penalised


def test_best_candidates_keeps_the_offer_list():
    body = {"results": [{"jobTitle": "Stage", "id": "1"}], "misc": [{"count": 2}]}
    req = {"method": "GET", "url": "https://api.test/search?q=stage&offset=0&limit=20",
           "headers": {"Accept": "application/json", "Cookie": "sid=abc", "Referer": "https://x.test/"}}
    cands = discover.best_candidates(body, req)
    assert len(cands) == 1 and cands[0].json_path == "$.results"
    assert "cookie" not in {k.lower() for k in cands[0].headers}     # volatile header dropped
    assert cands[0].headers["Referer"] == "https://x.test/"


# --------------------------------------------------------------------------- anti-bot guard
def test_antibot_detection():
    assert discover.is_antibot("cf_clearance") and discover.is_antibot("__cf_bm")
    assert discover.antibot_in(cookies=[{"name": "sid"}, {"name": "datadome"}]) == "datadome"
    assert discover.antibot_in(cookies=[{"name": "sid"}], headers={"x-ok": "1"}) is None


# --------------------------------------------------------------------------- generalization
def test_generalize_post_body_clears_filters_and_finds_pagination():
    cand = discover.Candidate(
        method="POST", url="https://x.wd.myworkdayjobs.com/wday/cxs/x/Careers/jobs", json_path="$.jobPostings",
        post_data=json.dumps({"appliedFacets": {"locations": ["paris"]}, "searchText": "stage",
                              "limit": 20, "offset": 40}))
    g = discover.generalize_request(cand)
    body = json.loads(g.post_data)
    assert body["appliedFacets"] == {} and body["searchText"] == ""
    assert g.page == {"param": "offset", "size_param": "limit", "kind": "offset", "where": "body", "size": 20}
    # paging builds the next offset
    _url, pdata = discover.apply_page(g, 2)
    assert json.loads(pdata)["offset"] == 40


def test_generalize_get_query_clears_filters_and_pages():
    cand = discover.Candidate(method="GET", json_path="$.results",
                              url="https://api.test/jobs?q=stage&location=Paris&page=0&size=25")
    g = discover.generalize_request(cand)
    assert "q=" not in g.url and "location=" not in g.url
    assert g.page["kind"] == "page" and g.page["param"] == "page" and g.page["size"] == 25
    url2, _ = discover.apply_page(g, 3)
    assert "page=3" in url2


def test_resolve_path():
    body = {"a": {"b": [{"c": 1}, {"items": [1, 2]}]}}
    assert discover.resolve_path(body, "$.a.b[1].items") == [1, 2]
    assert discover.resolve_path(body, "$.a.missing") is None


# --------------------------------------------------------------------------- field mapping
def test_map_offer_fields_heuristic():
    item = {"jobTitle": "Stage Analyste", "requisitionId": "R123", "primaryLocation": {"name": "Paris"},
            "employmentType": "Intern", "datePosted": "2026-10-20", "externalPath": "/job/R123"}
    f = discover.map_offer_fields(item, "https://api.test")
    assert f["title"] == "Stage Analyste" and f["ext_id"] == "R123"
    assert f["location"] == "Paris" and f["contract"] == "Intern"
    assert f["url"] == "https://api.test/job/R123" and f["published"] == "2026-10-20"


# --------------------------------------------------------------------------- browser-free replay through auto
def test_auto_replays_remembered_endpoint_with_pagination(make_ctx):
    endpoint = {"method": "GET", "url": "https://api.example.com/jobs?limit=2&offset=0",
                "json_path": "$.results", "post_data": None, "headers": {},
                "page": {"param": "offset", "size_param": "limit", "kind": "offset", "where": "query", "size": 2}}
    routes = {
        r"offset=0$": (200, '{"results":[{"title":"Stage A","id":"1","url":"/o/1","datePosted":"2026-10-01"},'
                            '{"title":"Stage B","id":"2","url":"/o/2"}]}'),
        r"offset=2$": (200, '{"results":[{"title":"Stage C","id":"3","url":"/o/3"}]}'),
        r"offset=4$": (200, '{"results":[]}'),
    }
    ctx = make_ctx(routes)
    src = {"id": "x", "company": "Exemple", "kind": "auto", "params": {"endpoint": endpoint}}
    res = get_parser("auto", ctx).read(src)
    assert res.ok and res.complete and res.method == "api découverte"
    ids = sorted(o.ext_id for o in res.offers)
    assert ids == ["1", "2", "3"]
    a = next(o for o in res.offers if o.ext_id == "1")
    assert a.title == "Stage A" and a.url == "https://api.example.com/o/1" and a.published == date(2026, 10, 1)
    assert sum("offset=" in c for c in ctx.fetcher.calls) == 3          # two full pages + the empty one


def test_discover_skipped_without_browser(make_ctx):
    """Live discovery stays off unless ENABLE_BROWSER and a browser are present."""
    ctx = make_ctx({})
    p = get_parser("auto", ctx)
    assert p._discover({"id": "x", "company": "X", "params": {}}, "https://x.test", p.result({"id": "x"})) is None
