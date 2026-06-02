from datetime import datetime, timezone

from agentpool import auth, db


def _mk_account(conn, handle="alice", tier="free"):
    return auth.register(conn, handle, tier)


def _vec(seed: int):
    # deterministic vector with a distinct dominant direction per seed
    v = [0.01 * ((seed + i) % 3) for i in range(384)]
    v[seed % 384] = 1.0
    return v


def test_account_unique_handle(conn):
    _mk_account(conn, "bob")
    try:
        _mk_account(conn, "bob")
        assert False, "expected unique violation"
    except Exception:
        pass


def test_insert_and_fetch_entry(conn):
    acct = _mk_account(conn)
    eid = db.insert_entry(
        conn, "problem x", "fix x", ["py", "asyncio"], "Traceback...",
        acct["id"], acct["tier"], _vec(1),
    )
    row = db.get_entry(conn, eid)
    assert row["problem_text"] == "problem x"
    assert row["tier"] == "free"
    assert row["status"] == "active"


def test_knn_returns_nearest(conn):
    acct = _mk_account(conn)
    a = db.insert_entry(conn, "a", "a", [], "", acct["id"], acct["tier"], _vec(1))
    b = db.insert_entry(conn, "b", "b", [], "", acct["id"], acct["tier"], _vec(50))
    hits = db.knn(conn, _vec(1), n=2)
    assert hits[0][0] == a  # closest to its own vector
    ids = {h[0] for h in hits}
    assert ids == {a, b}


def test_confirmation_unique_and_score(conn):
    acct = _mk_account(conn, "carol", "verified")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(2))

    inserted, score = db.record_confirmation(conn, eid, acct["id"], True, 3)
    assert inserted is True
    assert score == 3.0

    # second vote from same account is ignored, score unchanged
    inserted2, score2 = db.record_confirmation(conn, eid, acct["id"], True, 3)
    assert inserted2 is False
    assert score2 == 3.0


def test_fail_vote_sinks_score(conn):
    acct = _mk_account(conn, "dave")
    voter = _mk_account(conn, "eve")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(3))
    db.record_confirmation(conn, eid, acct["id"], True, 1)
    _, score = db.record_confirmation(conn, eid, voter["id"], False, 1)
    assert score == 0.0  # +1 then -1


def test_remove_by_tier_since(conn):
    acct = _mk_account(conn, "frank", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(4))
    epoch = "2000-01-01T00:00:00+00:00"
    n = db.remove_entries_by_tier_since(conn, "free", epoch)
    assert n == 1
    assert db.get_entry(conn, eid)["status"] == "removed"
