"""AgentPool FastMCP server: 5 tools + /register + /health."""
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from . import auth, db
from . import config
from . import ranking, render
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
        entry_id = db.insert_entry(
            conn,
            problem_text=problem.strip(),
            solution_text=solution.strip(),
            tags=[t.strip() for t in tags if t.strip()][:8],
            error_signature=error_signature.strip(),
            author_id=account["id"],
            tier=account["tier"],
            embedding=embed(problem + "\n" + solution),
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
        return render.render_join(result["handle"], result["api_key"])
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


def main() -> None:
    mcp.run(transport="http", host=config.HOST, port=config.PORT, path="/mcp")


if __name__ == "__main__":
    main()
