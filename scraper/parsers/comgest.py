"""Comgest careers pages (server-rendered, one block of text per offer).

https://www.comgest.com/en/about-us/our-people/careers/internship-offers (and
.../careers/job-offers) show each offer as a div.rich-text:

    <p><strong>Job Title:</strong> STAGIAIRE CONFORMITE ET CONTROLE INTERNE</p>
    <p><strong>Job Location:</strong> Paris</p>
    <ul><li>Comgest S.A.</li></ul>                      (entity -> description)
    <p><strong>Position Type:</strong> Stage (Internship)</p>
    <p>... <a class="document-link" href="....pdf">...</a></p>   (job description PDF -> url)
    <p><a class="cta-link" href=".../application-form?jobID={GUID}">Apply</a></p>

ext_id = jobID GUID (lower case, no braces), else slug of the PDF file name.
Detail pages are PDFs: detail_pages = False. A page without any offer block is
a valid empty result (no offer at the moment).

params: {"urls": [page URL, ...]}
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

from ..http import FetchError
from ..models import SourceResult, slugify
from .base import BaseParser, absolute, clean_text

TITLE = re.compile(r"^\s*(?:job title|intitul[ée] du poste)\s*:\s*(.*)$", re.I)
TITLE_ANYWHERE = re.compile(r"(?:job title|intitul[ée] du poste)\s*:", re.I)
LABELS = {
    "location": re.compile(r"^\s*(?:job location|location|lieu(?: du poste)?|localisation)\s*:\s*(.*)$", re.I),
    "contract": re.compile(r"^\s*(?:position type|contract(?: type)?|type de (?:contrat|poste))\s*:\s*(.*)$", re.I),
}
GUID = re.compile(r"jobid=\{?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\}?", re.I)
ITEM_TAGS = ["p", "ul", "ol", "h2", "h3", "h4", "h5"]


def _items(block: Tag) -> list[Tag]:
    """Paragraphs / lists / headings of the block, outermost only, in order."""
    out = []
    for el in block.find_all(ITEM_TAGS):
        par, nested = el.parent, False
        while par is not None and par is not block:
            if par.name in ("p", "ul", "ol"):
                nested = True
                break
            par = par.parent
        if not nested:
            out.append(el)
    return out


def _blocks(soup: BeautifulSoup) -> list[Tag]:
    blocks = [d for d in soup.select("div.rich-text") if TITLE_ANYWHERE.search(_flat(d))]
    if blocks:
        return blocks
    # tolerant fallback (class renamed): the div around each "Job Title:" label
    out: list[Tag] = []
    for s in soup.find_all(string=re.compile(r"job title|intitul[ée] du poste", re.I)):
        d = s.find_parent("div")
        if d is not None and all(d is not x for x in out):
            out.append(d)
    return out


def _flat(el: Tag) -> str:
    return clean_text(el.get_text(" "))


def _parse_block(block: Tag, page_url: str) -> list[dict]:
    offers: list[dict] = []
    cur: dict | None = None
    for el in _items(block):
        text = _flat(el)
        m = TITLE.match(text)
        if m:
            cur = {"title": m.group(1), "location": "", "contract": "", "entity": [], "pdf": "", "guid": ""}
            offers.append(cur)
        if cur is None:
            continue
        if not m:
            for key, rx in LABELS.items():
                mm = rx.match(text)
                if mm:
                    cur[key] = cur[key] or mm.group(1)
                    break
            else:
                if el.name in ("ul", "ol"):
                    cur["entity"] += [t for t in (_flat(li) for li in el.find_all("li")) if t]
        for a in el.find_all("a", href=True):
            href = unquote(a["href"])
            g = GUID.search(href)
            if g:
                cur["guid"] = cur["guid"] or g.group(1).lower()
            elif "document-link" in (a.get("class") or []) or urlsplit(href).path.lower().endswith(".pdf"):
                cur["pdf"] = cur["pdf"] or absolute(page_url, a["href"])
    return [o for o in offers if o["title"]]


def _partial(res: SourceResult, url: str, exc: Exception) -> None:
    res.complete = False
    res.status = "partiel"
    res.reason = (f"{res.reason} La page {url} n'a pas pu être lue "
                  f"({getattr(exc, 'status', None) or 'erreur réseau'}) : seules les offres des autres "
                  "pages sont affichées, aucune offre n'est marquée comme fermée.").strip()
    res.fix = ("Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage. "
               "Sinon, vérifie l'adresse de la page dans l'onglet Sources.")
    res.error = f"{res.error} | {exc}".strip(" |")


class Parser(BaseParser):
    name = "comgest"
    method = "html"
    detail_pages = False          # the job description is a PDF

    def read(self, source: dict) -> SourceResult:
        res = self.result(source)
        p = self.params(source)
        urls = [u for u in (p.get("urls") or [p.get("url") or source["catalog_url"]]) if u]
        failed: list[tuple[str, FetchError]] = []
        seen: set[str] = set()
        for page_url in urls:
            try:
                soup = self.soup(page_url, res)
            except FetchError as e:
                failed.append((page_url, e))
                continue
            for block in _blocks(soup):
                for o in _parse_block(block, page_url):
                    stem = urlsplit(o["pdf"]).path.rsplit("/", 1)[-1].rsplit(".", 1)[0] if o["pdf"] else ""
                    ext_id = o["guid"] or (slugify(unquote(stem)) if stem else slugify(o["title"]))
                    if ext_id in seen:
                        continue
                    seen.add(ext_id)
                    res.offers.append(self.offer(
                        source, ext_id=ext_id, title=o["title"], url=o["pdf"] or page_url,
                        location=o["location"], contract=o["contract"],
                        description=", ".join(o["entity"])))
        if failed:
            if len(failed) == len(urls):
                raise failed[0][1]
            for u, e in failed:
                _partial(res, u, e)
        return res
