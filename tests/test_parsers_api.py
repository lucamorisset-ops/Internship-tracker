"""JSON-API parsers: oracle_hcm, smartrecruiters, wp_job (fixtures from docs/probes.md)."""
from __future__ import annotations

import json
import re
from datetime import date

from scraper.matching import classify
from scraper.parsers import get_parser

ORACLE_LIST = r"recruitingCEJobRequisitions\?"
ORACLE_DETAIL = r"recruitingCEJobRequisitionDetails\?"

LAZARD = {"id": "lazard", "company": "Lazard Frères Gestion", "kind": "oracle_hcm",
          "params": {"host": "https://icbpjb.fa.ocs.oraclecloud.com", "site": "LazardStudentCareers",
                     "facets": {"selectedFlexFieldsFacets": "\"AttributeChar8|Asset Management;Corporate\"",
                                "selectedLocationsFacet": "300000000798421;300000000798256;300000000798598"}}}
JPM = {"id": "jpm", "company": "J.P. Morgan", "kind": "oracle_hcm",
       "params": {"host": "https://jpmc.fa.oraclecloud.com", "site": "CX_1001", "keywords": ["internship", "off-cycle"],
                  "facets": {"selectedLocationsFacet": "300000000289270;300000000289276"}}}
EDR = {"id": "edram", "company": "Edmond de Rothschild", "kind": "oracle_hcm",
       "params": {"host": "https://evht.fa.ocs.oraclecloud.eu", "site": "CX_7001",
                  "partial_note": "Edmond de Rothschild publie la plupart de ses stages sur JobTeaser, que le robot "
                                  "ne lit pas (conditions d'utilisation) : seul le portail officiel est lu."}}
SYCOMORE = {"id": "sycomore", "company": "Sycomore AM", "kind": "smartrecruiters",
            "params": {"company": "SycomoreAssetManagement"}}
MIROVA = {"id": "mirova", "company": "Mirova", "kind": "wp_job",
          "params": {"api": "https://recrutement.natixis.com/app/wp-json/wp/v2/job", "searches": ["stage", "internship"],
                     "brands": ["tax_brands-mirova", "tax_brands-mirova-us"]}}


def _parser(ctx, source):
    return get_parser(source["kind"], ctx)


def _by_id(res):
    return {o.ext_id: o for o in res.offers}


# --------------------------------------------------------------------------- oracle_hcm
def test_oracle_lazard_facets_and_fields(make_ctx):
    ctx = make_ctx({ORACLE_LIST: "oracle_lazard.json"})
    res = _parser(ctx, LAZARD).read(LAZARD)

    assert res.ok and res.status == "ok" and res.complete and res.method == "api"
    assert [o.ext_id for o in res.offers] == ["6687", "6316", "6313"]
    o = _by_id(res)["6313"]
    assert o.title == "Stage H/F - Analyste Actions – Janvier 2027"
    assert o.url == "https://icbpjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/LazardStudentCareers/job/6313"
    assert o.published == date(2026, 6, 30)
    assert o.location == "Paris, France" and o.country == "FR"
    assert o.company == "Lazard Frères Gestion" and o.source_id == "lazard"
    assert o.description == "Stage de 6 mois au sein de l'équipe d'analyse actions."   # HTML + entities cleaned
    assert _by_id(res)["6687"].published == date(2026, 10, 2)
    # one call only: 3 jobs < TotalJobsCount 3 -> paging stops
    calls = ctx.fetcher.calls
    assert len(calls) == 1
    assert ("finder=findReqs;siteNumber=LazardStudentCareers,facetsList=NONE,limit=25,offset=0,"
            "sortBy=POSTING_DATES_DESC") in calls[0]
    assert ",selectedFlexFieldsFacets=%22AttributeChar8%7CAsset%20Management%3BCorporate%22" in calls[0]
    assert ",selectedLocationsFacet=300000000798421%3B300000000798256%3B300000000798598" in calls[0]
    assert "keyword=" not in calls[0]
    assert "expand=requisitionList.secondaryLocations" in calls[0]
    assert res.urls_read == calls


def test_oracle_jpm_keywords_merged(make_ctx):
    ctx = make_ctx({r"keyword=%22internship%22": "oracle_jpm.json",
                    r"keyword=%22off-cycle%22": "oracle_jpm_offcycle.json"})
    res = _parser(ctx, JPM).read(JPM)

    calls = ctx.fetcher.calls
    assert len(calls) == 2
    assert ",keyword=%22internship%22" in calls[0] and ",keyword=%22off-cycle%22" in calls[1]
    assert all(",selectedLocationsFacet=300000000289270%3B300000000289276" in c for c in calls)
    assert res.complete is True                       # complete for the query set
    # 210802419 is in both answers: merged once
    assert sorted(o.ext_id for o in res.offers) == ["210780537", "210802076", "210802419", "210807156"]
    o = _by_id(res)["210802419"]
    assert o.location == "Paris, France; New York, NY, United States"
    assert o.country == "FR"
    assert o.published == date(2026, 10, 22)
    assert o.url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210802419"
    assert o.extra["keywords"] == ["internship", "off-cycle"]
    assert _by_id(res)["210807156"].country == "GB"


def _oracle_page(offset: int, n: int, total: int) -> tuple[int, str]:
    reqs = [{"Id": str(1000 + offset + i), "Title": f"Job {offset + i}", "PostedDate": "2026-11-01",
             "PrimaryLocation": "Paris, France", "PrimaryLocationCountry": "FR", "secondaryLocations": []}
            for i in range(n)]
    return 200, json.dumps({"items": [{"TotalJobsCount": total, "Offset": offset, "Limit": 25,
                                       "requisitionList": reqs}], "hasMore": False})


def test_oracle_paging_until_total(make_ctx):
    ctx = make_ctx({r"offset=0,": _oracle_page(0, 25, 27), r"offset=25,": _oracle_page(25, 2, 27)})
    res = _parser(ctx, LAZARD).read(LAZARD)
    assert len(res.offers) == 27 and res.complete
    assert len(ctx.fetcher.calls) == 2
    assert "offset=25," in ctx.fetcher.calls[1]


def test_oracle_paging_cap_200(make_ctx):
    routes = {rf"offset={o},": _oracle_page(o, 25, 7110) for o in range(0, 300, 25)}
    ctx = make_ctx(routes)
    res = _parser(ctx, LAZARD).read(LAZARD)
    assert len(res.offers) == 200
    assert len(ctx.fetcher.calls) == 8
    assert res.complete is False                      # 7110 jobs, only the 200 newest read


def test_oracle_empty_list_is_ok(make_ctx):
    ctx = make_ctx({ORACLE_LIST: (200, '{"items":[{"TotalJobsCount":0,"requisitionList":[]}]}')})
    res = _parser(ctx, LAZARD).read(LAZARD)
    assert res.ok and res.offers == [] and res.complete


def test_oracle_partial_note(make_ctx):
    ctx = make_ctx({ORACLE_LIST: "oracle_edr.json"})
    res = _parser(ctx, EDR).read(EDR)
    assert res.ok and res.status == "partiel"
    assert res.reason == EDR["params"]["partial_note"]
    assert res.fix == ("Active l'alerte e-mail de l'entreprise sur son site carrières "
                       "pour les offres publiées ailleurs.")
    assert res.complete is True                       # the official portal itself is read in full
    assert [o.ext_id for o in res.offers] == ["2961", "2955"]
    assert _by_id(res)["2955"].country == "LU"
    assert "keyword=" not in ctx.fetcher.calls[0] and "siteNumber=CX_7001" in ctx.fetcher.calls[0]


def test_oracle_enrich_uses_details_api(make_ctx):
    ctx = make_ctx({ORACLE_DETAIL: "oracle_jpm_detail.json",
                    r"keyword=%22internship%22": "oracle_jpm.json",
                    r"keyword=%22off-cycle%22": "oracle_jpm_offcycle.json"})
    parser = _parser(ctx, JPM)
    res = parser.read(JPM)
    o = _by_id(res)["210802419"]
    parser.enrich(o, res)

    detail = ("https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
              "?expand=all&onlyData=true&finder=ById;Id=%22210802419%22,siteNumber=CX_1001")
    assert res.details_read == [detail]
    assert ctx.fetcher.calls[-1] == detail
    assert not any("/hcmUI/" in c for c in ctx.fetcher.calls)   # never the JavaScript job page
    d = o.description
    assert d.startswith("Job Description As an Off-cycle Intern in Sales & Marketing")
    assert "January 2027" in d and "Prepare market updates and pitch books" in d
    assert "Master’s student in finance" in d
    assert "<" not in d and "&" not in d.replace("Sales & Marketing", "")
    assert o.published == date(2026, 10, 22)          # list date kept


def test_oracle_enrich_caps_description(make_ctx):
    long = {"items": [{"ExternalDescriptionStr": "<p>" + "mot " * 3000 + "</p>"}]}
    ctx = make_ctx({ORACLE_DETAIL: (200, json.dumps(long)), ORACLE_LIST: "oracle_lazard.json"})
    parser = _parser(ctx, LAZARD)
    res = parser.read(LAZARD)
    o = res.offers[0]
    parser.enrich(o, res)
    assert len(o.description) == 4000
    assert "Id=%226687%22,siteNumber=LazardStudentCareers" in res.details_read[0]


def test_oracle_html_body_is_a_fetch_error(make_ctx):
    from scraper.http import FetchError
    ctx = make_ctx({ORACLE_LIST: (200, "<html><title>Just a moment...</title></html>")})
    try:
        _parser(ctx, LAZARD).read(LAZARD)
    except FetchError as e:
        assert "anti-robot" in e.detail
    else:  # pragma: no cover
        raise AssertionError("FetchError expected")


def test_oracle_classification_smoke(make_ctx):
    ctx = make_ctx({ORACLE_LIST: "oracle_lazard.json"})
    res = _parser(ctx, LAZARD).read(LAZARD)
    o = classify(_by_id(res)["6313"], today=date(2026, 11, 8))
    assert o.relevance == "cible", o.reasons
    assert o.start_label == "Janvier 2027"

    ctx = make_ctx({r"keyword=%22internship%22": "oracle_jpm.json",
                    r"keyword=%22off-cycle%22": "oracle_jpm_offcycle.json"})
    jpm = _by_id(_parser(ctx, JPM).read(JPM))
    assert classify(jpm["210807156"], today=date(2026, 11, 8)).relevance == "exclue"   # VP, not an internship
    assert classify(jpm["210780537"], today=date(2026, 11, 8)).relevance == "exclue"   # summer internship


# --------------------------------------------------------------------------- smartrecruiters
SR_LIST = r"api\.smartrecruiters\.com/v1/companies/SycomoreAssetManagement/postings\?"


def test_smartrecruiters_list(make_ctx):
    ctx = make_ctx({SR_LIST: "smartrecruiters_sycomore.json"})
    res = _parser(ctx, SYCOMORE).read(SYCOMORE)

    assert res.ok and res.complete and res.method == "api"
    assert ctx.fetcher.calls == [
        "https://api.smartrecruiters.com/v1/companies/SycomoreAssetManagement/postings?limit=100&offset=0"]
    assert [o.ext_id for o in res.offers] == ["744000154970480", "744000154965945", "744000154486600",
                                              "744000150123456"]
    o = _by_id(res)["744000154486600"]
    assert o.title == "Stage 6 mois – Analyste Crédit"
    assert o.url == ("https://jobs.smartrecruiters.com/SycomoreAssetManagement/"
                     "744000154486600-stage-6-mois-analyste-credit")
    assert o.published == date(2026, 10, 8)
    assert o.location == "Paris, Île-de-France, France" and o.country == "FR"
    assert o.contract == "Internship"
    q = _by_id(res)["744000154970480"]
    assert q.url.endswith("/744000154970480-stage-assistant-de-gestion-quantitative-finance-data-ia-6-mois-s1-2027")
    assert _by_id(res)["744000154965945"].location == "Paris"     # no fullLocation -> city
    # the permanent middle-office job is read, then excluded by matching
    assert classify(_by_id(res)["744000150123456"], today=date(2026, 11, 8)).relevance == "exclue"


def _sr_page(offset: int, n: int, total: int) -> tuple[int, str]:
    content = [{"id": str(9000 + offset + i), "name": f"Stage {offset + i}", "releasedDate": "2026-10-01T00:00:00.000Z",
                "location": {"city": "Paris", "country": "fr"}} for i in range(n)]
    return 200, json.dumps({"offset": offset, "limit": 100, "totalFound": total, "content": content})


def test_smartrecruiters_paging(make_ctx):
    ctx = make_ctx({r"offset=0$": _sr_page(0, 100, 150), r"offset=100$": _sr_page(100, 50, 150)})
    res = _parser(ctx, SYCOMORE).read(SYCOMORE)
    assert len(res.offers) == 150 and res.complete
    assert [c.rsplit("=", 1)[1] for c in ctx.fetcher.calls] == ["0", "100"]


def test_smartrecruiters_enrich(make_ctx):
    ctx = make_ctx({r"/postings/744000154486600$": "smartrecruiters_posting.json",
                    SR_LIST: "smartrecruiters_sycomore.json"})
    parser = _parser(ctx, SYCOMORE)
    res = parser.read(SYCOMORE)
    o = _by_id(res)["744000154486600"]
    parser.enrich(o, res)

    ref = "https://api.smartrecruiters.com/v1/companies/SycomoreAssetManagement/postings/744000154486600"
    assert res.details_read == [ref] and ctx.fetcher.calls[-1] == ref
    assert o.description.startswith("Au sein de l'équipe crédit, vous participerez à l’analyse fondamentale")
    assert "Master 1 ou 2 en finance" in o.description and "Stage de 6 mois basé à Paris." in o.description
    assert "société de gestion indépendante" not in o.description       # companyDescription not used
    assert o.url == ("https://jobs.smartrecruiters.com/SycomoreAssetManagement/"
                     "744000154486600-stage-6-mois-analyste-credit-h-f-")
    assert o.ext_id == "744000154486600"
    classify(o, today=date(2026, 11, 8))
    assert o.start_label == "Janvier 2027"


# --------------------------------------------------------------------------- wp_job
WP = r"recrutement\.natixis\.com/app/wp-json/wp/v2/job\?"


def _wp_routes():
    return {r"search=stage&": "wp_natixis.json", r"search=internship&": "wp_natixis_internship.json"}


def test_wp_job_mirova(make_ctx):
    ctx = make_ctx(_wp_routes())
    res = _parser(ctx, MIROVA).read(MIROVA)

    assert res.ok and res.complete and res.method == "api"
    assert ctx.fetcher.calls == [
        "https://recrutement.natixis.com/app/wp-json/wp/v2/job?search=stage&per_page=100&page=1"
        "&_fields=id,date,title,link,class_list",
        "https://recrutement.natixis.com/app/wp-json/wp/v2/job?search=internship&per_page=100&page=1"
        "&_fields=id,date,title,link,class_list",
    ]
    # Natixis CIB (20711) and Natixis IM (20690) filtered out; 20732 in both searches -> once
    assert [o.ext_id for o in res.offers] == ["20732", "20654", "20698"]
    o = _by_id(res)["20732"]
    assert o.title == "Stage – 6 mois – Analyste Investissement F/H"
    assert o.url == "https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/"
    assert o.published == date(2026, 11, 6)
    assert o.contract == "Stage" and o.location == "Paris" and o.country == "FR"
    assert o.company == "Mirova"
    assert _by_id(res)["20654"].title == "Stage – Analyste ESG & “Impact” d’actifs naturels F/H"
    us = _by_id(res)["20698"]
    assert us.title == "Investment Analyst Internship – Spring 2027"
    assert us.contract == "Internship" and us.location == "Boston" and us.country == "US"
    assert us.extra["brands"] == ["mirova-us"]


def test_wp_job_paging_with_header_and_empty_page(make_ctx):
    routes = {r"search=stage&.*page=1&": "wp_natixis.json", r"search=stage&.*page=2&": (200, "[]"),
              r"search=internship&.*page=1&": "wp_natixis_internship.json"}
    ctx = make_ctx(routes)
    orig = ctx.fetcher.request

    def with_headers(*a, **kw):
        r = orig(*a, **kw)
        if "search=stage" in r.url:
            r.headers["x-wp-totalpages"] = "3"        # lower case, as with HTTP/2
        return r

    ctx.fetcher.request = with_headers
    res = _parser(ctx, MIROVA).read(MIROVA)
    pages = [re.search(r"search=(\w+)&.*page=(\d+)&", c).groups() for c in ctx.fetcher.calls]
    # page 2 of "stage" is empty -> stop before page 3
    assert pages == [("stage", "1"), ("stage", "2"), ("internship", "1")]
    assert len(res.offers) == 3


def test_wp_job_generic_enrich(make_ctx):
    ctx = make_ctx({r"/job/stage-6-mois-analyste-investissement-f-h/": "wp_natixis_detail.html", **_wp_routes()})
    parser = _parser(ctx, MIROVA)
    res = parser.read(MIROVA)
    o = _by_id(res)["20732"]
    parser.enrich(o, res)
    assert res.details_read == ["https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/"]
    assert "à partir de janvier 2027" in o.description
    classify(o, today=date(2026, 11, 8))
    assert o.relevance == "cible", o.reasons
