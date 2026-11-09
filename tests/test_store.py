"""SupabaseStore builds the right PostgREST calls (no network)."""
import json

from scraper.store import SupabaseStore


class FakeResp:
    def __init__(self, status=200, body="[]"):
        self.status_code = status
        self.text = body

    def json(self):
        return json.loads(self.text)


def test_calls(monkeypatch):
    s = SupabaseStore("https://abc.supabase.co", "sb_secret_xyz")
    calls = []

    def fake_request(method, url, params=None, data=None, headers=None, timeout=None):
        calls.append((method, url, params, json.loads(data) if data else None, headers))
        return FakeResp(201, "")

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("GET", url, params, None, headers))
        return FakeResp(200, json.dumps([{"id": "a"}]))

    monkeypatch.setattr(s.s, "request", fake_request)
    monkeypatch.setattr(s.s, "get", fake_get)
    assert s.s.headers["apikey"] == "sb_secret_xyz"
    assert "Authorization" not in s.s.headers          # new keys: apikey header only

    assert s.load_sources() == [{"id": "a"}]
    s.insert_offers([{"id": "amundi:1", "source_id": "amundi", "title": "T", "status": "postule"}])
    m, url, params, body, headers = calls[-1]
    assert m == "POST" and url.endswith("/rest/v1/offers") and params == {"on_conflict": "id"}
    assert "status" not in body[0]                      # Luca's column is never overwritten
    assert "merge-duplicates" in headers["Prefer"]
    s.close_offers(["amundi:1", 'x:"2'], "2026-11-09")
    m, url, params, body, _ = calls[-1]
    assert m == "PATCH" and params["id"] == 'in.("amundi:1","x:2")' and body["closed"] is True


def test_legacy_key_uses_bearer():
    s = SupabaseStore("https://abc.supabase.co", "eyJhbGciOi.legacy.jwt")
    assert s.s.headers["Authorization"].startswith("Bearer ")


def test_schema_column_grants_are_not_bypassed_by_table_grants():
    """Supabase grants ALL on new tables to `authenticated`: a column grant (insert (sources))
    only restricts anything if the table-wide privilege is revoked first."""
    import re
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1] / "supabase" / "schema.sql").read_text("utf-8")
    revoked = {(priv, table) for privs, tables in
               re.findall(r"revoke ([a-z, ]+) on ([a-z_., ]+?) from authenticated", sql)
               for priv in re.split(r",\s*", privs) for table in re.split(r",\s*", tables)}
    column_grants = re.findall(r"grant (?:[a-z, ]*?\b)?(insert|update) \([^)]*\) on (public\.[a-z_]+) to authenticated",
                               sql)
    assert len(column_grants) == 4
    for priv, table in column_grants:
        assert (priv, table) in revoked or ("all", table) in revoked, (priv, table)
