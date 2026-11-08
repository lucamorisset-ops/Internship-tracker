"""Where the robot reads its sources and writes offers.

SupabaseStore talks to the project's REST API (PostgREST) with the secret
key, which bypasses Row Level Security: it must only ever live in the
GitHub secret SUPABASE_SECRET_KEY, never in the site or the repository.

LocalStore keeps everything in a JSON file: used by tests and dry runs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

log = logging.getLogger(__name__)

# Columns the robot owns on `offers`. Luca's own column (`status`) is never sent.
OFFER_COLUMNS = (
    "id", "source_id", "ext_id", "url", "url_key", "title", "company", "location", "country",
    "contract", "published", "published_label", "description", "start_label", "relevance",
    "reasons",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _offer_payload(row: dict) -> dict:
    out = {k: row.get(k) for k in OFFER_COLUMNS}
    if out.get("description"):
        out["description"] = out["description"][:4000]
    return out


class SupabaseStore:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.s = requests.Session()
        # New Supabase keys (sb_secret_...) go in the apikey header only.
        self.s.headers.update({"apikey": key, "Content-Type": "application/json"})
        if not key.startswith("sb_"):
            self.s.headers["Authorization"] = f"Bearer {key}"   # legacy service_role JWT

    # ------------------------------------------------------------- low level
    def _req(self, method: str, path: str, *, params: dict | None = None, body: Any = None,
             prefer: str | None = None) -> Any:
        headers = {"Prefer": prefer} if prefer else {}
        r = self.s.request(method, f"{self.base}/{path}", params=params,
                           data=json.dumps(body, default=str) if body is not None else None,
                           headers=headers, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.text and "return=minimal" not in (prefer or "") else None

    def _select_all(self, table: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        start = 0
        while True:
            r = self.s.get(f"{self.base}/{table}", params=params,
                           headers={"Range-Unit": "items", "Range": f"{start}-{start + 999}"}, timeout=60)
            if r.status_code >= 300:
                raise RuntimeError(f"Supabase GET {table} -> {r.status_code}: {r.text[:300]}")
            page = r.json()
            rows += page
            if len(page) < 1000:
                return rows
            start += 1000

    @staticmethod
    def _in(ids: Iterable[str]) -> str:
        return "in.(" + ",".join('"' + i.replace('"', '') + '"' for i in ids) + ")"

    # ------------------------------------------------------------- reads
    def load_sources(self) -> list[dict]:
        return self._select_all("sources", {"select": "*", "enabled": "eq.true", "order": "rank.asc"})

    def load_offers(self) -> list[dict]:
        return self._select_all("offers", {
            "select": "id,source_id,url,url_key,closed,manual,relevance,title"})

    def pending_requests(self) -> list[dict]:
        return self._select_all("run_requests", {"select": "*", "done_at": "is.null",
                                                 "order": "requested_at.asc"})

    # ------------------------------------------------------------- writes
    def insert_offers(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), 200):
            chunk = [_offer_payload(r) | {"closed": False, "closed_on": None,
                                          "first_seen": now_iso(), "last_seen": now_iso()}
                     for r in rows[i:i + 200]]
            self._req("POST", "offers", params={"on_conflict": "id"}, body=chunk,
                      prefer="resolution=merge-duplicates,return=minimal")

    def touch_offers(self, ids: list[str], extra: dict | None = None) -> None:
        for i in range(0, len(ids), 100):
            self._req("PATCH", "offers", params={"id": self._in(ids[i:i + 100])},
                      body={"last_seen": now_iso(), "closed": False, "closed_on": None, **(extra or {})},
                      prefer="return=minimal")

    def update_offer(self, oid: str, fields: dict) -> None:
        self._req("PATCH", "offers", params={"id": f"eq.{oid}"}, body=fields, prefer="return=minimal")

    def close_offers(self, ids: list[str], day: str) -> None:
        for i in range(0, len(ids), 100):
            self._req("PATCH", "offers", params={"id": self._in(ids[i:i + 100])},
                      body={"closed": True, "closed_on": day}, prefer="return=minimal")

    def update_source(self, sid: str, fields: dict) -> None:
        self._req("PATCH", "sources", params={"id": f"eq.{sid}"}, body=fields, prefer="return=minimal")

    def add_run(self, row: dict) -> None:
        self._req("POST", "runs", body=row, prefer="return=minimal")

    def finish_requests(self, ids: list[int], run_note: str) -> None:
        if ids:
            self._req("PATCH", "run_requests", params={"id": "in.(" + ",".join(map(str, ids)) + ")"},
                      body={"done_at": now_iso(), "note": run_note}, prefer="return=minimal")

    def set_meta(self, key: str, value: Any) -> None:
        self._req("POST", "meta", params={"on_conflict": "key"}, body=[{"key": key, "value": value}],
                  prefer="resolution=merge-duplicates,return=minimal")


class LocalStore:
    """Same interface, backed by a JSON file (tests, dry runs)."""

    def __init__(self, path: str | Path, sources: list[dict] | None = None):
        self.path = Path(path)
        if self.path.exists():
            self.db = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.db = {"sources": sources or [], "offers": [], "runs": [], "run_requests": [], "meta": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.db, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def load_sources(self) -> list[dict]:
        return sorted([s for s in self.db["sources"] if s.get("enabled", True)], key=lambda s: s.get("rank") or 999)

    def load_offers(self) -> list[dict]:
        return list(self.db["offers"])

    def pending_requests(self) -> list[dict]:
        return [r for r in self.db["run_requests"] if not r.get("done_at")]

    def _offer(self, oid: str) -> dict | None:
        return next((o for o in self.db["offers"] if o["id"] == oid), None)

    def insert_offers(self, rows: list[dict]) -> None:
        for r in rows:
            o = self._offer(r["id"])
            p = _offer_payload(r) | {"closed": False, "closed_on": None, "last_seen": now_iso()}
            if o:
                o.update(p)
            else:
                self.db["offers"].append(p | {"first_seen": now_iso(), "status": "nouvelle", "manual": False})
        self.save()

    def touch_offers(self, ids: list[str], extra: dict | None = None) -> None:
        for oid in ids:
            o = self._offer(oid)
            if o:
                o.update({"last_seen": now_iso(), "closed": False, "closed_on": None, **(extra or {})})
        self.save()

    def update_offer(self, oid: str, fields: dict) -> None:
        o = self._offer(oid)
        if o:
            o.update(fields)
        self.save()

    def close_offers(self, ids: list[str], day: str) -> None:
        for oid in ids:
            o = self._offer(oid)
            if o:
                o.update({"closed": True, "closed_on": day})
        self.save()

    def update_source(self, sid: str, fields: dict) -> None:
        for s in self.db["sources"]:
            if s["id"] == sid:
                s.update(fields)
        self.save()

    def add_run(self, row: dict) -> None:
        self.db["runs"].append(row)
        self.save()

    def finish_requests(self, ids: list[int], run_note: str) -> None:
        for r in self.db["run_requests"]:
            if r.get("id") in ids:
                r["done_at"] = now_iso()
                r["note"] = run_note
        self.save()

    def set_meta(self, key: str, value: Any) -> None:
        self.db["meta"][key] = value
        self.save()
