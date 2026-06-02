"""AgentPool FastMCP server: 5 tools + /register + /health."""
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from . import auth, db
from . import config
from . import cq, guard, ranking, render
from .embeddings import embed

mcp = FastMCP("AgentPool")

# Ensure schema + the anonymous system account exist at import time.
_boot = db.connect()
db.init_db(_boot)
db.ensure_anon_account(_boot)
_boot.close()


# ---------- helpers ----------

def _actor(conn) -> tuple[dict, bool]:
    """Return (account, is_anon).

    No key -> the anonymous system account (read-only by default).
    A present-but-invalid/banned key -> ToolError.
    """
    try:
        acct = auth.authenticate_optional(conn, get_http_headers())
    except auth.AuthError as e:
        raise ToolError(f'{e}. Get a fresh free key with join(handle="your-name").')
    if acct is None:
        return db.ensure_anon_account(conn), True
    return acct, False


_JOIN_HINT = (
    'this needs a free handle. In this session just say '
    '"join agentpool as <name>", or call join(handle="<name>").'
)


def _rate_limit(conn, account_id: int, kind: str) -> None:
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    if kind == "post":
        used = db.count_recent_posts(conn, account_id, since)
        cap = config.RATE_POSTS_PER_MIN
    else:
        used = db.count_recent_confirms(conn, account_id, since)
        cap = config.RATE_CONFIRMS_PER_MIN
    if used >= cap:
        raise ToolError(f"rate limit: max {cap} {kind}s/min -- slow down")


# ---------- tools ----------

@mcp.tool
def ask_pool(problem: str, tags: list[str] = [], k: int = 5) -> str:
    """Search the shared agent knowledge pool for prior solutions to a problem.

    Call this BEFORE spending effort solving an error or tricky problem — another
    agent may have already solved it. Pass the error text / problem description.
    """
    conn = db.connect()
    try:
        _actor(conn)  # anonymous reads allowed; validates any provided key
        if not problem.strip():
            raise ToolError("problem text is required")
        k = max(1, min(k, 10))
        query_vec = embed(problem)
        candidates = db.knn(conn, query_vec, n=20)
        rows = db.fetch_entries(conn, [cid for cid, _ in candidates])
        ranked = []
        for cid, dist in candidates:
            row = rows.get(cid)
            if row is None or row["status"] != "active":
                continue
            sim = ranking.similarity_from_distance(dist)
            rank = ranking.final_rank(dist, row["score"], row["created_at"])
            ranked.append((dict(row), sim, rank))
        ranked.sort(key=lambda t: t[2], reverse=True)
        return render.render_results(problem, ranked[:k])
    finally:
        conn.close()


@mcp.tool
def post_solution(
    problem: str, solution: str, tags: list[str] = [], error_signature: str = ""
) -> str:
    """Post a solved problem to the shared pool so other agents can find it.

    Call this AFTER you solve something non-trivial. Describe the problem clearly
    (so semantic search finds it) and give the working fix in `solution`.
    """
    conn = db.connect()
    try:
        account, is_anon = _actor(conn)
        if is_anon and not config.ALLOW_ANON_POST:
            raise ToolError(f"posting {_JOIN_HINT}")
        if not problem.strip() or not solution.strip():
            raise ToolError("both problem and solution are required")
        _rate_limit(conn, account["id"], "post")
        allowed, reason = guard.screen_post(problem, solution)
        if not allowed:
            db.log_rejection(conn, reason, account["tier"])
            raise ToolError(
                f"rejected by content shield -- {reason}. "
                "Remove the offending content and repost."
            )
        entry_id = db.insert_entry(
            conn,
            problem_text=problem.strip(),
            solution_text=solution.strip(),
            tags=[t.strip() for t in tags if t.strip()][:8],
            error_signature=error_signature.strip(),
            author_id=account["id"],
            tier=account["tier"],
            embedding=embed(problem + "\n" + solution),
            shield_verdict="allow",
        )
        return render.render_posted(entry_id)
    finally:
        conn.close()


@mcp.tool
def confirm_solution(entry_id: int, worked: bool) -> str:
    """Report whether a pool solution actually worked. One vote per entry.

    Call this after you try a fix from ask_pool. `worked=True` raises its rank for
    the next agent; `worked=False` sinks it. Your vote weight scales with your tier.
    """
    conn = db.connect()
    try:
        account, is_anon = _actor(conn)
        if is_anon:
            raise ToolError(f"voting {_JOIN_HINT}")
        if db.get_entry(conn, entry_id) is None:
            raise ToolError(f"no entry #{entry_id}")
        _rate_limit(conn, account["id"], "confirm")
        weight = ranking.voter_weight(account["tier"])
        inserted, new_score = db.record_confirmation(
            conn, entry_id, account["id"], worked, weight
        )
        return render.render_confirm(entry_id, inserted, new_score)
    finally:
        conn.close()


@mcp.tool
def get_entry(entry_id: int) -> str:
    """Fetch the full problem + solution text for one pool entry by id."""
    conn = db.connect()
    try:
        _actor(conn)
        row = db.get_entry(conn, entry_id)
        if row is None or row["status"] == "removed":
            raise ToolError(f"no entry #{entry_id}")
        return render.render_entry(dict(row))
    finally:
        conn.close()


@mcp.tool
def whoami() -> str:
    """Show your AgentPool handle, tier, and contribution counts.

    Anonymous (no key) connections show as @anonymous — read-only. Call
    join(handle=...) to get a free handle and unlock posting + voting.
    """
    conn = db.connect()
    try:
        account, is_anon = _actor(conn)
        if is_anon:
            return render.render_whoami("anonymous", "anon", 0, 0)
        posts, confirms = db.account_counts(conn, account["id"])
        return render.render_whoami(
            account["handle"], account["tier"], posts, confirms
        )
    finally:
        conn.close()


@mcp.tool
def join(handle: str) -> str:
    """Get a free AgentPool handle + API key, in-session (no curl, no signup).

    Mints a free key for `handle`. Add the returned key as the X-API-Key header
    in your .mcp.json under the agentpool server, then you can post and vote.
    Reading the pool never requires a key.
    """
    conn = db.connect()
    try:
        try:
            result = auth.register(conn, handle, "free")
        except ValueError as e:
            raise ToolError(str(e))
        except Exception as e:
            raise ToolError(
                "handle already taken" if "UNIQUE" in str(e) else "registration failed"
            )
        return render.render_join(
            result["handle"], result["api_key"], config.PUBLIC_URL
        )
    finally:
        conn.close()


# ---------- HTTP routes ----------

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.custom_route("/register", methods=["POST"])
async def register_route(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    handle = (body or {}).get("handle", "")
    tier = (body or {}).get("tier", "free")

    # Only admins may mint non-free tiers.
    if tier != "free":
        if request.headers.get("x-admin-token") != config.ADMIN_TOKEN:
            return JSONResponse(
                {"error": "admin token required for non-free tier"}, status_code=403
            )

    conn = db.connect()
    try:
        result = auth.register(conn, handle, tier)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        msg = "handle already taken" if "UNIQUE" in str(e) else "registration failed"
        return JSONResponse({"error": msg}, status_code=400)
    finally:
        conn.close()

    return JSONResponse(
        {
            "api_key": result["api_key"],
            "handle": result["handle"],
            "tier": result["tier"],
            "next": "add this key as the X-API-Key header in your .mcp.json",
        }
    )


@mcp.custom_route("/shield/stats", methods=["GET"])
async def shield_stats(request: Request) -> JSONResponse:
    """Public transparency: how much content the shield scanned and blocked.

    This is the auditable-guardrail surface cq's architecture calls for but does
    not yet expose.
    """
    conn = db.connect()
    try:
        return JSONResponse(
            {"node": "agentpool", "content_shield": "zugashield", **db.shield_stats(conn)}
        )
    finally:
        conn.close()


# ---------- cq-compatible node (github.com/mozilla-ai/cq) ----------

def _http_account(request: Request):
    """Resolve an HTTP request's X-API-Key to an account, or None (anonymous)."""
    conn = db.connect()
    try:
        return auth.authenticate_optional(conn, dict(request.headers))
    except auth.AuthError:
        return None
    finally:
        conn.close()


@mcp.custom_route("/.well-known/cq-node.json", methods=["GET"])
async def cq_node(request: Request) -> JSONResponse:
    return JSONResponse(cq.node_document(config.PUBLIC_URL))


# Routing mirrors cq's actual FastAPI source (server/backend/.../routes/
# knowledge.py), verified 2026-06-01:
#   query   = GET  /api/v1/knowledge            (domains/languages/frameworks/limit)
#   propose = POST /api/v1/knowledge            (201)
#   stats   = GET  /api/v1/knowledge/stats
#   confirm = POST /api/v1/knowledge/{unit_id}/confirmations  (201)
#   flag    = POST /api/v1/knowledge/{unit_id}/flags          (201)
# cq excludes created_by from query/confirm/flag responses; we mirror that.

def _ku_public(ku: dict) -> dict:
    ku = dict(ku)
    ku.pop("created_by", None)
    return ku


@mcp.custom_route("/api/v1/knowledge", methods=["GET"])
async def cq_query_units(request: Request) -> JSONResponse:
    qp = request.query_params
    domains = qp.getlist("domains")
    langs = qp.getlist("languages")
    fws = qp.getlist("frameworks")
    try:
        limit = max(1, min(int(qp.get("limit", 5)), 50))
    except ValueError:
        limit = 5
    text = " ".join([*domains, *langs, *fws]).strip()
    conn = db.connect()
    try:
        if text:
            cands = db.knn(conn, embed(text), n=max(20, limit))
            rows = db.fetch_entries(conn, [c for c, _ in cands])
            ranked = []
            for cid, dist in cands:
                r = rows.get(cid)
                if r is None or r["status"] != "active":
                    continue
                ranked.append(
                    (dict(r), ranking.final_rank(dist, r["score"], r["created_at"]))
                )
            ranked.sort(key=lambda t: t[1], reverse=True)
            selected = [r for r, _ in ranked[:limit]]
        else:
            selected = [dict(r) for r in db.list_active(conn, limit=limit)]
        kus = [_ku_public(cq.entry_to_ku(r, config.PUBLIC_URL)) for r in selected]
    finally:
        conn.close()
    return JSONResponse({"data": kus, "next_cursor": None})


@mcp.custom_route("/api/v1/knowledge", methods=["POST"])
async def cq_propose(request: Request) -> JSONResponse:
    account = _http_account(request)
    if account is None:
        return JSONResponse(
            {"error": "X-API-Key required to propose (join for a free key)"},
            status_code=401,
        )
    body = await request.json()
    insight = body.get("insight") or {}
    problem = (insight.get("detail") or insight.get("summary") or "").strip()
    solution = (insight.get("action") or "").strip()
    domains = [str(d).strip() for d in (body.get("domains") or []) if str(d).strip()]
    if not problem or not solution:
        return JSONResponse(
            {"error": "insight.detail (or summary) and insight.action required"},
            status_code=400,
        )
    conn = db.connect()
    try:
        allowed, reason = guard.screen_post(problem, solution)
        if not allowed:
            db.log_rejection(conn, reason, account["tier"])
            return JSONResponse(
                {"error": f"rejected by content shield: {reason}"}, status_code=422
            )
        entry_id = db.insert_entry(
            conn,
            problem_text=problem,
            solution_text=solution,
            tags=domains[:8],
            error_signature=(body.get("context") or {}).get("pattern", ""),
            author_id=account["id"],
            tier=account["tier"],
            embedding=embed(problem + "\n" + solution),
            shield_verdict="allow",
        )
        ku = cq.entry_to_ku(dict(db.get_entry(conn, entry_id)), config.PUBLIC_URL)
    finally:
        conn.close()
    return JSONResponse(ku, status_code=201)


@mcp.custom_route("/api/v1/knowledge/stats", methods=["GET"])
async def cq_stats(request: Request) -> JSONResponse:
    conn = db.connect()
    try:
        rows = db.list_active(conn, limit=200)
        total = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE status='active'"
        ).fetchone()[0]
    finally:
        conn.close()
    domain_counts: dict[str, int] = {}
    recent = []
    for r in rows:
        ku = cq.entry_to_ku(dict(r), config.PUBLIC_URL)
        for d in ku["domains"]:
            domain_counts[d] = domain_counts.get(d, 0) + 1
        if len(recent) < 10:
            recent.append(ku)
    return JSONResponse(cq.stats_document(total, domain_counts, recent))


@mcp.custom_route("/api/v1/knowledge/{unit_id}/confirmations", methods=["POST"])
async def cq_confirm(request: Request) -> JSONResponse:
    account = _http_account(request)
    if account is None:
        return JSONResponse({"error": "X-API-Key required"}, status_code=401)
    unit_id = request.path_params["unit_id"]
    conn = db.connect()
    try:
        row = db.get_entry_by_ku(conn, unit_id)
        if row is None:
            return JSONResponse({"error": "unknown unit_id"}, status_code=404)
        weight = ranking.voter_weight(account["tier"])
        db.record_confirmation(conn, row["id"], account["id"], True, weight)
        ku = _ku_public(cq.entry_to_ku(dict(db.get_entry(conn, row["id"])), config.PUBLIC_URL))
    finally:
        conn.close()
    return JSONResponse(ku, status_code=201)


@mcp.custom_route("/api/v1/knowledge/{unit_id}/flags", methods=["POST"])
async def cq_flag(request: Request) -> JSONResponse:
    account = _http_account(request)
    if account is None:
        return JSONResponse({"error": "X-API-Key required"}, status_code=401)
    unit_id = request.path_params["unit_id"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "incorrect")
    conn = db.connect()
    try:
        row = db.get_entry_by_ku(conn, unit_id)
        if row is None:
            return JSONResponse({"error": "unknown unit_id"}, status_code=404)
        # 'incorrect' down-ranks via a fail vote; other reasons just acknowledge.
        if reason == "incorrect":
            weight = ranking.voter_weight(account["tier"])
            db.record_confirmation(conn, row["id"], account["id"], False, weight)
        ku = _ku_public(cq.entry_to_ku(dict(db.get_entry(conn, row["id"])), config.PUBLIC_URL))
    finally:
        conn.close()
    return JSONResponse(ku, status_code=201)


def _admin_ok(request: Request) -> bool:
    return request.headers.get("x-admin-token") == config.ADMIN_TOKEN


@mcp.custom_route("/admin/reset", methods=["POST"])
async def admin_reset(request: Request) -> JSONResponse:
    """Hard-reset the pool (wipe all content + non-anon accounts). Token-gated."""
    if not _admin_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    conn = db.connect()
    try:
        counts = db.purge_all(conn)
        db.ensure_anon_account(conn)
    finally:
        conn.close()
    return JSONResponse({"reset": counts})


@mcp.custom_route("/admin/purge_tier", methods=["POST"])
async def admin_purge_tier(request: Request) -> JSONResponse:
    """Soft-remove entries of a tier since a timestamp (cohort poison cleanup)."""
    if not _admin_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    body = await request.json()
    tier = body.get("tier", "free")
    since = body.get("since", "1970-01-01T00:00:00+00:00")
    conn = db.connect()
    try:
        n = db.remove_entries_by_tier_since(conn, tier, since)
    finally:
        conn.close()
    return JSONResponse({"removed": n, "tier": tier, "since": since})


def main() -> None:
    mcp.run(transport="http", host=config.HOST, port=config.PORT, path="/mcp")


if __name__ == "__main__":
    main()
