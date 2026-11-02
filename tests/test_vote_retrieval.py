"""hm-#891: a vote is only accepted for an entry the same key has retrieved.

The server module opens its DB at import, so each test points db.DB_PATH at a
tmp file first. Embeddings are faked (one fixed unit vector) so no model loads.
"""
import asyncio
import json

import pytest
from fastmcp.exceptions import ToolError
from starlette.requests import Request

from agentpool import auth, db

VEC_A = [1.0] + [0.0] * 383  # entry the queries below match exactly
VEC_B = [0.0, 1.0] + [0.0] * 382  # orthogonal: below the similarity floor


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "vote.db"))
    from agentpool import server

    conn = db.connect()
    db.init_db(conn)
    db.ensure_anon_account(conn)

    headers: dict = {}
    monkeypatch.setattr(server, "get_http_headers", lambda: headers)
    monkeypatch.setattr(server, "embed", lambda text: list(VEC_A))

    class World:
        pass

    w = World()
    w.server, w.conn, w.headers = server, conn, headers
    w.author = auth.register(conn, "author", "free")
    w.voter = auth.register(conn, "voter", "free")
    w.other = auth.register(conn, "other", "free")
    w.entry = db.insert_entry(
        conn, "pnpm dev tailwind error", "install the postcss plugin", ["t"], "",
        w.author["id"], "free", VEC_A,
    )
    w.far_entry = db.insert_entry(
        conn, "unrelated problem", "unrelated fix", ["t"], "",
        w.author["id"], "free", VEC_B,
    )
    w.as_key = lambda acct: (headers.clear(), headers.update({"x-api-key": acct["api_key"]}))
    w.as_anon = headers.clear
    yield w
    conn.close()


def _score(w, entry_id):
    return w.conn.execute("SELECT score FROM entries WHERE id=?", (entry_id,)).fetchone()[0]


def _votes(w, entry_id):
    return w.conn.execute(
        "SELECT COUNT(*) FROM confirmations WHERE entry_id=?", (entry_id,)
    ).fetchone()[0]


def _retrieved(w, acct, entry_id) -> bool:
    return db.has_retrieved(w.conn, acct["id"], entry_id)


# ---------- db layer ----------

def test_record_retrievals_is_idempotent(conn):
    a = auth.register(conn, "a", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", a["id"], "free", VEC_A)
    assert not db.has_retrieved(conn, a["id"], eid)
    db.record_retrievals(conn, a["id"], [eid])
    db.record_retrievals(conn, a["id"], [eid, eid])
    assert db.has_retrieved(conn, a["id"], eid)
    assert conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0] == 1
    db.record_retrievals(conn, a["id"], [])  # no-op, no error


def test_retrievals_table_is_added_to_an_existing_db(conn):
    conn.execute("DROP TABLE retrievals")
    db.init_db(conn)  # what server import does on an already-deployed DB
    a = auth.register(conn, "late", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", a["id"], "free", VEC_A)
    db.record_retrievals(conn, a["id"], [eid])
    assert db.has_retrieved(conn, a["id"], eid)


def test_purge_handle_with_retrievals_does_not_hit_the_fk(conn):
    a = auth.register(conn, "reader-only", "free")
    poster = auth.register(conn, "poster", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", poster["id"], "free", VEC_A)
    db.record_retrievals(conn, a["id"], [eid])
    assert db.purge_handle(conn, "reader-only")["outcome"] == "deleted"
    assert conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0] == 0


def test_purge_all_clears_retrievals(conn):
    a = auth.register(conn, "a", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", a["id"], "free", VEC_A)
    db.record_retrievals(conn, a["id"], [eid])
    assert db.purge_all(conn)["retrievals"] == 1


# ---------- confirm_solution (MCP) ----------

def test_vote_without_retrieval_is_rejected(world):
    w = world
    w.as_key(w.voter)
    with pytest.raises(ToolError, match=r"no retrieval on record for entry #%d" % w.entry):
        w.server.confirm_solution(w.entry, True)
    assert _votes(w, w.entry) == 0
    assert _score(w, w.entry) == 0


def test_vote_after_ask_pool_is_accepted(world):
    w = world
    w.as_key(w.voter)
    found = w.server.ask_pool("tailwind postcss error")
    assert f"#{w.entry}" in found
    out = w.server.confirm_solution(w.entry, True)
    assert "new score" in out
    assert _votes(w, w.entry) == 1
    assert _score(w, w.entry) == 1


def test_vote_after_get_entry_is_accepted(world):
    w = world
    w.as_key(w.voter)
    w.server.get_entry(w.entry)
    assert "new score" in w.server.confirm_solution(w.entry, False)
    assert _votes(w, w.entry) == 1
    assert _score(w, w.entry) == -1


def test_retrieval_belongs_to_the_account_that_made_it(world):
    w = world
    w.as_key(w.other)
    w.server.get_entry(w.entry)
    w.as_key(w.voter)  # voter never read it; other's read doesn't count
    with pytest.raises(ToolError, match="no retrieval on record"):
        w.server.confirm_solution(w.entry, True)
    assert _votes(w, w.entry) == 0


def test_retrieval_belongs_to_the_entry_that_was_read(world):
    w = world
    w.as_key(w.voter)
    w.server.get_entry(w.entry)
    with pytest.raises(ToolError, match=r"entry #%d" % w.far_entry):
        w.server.confirm_solution(w.far_entry, True)


def test_ask_pool_only_records_entries_it_returned(world):
    w = world
    w.as_key(w.voter)
    out = w.server.ask_pool("tailwind postcss error")
    assert f"#{w.entry}" in out and f"#{w.far_entry}" not in out
    assert _retrieved(w, w.voter, w.entry)
    assert not _retrieved(w, w.voter, w.far_entry)
    with pytest.raises(ToolError, match="no retrieval on record"):
        w.server.confirm_solution(w.far_entry, True)


def test_anonymous_reads_record_nothing(world):
    w = world
    w.as_anon()
    w.server.ask_pool("tailwind postcss error")
    w.server.get_entry(w.entry)
    assert w.conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0] == 0


def test_failed_get_entry_records_nothing(world):
    w = world
    w.as_key(w.voter)
    with pytest.raises(ToolError, match="no entry #9999"):
        w.server.get_entry(9999)
    assert w.conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0] == 0


def test_anonymous_vote_still_told_to_join(world):
    w = world
    w.as_anon()
    with pytest.raises(ToolError, match="join"):
        w.server.confirm_solution(w.entry, True)


# ---------- cq HTTP surface ----------

def _req(key=None, unit_id=None, query="", body=None):
    headers = [(b"x-api-key", key.encode())] if key else []
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "headers": headers,
        "path_params": {"unit_id": unit_id}, "query_string": query.encode(),
    }
    return Request(scope, receive)


def _ku(w, entry_id):
    return db.get_entry(w.conn, entry_id)["ku_id"]


def _run(coro):
    resp = asyncio.run(coro)
    return resp.status_code, json.loads(resp.body)


def test_cq_confirm_without_retrieval_is_rejected(world):
    w = world
    status, body = _run(w.server.cq_confirm(
        _req(w.voter["api_key"], _ku(w, w.entry))))
    assert status == 403
    assert "no retrieval on record" in body["error"]
    assert _votes(w, w.entry) == 0


def test_cq_confirm_after_cq_query_is_accepted(world):
    w = world
    status, body = _run(w.server.cq_query_units(
        _req(w.voter["api_key"], query="domains=tailwind&limit=5")))
    assert status == 200 and body["data"]
    status, _ = _run(w.server.cq_confirm(
        _req(w.voter["api_key"], _ku(w, w.entry))))
    assert status == 201
    assert _votes(w, w.entry) == 1


def test_cq_confirm_after_mcp_get_entry_is_accepted(world):
    w = world
    w.as_key(w.voter)
    w.server.get_entry(w.entry)
    status, _ = _run(w.server.cq_confirm(
        _req(w.voter["api_key"], _ku(w, w.entry))))
    assert status == 201


def test_anonymous_cq_query_records_nothing(world):
    w = world
    status, _ = _run(w.server.cq_query_units(_req(None, query="domains=tailwind")))
    assert status == 200
    assert w.conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0] == 0


def test_cq_flag_incorrect_is_a_vote_and_needs_retrieval(world):
    w = world
    ku = _ku(w, w.entry)
    status, body = _run(w.server.cq_flag(
        _req(w.voter["api_key"], ku, body={"reason": "incorrect"})))
    assert status == 403 and "no retrieval on record" in body["error"]
    assert _votes(w, w.entry) == 0

    w.as_key(w.voter)
    w.server.get_entry(w.entry)
    status, _ = _run(w.server.cq_flag(
        _req(w.voter["api_key"], ku, body={"reason": "incorrect"})))
    assert status == 201
    assert _score(w, w.entry) == -1


def test_cq_flag_non_vote_reason_needs_no_retrieval(world):
    w = world
    status, _ = _run(w.server.cq_flag(
        _req(w.voter["api_key"], _ku(w, w.entry), body={"reason": "stale"})))
    assert status == 201
    assert _votes(w, w.entry) == 0
