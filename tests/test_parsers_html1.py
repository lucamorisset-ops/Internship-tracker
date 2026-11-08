"""Server-rendered HTML parsers: talentsoft, bnp, talentbrew, talnet, creditmutuel."""
from __future__ import annotations

from datetime import date

import pytest

from scraper.http import FetchError, RobotsDisallowed
from scraper.matching import classify
from scraper.parsers import get_parser

AMUNDI_FR = "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79"
AMUNDI_UK = "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=162"
BNP_AM = "https://group.bnpparibas/emploi-carriere/toutes-offres-emploi/stage/bnp-paribas-asset-management"
BNP_CIB = "https://group.bnpparibas/emploi-carriere/toutes-offres-emploi/stage/bnp-paribas-corporate-institutional-banking"
BLACKROCK = "https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/1"
MS = "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/"
LAFRANCAISE = ("https://recrutement.creditmutuel.fr/fr/nos_offres.html?"
               "socs=39%7C4962%7C1499%7C1497%7C4963%7C4965%7C5007%7C5008%7C1496")


def src(id_, kind, company, params, catalog_url=""):
    return {"id": id_, "kind": kind, "company": company, "params": params,
            "catalog_url": catalog_url or params.get("url") or (params.get("urls") or [""])[0]}


def by_id(res):
    return {o.ext_id: o for o in res.offers}


# --------------------------------------------------------------------- talentsoft
AMUNDI_ROUTES = {
    r"JobCountry=79&page=2$": "talentsoft_amundi_p2.html",
    r"JobCountry=79&page=3$": "talentsoft_amundi_p2.html",   # nothing new -> stop
    r"JobCountry=79$": "talentsoft_amundi_p1.html",
    r"JobCountry=162$": "talentsoft_amundi_uk.html",          # UK page 2 -> 404 -> stop
}


def amundi(max_pages=4, urls=(AMUNDI_FR, AMUNDI_UK)):
    return src("amundi", "talentsoft", "Amundi", {"urls": list(urls), "max_pages": max_pages})


def test_talentsoft_amundi_reads_pages_until_nothing_new(make_ctx):
    ctx = make_ctx(AMUNDI_ROUTES)
    p = get_parser("talentsoft", ctx)
    assert (p.name, p.method) == ("talentsoft", "html")
    res = p.read(amundi())
    assert res.ok and res.complete and res.status == "ok"
    assert [o.ext_id for o in res.offers] == ["116937", "117046", "116502", "113340", "117102"]
    assert ctx.fetcher.calls == [AMUNDI_FR, AMUNDI_FR + "&page=2", AMUNDI_FR + "&page=3",
                                 AMUNDI_UK, AMUNDI_UK + "&page=2"]
    o = by_id(res)
    first = o["116937"]
    assert first.title == "Stage - Assistant gestion multi-asset H/F"
    assert first.url == ("https://jobs.amundi.com/offre-de-emploi/"
                         "emploi-stage-assistant-gestion-multi-asset-h-f_116937.aspx")
    assert first.contract == "Stage"
    assert first.location == "Paris 15 éme, France"
    assert first.country == "FR"
    assert first.company == "Amundi" and first.source_id == "amundi"
    assert first.published is None
    assert first.extra["entity"] == "Amundi Asset Management"
    assert first.extra["reference"] == "2026-116937"
    assert o["116502"].contract == "CDI"
    london = o["117102"]
    assert (london.location, london.country) == ("Londres, Royaume-Uni", "GB")
    assert all(x.url.startswith("https://jobs.amundi.com/offre-de-emploi/") for x in res.offers)


def test_talentsoft_max_pages_reached_is_incomplete(make_ctx):
    res = get_parser("talentsoft", make_ctx(AMUNDI_ROUTES)).read(amundi(max_pages=2))
    assert len(res.offers) == 5
    assert res.complete is False and res.status == "partiel"
    assert "max_pages" in res.reason


def test_talentsoft_page_number_ignored_is_incomplete(make_ctx):
    cards = "".join(
        f'<li class="ts-offer-list-item"><h3><a class="ts-offer-list-item__title-link" '
        f'href="/offre-de-emploi/emploi-poste-{i}_{110000 + i}.aspx">Poste {i}</a></h3>'
        f'<ul class="ts-offer-list-item__description"><li>CDI</li><li>Amundi</li><li>France</li>'
        f'<li>Paris</li></ul></li>' for i in range(50))
    html = f"<html><body><ul class='ts-related-offers__row'>{cards}</ul></body></html>"
    ctx = make_ctx({r"JobCountry=79": (200, html)})
    res = get_parser("talentsoft", ctx).read(amundi(urls=[AMUNDI_FR]))
    assert len(res.offers) == 50
    assert len(ctx.fetcher.calls) == 2
    assert res.complete is False and "pagination" in res.reason


def test_talentsoft_error_on_extra_page_keeps_offers(make_ctx):
    routes = {r"JobCountry=79&page=2$": (500, "erreur"), r"JobCountry=79$": "talentsoft_amundi_p1.html"}
    res = get_parser("talentsoft", make_ctx(routes)).read(amundi(urls=[AMUNDI_FR]))
    assert len(res.offers) == 3
    assert res.ok and res.complete is False and res.status == "partiel"


def test_talentsoft_one_list_down(make_ctx):
    routes = {r"JobCountry=79&page=2$": "talentsoft_amundi_p2.html",
              r"JobCountry=79&page=3$": "talentsoft_amundi_p2.html",
              r"JobCountry=79$": "talentsoft_amundi_p1.html"}            # UK list -> 404
    res = get_parser("talentsoft", make_ctx(routes)).read(amundi())
    assert len(res.offers) == 4
    assert res.ok and res.complete is False and res.status == "partiel"
    with pytest.raises(FetchError):
        get_parser("talentsoft", make_ctx({})).read(amundi())


def test_talentsoft_fallback_links(make_ctx):
    html = ('<html><body><div class="new-list"><div class="card">'
            '<a href="/offre-de-emploi/emploi-stage-analyste-credit-h-f_117300.aspx">Stage - Analyste crédit H/F</a>'
            '<ul><li>Stage</li><li>Amundi</li><li>France</li><li>Paris</li></ul></div>'
            '<a href="/offre-de-emploi/liste-offres.aspx?page=2">2</a></div></body></html>')
    res = get_parser("talentsoft", make_ctx({r"JobCountry=79": (200, html)})).read(
        amundi(urls=[AMUNDI_FR], max_pages=1))
    assert [(o.ext_id, o.title) for o in res.offers] == [("117300", "Stage - Analyste crédit H/F")]


# --------------------------------------------------------------------- bnp
BNP_ROBOTS = {"https://group.bnpparibas": "User-agent: *\nDisallow: /*?\n"}


def bnp(urls):
    return src("bnp", "bnp", "BNP Paribas", {"urls": urls, "internships_only": True})


def test_bnp_reads_cards_without_query_string(make_ctx):
    ctx = make_ctx({r"/bnp-paribas-asset-management$": "bnp_am.html"}, robots=BNP_ROBOTS)
    res = get_parser("bnp", ctx).read(bnp([BNP_AM]))
    assert res.ok and res.complete and res.status == "ok"
    assert ctx.fetcher.calls == [BNP_AM]
    assert all("?" not in u for u in ctx.fetcher.calls)
    o = by_id(res)
    assert list(o) == ["praktikum-all-genders-im-bereich-marketing-communication-bei-asset-man",
                       "stage-assistant-gerant-actions-europeennes-hf-janvier-2027",
                       "stage-investment-specialist-multi-asset-hf"]
    de = o["praktikum-all-genders-im-bereich-marketing-communication-bei-asset-man"]
    assert de.title == "Praktikum (all genders) im Bereich Marketing & Communication bei Asset Management"
    assert de.url == ("https://group.bnpparibas/emploi-carriere/offre-emploi/"
                      "praktikum-all-genders-im-bereich-marketing-communication-bei-asset-man")
    assert (de.contract, de.location, de.country) == ("Stage", "Francfort, Hesse, Allemagne", "")
    paris = o["stage-assistant-gerant-actions-europeennes-hf-janvier-2027"]
    assert (paris.location, paris.country) == ("Paris, Île-de-France, France", "FR")
    assert o["stage-investment-specialist-multi-asset-hf"].country == "GB"
    assert paris.published is None


def test_bnp_more_offers_announced_than_shown(make_ctx):
    ctx = make_ctx({r"/bnp-paribas-asset-management$": "bnp_am.html",
                    r"/bnp-paribas-corporate-institutional-banking$": "bnp_cib.html"}, robots=BNP_ROBOTS)
    res = get_parser("bnp", ctx).read(bnp([BNP_AM, BNP_CIB]))
    assert len(res.offers) == 4                      # one CIB card is also on the AM page
    assert res.ok and res.complete is False and res.status == "partiel"
    assert "42 offres" in res.reason
    assert ctx.fetcher.calls == [BNP_AM, BNP_CIB]   # never follows ?NumPage=


def test_bnp_query_string_in_params_is_dropped(make_ctx):
    ctx = make_ctx({r"/bnp-paribas-asset-management$": "bnp_am.html"}, robots=BNP_ROBOTS)
    res = get_parser("bnp", ctx).read(bnp([BNP_AM + "?q=stage"]))
    assert len(res.offers) == 3 and ctx.fetcher.calls == [BNP_AM]


def test_bnp_fallback_links(make_ctx):
    ctx = make_ctx({r"/bnp-paribas-asset-management$": "bnp_redesign.html"}, robots=BNP_ROBOTS)
    res = get_parser("bnp", ctx).read(bnp([BNP_AM]))
    assert res.complete
    o = by_id(res)
    assert o["stage-analyste-credit-high-yield-hf"].title == "Stage - Analyste Crédit High Yield (H/F)"
    wm = o["stage-gestion-de-portefeuille-wealth-management-hf"]
    assert wm.url == ("https://group.bnpparibas/emploi-carriere/offre-emploi/"
                      "stage-gestion-de-portefeuille-wealth-management-hf")


def test_bnp_robots_on_list_propagates(make_ctx):
    ctx = make_ctx({}, robots={"https://group.bnpparibas": "User-agent: *\nDisallow: /\n"})
    with pytest.raises(RobotsDisallowed):
        get_parser("bnp", ctx).read(bnp([BNP_AM]))


# --------------------------------------------------------------------- talentbrew
def blackrock(max_pages=4):
    return src("blackrock", "talentbrew", "BlackRock", {"url": BLACKROCK, "max_pages": max_pages})


def test_talentbrew_blackrock(make_ctx):
    routes = {r"/9022304/1/2$": "talentbrew_blackrock_p2.html",
              r"/9022304/1/3$": "talentbrew_blackrock_p2.html",     # nothing new -> stop
              r"/9022304/1$": "talentbrew_blackrock_p1.html"}
    ctx = make_ctx(routes, robots={"https://careers.blackrock.com": "User-agent: *\nDisallow:/search-jobs/\n"})
    res = get_parser("talentbrew", ctx).read(blackrock())
    assert res.ok and res.complete and res.status == "ok"
    assert ctx.fetcher.calls == [BLACKROCK, BLACKROCK + "/2", BLACKROCK + "/3"]
    assert [o.ext_id for o in res.offers] == ["97150826656", "97104654800", "97162233411", "97150990012"]
    o = by_id(res)
    analyst = o["97150826656"]
    assert analyst.title == "2027 Full-Time Analyst Program - EMEA"
    assert analyst.url == ("https://careers.blackrock.com/job/london/"
                           "2027-full-time-analyst-program-emea/45831/97150826656")
    assert analyst.location.startswith("London, England, Abu Dhabi, Amsterdam,")
    assert analyst.location.endswith("Paris, Riyadh, Stockholm")
    assert analyst.country == "GB"
    assert analyst.extra["team"] == "STUDENTS AND GRADUATES"
    assert o["97104654800"].location == "London, England, Edinburgh, Paris"
    assert (o["97162233411"].location, o["97162233411"].country) == ("Paris, Ile-de-France", "FR")
    assert analyst.published is None


def test_talentbrew_404_ends_pagination(make_ctx):
    res = get_parser("talentbrew", make_ctx({r"/9022304/1$": "talentbrew_blackrock_p1.html"})).read(blackrock())
    assert len(res.offers) == 3 and res.complete


def test_talentbrew_max_pages(make_ctx):
    res = get_parser("talentbrew", make_ctx({r"/9022304/1$": "talentbrew_blackrock_p1.html"})).read(
        blackrock(max_pages=1))
    assert len(res.offers) == 3 and res.complete is False and res.status == "partiel"


# --------------------------------------------------------------------- talnet
def ms(max_pages=3):
    return src("ms", "talnet", "Morgan Stanley", {"url": MS, "max_pages": max_pages})


MS_ROUTES = {r"/adv/\?start=50$": "talnet_ms_p2.html", r"/adv/$": "talnet_ms.html"}


def test_talnet_morgan_stanley(make_ctx):
    ctx = make_ctx(MS_ROUTES)
    res = get_parser("talnet", ctx).read(ms())
    assert res.ok and res.complete and res.status == "ok"
    assert ctx.fetcher.calls == [MS, MS + "?start=50"]   # page 2 has no next link: stop
    assert [o.ext_id for o in res.offers] == ["22429", "22234", "22340", "22501"]
    o = by_id(res)
    coop = o["22429"]
    assert coop.title == "2027 Spring Investment Management Sustainability and Global Stewardship Co-Op (New York)"
    assert coop.url == ("https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/so/pm/1/pl/1/"
                        "opp/22429-2027-Spring-Investment-Management-Sustainability-and-Global-Stewardship-Co-Op-"
                        "New-York/en-GB")
    assert coop.location == "New York"
    assert o["22234"].location == "London"
    assert o["22340"].location == "Paris"
    assert coop.published is None


def test_talnet_short_page_without_next_link_is_last(make_ctx):
    html = ('<html><body><table><tbody><tr class="search_res" data-oppid="22234" data-title="Off-cycle">'
            '<td><a class="subject" href="/vx/lang-en-GB/mobile-0/brand-2/candidate/so/pm/1/pl/1/opp/22234-x/en-GB">'
            ' 2027 Investment Management Off-cycle Internship – Fixed Income </a></td><td> London </td></tr>'
            '</tbody></table></body></html>')
    ctx = make_ctx({r"/adv/$": (200, html)})
    res = get_parser("talnet", ctx).read(ms())
    assert ctx.fetcher.calls == [MS] and res.complete
    assert res.offers[0].url.startswith("https://morganstanley.tal.net/vx/")


def test_talnet_max_pages(make_ctx):
    ctx = make_ctx(MS_ROUTES)
    res = get_parser("talnet", ctx).read(ms(max_pages=1))
    assert len(res.offers) == 3 and ctx.fetcher.calls == [MS]
    assert res.complete is False and res.status == "partiel"


def test_talnet_fallback_rows(make_ctx):
    html = ('<html><body><table><tr data-oppid="22600"><td><a href="https://morganstanley.tal.net/vx/'
            'candidate/so/pm/1/pl/1/opp/22600-x/en-GB">2027 Equity Research Off-cycle Internship</a></td>'
            '<td>Paris</td></tr></table></body></html>')
    res = get_parser("talnet", make_ctx({r"/adv/$": (200, html)})).read(ms())
    assert [(o.ext_id, o.location) for o in res.offers] == [("22600", "Paris")]


# --------------------------------------------------------------------- creditmutuel
def lafrancaise():
    return src("lafrancaise", "creditmutuel", "La Française / Crédit Mutuel AM", {"url": LAFRANCAISE})


def test_creditmutuel_lafrancaise(make_ctx):
    ctx = make_ctx({r"nos_offres\.html\?socs=": "creditmutuel.html"})
    res = get_parser("creditmutuel", ctx).read(lafrancaise())
    assert res.ok and res.status == "ok"
    assert res.complete is False                     # only the 15 newest offers are shown
    assert [o.ext_id for o in res.offers] == ["116845", "117711", "117761", "117746"]
    o = by_id(res)
    taux = o["116845"]
    assert taux.title == "Stage - Assistant(e) gestion taux (F/H)"
    assert taux.url == "https://recrutement.creditmutuel.fr/fr/offre.html?annonce=116845"
    assert (taux.location, taux.contract, taux.country) == ("PARIS (75)", "Stage (6 mois)", "FR")
    assert taux.published == date(2026, 11, 5)
    assert o["117711"].location == "STRASBOURG (67)"
    assert o["117761"].contract == "CDI"
    assert o["117746"].published == date(2026, 11, 6)


def test_creditmutuel_fallback_links(make_ctx):
    html = ('<html><body><div class="offres"><div class="carte"><a href="/fr/offre.html?annonce=117800">'
            'Stage Assistant Fund Manager (F/H)</a><ul><li>PARIS (75)</li><li>Stage (6 mois)</li>'
            '<li>Date de publication : 08/11/2026</li></ul></div></div></body></html>')
    res = get_parser("creditmutuel", make_ctx({r"nos_offres": (200, html)})).read(lafrancaise())
    (off,) = res.offers
    assert (off.ext_id, off.location, off.contract, off.published) == (
        "117800", "PARIS (75)", "Stage (6 mois)", date(2026, 11, 8))


# --------------------------------------------------------------------- matching smoke checks
TODAY = date(2026, 11, 8)


def test_matching_on_parsed_offers(make_ctx):
    amundi_res = get_parser("talentsoft", make_ctx(AMUNDI_ROUTES)).read(amundi())
    a = by_id(amundi_res)
    assert classify(a["116937"], today=TODAY).relevance in ("cible", "proche")
    assert classify(a["117046"], today=TODAY).relevance in ("cible", "proche")
    assert classify(a["116502"], today=TODAY).relevance == "exclue"        # CDI
    assert classify(a["113340"], today=TODAY).relevance == "exclue"        # communication
    assert classify(a["117102"], today=TODAY).relevance in ("cible", "proche")  # Londres

    cm = by_id(get_parser("creditmutuel", make_ctx({r"nos_offres": "creditmutuel.html"})).read(lafrancaise()))
    assert classify(cm["116845"], today=TODAY).relevance in ("cible", "proche")
    assert classify(cm["117761"], today=TODAY).relevance == "exclue"
    assert classify(cm["117746"], today=TODAY).relevance == "exclue"

    m = by_id(get_parser("talnet", make_ctx(MS_ROUTES)).read(ms()))
    assert classify(m["22234"], today=TODAY).relevance in ("cible", "proche")
    assert classify(m["22429"], today=TODAY).relevance == "exclue"         # spring co-op, New York

    b = by_id(get_parser("talentbrew", make_ctx({r"/9022304/1$": "talentbrew_blackrock_p1.html"})).read(blackrock()))
    assert classify(b["97150826656"], today=TODAY).relevance == "exclue"   # graduate programme

    bnp_res = by_id(get_parser("bnp", make_ctx({r"asset-management$": "bnp_am.html"})).read(bnp([BNP_AM])))
    gerant = classify(bnp_res["stage-assistant-gerant-actions-europeennes-hf-janvier-2027"], today=TODAY,
                      assume_internship=True)
    assert gerant.relevance == "cible" and gerant.start_label == "Janvier 2027"
