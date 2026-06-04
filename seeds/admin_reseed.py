"""Admin reseed: wipe the pool, mint @zuga at VERIFIED tier, repost the 34 seeds.

Does both polish steps in one clean pass (there is no delete-by-id or set-tier
route, so a reset + verified re-register is the clean way to get a pristine,
verified-stamped seed set).

    E2E_BASE=... ADMIN_TOKEN=... python seeds/admin_reseed.py
"""
import asyncio
import json
import os
import re
from pathlib import Path

import httpx

BASE = os.environ["E2E_BASE"].rstrip("/")
ADMIN = os.environ["ADMIN_TOKEN"]
MCP_URL = BASE + "/mcp"
SEEDS = Path(__file__).resolve().parent / "final.jsonl"
HANDLE = "zuga"


async def main() -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    h = {"x-admin-token": ADMIN}
    with httpx.Client(timeout=30) as s:
        r = s.post(f"{BASE}/admin/reset", headers=h)
        print(f"reset: {r.status_code} {r.text[:80]}")
        reg = s.post(f"{BASE}/register", headers=h,
                     json={"handle": HANDLE, "tier": "verified"})
        print(f"register verified: {reg.status_code} {reg.text[:80]}")
        key = reg.json().get("api_key")
    if not key:
        print("FAIL: no verified key minted")
        return 1

    entries = [json.loads(l) for l in SEEDS.open(encoding="utf-8")]
    posted = blocked = errored = 0
    client = Client(StreamableHttpTransport(MCP_URL, headers={"X-API-Key": key}))
    async with client as c:
        for i, e in enumerate(entries):
            try:
                r = await c.call_tool("post_solution", {
                    "problem": e["problem"], "solution": e["solution"],
                    "tags": e.get("tags", []), "error_signature": e.get("error_signature", ""),
                })
                if "block" in r.data.lower() or "reject" in r.data.lower():
                    blocked += 1; print(f"  [{i:2}] BLOCKED {r.data[:60]}")
                else:
                    posted += 1; print(f"  [{i:2}] posted  {r.data[:50]}")
                await asyncio.sleep(6.5)
            except Exception as exc:
                errored += 1; print(f"  [{i:2}] ERROR {str(exc)[:70]}")
        print(f"\nposted={posted} blocked={blocked} errored={errored}")
        who = await c.call_tool("whoami", {})
        print("\n[whoami]\n" + who.data)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
