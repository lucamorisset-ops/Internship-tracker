"""Whole catalogue through the real runner: every source of supabase/sources_seed.json,
every parser, the real params, the real robots.txt rules (docs/probes.md), no network.

The LocalStore starts as setup.sql leaves Supabase: seed sources in status
"a_configurer" plus offers already known from the old tracker, built by
scripts/make_setup_sql.py. Each catalogue / API URL is served from tests/fixtures.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date

import scraper.runner as runner
from conftest import ROOT, FakeBrowser, FakeFetcher
from scraper.http import Fetcher, RobotsDisallowed
from scraper.notify import Notifier
from scraper.store import LocalStore

SEED = json.loads((ROOT / "supabase" / "sources_seed.json").read_text("utf-8"))
_spec = importlib.util.spec_from_file_location("make_setup_sql", ROOT / "scripts" / "make_setup_sql.py")
make_setup_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_setup_sql)

MS_URL = "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/"
GENERIC_URL = "https://www.exemple-gestion.fr/fr/carrieres/offres"

ROBOTS = {  # real rules captured on 08/11/2026 (docs/probes.md)
    "https://career012.successfactors.eu": "User-agent: *\nDisallow: /\nDisallow: /*company\nAllow: /login\n",
    "https://higher.gs.com": "User-agent: *\nAllow: /roles/\n\nUser-agent: *\nDisallow: /\n",
    "https://morganstanley.tal.net": ("User-agent: *\nDisallow: /*/agent/\nDisallow: /*/ats/\nDisallow: /*/channel/\n"
                                      "Crawl-delay: 10\nUser-agent: ClaudeBot\nUser-agent: GPTBot\nDisallow: /\n"),
    "https://group.bnpparibas": "User-agent: *\nDisallow: *?as_url_id*\nDisallow: *?ref*\nDisallow: *?NumPage*\n"
                                "Disallow: *?$\nDisallow: *?q\n",
    "https://careers.blackrock.com": "User-agent: *\nDisallow:/search-jobs/\n",
    "https://recrutement.natixis.com": "User-agent: *\nDisallow: /lieu/\nDisallow: /location/\nDisallow: /emploi/\n"
                                       "Disallow: /entreprise/\nDisallow: /emplois/\nDisallow: /category/\n",
    "https://recrutement.creditmutuel.fr": "User-agent: *\nAllow: /\nDisallow: /*message.html\nDisallow: /*_tabi=\n"
                                           "Disallow: /*_pid=\nDisallow: /*_fid=\n",
    "https://www.comgest.com": "User-agent: *\nDisallow: /-/media/feature/data/fund-documentation/\n",
    "https://www.dnca-investments.com": "User-agent: *\nDisallow: /admin\n",
    "https://amiralgestion.sainoo.com": "User-agent: *\nAllow: /\n",
}

ROUTES = {
    r"amiralgestion\.sainoo\.com/careers$": "sainoo_amiral.html",
    r"dnca-investments\.com/carrieres\?contract=stage$": "dnca_carrieres.html",
    r"natixis\.com/app/wp-json/wp/v2/job\?search=stage&per_page=100&page=1&": "wp_natixis.json",
    r"natixis\.com/app/wp-json/wp/v2/job\?search=internship&per_page=100&page=1&": "wp_natixis_internship.json",
    r"natixis\.com/job/stage-6-mois-analyste-investissement-f-h/$": "wp_natixis_detail.html",
    r"JobCountry=79&page=2$": "talentsoft_amundi_p2.html",
    r"JobCountry=79&page=3$": "talentsoft_amundi_p2.html",
    r"JobCountry=79$": "talentsoft_amundi_p1.html",
    r"JobCountry=162$": "talentsoft_amundi_uk.html",
    r"creditmutuel\.fr/fr/nos_offres\.html\?socs=": "creditmutuel.html",
    r"comgest\.com/en/about-us/our-people/careers/internship-offers$": "comgest_internships.html",
    r"comgest\.com/en/about-us/our-people/careers/job-offers$": "comgest_jobs_empty.html",
    r"api\.smartrecruiters\.com/v1/companies/SycomoreAssetManagement/postings\?limit=100&offset=0$":
        "smartrecruiters_sycomore.json",
    r"api\.smartrecruiters\.com/v1/companies/SycomoreAssetManagement/postings/744000154486600$":
        "smartrecruiters_posting.json",
    r"api\.smartrecruiters\.com/v1/companies/[^/]+/postings\?limit=1$": (200, '{"totalFound":0,"content":[]}'),
    r"evht\.fa\.ocs\.oraclecloud\.eu/hcmRestApi/resources/latest/recruitingCEJobRequisitions\?": "oracle_edr.json",
    r"icbpjb\.fa\.ocs\.oraclecloud\.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions\?": "oracle_lazard.json",
    r"jpmc\.fa\.oraclecloud\.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails\?.*%22210802419%22":
        "oracle_jpm_detail.json",
    r"jpmc\.fa\.oraclecloud\.com/hcmRestApi/.*recruitingCEJobRequisitions\?.*keyword=%22internship%22": "oracle_jpm.json",
    r"jpmc\.fa\.oraclecloud\.com/hcmRestApi/.*recruitingCEJobRequisitions\?.*keyword=%22off-cycle%22":
        "oracle_jpm_offcycle.json",
    r"moneta\.fr/contact/stagiaires-apprentis$": "page_watch_moneta.html",
    r"/stage/bnp-paribas-asset-management$": "bnp_am.html",
    r"/stage/bnp-paribas-corporate-institutional-banking$": "bnp_cib.html",
    r"/stage/bnp-paribas-wealth-management$": "bnp_redesign.html",
    r"/stage/portzamparc$": "bnp_cib.html",
    r"/adv/\?start=50$": "talnet_ms_p2.html",
    r"/adv/$": "talnet_ms.html",
    r"/9022304/1/2$": "talentbrew_blackrock_p2.html",
    r"/9022304/1/3$": "talentbrew_blackrock_p2.html",
    r"/9022304/1$": "talentbrew_blackrock_p1.html",
    r"higher\.gs\.com/roles/170877$": "gs_role_open.html",
    r"higher\.gs\.com/roles/184029$": (404, "<html><title>Not Found</title></html>"),
    r"db\.recsolu\.com/job_boards/1\?locale=en$": "yello_db.html",
    r"talents\.bpifrance\.fr/": "bpifrance_shell.html",          # lists and offer pages need JavaScript
    r"sycomore-am\.com/fr/carrieres$": "auto_sycomore_careers.html",
    r"exemple-gestion\.fr/fr/carrieres/offres$": "generic_careers.html",
}
BROWSER = {
    r"carmignac\.com/en-fr/about-us/careers$": "carmignac_rendered.html",
    r"criteres=stage(,|%2C)finances": "bpifrance_finances.html",
    r"criteres=stage(,|%2C)capital-investissement": "bpifrance_ci.html",
    r"talents\.bpifrance\.fr/opportunites/": "bpifrance_detail.html",
}


class SiteFetcher(FakeFetcher):
    """FakeFetcher + one Goldman Sachs role that redirects to /campus (forbidden by robots.txt)."""

    def request(self, method, url, **kw):
        if url.endswith("/roles/170901"):
            self.calls.append(url)
            raise RobotsDisallowed("https://higher.gs.com/campus?page=1", via=url)
        return super().request(method, url, **kw)


# offers of the old tracker, as exported (doc id -> data), turned into rows by make_setup_sql
EXPORT = {
    "lazard-6313": {"url": "https://icbpjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/"
                           "LazardStudentCareers/job/6313/?utm_medium=jobshare",
                    "title": "Stage H/F - Analyste Actions – Janvier 2027", "status": "postule"},
    "sycomore-1": {"url": "https://jobs.smartrecruiters.com/SycomoreAssetManagement/744000154486600-stage-6-mois",
                   "title": "Stage 6 mois – Analyste Crédit", "status": "a_postuler"},
    "ms-1": {"url": "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/so/pm/1/pl/1/opp/"
                    "22234-2027-Investment-Management-Off-cycle-Internship-Fixed-Income/en-GB",
             "title": "2027 Investment Management Off-cycle Internship – Fixed Income"},
    "blackrock-1": {"url": "https://careers.blackrock.com/job/london/2027-off-cycle-internship-program-emea/"
                           "45831/97104654800", "title": "2027 Off-cycle Internship Program – EMEA"},
    "bpifrance-1": {"url": "https://talents.bpifrance.fr/opportunites/assistant-gerant-portefeuille-cross-assets-f-h/"
                           "?id=9986-81", "title": "Assistant gérant portefeuille cross-assets F/H"},
    "amiral-1": {"url": "https://amiralgestion.sainoo.com/jobs/1131?from_careers_page=true&standalone=true",
                 "title": "Stage Analyste Financier", "status": "entretien"},
    "cmam-1": {"url": "https://recrutement.creditmutuel.fr/fr/offre.html?annonce=116845",
               "title": "Stage - Assistant(e) gestion taux (F/H)"},
    "amundi-1": {"url": "https://jobs.amundi.com/offre-de-emploi/emploi-stage-assistant-gestion-multi-asset-h-f_116937.aspx",
                 "title": "Stage - Assistant gestion multi-asset H/F"},
    "amundi-2": {"url": "https://jobs.amundi.com/offre-de-emploi/emploi-stage-ancienne-offre-h-f_115000.aspx",
                 "title": "Stage - Ancienne offre H/F"},                       # gone from the site: closed
    "mirova-22462": {"url": "https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/",
                     "title": "Stage – 6 mois – Analyste Investissement F/H"},
    "gs-1": {"url": "https://higher.gs.com/roles/170877", "title": "2027 | Paris | Off-Cycle Internship"},
    "gs-2": {"url": "https://higher.gs.com/roles/184029", "title": "2027 | London | Off-Cycle Internship"},
    "gs-3": {"url": "https://higher.gs.com/roles/170901", "title": "2027 | Paris | AWM Off-Cycle Internship"},
    "dnca-1": {"url": "https://www.dnca-investments.com/carrieres/VBPXW547",
               "title": "Stagiaire Risques de Marché et Développement"},
    "jpm-1": {"url": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210802076",
              "title": "2027 Commercial & Investment Banking - Global Markets - Off-cycle Internship – Paris"},
    "db-1": {"url": "https://db.recsolu.com/jobs/wsSne9C62Ef0mymYhfNSyQ?job_board_id=DT5zqeU-qZM-ltrVsIvR9Q",
             "title": "Deutsche Bank Graduate Programme - Investment Bank: Corporate Finance – Paris – 2027"},
    "bnp-1": {"url": "https://group.bnpparibas/en/careers/job-offer/stage-investment-specialist-multi-asset-hf",
              "title": "Stage – Investment Specialist Multi-Asset (H/F)"},
    "carmignac-1": {"url": "https://www.carmignac.com/en-fr/about-us/careers", "location": "Paris",
                    "title": "Investment Analyst Intern – Global Equities"},
    "edram-1": {"url": "https://www.jobteaser.com/fr/job-offers/1a2b3c4d-stage-analyste", "title": "Stage Analyste"},
    "moneta-1": {"url": "https://www.moneta.fr/contact/stagiaires-apprentis", "title": "Candidature spontanée"},
}
# what each export must become: the id the reader gives to the same offer
EXPECTED_IDS = {
    "lazard-6313": "lazard:6313", "sycomore-1": "sycomore:744000154486600", "ms-1": "ms:22234",
    "blackrock-1": "blackrock:97104654800", "bpifrance-1": "bpifrance:9986", "amiral-1": "amiral:1131",
    "cmam-1": "lafrancaise:116845", "amundi-1": "amundi:116937", "amundi-2": "amundi:115000",
    "mirova-22462": "mirova:20732", "gs-1": "gs:170877", "gs-2": "gs:184029", "gs-3": "gs:170901",
    "dnca-1": "dnca:VBPXW547", "jpm-1": "jpm:210802076", "db-1": "db:wsSne9C62Ef0mymYhfNSyQ",
    "bnp-1": "bnp:stage-investment-specialist-multi-asset-hf",
    "carmignac-1": "carmignac:investment-analyst-intern-global-equities-paris",
    "edram-1": "edram:jt-1a2b3c4d", "moneta-1": "moneta:spontanee",
}

# companies Luca adds from the site (kind "auto")
ADDED = [
    {"id": "sycomore-site", "company": "Sycomore Asset Management", "rank": 21, "kind": "auto",
     "params": {"url": "https://www.sycomore-am.com/fr/carrieres"}, "catalog_url": "https://www.sycomore-am.com/fr/carrieres",
     "criteria": {"types": ["Gestion d'actifs", "Investment analyst"], "starts": ["Janvier 2027"], "keywords": "",
                  "cities": ""}},
    {"id": "exemple-gestion", "company": "Exemple Gestion", "rank": 22, "kind": "auto",
     "params": {"url": GENERIC_URL}, "catalog_url": GENERIC_URL},
    {"id": "inconnue", "company": "Gestion Inconnue Privée", "rank": 23, "kind": "auto", "params": {"url": None}},
]

STATUS_AFTER_FIRST_PASS = {
    "amiral": "ok", "dnca": "ok", "eleva": "sans_catalogue", "mirova": "ok", "amundi": "ok", "lafrancaise": "ok",
    "comgest": "ok", "carmignac": "ok", "sycomore": "ok", "edram": "partiel", "lazard": "ok",
    "moneta": "sans_catalogue", "bnp": "partiel", "ms": "ok", "pictet": "resiste", "blackrock": "ok", "jpm": "ok",
    "gs": "partiel", "db": "ok", "bpifrance": "ok",
    "sycomore-site": "ok", "exemple-gestion": "partiel", "inconnue": "a_configurer",
}


def _imported() -> list[dict]:
    rows = []
    for doc_id, d in EXPORT.items():
        r = make_setup_sql.offer_row(doc_id, {"company": "", "relevance": "cible", **d})
        rows.append(r | {"first_seen": "2026-10-25", "last_seen": "2026-10-25"})
    return rows


def _store(tmp_path) -> LocalStore:
    sources = [dict(s, status="a_configurer", enabled=True) for s in SEED]
    sources += [dict(s, status="a_configurer", enabled=True, added_from_site=True) for s in ADDED]
    store = LocalStore(tmp_path / "db.json", sources=sources)
    store.db["offers"] = _imported()
    return store


def _pass(store, monkeypatch, day: date):
    fetcher = SiteFetcher(ROUTES, ROBOTS)
    browser = FakeBrowser(BROWSER)
    monkeypatch.setattr(runner, "LazyBrowser", lambda f: browser)
    notifier = Notifier(None, dry_run=True)
    summary = runner.run(store, notifier, fetcher=fetcher, today=day)
    return summary, fetcher, browser, notifier


def test_export_ids_follow_the_readers_conventions():
    for doc_id, d in EXPORT.items():
        assert make_setup_sql.offer_row(doc_id, d)["id"] == EXPECTED_IDS[doc_id], doc_id


def test_whole_seed_two_passes(tmp_path, monkeypatch):
    store = _store(tmp_path)
    imported = {r["id"]: r for r in _imported()}

    # ------------------------------------------------------------------ first pass
    s1, fetcher, browser, notif = _pass(store, monkeypatch, date(2026, 11, 9))
    src = {s["id"]: s for s in store.db["sources"]}
    report = {r["source"]: r for r in s1["sources"]}
    assert {k: src[k]["status"] for k in STATUS_AFTER_FIRST_PASS} == STATUS_AFTER_FIRST_PASS
    assert not [r for r in s1["sources"] if r["error"]]              # no reader crashed
    assert s1["totals"]["erreur"] == 0 and s1["totals"]["sources"] == len(SEED) + len(ADDED)

    # every problem source explains itself in French; what to do is given by the robot for the
    # blocking states (the site has a default « Ce que tu peux faire » for partiel / sans_catalogue)
    for sid, st in STATUS_AFTER_FIRST_PASS.items():
        if st != "ok":
            assert src[sid]["reason"], sid
        if st in ("resiste", "erreur", "a_configurer"):
            assert src[sid]["fix"], sid
    assert "robots.txt" in src["pictet"]["reason"] and "robots.txt" in src["gs"]["reason"]
    assert "JobTeaser" in src["edram"]["reason"] and "JobTeaser" in src["eleva"]["filters"]

    # robots.txt: nothing forbidden was requested, Crawl-delay of Morgan Stanley is read
    assert not any("successfactors" in c or "/campus" in c for c in fetcher.calls)
    assert not any("group.bnpparibas" in c and "?" in c for c in fetcher.calls)
    assert not any("jobteaser" in c for c in fetcher.calls + browser.calls)
    assert Fetcher._crawl_delay(fetcher, MS_URL) == 10

    # every URL read is shown on the site: source card (last_urls) or run history (urls + details)
    shown = {u for r in s1["sources"] for u in r["urls"] + r["details"]}
    assert set(fetcher.calls) - shown == set()
    assert set(browser.calls) - shown == set()
    for sid in STATUS_AFTER_FIRST_PASS:
        if sid not in ("eleva", "inconnue"):
            assert src[sid]["last_urls"], sid
    assert src["pictet"]["last_urls"] == ["https://career012.successfactors.eu/robots.txt"]

    # offers: ids, classification, publication date when the site gives one
    offers = store.db["offers"]
    ids = [o["id"] for o in offers]
    assert len(ids) == len(set(ids))
    for o in offers:
        assert o["id"] == f"{o['source_id']}:{o['ext_id']}" and o["ext_id"], o
        assert o["relevance"] in ("cible", "proche", "exclue"), o
        if o["id"] not in imported:
            assert o["reasons"] and o["start_label"], o
    by_id = {o["id"]: o for o in offers}
    for oid in ("lazard:6316", "mirova:20654", "dnca:QX4TR2M9", "lafrancaise:117711", "sycomore:744000154970480",
                "db:Kp3aQ7xR2Lm9TzVb4NcWdE", "bpifrance:10140", "jpm:210802419"):
        assert by_id[oid]["published"], oid
    assert by_id["lazard:6316"]["relevance"] == "cible"
    assert by_id["amundi:117102"]["relevance"] == "cible"                  # London, Investment Specialist
    assert by_id["ms:22501"]["relevance"] == "exclue"                      # summer analyst
    assert by_id["comgest:e29a4c1f-1d80-41a7-ae87-4e42649bcb64"]["relevance"] == "exclue"

    # offers already known from the old tracker are recognised, never duplicated nor re-notified
    for oid, row in imported.items():
        same = [o for o in offers if o["source_id"] == row["source_id"] and o["title"] == row["title"]]
        assert [o["id"] for o in same] == [oid], oid
    assert by_id["lazard:6313"]["status"] == "postule" and by_id["amiral:1131"]["status"] == "entretien"
    assert by_id["amundi:115000"]["closed"] is True                         # gone from a complete list
    assert by_id["gs:184029"]["closed"] is True                             # 404
    assert by_id["gs:170901"]["closed"] is True                             # redirects to the forbidden /campus
    assert by_id["gs:170877"]["closed"] is False
    assert by_id["edram:jt-1a2b3c4d"]["closed"] is False                    # JobTeaser offer kept by hand
    assert by_id["moneta:spontanee"]["closed"] is False
    assert s1["totals"]["closed"] == 3

    # notifications: new offers (targets, to check) and the sites that resist
    titles = [m["title"] for m in notif.sent]
    bodies = "\n".join(m["message"] for m in notif.sent)
    assert any(t.startswith("🎯") for t in titles) and any("à vérifier" in t for t in titles)
    resist = next(m for m in notif.sent if "résistent" in m["title"])
    for company in ("Pictet", "Goldman Sachs", "BNP Paribas", "Edmond de Rothschild"):
        assert company in resist["message"]
    company = {s["id"]: s["company"] for s in SEED}
    for row in imported.values():
        assert f"{company[row['source_id']]} : {row['title']}" not in bodies, row["title"]

    # companies added from the site: a real search, then their dedicated reader
    assert src["sycomore-site"]["kind"] == "smartrecruiters"
    assert src["sycomore-site"]["params"] == {"company": "SycomoreAssetManagement"}
    assert report["sycomore-site"]["found"] == 4
    assert any(o["source_id"] == "exemple-gestion" for o in offers)
    assert src["inconnue"]["reason"].startswith("Je n'ai pas trouvé de catalogue officiel")

    # ------------------------------------------------------------------ second pass, same pages
    n_offers = len(store.db["offers"])
    s2, _, _, notif2 = _pass(store, monkeypatch, date(2026, 11, 10))
    assert s2["totals"]["new"] == 0 and s2["totals"]["closed"] == 0
    assert len(store.db["offers"]) == n_offers
    assert {k: v["status"] for k, v in {s["id"]: s for s in store.db["sources"]}.items()
            if k in STATUS_AFTER_FIRST_PASS} == STATUS_AFTER_FIRST_PASS
    assert notif2.sent == []                                              # nothing new, no status change
    assert [o["id"] for o in store.db["offers"] if o["closed"]] == ["amundi:115000", "gs:184029", "gs:170901"]
    assert {r["source"]: r for r in s2["sources"]}["sycomore-site"]["method"] == "api"   # dedicated reader now


# ---------------------------------------------------------------------- generic titles
BLACKROCK_DETAIL = """<html><head><script type="application/ld+json">{"@context": "https://schema.org",
 "@type": "JobPosting", "title": "2027 Off-cycle Internship Program - EMEA", "datePosted": "2026-10-29",
 "description": "<p>Join our Investment Management teams for a 6-month off-cycle internship starting January 2027.</p>"}
</script></head><body></body></html>"""


def _blackrock_store(tmp_path):
    src = next(s for s in SEED if s["id"] == "blackrock")
    return LocalStore(tmp_path / "br.json", sources=[dict(src, status="ok", enabled=True)])


def test_internship_with_a_generic_title_is_judged_on_its_page(tmp_path, monkeypatch):
    """« 2027 Off-cycle Internship Program – EMEA » names no métier: its page does."""
    store = _blackrock_store(tmp_path)
    routes = {r"/45831/97104654800$": (200, BLACKROCK_DETAIL), r"/9022304/1$": "talentbrew_blackrock_p1.html"}
    fetcher = FakeFetcher(routes)
    runner.run(store, Notifier(None, dry_run=True), fetcher=fetcher, use_browser=False, today=date(2026, 11, 9))
    o = next(o for o in store.db["offers"] if o["id"] == "blackrock:97104654800")
    assert o["relevance"] == "proche" and o["start_label"] == "Janvier 2027"
    assert o["published"] == "2026-10-29"
    assert any(c.endswith("/97104654800") for c in fetcher.calls)
    # a summer programme is not opened: it is excluded for its contract
    assert not any(c.endswith("/97150990012") for c in fetcher.calls)


def test_offer_pages_of_target_offers_come_first(tmp_path, monkeypatch):
    store = _blackrock_store(tmp_path)
    monkeypatch.setattr(runner, "MAX_DETAILS_PER_SOURCE", 1)
    fetcher = FakeFetcher({r"/9022304/1$": "talentbrew_blackrock_p1.html"})
    runner.run(store, Notifier(None, dry_run=True), fetcher=fetcher, use_browser=False, today=date(2026, 11, 9))
    details = [c for c in fetcher.calls if "/job/" in c]
    assert len(details) == 1 and details[0].endswith("/97162233411")       # the Investment Specialist offer


# ---------------------------------------------------------------------- setup.sql
def test_setup_sql_skips_offers_of_unknown_companies(tmp_path, monkeypatch, capsys):
    export = tmp_path / "export" / "offers"
    export.mkdir(parents=True)
    (export / "amundi-116937.json").write_text(json.dumps({"data": EXPORT["amundi-1"]}), "utf-8")
    (export / "oddo-12.json").write_text(json.dumps({"data": {"url": "https://oddo.example/1", "title": "Stage"}}),
                                         "utf-8")
    out = tmp_path / "setup.sql"
    monkeypatch.setattr("sys.argv", ["make_setup_sql.py", "--email", "Moi@Exemple.fr",
                                     "--export", str(tmp_path / "export"), "--out", str(out)])
    assert make_setup_sql.main() == 0
    sql = out.read_text("utf-8")
    assert "'amundi:116937'" in sql and "oddo" not in sql
    assert "values ('moi@exemple.fr')" in sql
    assert "oddo-12.json" in capsys.readouterr().err
