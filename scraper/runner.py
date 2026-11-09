"""One pass of the robot over every enabled source.

    python -m scraper                 # all sources, writes to Supabase
    python -m scraper --only amundi,dnca --dry-run
    python -m scraper --local data/local.json   # no Supabase, JSON file

Environment (GitHub secrets / variables):
    SUPABASE_URL, SUPABASE_SECRET_KEY, NTFY_TOPIC, SITE_URL, CAPTURE_DIR
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
import traceback
from datetime import date, datetime, timezone
from typing import Any

from .browser import LazyBrowser
from .http import MAX_CRAWL_DELAY, Fetcher, FetchError, RobotsDisallowed, env_capture_dir
from .matching import classify
from .models import Offer, SourceResult, url_key
from .notify import Notifier
from .parsers import Context, get_parser
from .store import LocalStore, SupabaseStore, now_iso

log = logging.getLogger("scraper")

MAX_DETAILS_PER_SOURCE = 12
METIER_ONLY = "métier hors critères"   # classify(): the only reason an offer was excluded
ALERT_FIX = ("Crée une alerte e-mail sur le site carrières officiel de l'entreprise : "
             "c'est la seule façon fiable d'être prévenu pour ce site.")


# ------------------------------------------------------------------ helpers
def explain_failure(exc: Exception) -> tuple[str, str, str]:
    """(status, reason, fix) in French for the « Sites qui résistent » tab."""
    if isinstance(exc, RobotsDisallowed) and exc.unreachable:
        return ("erreur",
                f"Le fichier robots.txt de {exc.url.split('/')[2]} n'a pas pu être lu (erreur réseau ou serveur). "
                "Par prudence (règle RFC 9309), le robot ne lit pas le site tant que ce fichier est injoignable.",
                "Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage.")
    if isinstance(exc, RobotsDisallowed):
        return ("resiste",
                f"Le fichier robots.txt du site interdit aux robots de lire {exc.url}. "
                "Le robot respecte cette règle et ne lit pas la page.",
                ALERT_FIX)
    if isinstance(exc, FetchError):
        if "Crawl-delay" in exc.detail:
            return ("resiste",
                    f"Le fichier robots.txt de {exc.url.split('/')[2]} demande d'attendre plus de "
                    f"{MAX_CRAWL_DELAY:g} secondes entre deux pages ({exc.detail}). Le robot respecte "
                    "cette règle et ne lit pas ce site.",
                    ALERT_FIX)
        if exc.status in (401, 403, 429) or "anti-robot" in exc.detail:
            return ("resiste",
                    f"Le site refuse la lecture automatique (réponse {exc.status or '?'}"
                    f"{', page anti-robot' if 'anti-robot' in exc.detail else ''}) sur {exc.url}.",
                    ALERT_FIX + " Le robot réessaiera à chaque passage.")
        if exc.status == 404:
            return ("erreur",
                    f"La page {exc.url} n'existe plus (404) : le site carrières a sans doute changé d'adresse.",
                    "Donne-moi la nouvelle adresse du catalogue d'offres, ou corrige-la dans l'onglet Sources.")
        return ("erreur", f"Le site n'a pas répondu correctement ({exc}).",
                "Rien à faire si cela ne se répète pas : le robot réessaiera au prochain passage.")
    return ("erreur",
            f"Le lecteur de ce site a échoué ({type(exc).__name__}: {str(exc)[:200]}). "
            "La structure de la page a probablement changé.",
            "Le lecteur doit être corrigé dans le code (dossier scraper/parsers).")


def read_source(parser, source: dict) -> SourceResult:
    fetcher = getattr(getattr(parser, "ctx", None), "fetcher", None)
    start = len(fetcher.log) if fetcher is not None else 0
    try:
        res = parser.read(source)
    except Exception as e:  # noqa: BLE001 - every failure becomes a report
        status, reason, fix = explain_failure(e)
        res = SourceResult(source_id=source["id"], ok=False, status=status, method=parser.method,
                           reason=reason, fix=fix, error=f"{type(e).__name__}: {e}")
        # the URLs tried before the failure stay visible on the site (« URL essayées »)
        tried = [x["url"] for x in (fetcher.log[start:] if fetcher is not None else []) if x.get("url")]
        if getattr(e, "url", None):
            tried.append(e.url)
        res.urls_read = list(dict.fromkeys(tried))
        if isinstance(e, RobotsDisallowed) and not e.unreachable:
            res.blocked_by_robots.append(e.url)
        if not isinstance(e, (RobotsDisallowed, FetchError)):
            log.error("source %s: %s", source["id"], traceback.format_exc())
    return res


def _dedupe(offers: list[Offer]) -> list[Offer]:
    """Same offer read twice (two lists, two searches) -> keep one, by id.

    Offers sharing one URL but with different ids (e.g. Carmignac: every row
    points to the careers page) are distinct and all kept.
    """
    seen: dict[str, Offer] = {}
    for o in offers:
        seen.setdefault(o.id, o)
    return list(seen.values())


# ------------------------------------------------------------------ main pass
def run(store, notifier: Notifier, *, only: list[str] | None = None, trigger: str = "schedule",
        capture_dir: str | None = None, use_browser: bool = True, today: date | None = None,
        fetcher: Fetcher | None = None) -> dict[str, Any]:
    started = now_iso()
    t0 = time.monotonic()
    today = today or date.today()
    fetcher = fetcher or Fetcher(capture_dir=capture_dir)
    browser = LazyBrowser(fetcher) if use_browser else None
    ctx = Context(fetcher=fetcher, browser=browser, today=today)

    sources = store.load_sources()
    if only:
        sources = [s for s in sources if s["id"] in only]
    existing = store.load_offers()
    by_key: dict[tuple[str, str], dict] = {}
    for o in existing:
        by_key[(o["source_id"], o.get("url_key") or url_key(o.get("url") or ""))] = o
        by_key[(o["source_id"], "id:" + o["id"])] = o

    report: list[dict] = []
    new_hits: list[Offer] = []
    status_changes: list[tuple[dict, SourceResult]] = []
    totals = {"sources": len(sources), "ok": 0, "resiste": 0, "erreur": 0, "new": 0, "closed": 0}

    try:
        for src in sources:
            kind = src.get("kind") or "auto"
            log.info("— %s (%s)", src["company"], kind)
            src = dict(src, known_offers=[o for o in existing if o["source_id"] == src["id"]
                                          and not o.get("closed")])
            try:
                parser = get_parser(kind, ctx)
            except Exception as e:  # noqa: BLE001
                res = SourceResult(src["id"], ok=False, status="erreur", reason=f"Lecteur introuvable : {kind}",
                                   fix="Le lecteur doit être ajouté dans scraper/parsers.", error=str(e))
                parser = None
            else:
                res = read_source(parser, src)
            res.offers = _dedupe(res.offers)
            criteria = src.get("criteria") or None
            assume_intern = bool((src.get("params") or {}).get("internships_only"))

            new_offers: list[Offer] = []
            to_enrich: list[Offer] = []
            seen_ids: list[str] = []
            url_count: dict[str, int] = {}
            for off in res.offers:
                url_count[off.url_key] = url_count.get(off.url_key, 0) + 1
            for off in res.offers:
                # by id first; by URL only when that URL is specific to this offer
                known = by_key.get((src["id"], "id:" + off.id))
                if (not known and off.url_key and url_count.get(off.url_key) == 1
                        and not off.extra.get("fixed")):   # page_watch alerts all share the page URL
                    known = by_key.get((src["id"], off.url_key))
                if known:
                    seen_ids.append(known["id"])
                    continue
                if off.extra.get("fixed"):          # e.g. page_watch: relevance set by the parser
                    new_offers.append(off)
                    continue
                classify(off, criteria, today, assume_internship=assume_intern)
                second_chance = off.reasons == METIER_ONLY or (
                    # companies added from the site: the list rarely says "stage", the offer page often does
                    kind in ("auto", "generic")
                    and set(off.reasons.split(" · ")) <= {"pas un stage", METIER_ONLY})
                if off.relevance != "exclue" or second_chance:
                    to_enrich.append(off)
                new_offers.append(off)
            # offer pages: interesting offers first, then internships whose title names no
            # métier ("2027 Off-cycle Internship Program – EMEA"): the page often does
            to_enrich.sort(key=lambda o: o.relevance == "exclue")
            for off in to_enrich[:MAX_DETAILS_PER_SOURCE] if parser is not None else []:
                try:
                    parser.enrich(off, res)
                except Exception as e:  # noqa: BLE001 - details are optional
                    log.info("  fiche illisible %s: %s", off.url, e)
                classify(off, criteria, today, assume_internship=assume_intern)

            # offers that disappeared from a complete, successful read are closed
            closed: list[str] = []
            if res.ok and res.complete:
                open_known = [o for o in existing if o["source_id"] == src["id"]
                              and not o.get("closed") and not o.get("manual")]
                if res.offers or len(open_known) <= 2:
                    closed = [o["id"] for o in open_known if o["id"] not in seen_ids]
                else:
                    res.status = "partiel"
                    res.reason = (f"Le site a renvoyé 0 offre alors que {len(open_known)} étaient en ligne : "
                                  "la page a peut-être changé. Aucune offre n'a été marquée comme fermée.")
                    res.fix = "À vérifier : ouvre le catalogue avec le bouton de la source."
            for u in res.closed_urls:
                k = by_key.get((src["id"], url_key(u)))
                if k and not k.get("closed"):
                    closed.append(k["id"])

            if new_offers:
                store.insert_offers([o.to_row() for o in new_offers])
            if seen_ids:
                store.touch_offers(seen_ids)
            if closed:
                store.close_offers(sorted(set(closed)), today.isoformat())

            fields = {
                "status": res.status if res.ok or res.status != "ok" else "erreur",
                "last_checked": now_iso(),
                "last_method": res.method,
                "last_error": res.error or None,
                "last_count": len(res.offers),
                "last_urls": res.urls_read,
                "reason": res.reason or None,
                "fix": res.fix or None,
            }
            if res.page_hash:
                fields["page_hash"] = res.page_hash
            fields.update(res.source_updates)  # e.g. kind/params found by "auto"
            store.update_source(src["id"], fields)
            if (src.get("status") or "ok") != fields["status"]:
                status_changes.append((src, res))

            hits = [o for o in new_offers if o.relevance in ("cible", "proche")]
            new_hits += hits
            totals["new"] += len(new_offers)
            totals["closed"] += len(set(closed))
            key = fields["status"] if fields["status"] in ("resiste", "erreur") else "ok"
            totals[key] += 1
            item = res.summary() | {"company": src["company"], "new": len(new_offers),
                                    "hits": len(hits), "closed": len(set(closed))}
            report.append(item)
            log.info("  %s · %d offres · %d nouvelles (%d intéressantes) · %d fermées · %s",
                     fields["status"], len(res.offers), len(new_offers), len(hits), len(set(closed)),
                     res.reason[:120] if res.reason else "")
    finally:
        if browser:
            browser.close()

    _notify(notifier, new_hits, status_changes, sources)
    summary = {
        "started_at": started,
        "finished_at": now_iso(),
        "duration_s": round(time.monotonic() - t0),
        "trigger": trigger,
        "totals": totals,
        "sources": report,
    }
    store.add_run({"started_at": started, "finished_at": summary["finished_at"], "trigger": trigger,
                   "totals": totals, "report": report})
    store.set_meta("last_run", {k: summary[k] for k in ("started_at", "finished_at", "trigger", "totals")})
    return summary


def _notify(notifier: Notifier, hits: list[Offer], changes: list[tuple[dict, SourceResult]],
            sources: list[dict]) -> None:
    names = {s["id"]: s["company"] for s in sources}
    cible = [o for o in hits if o.relevance == "cible"]
    proche = [o for o in hits if o.relevance == "proche"]
    if len(cible) <= 4:
        for o in cible:
            notifier.send(f"🎯 {names.get(o.source_id, o.company)} : {o.title}",
                          f"{o.location or 'Lieu non précisé'} · démarrage {o.start_label}\n{o.reasons}",
                          priority=4, tags=["dart"], click=o.url)
    else:
        notifier.send(f"🎯 {len(cible)} nouvelles offres ciblées",
                      "\n".join(f"• {names.get(o.source_id, o.company)} : {o.title}" for o in cible[:15]),
                      priority=4, tags=["dart"])
    if proche:
        notifier.send(f"{len(proche)} nouvelle(s) offre(s) à vérifier",
                      "\n".join(f"• {names.get(o.source_id, o.company)} : {o.title}" for o in proche[:15]),
                      priority=3, tags=["mag"])
    bad = [(s, r) for s, r in changes if r.status in ("resiste", "erreur", "partiel")]
    good = [(s, r) for s, r in changes if r.status == "ok" and (s.get("status") in ("resiste", "erreur", "partiel"))]
    if bad:
        notifier.send(f"⚠️ {len(bad)} site(s) résistent",
                      "\n".join(f"• {s['company']} : {r.reason[:180]}" for s, r in bad),
                      priority=4, tags=["warning"])
    if good:
        notifier.send(f"✅ {len(good)} site(s) lisible(s) à nouveau",
                      ", ".join(s["company"] for s, _ in good), priority=2, tags=["white_check_mark"])


# ------------------------------------------------------------------ CLI
def _env(name: str) -> str:
    """Environment value without surrounding whitespace, quotes or line breaks."""
    return (os.environ.get(name) or "").strip().strip('"').strip("'").strip()


def _secret_key() -> str:
    """The Supabase secret key, even if pasted with a label or on several lines."""
    raw = _env("SUPABASE_SECRET_KEY")
    m = re.search(r"sb_secret_[A-Za-z0-9_\-]+|eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", raw)
    if m:
        if m.group(0) != raw:
            print(f"Secret SUPABASE_SECRET_KEY : clé extraite d'un collage de {raw.count(chr(10)) + 1} ligne(s) "
                  f"({len(m.group(0))} caractères gardés sur {len(raw)}).", file=sys.stderr)
        return m.group(0)
    if raw:
        # never print the key itself: only its shape
        print("La valeur du secret SUPABASE_SECRET_KEY ne ressemble pas à une clé Supabase "
              f"({len(raw)} caractères, {raw.count(chr(10)) + 1} ligne(s), "
              f"commence par « sb_secret_ » : {'oui' if raw.startswith('sb_secret_') else 'non'}). "
              "Recopie la Secret key avec l'icône de copie de Supabase (Project Settings > API Keys).",
              file=sys.stderr)
    return raw


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper")
    ap.add_argument("--only", help="ids de sources séparés par des virgules")
    ap.add_argument("--dry-run", action="store_true", help="aucune notification")
    ap.add_argument("--local", help="fichier JSON à la place de Supabase")
    ap.add_argument("--trigger", default=os.environ.get("RUN_TRIGGER", "schedule"))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--requests-only", action="store_true",
                    help="ne lancer un passage que si le site en a demandé un")
    ap.add_argument("--has-requests", action="store_true",
                    help="écrire pending=true/false dans $GITHUB_OUTPUT et s'arrêter")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.local:
        store = LocalStore(args.local)
    else:
        # secrets pasted in GitHub often carry a trailing newline or spaces
        url, key = _env("SUPABASE_URL"), _secret_key()
        if not url or not key:
            print("SUPABASE_URL et SUPABASE_SECRET_KEY sont nécessaires (ou --local).", file=sys.stderr)
            return 2
        store = SupabaseStore(url, key)

    try:
        pending = store.pending_requests()
    except RuntimeError as e:
        if " 401" in str(e) or " 403" in str(e):
            print("Supabase refuse la clé (401/403) : le secret SUPABASE_SECRET_KEY n'est pas la Secret key "
                  "complète du projet. Recopie-la avec l'icône de copie (Project Settings > API Keys) "
                  "et remplace le secret dans GitHub.", file=sys.stderr)
            return 2
        raise
    if args.has_requests:
        out = os.environ.get("GITHUB_OUTPUT")
        line = f"pending={'true' if pending else 'false'}\n"
        if out:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(line)
        print(line.strip())
        return 0
    if args.requests_only and not pending:
        log.info("Aucune demande de mise à jour en attente.")
        return 0
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    req_only = sorted({s for r in pending for s in (r.get("sources") or [])})
    if args.requests_only and req_only and all(r.get("sources") for r in pending):
        only = req_only
    trigger = "demande du site" if pending and args.requests_only else args.trigger

    notifier = Notifier(_env("NTFY_TOPIC"), _env("SITE_URL"), dry_run=args.dry_run)
    summary = run(store, notifier, only=only, trigger=trigger, capture_dir=env_capture_dir(),
                  use_browser=not args.no_browser)
    store.finish_requests([r["id"] for r in pending if "id" in r],
                          f"passage du {datetime.now(timezone.utc):%d/%m %H:%M} UTC")
    t = summary["totals"]
    log.info("Terminé : %d sources, %d lisibles, %d résistent, %d en erreur, %d nouvelles offres, %d fermées.",
             t["sources"], t["ok"], t["resiste"], t["erreur"], t["new"], t["closed"])
    return 0
