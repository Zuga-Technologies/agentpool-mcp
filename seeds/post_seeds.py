"""Post the reviewed seed corpus to the LIVE AgentPool, shield-gated.

Joins as a handle in-band, then posts every entry in seeds/final.jsonl through
post_solution (the ZugaShield write-gate runs on each). Prints posted vs blocked,
then proves retrieval with an ask_pool query.

    E2E_BASE=https://agentpool-mcp-production.up.railway.app \
    python seeds/post_seeds.py [--handle zuga]
"""
import argparse
import asyncio
import json
import os
import re
from pathlib import Path

BASE = os.environ.get("E2E_BASE", "https://agentpool-mcp-production.up.railway.app")
MCP_URL = BASE + "/mcp"
SEEDS = Path(__file__).resolve().parent / "final.jsonl"


async def main(handle: str) -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    entries = [json.loads(l) for l in SEEDS.open(encoding="utf-8")][START:]
    print(f"posting {len(entries)} seeds (from #{START}) to {BASE} as @{handle}")

    def client_for(key):
        headers = {"X-API-Key": key} if key else {}
        return Client(StreamableHttpTransport(MCP_URL, headers=headers))

    async with client_for(None) as anon:
        try:
            joined = await anon.call_tool("join", {"handle": handle})
        except Exception:  # handle taken (run 1) -> suffix it
            handle = f"{handle}-{os.getpid()}"
            joined = await anon.call_tool("join", {"handle": handle})
        m = re.search(r"(ap_[\w-]+)", joined.data)
    if not m:
        print("FAIL: no key from join:\n" + joined.data)
        return 1
    key = m.group(1)
    print(f"joined: @{handle}  key {key[:10]}...")

    posted, blocked, errored = 0, 0, 0
    async with client_for(key) as c:
        for i, e in enumerate(entries):
            try:
                r = await c.call_tool("post_solution", {
                    "problem": e["problem"],
                    "solution": e["solution"],
                    "tags": e.get("tags", []),
                    "error_signature": e.get("error_signature", ""),
                })
                txt = r.data
                if "block" in txt.lower() or "reject" in txt.lower():
                    blocked += 1
                    print(f"  [{i:2}] BLOCKED  {e['tags'][:2]}  {txt[:70]}")
                else:
                    posted += 1
                    print(f"  [{i+START:2}] posted   {txt[:60]}")
                await asyncio.sleep(6.5)  # stay under 10 posts/min
            except Exception as exc:
                errored += 1
                print(f"  [{i:2}] ERROR    {str(exc)[:80]}")

        print(f"\nposted={posted}  blocked={blocked}  errored={errored}")

        # prove retrieval
        q = await c.call_tool("ask_pool", {"problem": "tailwind v4 postcss plugin error after upgrade"})
        print("\n=== ask_pool('tailwind v4 postcss') ===\n" + q.data[:600])
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", default="zuga")
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()
    START = args.start
    raise SystemExit(asyncio.run(main(args.handle)))
