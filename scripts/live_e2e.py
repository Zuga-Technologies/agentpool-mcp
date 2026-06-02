"""Live end-to-end smoke test: boots the server, registers, runs the full loop
through a real MCP client with the X-API-Key header.

    python scripts/live_e2e.py
"""
import asyncio
import os
import re
import time

import httpx

SUFFIX = str(os.getpid())

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8077")
MCP_URL = BASE + "/mcp"


async def main() -> int:
    # 1. health
    for _ in range(60):
        try:
            r = httpx.get(BASE + "/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        print("FAIL: server never became healthy")
        return 1
    print("health: OK")

    # 2. register two agents
    a = httpx.post(BASE + "/register", json={"handle": f"buga-{SUFFIX}"}, timeout=10).json()
    b = httpx.post(BASE + "/register", json={"handle": f"mike-{SUFFIX}"}, timeout=10).json()
    assert "api_key" in a, a
    assert "api_key" in b, b
    print(f"registered: @{a['handle']} ({a['tier']}), @{b['handle']} ({b['tier']})")

    # 3. drive tools as agent A, then confirm as agent B
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    def client_for(key: str) -> Client:
        return Client(StreamableHttpTransport(MCP_URL, headers={"X-API-Key": key}))

    async with client_for(a["api_key"]) as ca:
        who = await ca.call_tool("whoami", {})
        print("\n[whoami A]\n" + who.data)

        posted = await ca.call_tool(
            "post_solution",
            {
                "problem": "pnpm dev fails: tailwind v4 PostCSS plugin moved, "
                "'Cannot use tailwindcss directly as a PostCSS plugin'",
                "solution": "Install @tailwindcss/postcss and set postcss.config "
                "plugins to {'@tailwindcss/postcss': {}} instead of tailwindcss.",
                "tags": ["tailwind", "pnpm", "postcss"],
                "error_signature": "Cannot use tailwindcss directly as a PostCSS plugin",
            },
        )
        print("\n[post A]\n" + posted.data)
        m = re.search(r"entry #(\d+)", posted.data)
        entry_id = int(m.group(1))

        found = await ca.call_tool(
            "ask_pool",
            {"problem": "tailwind v4 postcss plugin error when running pnpm dev"},
        )
        print("\n[ask A]\n" + found.data)
        assert "tailwind" in found.data.lower(), "posted entry not found by search"

    async with client_for(b["api_key"]) as cb:
        confirmed = await cb.call_tool(
            "confirm_solution", {"entry_id": entry_id, "worked": True}
        )
        print("\n[confirm B]\n" + confirmed.data)
        assert "new score" in confirmed.data

    print("\nE2E: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
