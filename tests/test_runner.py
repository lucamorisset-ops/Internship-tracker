"""End-to-end pass on a LocalStore with fake parsers (no network)."""
from datetime import date

import scraper.parsers as parsers
from scraper.http import RobotsDisallowed
from scraper.models import SourceResult
from scraper.notify import Notifier
from scraper.parsers.base import BaseParser
from scraper.runner import run
from scraper.store import LocalStore

from conftest import FakeFetcher

STATE = {"offers": []}


class ListParser(BaseParser):
    name = "fake_list"
    method = "html"
    detail_pages = False

    def read(self, source):
        res = self.result(source)
        res.urls_read.append("https://x.test/list")
        for ext, title in STATE["offers"]:
            res.offers.append(self.offer(source, ext_id=ext, title=title, url=f"https://x.test/o/{ext}",
                                         location="Paris", contract="Stage"))
        return res


class RobotsParser(BaseParser):
    name = "fake_robots"

    def read(self, source):
        raise RobotsDisallowed("https://blocked.test/careers")


def _install(monkeypatch):
    import sys
    import types

    for name, cls in (("fake_list", ListParser), ("fake_robots", RobotsParser)):
        mod = types.ModuleType(f"scraper.parsers.{name}")
        mod.Parser = cls
        sys.modules[f"scraper.parsers.{name}"] = mod
        monkeypatch.setitem(parsers.REGISTRY, name, name)


def _store(tmp_path):
    return LocalStore(tmp_path / "db.json", sources=[
        {"id": "acme", "company": "Acme AM", "rank": 1, "kind": "fake_list", "status": "ok", "enabled": True},
        {"id": "blk", "company": "Blocked Bank", "rank": 2, "kind": "fake_robots", "status": "ok", "enabled": True},
    ])


def test_full_pass(tmp_path, monkeypatch):
    _install(monkeypatch)
    store = _store(tmp_path)
    notif = Notifier(None, dry_run=True)
    STATE["offers"] = [("1", "Stage Assistant gérant actions - Janvier 2027"),
                       ("2", "Stage Juriste")]
    s = run(store, notif, use_browser=False, fetcher=FakeFetcher({}), today=date(2026, 11, 8))
    offers = {o["id"]: o for o in store.db["offers"]}
    assert offers["acme:1"]["relevance"] == "cible"
    assert offers["acme:2"]["relevance"] == "exclue"
    assert s["totals"]["new"] == 2 and s["totals"]["resiste"] == 1
    blk = next(x for x in store.db["sources"] if x["id"] == "blk")
    assert blk["status"] == "resiste" and "robots.txt" in blk["reason"]
    titles = [m["title"] for m in notif.sent]
    assert any("Assistant gérant" in t for t in titles)            # new target offer pushed
    assert any("résistent" in t for t in titles)                    # resisting site pushed

    # second pass: offer 1 disappears -> closed; offer 3 new; no duplicate push for 2
    STATE["offers"] = [("2", "Stage Juriste"), ("3", "Stage Analyste ESG - Mars 2027")]
    store.db["sources"][0]["status"] = "ok"
    store.db["sources"][1]["status"] = "resiste"
    notif2 = Notifier(None, dry_run=True)
    s2 = run(store, notif2, use_browser=False, fetcher=FakeFetcher({}), today=date(2026, 11, 9))
    offers = {o["id"]: o for o in store.db["offers"]}
    assert offers["acme:1"]["closed"] is True and offers["acme:1"]["closed_on"] == "2026-11-09"
    assert offers["acme:3"]["relevance"] == "proche"
    assert s2["totals"]["new"] == 1 and s2["totals"]["closed"] == 1
    assert not any("résistent" in m["title"] for m in notif2.sent)  # unchanged status: no repeat
    assert len(store.db["runs"]) == 2


def test_empty_read_does_not_close_everything(tmp_path, monkeypatch):
    _install(monkeypatch)
    store = _store(tmp_path)
    STATE["offers"] = [(str(i), f"Stage analyste actions {i}") for i in range(5)]
    run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=FakeFetcher({}), only=["acme"])
    STATE["offers"] = []
    run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=FakeFetcher({}), only=["acme"])
    assert not any(o["closed"] for o in store.db["offers"])
    acme = next(x for x in store.db["sources"] if x["id"] == "acme")
    assert acme["status"] == "partiel"


def test_same_url_different_offers(tmp_path, monkeypatch):
    """Carmignac: every row points to the careers page; rows must stay distinct."""
    _install(monkeypatch)
    store = _store(tmp_path)

    class SameUrl(ListParser):
        def read(self, source):
            res = self.result(source)
            for ext, title in STATE["offers"]:
                res.offers.append(self.offer(source, ext_id=ext, title=title, url="https://x.test/careers",
                                             location="Paris", contract="Internship"))
            return res

    import sys
    sys.modules["scraper.parsers.fake_list"].Parser = SameUrl
    STATE["offers"] = [("a", "Equity Analyst Intern"), ("b", "Fixed Income Intern")]
    run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=FakeFetcher({}), only=["acme"])
    STATE["offers"] = [("a", "Equity Analyst Intern"), ("b", "Fixed Income Intern"), ("c", "Quant Intern")]
    s = run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=FakeFetcher({}), only=["acme"])
    assert sorted(o["id"] for o in store.db["offers"]) == ["acme:a", "acme:b", "acme:c"]
    assert s["totals"]["new"] == 1 and not any(o["closed"] for o in store.db["offers"])


def test_failed_source_keeps_the_urls_it_tried(tmp_path, monkeypatch):
    """A site that resists half-way: the pages already read and the refused one stay visible."""
    _install(monkeypatch)
    store = _store(tmp_path)

    class TwoPages(BaseParser):
        def read(self, source):
            res = self.result(source)
            self.get("https://x.test/list", res)
            self.get("https://x.test/list?page=2", res)
            return res

    import sys
    sys.modules["scraper.parsers.fake_list"].Parser = TwoPages
    fetcher = FakeFetcher({r"/list$": (200, "<html></html>"), r"page=2": (403, "Forbidden")})
    run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=fetcher, only=["acme"])
    acme = next(x for x in store.db["sources"] if x["id"] == "acme")
    assert acme["status"] == "resiste"
    assert acme["last_urls"] == ["https://x.test/list", "https://x.test/list?page=2"]


def test_robots_failure_lists_the_forbidden_url(tmp_path, monkeypatch):
    _install(monkeypatch)
    store = _store(tmp_path)
    run(store, Notifier(None, dry_run=True), use_browser=False, fetcher=FakeFetcher({}), only=["blk"])
    blk = next(x for x in store.db["sources"] if x["id"] == "blk")
    assert blk["last_urls"] == ["https://blocked.test/careers"]


def test_crawl_delay_too_long_is_explained():
    from scraper.http import FetchError
    from scraper.runner import explain_failure

    status, reason, fix = explain_failure(
        FetchError("https://slow.test/jobs", None, "Crawl-delay de 120 s demandé par robots.txt"))
    assert status == "resiste"
    assert reason.startswith("Le fichier robots.txt de slow.test demande d'attendre plus de 60 secondes")
    assert "alerte" in fix


def test_reclassify_when_rules_change(tmp_path, monkeypatch):
    """Offers wrongly excluded by older rules are re-sorted once, and Luca is told."""
    _install(monkeypatch)
    store = _store(tmp_path)
    store.db["offers"] = [
        {"id": "acme:9", "source_id": "acme", "title": "Stage - Assistant gestion multi-asset H/F", "url": "https://x.test/o/9",
         "url_key": "https://x.test/o/9", "location": "Paris 15 éme", "contract": "Stage", "closed": False, "manual": False,
         "description": "Mis à jour le 01/12/2024", "relevance": "exclue", "reasons": "démarrage Décembre 2024",
         "start_label": "Décembre 2024"},
        {"id": "acme:old", "source_id": "acme", "title": "Stage Juriste", "url": "https://x.test/o/old",
         "url_key": "https://x.test/o/old", "closed": False, "manual": False, "relevance": "cible",
         "reasons": "Note écrite à la main pour l'ancien tracker"},
    ]
    store.save()
    STATE["offers"] = [("9", "Stage - Assistant gestion multi-asset H/F")]
    notif = Notifier(None, dry_run=True)
    run(store, notif, use_browser=False, fetcher=FakeFetcher({}), today=date(2026, 11, 9))
    offers = {o["id"]: o for o in store.db["offers"]}
    assert offers["acme:9"]["relevance"] == "cible" and offers["acme:9"]["start_label"] == "Non précisé"
    assert offers["acme:old"]["relevance"] == "cible"          # hand-written explanation: untouched
    assert any("remontée" in m["title"] for m in notif.sent)
    # second pass: rules unchanged, nothing re-sorted, no new message
    notif2 = Notifier(None, dry_run=True)
    run(store, notif2, use_browser=False, fetcher=FakeFetcher({}), today=date(2026, 11, 9))
    assert not any("remontée" in m["title"] for m in notif2.sent)
