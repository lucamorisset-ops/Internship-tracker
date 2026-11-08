"""Parser registry: `sources.kind` -> module in this package exposing `Parser`."""
from __future__ import annotations

import importlib

from .base import BaseParser, Context

# kind -> module name (scraper/parsers/<module>.py)
REGISTRY: dict[str, str] = {
    # public JSON APIs of the official portals
    "oracle_hcm": "oracle_hcm",          # Lazard, JP Morgan, Edmond de Rothschild
    "smartrecruiters": "smartrecruiters",  # Sycomore
    "wp_job": "wp_job",                  # Mirova (site Natixis, WordPress)
    # server-rendered HTML catalogues
    "talentsoft": "talentsoft",          # Amundi
    "bnp": "bnp",                        # BNP Paribas
    "talentbrew": "talentbrew",          # BlackRock
    "talnet": "talnet",                  # Morgan Stanley
    "creditmutuel": "creditmutuel",      # La Française / Crédit Mutuel AM
    "sainoo": "sainoo",                  # Amiral Gestion
    "dnca": "dnca",                      # DNCA
    "comgest": "comgest",                # Comgest
    "yello": "yello",                    # Deutsche Bank
    # pages that need a browser
    "carmignac": "carmignac",            # Carmignac
    "bpifrance": "bpifrance",            # Bpifrance
    # no readable catalogue
    "page_watch": "page_watch",          # Moneta, Eleva: alert when the page changes
    "roles_watch": "roles_watch",        # Goldman Sachs: check known offer pages only
    "blocked": "blocked",                # Pictet: robots.txt forbids every page
    # new companies added from the site
    "auto": "auto",                      # detect the ATS, then read it
    "generic": "generic",                # links that look like offers on a careers page
}


def get_parser(kind: str, ctx: Context) -> BaseParser:
    mod_name = REGISTRY.get(kind or "auto")
    if not mod_name:
        raise KeyError(f"lecteur inconnu : {kind}")
    mod = importlib.import_module(f"{__name__}.{mod_name}")
    return mod.Parser(ctx)


__all__ = ["REGISTRY", "get_parser", "BaseParser", "Context"]
