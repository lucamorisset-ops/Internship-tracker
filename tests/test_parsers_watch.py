"""Watch / blocked / generic / auto parsers (fixtures built from docs/probes.md)."""
from datetime import date

import pytest

from conftest import fixture
from scraper.http import FetchError
from scraper.parsers import get_parser
from scraper.parsers.auto import detect_ats, name_slugs, same_company
from scraper.parsers.generic import ext_id_for, is_intermediary
from scraper.parsers.page_watch import page_hash, page_text

TODAY = date(2026, 11, 8)


# --------------------------------------------------------------------------- page_watch
MONETA = {"id": "moneta", "company": "Moneta AM", "kind": "page_watch",
          "catalog_url": "https://www.moneta.fr/contact/stagiaires-apprentis",
          "params": {"url": "https://www.moneta.fr/contact/stagiaires-apprentis"}}
MONETA_ROUTE = {r"moneta\.fr/contact/stagiaires-apprentis": "page_watch_moneta.html"}


def test_page_watch_without_url_fetches_nothing(make_ctx):
    ctx = make_ctx({})
    src = {"id": "eleva", "company": "Eleva Capital", "kind": "page_watch",
           "catalog_url": "https://www.jobteaser.com/en/companies/eleva-capital/job-offers", "params": {"url": None}}
    res = get_parser("page_watch", ctx).read(src)
    assert res.ok and res.status == "sans_catalogue" and not res.complete
    assert res.reason == "Pas de page carrières officielle lisible pour cette entreprise."
    assert res.fix == "Crée une alerte e-mail (ou un suivi LinkedIn) pour être prévenu de ses offres."
    assert ctx.fetcher.calls == [] and res.offers == [] and res.page_hash == ""


def test_page_hash_ignores_whitespace_numbers_and_noise():
    html = fixture("page_watch_moneta.html")
    variant = (html.replace("8 novembre 2026", "9 décembre 2026")
                   .replace("3 candidatures", "12 candidatures")
                   .replace("version 14 du 08/11/2026", "version 15 du 09/12/2026")
                   .replace('"nonce": "a8f3c1"', '"nonce": "ffffff"')
                   .replace("© 2026", "© 2027")
                   .replace("app.4f2a9c.js", "app.99aa00.js")
                   .replace("<p>Nous recherchons", "\n\n      <p>Nous   recherchons")
                   .replace('<a href="/fonds">Nos fonds</a>', '<a href="/fonds">Nos fonds et SICAV</a>'))
    assert variant != html
    assert page_hash(variant) == page_hash(html)
    text = page_text(html)
    assert "Moneta Asset Management accueille chaque année des stagiaires" in text
    assert "cookies" not in text and "La société" not in text and "Mentions légales" not in text
    assert "2026" not in text and "novembre" not in text

    changed = html.replace("</main>", "<p>Nous recherchons un stagiaire en gestion actions pour janvier.</p></main>")
    assert page_hash(changed) != page_hash(html)


def test_page_watch_first_run_stores_hash_without_offer(make_ctx):
    res = get_parser("page_watch", make_ctx(MONETA_ROUTE)).read(MONETA)
    assert res.ok and res.status == "sans_catalogue" and not res.complete
    assert res.reason == "Pas de liste d'offres : le robot surveille la page et te prévient quand elle change."
    assert res.page_hash == page_hash(fixture("page_watch_moneta.html")) and len(res.page_hash) == 64
    assert res.offers == []
    assert res.urls_read == [MONETA["params"]["url"]]


def test_page_watch_same_hash_no_offer(make_ctx):
    src = dict(MONETA, page_hash=page_hash(fixture("page_watch_moneta.html")))
    res = get_parser("page_watch", make_ctx(MONETA_ROUTE)).read(src)
    assert res.offers == []


def test_page_watch_change_emits_one_fixed_offer(make_ctx):
    src = dict(MONETA, page_hash="0" * 64)
    res = get_parser("page_watch", make_ctx(MONETA_ROUTE)).read(src)
    assert not res.complete and res.status == "sans_catalogue"
    assert len(res.offers) == 1
    o = res.offers[0]
    assert o.ext_id == "page-20261108" and o.id == "moneta:page-20261108"
    assert o.title == "La page carrières de Moneta AM a changé"
    assert o.url == MONETA["params"]["url"]
    assert o.relevance == "proche" and o.reasons == "page modifiée depuis le dernier passage"
    assert o.start_label == "Non précisé" and o.extra == {"fixed": True}
    assert o.published == TODAY


# --------------------------------------------------------------------------- roles_watch
GS_ROBOTS = {"https://higher.gs.com": "User-agent: *\nAllow: /roles/\nDisallow: /"}
GS = {"id": "gs", "company": "Goldman Sachs", "kind": "roles_watch",
      "catalog_url": "https://higher.gs.com/campus?LOCATION=Paris|London&page=1&sort=RELEVANCE", "params": {}}


def _known(*ids):
    return [{"id": f"gs:{i}", "source_id": "gs", "url": f"https://higher.gs.com/roles/{i}", "closed": False}
            for i in ids]


def test_roles_watch_closes_gone_roles_and_keeps_open_ones(make_ctx):
    ctx = make_ctx({
        r"/roles/170877$": "gs_role_open.html",
        r"/roles/184029$": (404, "<html><title>Not Found</title></html>"),
        r"/roles/170901$": (200, "<html><body><main><h1>Sorry</h1><p>This role is no longer available.</p>"
                                 "</main></body></html>"),
    }, robots=GS_ROBOTS)
    res = get_parser("roles_watch", ctx).read(dict(GS, known_offers=_known(170877, 184029, 170901)))
    assert res.ok and res.status == "partiel" and not res.complete
    assert res.offers == []                       # never re-emitted
    assert res.closed_urls == ["https://higher.gs.com/roles/184029", "https://higher.gs.com/roles/170901"]
    assert res.reason.startswith("Le robots.txt de Goldman Sachs n'autorise que les fiches d'offres : "
                                 "le robot vérifie les offres connues mais ne peut pas découvrir les nouvelles.")
    assert "1 toujours en ligne, 2 fermée(s)" in res.reason
    assert res.fix == "Crée une alerte sur higher.gs.com (Job alerts)."
    assert len(ctx.fetcher.calls) == 3


def test_roles_watch_open_page_with_error_strings_in_scripts_stays_open(make_ctx):
    ctx = make_ctx({r"/roles/170877$": "gs_role_open.html"}, robots=GS_ROBOTS)
    res = get_parser("roles_watch", ctx).read(dict(GS, known_offers=_known(170877)))
    assert res.closed_urls == []


def test_roles_watch_without_known_offers(make_ctx):
    ctx = make_ctx({}, robots=GS_ROBOTS)
    res = get_parser("roles_watch", ctx).read(dict(GS, known_offers=[]))
    assert res.ok and res.status == "partiel" and not res.complete and res.offers == []
    assert "ne peut pas découvrir les nouvelles" in res.reason
    assert ctx.fetcher.calls == []


def test_roles_watch_all_checks_failing_raises(make_ctx):
    ctx = make_ctx({r"/roles/": (503, "busy")}, robots=GS_ROBOTS)
    with pytest.raises(FetchError):
        get_parser("roles_watch", ctx).read(dict(GS, known_offers=_known(170877, 184029)))


# --------------------------------------------------------------------------- blocked
PICTET = {"id": "pictet", "company": "Pictet", "kind": "blocked",
          "catalog_url": "https://career012.successfactors.eu/career?company=banquepict",
          "params": {"url": "https://career012.successfactors.eu/career?company=banquepict"}}


def test_blocked_robots_forbids(make_ctx):
    ctx = make_ctx({}, robots={"https://career012.successfactors.eu": "User-agent: *\nDisallow: /"})
    res = get_parser("blocked", ctx).read(PICTET)
    assert res.ok and res.status == "resiste" and not res.complete
    assert res.reason == ("Le fichier robots.txt de career012.successfactors.eu interdit aux robots toutes les "
                          "pages du catalogue (Disallow: /). Le robot respecte cette règle.")
    assert res.fix == ("Crée une alerte e-mail sur le site carrières de Pictet : "
                       "c'est la seule façon d'être prévenu.")
    assert res.blocked_by_robots == [PICTET["params"]["url"]]
    assert ctx.fetcher.calls == [] and res.offers == []


def test_blocked_robots_now_allows(make_ctx):
    ctx = make_ctx({}, robots={"https://career012.successfactors.eu": "User-agent: *\nDisallow: /admin"})
    res = get_parser("blocked", ctx).read(PICTET)
    assert res.ok and res.status == "a_configurer" and not res.complete
    assert res.reason == "Le robots.txt autorise maintenant la lecture : le lecteur de ce site peut être écrit."
    assert res.blocked_by_robots == [] and ctx.fetcher.calls == []


# --------------------------------------------------------------------------- generic
GENERIC_URL = "https://www.exemple-gestion.fr/fr/carrieres/offres"
GENERIC = {"id": "exemple", "company": "Exemple Gestion", "kind": "generic",
           "catalog_url": GENERIC_URL, "params": {"url": GENERIC_URL}}


def test_generic_finds_offer_links_and_ignores_navigation(make_ctx):
    ctx = make_ctx({r"exemple-gestion\.fr/fr/carrieres/offres$": "generic_careers.html"})
    res = get_parser("generic", ctx).read(GENERIC)
    assert res.ok and res.status == "partiel" and not res.complete
    assert res.reason == ("Lecture générique : le robot repère les liens qui ressemblent à des offres. "
                          "Les détails (contrat, date) peuvent manquer.")
    by_url = {o.url: o for o in res.offers}
    base = "https://www.exemple-gestion.fr/fr/carrieres/offres/"
    assert set(by_url) == {
        base + "stage-assistant-gerant-actions-europe-2027",
        base + "analyste-investissement-private-equity-4471?utm_source=site",
        base + "stage-analyste-credit-6-mois-2027",
    }
    a = by_url[base + "stage-assistant-gerant-actions-europe-2027"]
    assert a.title == "Stage – Assistant gérant actions Europe H/F"
    assert a.published == date(2026, 11, 5)
    assert a.ext_id == ext_id_for(a.url) and len(a.ext_id) <= 60
    cta = by_url[base + "analyste-investissement-private-equity-4471?utm_source=site"]
    assert cta.title == "Analyste Investissement Private Equity (CDI)"     # card heading, not "Voir l'offre"
    credit = by_url[base + "stage-analyste-credit-6-mois-2027"]
    assert credit.title == "Stage – Analyste Crédit (6 mois)"
    assert credit.published == date(2026, 10, 28)                           # from JSON-LD
    assert credit.location == "Paris, FR" and credit.contract == "INTERN"
    assert "janvier 2027" in credit.description
    titles = " ".join(o.title for o in res.offers).lower()
    for noise in ("spontan", "jobteaser", "linkedin", "suivant", "menu", "contrôle des risques", "trophées"):
        assert noise not in titles


def test_generic_ext_ids_are_unique_for_long_urls():
    a = ext_id_for("https://www.exemple.fr/fr/carrieres/offres-d-emploi/stage-analyste-gestion-actions-europe-a")
    b = ext_id_for("https://www.exemple.fr/fr/carrieres/offres-d-emploi/stage-analyste-gestion-actions-europe-b")
    assert a != b and len(a) <= 60 and len(b) <= 60


def test_is_intermediary():
    assert is_intermediary("https://www.jobteaser.com/en/companies/eleva-capital/job-offers")
    assert is_intermediary("https://sciencespo.jobteaser.com/fr/job-offers/123")
    assert is_intermediary("https://fr.linkedin.com/jobs/view/1")
    assert is_intermediary("https://www.welcometothejungle.com/fr/companies/x/jobs")
    assert is_intermediary("https://www.apec.fr/candidat/recherche-emploi.html")
    assert not is_intermediary("https://careers.smartrecruiters.com/SycomoreAssetManagement")
    assert not is_intermediary("https://www.capec-gestion.fr/carrieres")
    assert not is_intermediary(None)


# --------------------------------------------------------------------------- auto: detection
SR_API = r"api\.smartrecruiters\.com/v1/companies/SycomoreAssetManagement/postings\?limit=100"


def test_detect_ats_patterns():
    assert detect_ats("https://careers.smartrecruiters.com/SycomoreAssetManagement") == (
        "smartrecruiters", {"company": "SycomoreAssetManagement"})
    assert detect_ats("https://jobs.smartrecruiters.com/SycomoreAssetManagement/744000154486600-stage") == (
        "smartrecruiters", {"company": "SycomoreAssetManagement"})
    kind, p = detect_ats(
        "https://icbpjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/LazardStudentCareers/jobs"
        "?lastSelectedFacet=LOCATIONS&selectedFlexFieldsFacets=%22AttributeChar8%7CAsset%20Management%3BCorporate%22"
        "&selectedLocationsFacet=300000000798421%3B300000000798256%3B300000000798598")
    assert kind == "oracle_hcm"
    assert p == {"host": "https://icbpjb.fa.ocs.oraclecloud.com", "site": "LazardStudentCareers",
                 "facets": {"selectedFlexFieldsFacets": "\"AttributeChar8|Asset Management;Corporate\"",
                            "selectedLocationsFacet": "300000000798421;300000000798256;300000000798598"}}
    assert detect_ats("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?keyword=internship") == (
        "oracle_hcm", {"host": "https://jpmc.fa.oraclecloud.com", "site": "CX_1001", "keywords": ["internship"]})
    amundi = "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79"
    assert detect_ats(amundi) == ("talentsoft", {"urls": [amundi], "max_pages": 4})
    assert detect_ats("https://amiralgestion.sainoo.com/careers") == (
        "sainoo", {"url": "https://amiralgestion.sainoo.com/careers"})
    assert detect_ats("https://boards.greenhouse.io/exampleam") == ("greenhouse", {"slug": "exampleam"})
    assert detect_ats("https://job-boards.greenhouse.io/exampleam/jobs/4012345") == ("greenhouse", {"slug": "exampleam"})
    assert detect_ats("https://jobs.lever.co/exampleam") == ("lever", {"slug": "exampleam"})
    assert detect_ats("https://exampleam.wd3.myworkdayjobs.com/en-US/Careers") == (
        "workday", {"host": "exampleam.wd3.myworkdayjobs.com", "tenant": "exampleam", "site": "Careers"})
    assert detect_ats("https://exampleam.recruitee.com/") == ("recruitee", {"slug": "exampleam"})
    bk = "https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/1"
    assert detect_ats(bk) == ("talentbrew", {"url": bk, "max_pages": 4})
    assert detect_ats("https://www.exemple-gestion.fr/fr/carrieres") is None
    # from the page: Greenhouse embed, TalentBrew CDN with a students category link
    gh = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=exampleam"></script>'
    assert detect_ats("https://www.example.com/careers", gh) == ("greenhouse", {"slug": "exampleam"})
    tb = ('<link href="https://tbcdn.talentbrew.com/company/45831/css/site.css" rel="stylesheet">'
          '<a href="/category/experienced-jobs/45831/1/1">Experienced</a>'
          '<a href="/category/students-and-graduates-jobs/45831/9022304/1">Students</a>')
    assert detect_ats("https://careers.example.com/", tb) == (
        "talentbrew", {"url": "https://careers.example.com/category/students-and-graduates-jobs/45831/9022304/1",
                       "max_pages": 4})


def test_name_slugs_and_company_check():
    assert name_slugs("Sycomore AM") == ["sycomoream", "sycomore-am", "SycomoreAM", "sycomore"]
    assert name_slugs("Lazard Frères Gestion SAS") == [
        "lazardfreresgestion", "lazard-freres-gestion", "LazardFreresGestion", "lazard"]
    assert name_slugs("") == []
    assert same_company("Sycomore AM", "Sycomore Asset Management")
    assert not same_company("Sycomore AM", "Acme Robotics")
    assert same_company("Sycomore AM", None)


# --------------------------------------------------------------------------- auto: reading
def _auto(catalog_url=None, params=None, company="Sycomore AM"):
    return {"id": "sycomore-auto", "company": company, "kind": "auto", "catalog_url": catalog_url,
            "params": params or {}}


def test_auto_detects_smartrecruiters_from_url_and_delegates(make_ctx):
    ctx = make_ctx({SR_API: "auto_smartrecruiters.json"})
    p = get_parser("auto", ctx)
    res = p.read(_auto("https://careers.smartrecruiters.com/SycomoreAssetManagement"))
    assert res.source_updates == {"kind": "smartrecruiters", "params": {"company": "SycomoreAssetManagement"}}
    assert res.ok and res.status == "ok"
    assert {o.ext_id for o in res.offers} == {"744000154486600", "744000154965945"}
    assert all(o.source_id == "sycomore-auto" for o in res.offers)
    assert any("api.smartrecruiters.com" in u for u in res.urls_read)
    assert "SmartRecruiters" in res.reason and res.method.startswith("détection puis")
    assert type(p._delegate).__module__.endswith("smartrecruiters")      # enrich goes to the real reader


def test_auto_detects_smartrecruiters_from_the_careers_page(make_ctx):
    url = "https://www.sycomore-am.com/fr/carrieres"
    ctx = make_ctx({r"sycomore-am\.com/fr/carrieres$": "auto_sycomore_careers.html", SR_API: "auto_smartrecruiters.json"})
    res = get_parser("auto", ctx).read(_auto(url))
    assert res.urls_read[0] == url
    assert res.source_updates["kind"] == "smartrecruiters"
    assert res.source_updates["params"] == {"company": "SycomoreAssetManagement"}
    assert len(res.offers) == 2


def test_auto_refuses_jobteaser(make_ctx):
    ctx = make_ctx({})
    res = get_parser("auto", ctx).read(_auto("https://www.jobteaser.com/en/companies/eleva-capital/job-offers"))
    assert res.ok and res.status == "a_configurer" and not res.complete
    assert res.reason == "Ce lien est un site intermédiaire : le robot lit uniquement les sites carrières officiels."
    assert res.fix == "Donne le lien de la page carrières officielle de l'entreprise."
    assert ctx.fetcher.calls == [] and res.source_updates == {}


def test_auto_name_guess_finds_greenhouse_board(make_ctx):
    ctx = make_ctx({
        r"api\.smartrecruiters\.com/v1/companies/": (200, '{"offset":0,"limit":1,"totalFound":0,"content":[]}'),
        r"boards-api\.greenhouse\.io/v1/boards/sycomore-am/jobs\?content=true$": "greenhouse_jobs.json",
    })
    res = get_parser("auto", ctx).read(_auto())
    assert res.ok and res.status == "ok" and res.complete
    assert res.source_updates == {"kind": "auto", "params": {"ats": "greenhouse", "slug": "sycomore-am"},
                                  "catalog_url": "https://job-boards.greenhouse.io/sycomore-am"}
    assert len(res.offers) == 2
    o = next(o for o in res.offers if o.ext_id == "4012345")
    assert o.title == "Stage – Analyste Actions européennes (6 mois, janvier 2027)"
    assert o.url == "https://job-boards.greenhouse.io/sycomore-am/jobs/4012345"
    assert o.location == "Paris, France" and o.contract == "Internship"
    assert o.published == date(2026, 10, 20)
    assert "analyse fondamentale de small & mid caps" in o.description and "<" not in o.description
    assert "Vérifie qu'il s'agit bien de la bonne entreprise" in res.reason
    # stopped at the first hit: no Lever call, Greenhouse "sycomore" never tried
    assert not any("lever.co" in c for c in ctx.fetcher.calls)
    assert not any(c.endswith("/boards/sycomore/jobs?content=true") for c in ctx.fetcher.calls)


def test_auto_name_guess_nothing_found(make_ctx):
    ctx = make_ctx({r"api\.smartrecruiters\.com/v1/companies/": (200, '{"totalFound":0,"content":[]}')})
    res = get_parser("auto", ctx).read(_auto(company="Exemple Gestion Privée"))
    assert res.ok and res.status == "a_configurer" and not res.complete
    assert res.reason == "Je n'ai pas trouvé de catalogue officiel à partir du nom seul."
    assert res.fix == ("Ajoute le lien de la page carrières officielle (champ « Lien du catalogue ») : "
                       "le robot la lira au prochain passage.")
    assert res.offers == [] and res.source_updates == {}


def test_auto_reads_known_greenhouse_board_without_detection(make_ctx):
    ctx = make_ctx({r"boards-api\.greenhouse\.io/v1/boards/sycomore-am/jobs": "greenhouse_jobs.json"})
    res = get_parser("auto", ctx).read(_auto(params={"ats": "greenhouse", "slug": "sycomore-am"}))
    assert ctx.fetcher.calls == ["https://boards-api.greenhouse.io/v1/boards/sycomore-am/jobs?content=true"]
    assert res.ok and res.status == "ok" and res.complete and len(res.offers) == 2
    assert res.source_updates == {} and res.method == "api Greenhouse"


def test_auto_reads_lever(make_ctx):
    ctx = make_ctx({r"api\.lever\.co/v0/postings/exampleam\?mode=json": "lever_postings.json"})
    res = get_parser("auto", ctx).read(_auto(params={"ats": "lever", "slug": "exampleam"}, company="Example AM"))
    assert res.ok and res.complete and len(res.offers) == 2
    o = res.offers[0]
    assert o.title == "Equity Research Intern (6 months)" and o.contract == "Internship"
    assert o.location == "London" and o.country == "GB" and o.published == date(2026, 10, 30)
    assert "Build financial models" in o.description and "March 2027" in o.description
    assert o.url == "https://jobs.lever.co/exampleam/5f1d2c3b-aaaa-4bbb-8ccc-000000000001"


def test_auto_detects_workday_and_reads_its_api(make_ctx):
    api = r"exampleam\.wd3\.myworkdayjobs\.com/wday/cxs/exampleam/Careers/jobs$"
    detail = r"wday/cxs/exampleam/Careers/job/Paris/"
    ctx = make_ctx({api: "workday_jobs.json",
                    detail: (200, '{"jobPostingInfo":{"jobDescription":"<p>Stage de 6 mois, janvier 2027.</p>",'
                                  '"startDate":"2026-11-05","location":"Paris"}}')})
    p = get_parser("auto", ctx)
    res = p.read(_auto("https://exampleam.wd3.myworkdayjobs.com/en-US/Careers", company="Example AM"))
    assert res.source_updates == {"kind": "auto", "params": {
        "ats": "workday", "host": "exampleam.wd3.myworkdayjobs.com", "tenant": "exampleam", "site": "Careers"}}
    assert not res.complete and len(res.offers) == 2                 # two searches, deduped
    assert sum("/wday/cxs/" in c for c in ctx.fetcher.calls) == 2     # "intern" and "stage"
    o = next(o for o in res.offers if o.ext_id == "R0012345")
    assert o.url == "https://exampleam.wd3.myworkdayjobs.com/Careers/job/Paris/Stage---Analyste-Investissement-H-F_R0012345"
    assert o.published == date(2026, 11, 5) and o.published_label == "Posted 3 Days Ago"
    assert next(x for x in res.offers if x.ext_id == "R0012399").published == date(2026, 10, 9)
    p.enrich(o, res)
    assert o.description == "Stage de 6 mois, janvier 2027." and res.details_read


def test_auto_falls_back_to_generic_reading(make_ctx):
    ctx = make_ctx({r"exemple-gestion\.fr/fr/carrieres/offres$": "generic_careers.html"})
    res = get_parser("auto", ctx).read(_auto(GENERIC_URL, company="Exemple Gestion"))
    assert res.ok and res.status == "partiel" and not res.complete
    assert res.reason.startswith("Aucun logiciel de recrutement connu n'a été détecté sur cette page. Lecture générique")
    assert len(res.offers) == 3 and res.source_updates == {}
    assert ctx.fetcher.calls == ["https://www.exemple-gestion.fr/fr/carrieres/offres"]   # page read once


def test_roles_watch_role_redirecting_to_the_forbidden_search_page_is_closed(make_ctx):
    """A closed role sends to /campus, which robots.txt forbids: not read, but the role is gone."""
    from scraper.http import RobotsDisallowed

    ctx = make_ctx({r"/roles/170877$": "gs_role_open.html"}, robots=GS_ROBOTS)
    real = ctx.fetcher.request

    def request(method, url, **kw):
        if url.endswith("/roles/170901"):
            raise RobotsDisallowed("https://higher.gs.com/campus?page=1", via=url)
        return real(method, url, **kw)

    ctx.fetcher.request = request
    res = get_parser("roles_watch", ctx).read(dict(GS, known_offers=_known(170877, 170901)))
    assert res.closed_urls == ["https://higher.gs.com/roles/170901"]
    assert res.blocked_by_robots == [] and res.error == ""
    assert res.urls_read == ["https://higher.gs.com/roles/170877", "https://higher.gs.com/roles/170901"]
    assert "1 toujours en ligne, 1 fermée(s)" in res.reason
