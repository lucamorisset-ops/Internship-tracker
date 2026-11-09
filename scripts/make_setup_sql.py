"""Build the one-shot SQL to paste in Supabase (schema + sources + existing offers + allowed e-mail).

    python scripts/make_setup_sql.py --email you@example.com \
        [--export DIR_WITH_offers/*.json] --out setup.sql

The output contains personal data (your e-mail, your follow-up of offers): do not commit it.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.models import slugify, url_key  # noqa: E402
from scraper.parsers.base import clean_text  # noqa: E402

PREFIX_TO_SOURCE = {"cmam": "lafrancaise"}
MIROVA_IDS = {"21608": "20227", "22240": "20473", "22462": "20732"}
EXT_PATTERNS = {
    "amundi": r"_(\d+)\.aspx",
    "lazard": r"/job/(\d+)",
    "jpm": r"/job/(\d+)",
    "sycomore": r"/(\d{10,})",
    "ms": r"/opp/(\d+)",
    "blackrock": r"/(\d{8,})$",
    "bpifrance": r"[?&]id=(\d+)",
    "lafrancaise": r"annonce=(\d+)",
    "amiral": r"/jobs/(\d+)",
    "gs": r"/roles/(\d+)",
    "dnca": r"/carrieres/([A-Z0-9]+)",
    "db": r"/jobs/([^/?#]+)",           # yello drops ?job_board_id=..., the exported URL may keep it
    "bnp": r"/(?:offre-emploi|job-offer)/([^/?#]+)",
}


def q(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(v).replace("'", "''") + "'"


def fr_to_iso(d: str | None) -> str | None:
    if not d:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def offer_row(doc_id: str, d: dict) -> dict | None:
    prefix = doc_id.split("-")[0]
    src = PREFIX_TO_SOURCE.get(prefix, prefix)
    url = d.get("url") or ""
    manual = False
    if src == "mirova":
        ext = MIROVA_IDS.get(doc_id.split("-")[1], doc_id.split("-", 1)[1])
    elif src == "edram":            # found on JobTeaser by hand: never auto-closed
        m = re.search(r"job-offers/([0-9a-f]{8})", url)
        ext, manual = "jt-" + (m.group(1) if m else doc_id.split("-", 1)[1]), True
    elif src == "moneta":
        ext, manual = "spontanee", True
    elif src == "carmignac":        # no offer URL on the site: same id as the carmignac reader
        ext = slugify(f"{clean_text(d.get('title'))}-{clean_text(d.get('location'))}")
    elif src in EXT_PATTERNS and re.search(EXT_PATTERNS[src], url):
        ext = re.search(EXT_PATTERNS[src], url).group(1)
    else:
        ext = doc_id.split("-", 1)[1]
    published_iso = d.get("publishedIso") or None
    return {
        "id": f"{src}:{ext}",
        "source_id": src,
        "ext_id": ext,
        "url": url,
        "url_key": url_key(url),
        "title": d.get("title"),
        "company": d.get("company"),
        "location": d.get("location"),
        "published": published_iso,
        "published_label": None if published_iso else d.get("published"),
        "start_label": d.get("start"),
        "relevance": d.get("relevance"),
        "reasons": d.get("note"),
        "status": d.get("status") or "nouvelle",
        "manual": manual,
        "first_seen": fr_to_iso(d.get("firstSeen")),
        "closed": bool(d.get("closed")),
        "closed_on": fr_to_iso(d.get("closedOn")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--export", help="dossier contenant offers/*.json (export de l'ancien tracker)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    parts = [f"-- Généré le {datetime.now():%d/%m/%Y %H:%M}. Contient ton e-mail : ne pas publier.\n",
             (ROOT / "supabase/schema.sql").read_text(encoding="utf-8"),
             "\n-- ---------------------------------------------------------------- accès\n",
             f"insert into public.allowed_users(email) values ({q(a.email.lower())}) on conflict do nothing;\n",
             "\n-- ---------------------------------------------------------------- sources\n"]
    seed = json.loads((ROOT / "supabase/sources_seed.json").read_text(encoding="utf-8"))
    for s in seed:
        cols = ["id", "company", "rank", "kind", "params", "catalog_url", "filters", "status"]
        vals = [s["id"], s["company"], s["rank"], s["kind"], s.get("params") or {}, s.get("catalog_url"),
                s.get("filters"), "a_configurer"]
        upd = ", ".join(f"{c} = excluded.{c}" for c in cols[1:-1])
        parts.append(f"insert into public.sources ({', '.join(cols)}) values ({', '.join(q(v) for v in vals)})\n"
                     f"  on conflict (id) do update set {upd};\n")

    if a.export:
        parts.append("\n-- ---------------------------------------------------------------- offres déjà repérées\n")
        for f in sorted(glob.glob(str(Path(a.export) / "offers" / "*.json"))):
            raw = json.loads(Path(f).read_text(encoding="utf-8"))
            d = raw.get("data", raw)
            r = offer_row(Path(f).stem, d)
            if not r:
                continue
            if r["source_id"] not in {s["id"] for s in seed}:
                # an unknown entreprise would break the whole script (foreign key): skipped
                print(f"offre ignorée, entreprise inconnue « {r['source_id']} » : {Path(f).name}", file=sys.stderr)
                continue
            cols = [k for k, v in r.items() if v is not None]
            parts.append(
                f"insert into public.offers ({', '.join(cols)}) values ({', '.join(q(r[c]) for c in cols)})\n"
                f"  on conflict (id) do nothing;\n")   # re-running never overwrites your follow-up
    Path(a.out).write_text("".join(parts), encoding="utf-8")
    print(f"écrit : {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
