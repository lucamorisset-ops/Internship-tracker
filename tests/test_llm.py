"""(d) step 5 — LLM extraction interface. The stub is inert by default; the hook wires in."""
import scraper.llm_extract as llm
from scraper.parsers.generic import Parser


def test_llm_disabled_by_default():
    assert not llm.llm_enabled()
    assert llm.maybe_llm_offers({"id": "x"}, "du texte de page") == []


def test_llm_enabled_with_injected_extractor(monkeypatch):
    monkeypatch.setenv("SCRAPER_LLM", "1")
    monkeypatch.setattr(llm, "EXTRACTOR", lambda text, source: [
        {"title": "Stage Analyste", "url": "https://x.test/o/1", "location": "Paris"},
        {"title": "", "url": "https://x.test/o/2"},          # dropped: no title
    ])
    rows = llm.maybe_llm_offers({"id": "x"}, "texte")
    assert rows == [{"title": "Stage Analyste", "url": "https://x.test/o/1", "location": "Paris"}]


def test_llm_extractor_errors_never_raise(monkeypatch):
    monkeypatch.setenv("SCRAPER_LLM", "1")
    def boom(text, source):
        raise RuntimeError("model down")
    monkeypatch.setattr(llm, "EXTRACTOR", boom)
    assert llm.maybe_llm_offers({"id": "x"}, "texte") == []


def test_generic_uses_llm_when_nothing_else_matched(make_ctx, monkeypatch):
    """A page with no ATS/links/structured data falls back to the LLM step when enabled."""
    monkeypatch.setenv("SCRAPER_LLM", "1")
    monkeypatch.setattr(llm, "EXTRACTOR", lambda text, source: [
        {"title": "Stage Gestion d'actifs", "url": "https://exemple.test/offres/1",
         "location": "Paris", "contract": "Stage", "published": "2026-11-01"}])
    page = "<html><body><main><p>Contactez-nous pour nos stages.</p></main></body></html>"
    ctx = make_ctx({r"exemple\.test/carrieres$": (200, page)})
    src = {"id": "exemple", "company": "Exemple", "kind": "generic",
           "params": {"url": "https://exemple.test/carrieres"}}
    res = Parser(ctx).read(src)
    assert len(res.offers) == 1
    o = res.offers[0]
    assert o.title == "Stage Gestion d'actifs" and o.url == "https://exemple.test/offres/1"
    assert o.extra.get("llm") is True
