"""Sitemap / RSS discovery of offer pages (brief §5): pure parsing + bounded driver."""
from scraper import sitemap
from scraper.parsers.generic import Parser

ROBOTS = "User-agent: *\nAllow: /\nSitemap: https://www.exemple-am.com/sitemap.xml\n"
URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.exemple-am.com/offres/stage-analyste-actions-1</loc></url>
  <url><loc>https://www.exemple-am.com/a-propos</loc></url>
  <url><loc>https://www.exemple-am.com/offres</loc></url>
  <url><loc>https://www.exemple-am.com/offres/stage-credit-2</loc></url>
</urlset>"""
INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.exemple-am.com/sitemap-jobs.xml</loc></sitemap>
  <sitemap><loc>https://www.exemple-am.com/sitemap-pages.xml</loc></sitemap>
</sitemapindex>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><link href="https://www.exemple-am.com/offres/stage-esg-3"/></entry>
</feed>"""


def test_sitemaps_in_robots():
    assert sitemap.sitemaps_in_robots(ROBOTS) == ["https://www.exemple-am.com/sitemap.xml"]


def test_parse_sitemap_index_and_urlset():
    children, pages = sitemap.parse_sitemap(INDEX)
    assert children == ["https://www.exemple-am.com/sitemap-jobs.xml",
                        "https://www.exemple-am.com/sitemap-pages.xml"] and pages == []
    children, pages = sitemap.parse_sitemap(URLSET)
    assert children == [] and len(pages) == 4


def test_parse_feed_atom():
    assert sitemap.parse_feed(ATOM) == ["https://www.exemple-am.com/offres/stage-esg-3"]


def test_is_offer_url_and_filter():
    keep = sitemap.filter_offer_urls([
        "https://www.exemple-am.com/offres/stage-analyste-actions-1",   # offer
        "https://www.exemple-am.com/offres",                            # list page -> no
        "https://www.exemple-am.com/a-propos",                          # not an offer
        "https://www.exemple-am.com/jobs/senior-engineer",             # offer
        "https://www.jobteaser.com/en/companies/x/job-offers",         # intermediary -> no
        "https://www.exemple-am.com/assets/logo.png",                  # asset -> no
    ])
    assert keep == ["https://www.exemple-am.com/offres/stage-analyste-actions-1",
                    "https://www.exemple-am.com/jobs/senior-engineer"]


def test_collect_offer_pages_driver(make_ctx):
    ctx = make_ctx({
        r"exemple-am\.com/robots\.txt$": (200, ROBOTS),
        r"exemple-am\.com/sitemap\.xml$": (200, URLSET),
    })
    urls = sitemap.collect_offer_pages(ctx.fetcher, "https://www.exemple-am.com/carrieres")
    assert urls == ["https://www.exemple-am.com/offres/stage-analyste-actions-1",
                    "https://www.exemple-am.com/offres/stage-credit-2"]


def test_generic_falls_back_to_sitemap_offer_pages(make_ctx):
    """Careers page with no offer link -> offers are found via the sitemap and their JSON-LD."""
    careers = "<html><body><main><p>Découvrez nos métiers.</p></main></body></html>"
    offer_page = ("<html><head><script type='application/ld+json'>"
                  '{"@context":"https://schema.org","@type":"JobPosting",'
                  '"title":"Stage - Analyste Actions","datePosted":"2026-11-02","employmentType":"INTERN",'
                  '"url":"https://www.exemple-am.com/offres/stage-analyste-actions-1",'
                  '"description":"Stage de 6 mois, janvier 2027.",'
                  '"jobLocation":{"@type":"Place","address":{"addressLocality":"Paris","addressCountry":"FR"}}}'
                  "</script></head><body>Stage</body></html>")
    ctx = make_ctx({
        r"exemple-am\.com/carrieres$": (200, careers),
        r"exemple-am\.com/robots\.txt$": (200, ROBOTS),
        r"exemple-am\.com/sitemap\.xml$": (200, URLSET),
        r"exemple-am\.com/offres/stage-analyste-actions-1$": (200, offer_page),
        r"exemple-am\.com/offres/stage-credit-2$": (200, "<html><body>pas de données</body></html>"),
    })
    src = {"id": "exemple-am", "company": "Exemple AM", "kind": "generic",
           "params": {"url": "https://www.exemple-am.com/carrieres"}}
    res = Parser(ctx).read(src)
    titles = {o.title for o in res.offers}
    assert "Stage - Analyste Actions" in titles
    o = next(o for o in res.offers if o.title == "Stage - Analyste Actions")
    assert o.url == "https://www.exemple-am.com/offres/stage-analyste-actions-1"
    assert o.extra.get("via") == "sitemap"
