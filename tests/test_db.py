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


def test_purge_all_keeps_anon(conn):
    db.ensure_anon_account(conn)
    acct = _mk_account(conn, "grace")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(7))
    db.record_confirmation(conn, eid, acct["id"], True, 1)
    counts = db.purge_all(conn)
    assert counts["entries"] == 1
    assert db.get_entry(conn, eid) is None
    assert db.get_account_by_handle(conn, "grace") is None
    # anon system account survives
    from agentpool import ANON_HANDLE
    assert db.get_account_by_handle(conn, ANON_HANDLE) is not None
    # vec table emptied — a fresh insert reuses the space without KNN errors
    assert db.knn(conn, _vec(7), n=5) == []


def test_purge_handle_deletes_when_no_posts(conn):
    _mk_account(conn, "junk-test-handle")
    result = db.purge_handle(conn, "junk-test-handle")
    assert result["outcome"] == "deleted"
    assert result["entries_removed"] == 0
    assert db.get_account_by_handle(conn, "junk-test-handle") is None


def test_purge_handle_bans_when_has_posts(conn):
    acct = _mk_account(conn, "heidi")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(5))
    db.record_confirmation(conn, eid, acct["id"], True, 1)
    result = db.purge_handle(conn, "heidi")
    assert result["outcome"] == "banned"
    assert result["entries_removed"] == 1
    assert result["votes_deleted"] == 1
    row = db.get_account_by_handle(conn, "heidi")
    assert row is not None and row["banned"] == 1  # account row kept (FK), just hidden
    assert db.get_entry(conn, eid)["status"] == "removed"


def test_purge_handle_unknown_returns_none(conn):
    assert db.purge_handle(conn, "nobody-registered-this") is None


def test_purge_handle_rejects_anon(conn):
    db.ensure_anon_account(conn)
    from agentpool import ANON_HANDLE
    try:
        db.purge_handle(conn, ANON_HANDLE)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_remove_by_tier_since(conn):
    acct = _mk_account(conn, "frank", "free")
    eid = db.insert_entry(conn, "p", "s", [], "", acct["id"], acct["tier"], _vec(4))
    epoch = "2000-01-01T00:00:00+00:00"
    n = db.remove_entries_by_tier_since(conn, "free", epoch)
    assert n == 1
    assert db.get_entry(conn, eid)["status"] == "removed"


def test_leaderboard_orders_by_confirms_then_posts(conn):
    db.ensure_anon_account(conn)
    alice = _mk_account(conn, "alice")
    bob = _mk_account(conn, "bob")
    voter1 = _mk_account(conn, "voter1")
    voter2 = _mk_account(conn, "voter2")

    a1 = db.insert_entry(conn, "p1", "s1", [], "", alice["id"], alice["tier"], _vec(10))
    db.insert_entry(conn, "p2", "s2", [], "", alice["id"], alice["tier"], _vec(11))
    b1 = db.insert_entry(conn, "p3", "s3", [], "", bob["id"], bob["tier"], _vec(12))

    # bob has fewer posts (1) but more confirms received (2) -> should rank first
    db.record_confirmation(conn, b1, voter1["id"], True, 1)
    db.record_confirmation(conn, b1, voter2["id"], True, 1)
    db.record_confirmation(conn, a1, voter1["id"], True, 1)

    board = db.leaderboard(conn)
    handles = [row["handle"] for row in board]
    assert handles == ["bob", "alice"]
    assert board[0]["posts"] == 1
    assert board[0]["confirms_received"] == 2


def test_leaderboard_excludes_anon_and_zero_post_accounts(conn):
    db.ensure_anon_account(conn)
    _mk_account(conn, "carol")  # never posts
    board = db.leaderboard(conn)
    assert board == []


def test_trust_totals_counts_and_tier_weights(conn):
    db.ensure_anon_account(conn)
    alice = _mk_account(conn, "alice", "free")
    carol = _mk_account(conn, "carol", "verified")
    eid = db.insert_entry(conn, "p", "s", [], "", alice["id"], alice["tier"], _vec(5))
    db.record_confirmation(conn, eid, carol["id"], True, 3)

    totals = db.trust_totals(conn)
    assert totals["active_entries"] == 1
    assert totals["contributors"] == 2  # alice + carol, anon excluded
    assert totals["total_confirmations"] == 1
    assert totals["contributors_by_tier"] == {"free": 1, "verified": 1}
    assert totals["vote_weight_by_tier"]["verified"] == 3
