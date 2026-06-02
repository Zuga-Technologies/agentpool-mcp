from agentpool import auth, db, render


def test_extract_key_from_both_headers():
    # AgentPool native header
    assert auth.extract_key({"x-api-key": "ap_123"}) == "ap_123"
    # cq tooling sends Authorization: Bearer
    assert auth.extract_key({"authorization": "Bearer ap_456"}) == "ap_456"
    assert auth.extract_key({"authorization": "bearer ap_789"}) == "ap_789"
    # X-API-Key wins when both present; nothing when absent
    assert auth.extract_key({"x-api-key": "ap_a", "authorization": "Bearer ap_b"}) == "ap_a"
    assert auth.extract_key({}) == ""
    assert auth.extract_key({"authorization": "Basic xyz"}) == ""


def test_optional_auth_accepts_bearer(conn):
    acct = auth.register(conn, "bearer-user", "free")
    got = auth.authenticate_optional(conn, {"authorization": f"Bearer {acct['api_key']}"})
    assert got["handle"] == "bearer-user"


def test_optional_auth_none_when_no_key(conn):
    assert auth.authenticate_optional(conn, {}) is None
    assert auth.authenticate_optional(conn, {"x-api-key": "  "}) is None


def test_optional_auth_resolves_valid_key(conn):
    acct = auth.register(conn, "grace", "free")
    got = auth.authenticate_optional(conn, {"x-api-key": acct["api_key"]})
    assert got["handle"] == "grace"


def test_optional_auth_raises_on_bad_key(conn):
    try:
        auth.authenticate_optional(conn, {"x-api-key": "ap_not_real"})
        assert False, "expected AuthError"
    except auth.AuthError:
        pass


def test_anon_account_is_singleton(conn):
    a = db.ensure_anon_account(conn)
    b = db.ensure_anon_account(conn)
    assert a["id"] == b["id"]
    assert a["tier"] == "anon"


def test_register_rejects_internal_anon_tier(conn):
    try:
        auth.register(conn, "sneaky", "anon")
        assert False, "anon must not be self-registerable"
    except ValueError:
        pass


def test_badge_anon_is_read_only():
    assert render._badge("anon") == "[read-only]"
