"""Structured-data extraction (a): JSON-LD + Microdata + OpenGraph on fixtures, no network."""
from datetime import date

from conftest import fixture
from scraper.structured import (
    extra_structured_jobpostings,
    microdata_jobpostings,
    opengraph,
    structured_jobpostings,
)

BASE = "https://www.exemple-gestion.fr/carrieres"


def test_microdata_jobpostings():
    html = fixture("microdata_careers.html")
    posts = microdata_jobpostings(html, BASE)
    assert len(posts) == 2
    p = next(p for p in posts if "Obligataire" in p["title"])
    assert p["title"] == "Stage - Assistant Gérant Obligataire (Microdata)"
    assert p["url"] == "https://www.exemple-gestion.fr/offres/microdata-gerant-obligataire"
    assert p["contract"] == "Intern" and p["published"] == date(2026, 10, 15)
    assert "gestion obligataire" in p["description"] and p["syntax"] == "microdata"
    assert p["location"] == "Paris, France"


def test_opengraph_fallback():
    og = opengraph(fixture("microdata_careers.html"))
    assert og["title"].startswith("Carrières") and "gestion d'actifs" in og["description"]


def test_structured_combines_syntaxes_jsonld_first():
    posts = structured_jobpostings(fixture("microdata_careers.html"), BASE)
    titles = sorted(p["title"] for p in posts)
    # one JSON-LD + two Microdata
    assert titles == [
        "Stage - Analyste Actions (JSON-LD)",
        "Stage - Assistant Gérant Obligataire (Microdata)",
        "Stage - Développeur (Microdata)",
    ]
    jsonld = next(p for p in posts if "JSON-LD" in p["title"])
    assert jsonld["syntax"] == "json-ld" and jsonld["location"] == "Paris, FR"


def test_extra_structured_excludes_jsonld():
    posts = extra_structured_jobpostings(fixture("microdata_careers.html"), BASE)
    assert all(p["syntax"] != "json-ld" for p in posts) and len(posts) == 2


def test_no_structured_data_is_empty():
    assert structured_jobpostings("<html><body><p>rien</p></body></html>", BASE) == []


def test_generic_reader_picks_up_microdata(make_ctx):
    """The generic reader finds Microdata offers, not only JSON-LD and link-based ones."""
    from scraper.parsers.generic import Parser
    ctx = make_ctx({})
    gen = Parser(ctx)
    source = {"id": "exemple", "company": "Exemple Gestion"}
    offers = gen.extract_offers(source, BASE, fixture("microdata_careers.html"))
    titles = {o.title for o in offers}
    assert "Stage - Assistant Gérant Obligataire (Microdata)" in titles   # microdata
    assert "Stage - Analyste Actions (JSON-LD)" in titles                 # json-ld
    oblig = next(o for o in offers if "Obligataire" in o.title)
    assert oblig.url == "https://www.exemple-gestion.fr/offres/microdata-gerant-obligataire"
    assert oblig.contract == "Intern"
