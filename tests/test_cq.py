import re

from agentpool import cq, db


def _entry(**kw):
    base = dict(
        id=42, problem_text="pnpm dev fails with tailwind v4 postcss error",
        solution_text="install @tailwindcss/postcss", tags='["pnpm","tailwind"]',
        error_signature="ERR_X", author_id=1, tier="verified", confirms=3, fails=0,
        score=3.0, status="active", created_at="2026-06-01T00:00:00+00:00",
        ku_id="", shield_verdict="allow",
    )
    base.update(kw)
    return base


def test_ku_id_format_and_determinism():
    a = cq.ku_id_for(42)
    b = cq.ku_id_for(42)
    assert a == b
    assert re.match(cq.KU_RE, a)
    assert cq.ku_id_for(43) != a


def test_entry_to_ku_shape():
    ku = cq.entry_to_ku(_entry(), "https://x.dev")
    assert re.match(cq.KU_RE, ku["id"])
    assert ku["domains"] == ["pnpm", "tailwind"]
    assert ku["insight"]["action"] == "install @tailwindcss/postcss"
    assert ku["insight"]["summary"] and ku["insight"]["detail"]
    assert ku["tier"] == "public"
    assert 0.0 <= ku["evidence"]["confidence"] <= 1.0
    assert "x_agentpool" not in ku  # strict schema: no extension keys allowed


def test_entry_to_ku_empty_domains_defaults():
    ku = cq.entry_to_ku(_entry(tags="[]"))
    assert ku["domains"] == ["general"]


def test_node_document():
    doc = cq.node_document("https://agentpool.example/")
    assert doc["api_base_url"] == "https://agentpool.example/api/v1"
    assert doc["api_version"] == "v1"
    assert "x_features" not in doc  # strict schema: no extension keys allowed


def test_db_ku_id_assigned_on_insert(conn):
    from agentpool import auth
    acct = auth.register(conn, "ku-user", "free")
    eid = db.insert_entry(
        conn, "p", "s", [], "", acct["id"], acct["tier"],
        [0.0] * 384, shield_verdict="allow",
    )
    row = db.get_entry(conn, eid)
    assert re.match(cq.KU_RE, row["ku_id"])
    assert db.get_entry_by_ku(conn, row["ku_id"])["id"] == eid


def test_rejection_logged_in_stats(conn):
    db.log_rejection(conn, "injection risk (x)", "free")
    stats = db.shield_stats(conn)
    assert stats["blocked"] == 1
    assert stats["recent_blocks"][0]["reason"].startswith("injection")
