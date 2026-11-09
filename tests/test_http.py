"""robots.txt handling on the real rules captured on 08/11/2026."""
from scraper.robots import Robots as Protego

from scraper.http import BOT_NAME, Fetcher, looks_like_challenge

BNP = """User-agent: *
Disallow: *?as_url_id*
Disallow: *?ref*
Disallow: *?NumPage*
Disallow: *?$
Disallow: *?q
"""
MS = """User-agent: *
Disallow: /*/agent/
Disallow: /*/ats/
Disallow: /*/channel/
Crawl-delay: 10
User-agent: Bytespider
User-agent: ClaudeBot
User-agent: GPTBot
Disallow: /
"""
GS = """# Allow crawlers on roles
User-agent: *
Allow: /roles/
# Disallow crawlers on other pages
User-agent: *
Disallow: /
"""
PICTET = "User-agent: *\nDisallow: /\nDisallow: /*company\nAllow: /login\n"


def test_bnp_wildcards():
    rp = Protego.parse(BNP)
    base = "https://group.bnpparibas/emploi-carriere/toutes-offres-emploi/stage/bnp-paribas-asset-management"
    assert rp.can_fetch(base, BOT_NAME)
    assert not rp.can_fetch(base + "?q=analyste", BOT_NAME)
    assert not rp.can_fetch(base + "?", BOT_NAME)


def test_ms_crawl_delay_and_our_agent():
    rp = Protego.parse(MS)
    url = "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/"
    assert rp.can_fetch(url, BOT_NAME)
    assert rp.crawl_delay(BOT_NAME) == 10
    assert not rp.can_fetch(url, "ClaudeBot")


def test_gs_only_roles():
    rp = Protego.parse(GS)
    assert rp.can_fetch("https://higher.gs.com/roles/170901", BOT_NAME)
    assert not rp.can_fetch("https://higher.gs.com/campus?LOCATION=Paris|London", BOT_NAME)


def test_pictet_everything_forbidden():
    rp = Protego.parse(PICTET)
    assert not rp.can_fetch("https://career012.successfactors.eu/career?company=banquepict", BOT_NAME)


def test_robots_status_codes(monkeypatch):
    f = Fetcher(min_delay=0)

    class R:
        def __init__(self, code, text="", ctype="text/plain"):
            self.status_code, self.text, self.headers = code, text, {"content-type": ctype}

    answers = {"https://a.test": R(404), "https://b.test": R(503), "https://c.test": R(403),
               "https://d.test": R(200, "<html>oops</html>", "text/html")}
    monkeypatch.setattr(f.session, "get", lambda url, **kw: answers[url.rsplit("/robots.txt", 1)[0]])
    assert f.allowed("https://a.test/x")       # 404: no robots.txt -> allowed (RFC 9309)
    assert not f.allowed("https://b.test/x")   # 5xx -> assume disallow
    assert f.allowed("https://c.test/x")       # 4xx (JP Morgan answers 403) -> allowed
    assert f.allowed("https://d.test/x")       # HTML instead of robots.txt -> treated as none


def test_challenge_detection():
    carmignac = ("<html lang=\"en\"><head></head><body><script>window.location.href='/redirect_X/en-fr/about-us/careers';"
                 "</script><noscript>This website requires JS enabled and cookies</noscript></body></html>")
    assert looks_like_challenge(carmignac, 200)
    assert looks_like_challenge("Forbidden", 403)
    assert not looks_like_challenge("<html>" + "x" * 60000 + "</html>", 200)


def test_redirect_to_forbidden_page_is_not_followed(monkeypatch):
    """A closed Goldman Sachs role redirecting to /campus (forbidden) must not be read."""
    import pytest
    import requests
    from scraper.http import RobotsDisallowed
    from scraper.robots import Robots

    f = Fetcher(min_delay=0)
    monkeypatch.setattr(f, "robots_for", lambda url: Robots.parse(GS))
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        r = requests.Response()
        r.url = url
        if url.endswith("/roles/1"):
            r.status_code, r.headers["location"] = 302, "/campus?page=1"
        else:
            r.status_code, r._content = 200, b"campus"
        return r

    monkeypatch.setattr(f.session, "request", fake)
    with pytest.raises(RobotsDisallowed):
        f.get("https://higher.gs.com/roles/1", retries=0)
    assert calls == ["https://higher.gs.com/roles/1"]


def test_redirect_to_forbidden_page_names_the_page_that_redirected(monkeypatch):
    import pytest
    import requests
    from scraper.http import RobotsDisallowed
    from scraper.robots import Robots

    f = Fetcher(min_delay=0)
    monkeypatch.setattr(f, "robots_for", lambda url: Robots.parse(GS))

    def fake(method, url, **kw):
        r = requests.Response()
        r.url, r.status_code, r.headers["location"] = url, 302, "/campus?page=1"
        return r

    monkeypatch.setattr(f.session, "request", fake)
    with pytest.raises(RobotsDisallowed) as e:
        f.get("https://higher.gs.com/roles/1", retries=0)
    assert e.value.via == "https://higher.gs.com/roles/1"
    assert [x["url"] for x in f.log] == ["https://higher.gs.com/roles/1", "https://higher.gs.com/campus?page=1"]


def test_crawl_delay_is_obeyed_in_full_or_the_host_is_not_read(monkeypatch):
    import pytest
    from scraper.http import FetchError
    from scraper.robots import Robots

    f = Fetcher(min_delay=2)
    rules = {"https://slow.test": "User-agent: *\nCrawl-delay: 30\n",
             "https://very-slow.test": "User-agent: *\nCrawl-delay: 120\n"}
    monkeypatch.setattr(f, "robots_for", lambda url: Robots.parse(rules.get(f._host(url), "")))
    assert f._crawl_delay("https://slow.test/jobs") == 30        # not shortened
    assert f._crawl_delay("https://other.test/jobs") == 2        # no Crawl-delay: our own minimum
    monkeypatch.setattr(f.session, "request", lambda *a, **kw: pytest.fail("must not be requested"))
    with pytest.raises(FetchError) as e:
        f.get("https://very-slow.test/jobs")
    assert "Crawl-delay de 120 s" in e.value.detail
