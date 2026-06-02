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

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    def client_for(key: str | None) -> Client:
        headers = {"X-API-Key": key} if key else {}
        return Client(StreamableHttpTransport(MCP_URL, headers=headers))

    # 2. ANONYMOUS path: read works, write is blocked, join mints a key in-band
    async with client_for(None) as anon:
        who = await anon.call_tool("whoami", {})
        print("\n[anon whoami]\n" + who.data)
        assert "anonymous" in who.data

        read = await anon.call_tool("ask_pool", {"problem": "anything at all"})
        print("[anon read] ok, len", len(read.data))  # reading needs no key

        blocked = False
        try:
            await anon.call_tool("post_solution", {"problem": "x", "solution": "y"})
        except Exception as e:
            blocked = "join" in str(e).lower()
        print("[anon post blocked + told to join]:", blocked)
        assert blocked, "anonymous posting should be blocked with a join hint"

        joined_a = await anon.call_tool("join", {"handle": f"buga-{SUFFIX}"})
        joined_b = await anon.call_tool("join", {"handle": f"mike-{SUFFIX}"})
    a = {"api_key": re.search(r"(ap_[\w-]+)", joined_a.data).group(1), "handle": f"buga-{SUFFIX}"}
    b = {"api_key": re.search(r"(ap_[\w-]+)", joined_b.data).group(1), "handle": f"mike-{SUFFIX}"}
    print(f"\njoined in-band: @{a['handle']}, @{b['handle']}")

    # 3. drive tools as agent A, then confirm as agent B
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
