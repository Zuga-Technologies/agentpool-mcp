from agentpool import render


def _entry(**kw):
    base = dict(
        id=1, problem_text="pnpm install fails with tailwind v4 postcss error",
        solution_text="add @tailwindcss/postcss to postcss config", tags='["pnpm","tailwind"]',
        error_signature="", author_id=1, tier="verified", confirms=3, fails=0,
        score=3.0, status="active", created_at="2026-06-01T00:00:00+00:00",
    )
    base.update(kw)
    return base


def test_render_results_empty_invites_posting():
    out = render.render_results("anything", [])
    assert "No matches yet" in out
    assert "post_solution" in out


def test_render_results_shows_entry_fields():
    out = render.render_results("tailwind", [(_entry(), 0.91, 0.8)])
    assert "#1" in out
    assert "verified" in out
    assert "PROBLEM:" in out
    assert "FIX:" in out
    assert "#pnpm" in out


def test_render_entry_full():
    out = render.render_entry(_entry(error_signature="ERR_PNPM_X"))
    assert "ENTRY #1" in out
    assert "ERROR SIGNATURE" in out
    assert "ERR_PNPM_X" in out
    assert "SOLUTION" in out


def test_render_confirm_idempotent_note():
    assert "already voted" in render.render_confirm(1, False, 5.0)
    assert "recorded" in render.render_confirm(1, True, 5.0)


def test_render_whoami():
    assert "@alice" in render.render_whoami("alice", "paid", 2, 5)
