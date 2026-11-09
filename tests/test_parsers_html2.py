"""Parsers sainoo, dnca, comgest, yello (HTML) and carmignac, bpifrance (browser).

Fixtures are built from the real cards captured in docs/probes.md; the
Bpifrance offer list is invented (the site was in maintenance during the
capture) following the documented URL pattern.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from conftest import FIXTURES, ROOT, fixture
from scraper.http import FetchError
from scraper.matching import classify
from scraper.parsers import get_parser
from scraper.runner import read_source

SEED = {s["id"]: s for s in json.loads((ROOT / "supabase" / "sources_seed.json").read_text("utf-8"))}


def by_id(res):
    return {o.ext_id: o for o in res.offers}


def relevance(offer, internships_only=False):
    return classify(offer, None, date(2026, 11, 8), assume_internship=internships_only).relevance


# ---------------------------------------------------------------- registry
@pytest.mark.parametrize("kind,method,details", [
    ("sainoo", "html", True), ("dnca", "html", True), ("comgest", "html", False),
    ("yello", "html", True), ("carmignac", "navigateur", False), ("bpifrance", "navigateur", True),
])
def test_registry(make_ctx, kind, method, details):
    p = get_parser(kind, make_ctx({}))
    assert p.name == kind and p.method == method and p.detail_pages is details


# ---------------------------------------------------------------- sainoo (Amiral)
def test_sainoo_cards(make_ctx):
    src = SEED["amiral"]
    ctx = make_ctx({r"amiralgestion\.sainoo\.com/careers$": "sainoo_amiral.html"})
    res = get_parser("sainoo", ctx).read(src)
    assert res.ok and res.complete and res.method == "html"
    assert res.urls_read == ["https://amiralgestion.sainoo.com/careers"]
    assert [o.ext_id for o in res.offers] == ["10279", "9461", "1131"]
    o = by_id(res)["1131"]
    assert o.title == "Stage Analyste Financier"
    assert o.url == "https://amiralgestion.sainoo.com/jobs/1131"
    assert o.location == "Paris"
    assert o.contract == "Full-time | Internship"
    assert o.description == "Deadline: on a rolling basis · Length: 6 months"
    assert o.company == "Amiral Gestion" and o.id == "amiral:1131"
    assert by_id(res)["9461"].title == "Analyste Junior – Amiral Climate Solutions (stage)"
    assert relevance(o) in ("cible", "proche")
    assert relevance(by_id(res)["10279"]) == "exclue"      # juridique / conformité


def test_sainoo_fallback_links(make_ctx):
    html = ('<div class="jobs"><a href="/jobs/77?from_careers_page=true">Stage Analyste Crédit</a>'
            '<a href="/careers">Careers</a></div>')
    ctx = make_ctx({r"sainoo\.com/careers": (200, html)})
    res = get_parser("sainoo", ctx).read(SEED["amiral"])
    assert [(o.ext_id, o.title, o.url) for o in res.offers] == [
        ("77", "Stage Analyste Crédit", "https://amiralgestion.sainoo.com/jobs/77")]


# ---------------------------------------------------------------- dnca
def test_dnca_cards(make_ctx):
    src = SEED["dnca"]
    ctx = make_ctx({r"dnca-investments\.com/carrieres\?contract=stage": "dnca_carrieres.html"})
    res = get_parser("dnca", ctx).read(src)
    assert res.ok and res.complete
    assert [o.ext_id for o in res.offers] == ["VBPXW547", "QX4TR2M9"]     # filter links ignored
    o = by_id(res)["VBPXW547"]
    assert o.title == "Stagiaire Risques de Marché et Développement"
    assert o.url == "https://www.dnca-investments.com/carrieres/VBPXW547"
    assert (o.contract, o.description, o.location) == ("Stage", "Contrôle des Risques", "Paris")
    assert o.published == date(2026, 10, 20)
    o2 = by_id(res)["QX4TR2M9"]
    assert o2.published == date(2026, 11, 5)
    assert relevance(o2, internships_only=True) == "cible"
    assert relevance(o, internships_only=True) == "exclue"                # risques


def test_dnca_fallback_links(make_ctx):
    html = ('<main><a href="/carrieres?contract=stage">Stage</a>'
            '<div><a href="https://www.dnca-investments.com/carrieres/AB12CD34">'
            '<span>Stagiaire Analyste ISR</span></a></div></main>')
    ctx = make_ctx({r"dnca-investments\.com": (200, html)})
    res = get_parser("dnca", ctx).read(SEED["dnca"])
    assert [(o.ext_id, o.title, o.url) for o in res.offers] == [
        ("AB12CD34", "Stagiaire Analyste ISR", "https://www.dnca-investments.com/carrieres/AB12CD34")]


# ---------------------------------------------------------------- comgest
COMGEST = {r"careers/internship-offers$": "comgest_internships.html",
           r"careers/job-offers$": "comgest_jobs_empty.html"}


def test_comgest_blocks(make_ctx):
    src = SEED["comgest"]
    ctx = make_ctx(COMGEST)
    parser = get_parser("comgest", ctx)
    res = parser.read(src)
    assert res.ok and res.complete and res.status == "ok"
    assert res.urls_read == src["params"]["urls"]
    assert len(res.offers) == 1
    o = res.offers[0]
    assert o.ext_id == "e29a4c1f-1d80-41a7-ae87-4e42649bcb64"
    assert o.title == "STAGIAIRE CONFORMITE ET CONTROLE INTERNE"
    assert o.url == ("https://www.comgest.com/-/media/files/jobs-and-internships/internships/"
                     "stagiaire-conformit-et-controle-interne.pdf")
    assert (o.location, o.contract, o.description) == ("Paris", "Stage (Internship)", "Comgest S.A.")
    # detail page is a PDF: enrich must not fetch anything
    calls = list(ctx.fetcher.calls)
    parser.enrich(o, res)
    assert ctx.fetcher.calls == calls and res.details_read == []
    assert relevance(o) == "exclue"                                      # conformité


def test_comgest_page_without_offer_is_valid(make_ctx):
    src = dict(SEED["comgest"], params={"urls": [SEED["comgest"]["params"]["urls"][1]]})
    res = get_parser("comgest", make_ctx(COMGEST)).read(src)
    assert res.ok and res.complete and res.offers == [] and res.status == "ok"


def test_comgest_pdf_slug_when_no_application_form(make_ctx):
    src = dict(SEED["comgest"], params={"urls": [SEED["comgest"]["params"]["urls"][1]]})
    res = get_parser("comgest", make_ctx({r"careers/job-offers$": "comgest_no_form.html"})).read(src)
    o = res.offers[0]
    assert o.ext_id == "internship-financial-analyst-talent-program"
    assert o.url == ("https://www.comgest.com/-/media/files/jobs-and-internships/internships/"
                     "internship_financial-analyst_talent-program.pdf")
    assert o.contract == "Internship"


def test_comgest_one_page_down_is_partial(make_ctx):
    ctx = make_ctx({r"careers/internship-offers$": "comgest_internships.html"})   # job-offers -> 404
    res = get_parser("comgest", ctx).read(SEED["comgest"])
    assert res.ok and not res.complete and res.status == "partiel"
    assert len(res.offers) == 1 and "job-offers" in res.reason


def test_comgest_all_pages_down_raises(make_ctx):
    with pytest.raises(FetchError):
        get_parser("comgest", make_ctx({})).read(SEED["comgest"])


# ---------------------------------------------------------------- yello (Deutsche Bank)
def test_yello_items(make_ctx):
    src = SEED["db"]
    ctx = make_ctx({r"db\.recsolu\.com/job_boards/1": "yello_db.html"})
    res = get_parser("yello", ctx).read(src)
    assert res.ok and res.complete is False          # 25 newest of "74 Results"
    assert [o.ext_id for o in res.offers] == ["wsSne9C62Ef0mymYhfNSyQ", "Kp3aQ7xR2Lm9TzVb4NcWdE",
                                              "Zr8bN1vQ6Ys0HaUe5KjXpF"]
    paris, london, frankfurt = res.offers
    assert paris.url == "https://db.recsolu.com/jobs/wsSne9C62Ef0mymYhfNSyQ"
    assert paris.title == "Deutsche Bank Graduate Programme - Investment Bank: Corporate Finance – Paris – 2027"
    assert (paris.location, paris.country) == ("Paris, France", "FR")
    assert (paris.published, paris.published_label) == (date(2026, 11, 5), "3d")
    assert (london.location, london.country) == ("London, United Kingdom", "GB")
    assert (london.published, london.published_label) == (date(2026, 11, 1), "1w")
    assert (frankfurt.location, frankfurt.country) == ("Frankfurt, Germany", "DE")
    assert relevance(london) == "cible"
    assert relevance(paris) == "exclue"              # graduate programme
    assert relevance(frankfurt) == "exclue"          # place


def test_yello_complete_when_board_shows_everything(make_ctx):
    html = fixture("yello_db.html").replace("74 Results", "3 Results")
    res = get_parser("yello", make_ctx({r"db\.recsolu\.com": (200, html)})).read(SEED["db"])
    assert len(res.offers) == 3 and res.complete is True


# ---------------------------------------------------------------- carmignac (browser)
def test_carmignac_rendered_table(make_ctx):
    src = SEED["carmignac"]
    ctx = make_ctx({}, browser_routes={r"carmignac\.com/en-fr/about-us/careers": "carmignac_rendered.html"})
    res = get_parser("carmignac", ctx).read(src)
    assert ctx.fetcher.calls == []                   # no plain GET: it only returns the JS redirect
    assert ctx.browser.calls == [src["params"]["url"]]
    assert res.ok and res.complete and res.method == "navigateur"
    assert res.urls_read == [src["params"]["url"]]
    assert [o.ext_id for o in res.offers] == ["equity-product-specialist-london",
                                              "investment-analyst-intern-global-equities-paris"]
    eps, intern = res.offers
    assert (eps.title, eps.contract, eps.location, eps.url) == (
        "Equity Product Specialist", "Permanent", "London", src["params"]["url"])
    assert (intern.contract, intern.location) == ("Internship", "Paris")
    assert relevance(intern) == "cible"
    assert relevance(eps) == "exclue"                # CDI


def test_carmignac_browser_refused_propagates(make_ctx):
    ctx = make_ctx({}, browser_routes={})            # FakeBrowser -> FetchError
    with pytest.raises(FetchError):
        get_parser("carmignac", ctx).read(SEED["carmignac"])


def test_carmignac_anti_robot_is_reported_as_resisting(make_ctx):
    class Refused:
        def render(self, url, **kw):
            raise FetchError(url, 200, "page anti-robot")

    ctx = make_ctx({})
    ctx.browser = Refused()
    res = read_source(get_parser("carmignac", ctx), SEED["carmignac"])
    assert not res.ok and res.status == "resiste"


def test_carmignac_without_offer_table_closes_nothing(make_ctx):
    ctx = make_ctx({}, browser_routes={r"carmignac": "carmignac_no_table.html"})
    res = get_parser("carmignac", ctx).read(SEED["carmignac"])
    assert res.ok and res.offers == [] and not res.complete and res.status == "partiel"


# ---------------------------------------------------------------- bpifrance (browser)
FIN = r"criteres=stage(,|%2C)finances"
CI = r"criteres=stage(,|%2C)capital-investissement"


def test_bpifrance_maintenance(make_ctx):
    src = SEED["bpifrance"]
    ctx = make_ctx({FIN: "bpifrance_maintenance.html", CI: "bpifrance_maintenance.html"},
                   browser_routes={r".": "bpifrance_finances.html"})
    res = get_parser("bpifrance", ctx).read(src)
    assert res.ok is False and res.status == "erreur"
    assert res.reason == "Le site Bpifrance Talents est en maintenance : aucune offre lisible pour l'instant."
    assert res.fix == "Rien à faire : le robot réessaiera au prochain passage."
    assert res.offers == []
    assert res.urls_read == [src["params"]["urls"][0]]
    assert ctx.browser.calls == []                   # no browser for a maintenance page


def test_bpifrance_maintenance_served_as_503(make_ctx):
    ctx = make_ctx({FIN: (503, "bpifrance_maintenance.html"), CI: (503, "bpifrance_maintenance.html")})
    res = get_parser("bpifrance", ctx).read(SEED["bpifrance"])
    assert res.status == "erreur" and "maintenance" in res.reason


def test_bpifrance_rendered_lists_are_merged(make_ctx):
    src = SEED["bpifrance"]
    ctx = make_ctx({FIN: "bpifrance_shell.html", CI: "bpifrance_shell.html"},
                   browser_routes={FIN: "bpifrance_finances.html", CI: "bpifrance_ci.html"})
    res = get_parser("bpifrance", ctx).read(src)
    assert res.ok and res.complete and res.status == "ok"
    assert ctx.browser.calls == src["params"]["urls"]
    assert len(res.urls_read) == 4                   # plain GET then browser, for each list
    assert [o.ext_id for o in res.offers] == ["9986", "10012", "10140"]
    o = by_id(res)["9986"]
    assert o.title == "Assistant gérant portefeuille cross-assets F/H"
    assert o.url == "https://talents.bpifrance.fr/opportunites/assistant-gerant-portefeuille-cross-assets-f-h/?id=9986-81"
    assert (o.contract, o.location, o.published) == ("Stage", "Paris", date(2026, 11, 4))
    o2 = by_id(res)["10012"]
    assert o2.title == "Stage - Analyste Financement Structuré F/H"
    assert (o2.contract, o2.location) == ("Stage", "Maisons-Alfort (94)")
    assert (o2.published, o2.published_label) == (date(2026, 11, 5), "Il y a 3 jours")
    o3 = by_id(res)["10140"]
    assert o3.url == ("https://talents.bpifrance.fr/opportunites/stage-analyste-capital-developpement-f-h/"
                      "?id=10140-81")
    assert (o3.location, o3.contract, o3.published) == ("Paris 9e", "Stage de 6 mois", date(2026, 11, 2))
    assert o3.description == "Démarrage janvier 2027"
    assert relevance(o, internships_only=True) == "cible"


def test_bpifrance_links_in_raw_html_need_no_browser(make_ctx):
    src = dict(SEED["bpifrance"], params={"urls": [SEED["bpifrance"]["params"]["urls"][0]],
                                          "internships_only": True})
    ctx = make_ctx({FIN: "bpifrance_finances.html"})          # no browser at all
    res = get_parser("bpifrance", ctx).read(src)
    assert res.ok and [o.ext_id for o in res.offers] == ["9986", "10012"]
    assert res.urls_read == [src["params"]["urls"][0]]


def test_bpifrance_empty_list_closes_nothing(make_ctx):
    class Browser:
        calls: list[str] = []

        def render(self, url, wait_for=None, **kw):
            self.calls.append(url)
            if "capital-investissement" in url:
                raise FetchError(url, 200, f"élément « {wait_for} » introuvable")
            return fixture("bpifrance_finances.html"), None

    ctx = make_ctx({FIN: "bpifrance_shell.html", CI: "bpifrance_shell.html"})
    ctx.browser = Browser()
    res = get_parser("bpifrance", ctx).read(SEED["bpifrance"])
    assert res.ok and len(res.offers) == 2 and res.complete is False and res.status == "ok"


def test_bpifrance_enrich_uses_rendered_offer_page(make_ctx):
    url = "https://talents.bpifrance.fr/opportunites/assistant-gerant-portefeuille-cross-assets-f-h/?id=9986-81"
    ctx = make_ctx({r"/opportunites/": "bpifrance_shell.html"},
                   browser_routes={r"/opportunites/": "bpifrance_detail.html"})
    parser = get_parser("bpifrance", ctx)
    res = parser.result(SEED["bpifrance"])
    o = parser.offer(SEED["bpifrance"], ext_id="9986", url=url,
                     title="Assistant gérant portefeuille cross-assets F/H")
    parser.enrich(o, res)
    assert res.details_read == [url, url]            # plain GET (shell), then browser
    assert "janvier 2027" in o.description
    assert "Mentions légales" not in o.description


def test_bpifrance_enrich_ignores_page_without_the_offer(make_ctx):
    ctx = make_ctx({r"/opportunites/": "bpifrance_shell.html"})   # no browser
    parser = get_parser("bpifrance", ctx)
    res = parser.result(SEED["bpifrance"])
    o = parser.offer(SEED["bpifrance"], ext_id="1", title="Stage Analyste",
                     url="https://talents.bpifrance.fr/opportunites/stage-analyste/?id=1-81")
    parser.enrich(o, res)
    assert o.description == ""


def test_fixture_files_exist():
    for name in ("sainoo_amiral.html", "dnca_carrieres.html", "comgest_internships.html",
                 "comgest_jobs_empty.html", "yello_db.html", "carmignac_rendered.html",
                 "bpifrance_maintenance.html", "bpifrance_finances.html", "bpifrance_ci.html"):
        assert (FIXTURES / name).exists(), name
