#!/usr/bin/env python3
"""Bulk-extract generalizable AgentPool seed entries from the Claude-memory files.

Walks the dev-memory markdown (feedback/ projects/ references/), and for each
file asks Claude to decide: is this a GENERALIZABLE technical fix a stranger's
Claude Code could hit (library/tool/error/config gotcha) -- NOT Zuga-internal
process, preferences, infra names, or anything containing a secret? If yes, it
emits a clean {problem, solution, tags, error_signature}. If no, it's skipped
with a reason.

Output is REVIEWABLE, never auto-posted:
    seeds/extracted.jsonl   candidate entries (one JSON per line, + _source)
    seeds/skipped.tsv       file <tab> reason (audit trail)

Usage:
    ANTHROPIC_API_KEY=... python seeds/seed_extract.py [--limit N] [--memory DIR]

Then eyeball extracted.jsonl, strike junk, and post the survivors through the
shield-gated post path. Nothing here touches the live pool.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

DEFAULT_MEMORY = Path(
    "C:/Users/Antonio/.claude/projects/E--Programming/memory"
)
BUCKETS = ("feedback", "projects", "references")
MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
CONCURRENCY = 5

SYSTEM = """You curate a PUBLIC "Stack Overflow for AI coding agents". You are
given one internal dev-memory note. Decide if it contains a GENERALIZABLE
technical fix that an unrelated developer's Claude Code agent could hit and use.

KEEP only if it is a reusable fix about a public library, framework, tool, CLI,
language, build system, API, or error -- the kind of thing Claude often cannot
one-shot (post-cutoff version churn, non-obvious gotcha, trial-and-error fix).

SKIP (do not emit) if it is any of:
- internal process/workflow/preferences (how THIS team works, deploy targets,
  who is admin, naming conventions, "always do X here")
- project status, planning, roadmap, business/strategy
- anything naming private infra/hosts/services or that only makes sense with
  insider context
- anything containing or referencing a secret, key, token, or credential value

NEVER include a secret. Rewrite the problem as a stranger would phrase the
SYMPTOM/ERROR (no internal names). Make the solution self-contained and correct.
Use PLAIN ASCII ONLY in every field: write >= not the unicode sign, -> not an
arrow, -- not an em-dash, and straight quotes. No non-ASCII characters anywhere.

Respond with ONE json object, nothing else:
  {"keep": true, "problem": "...", "solution": "...", "tags": ["..."], "error_signature": "..."}
or
  {"keep": false, "reason": "<short why skipped>"}"""


async def classify(client: httpx.AsyncClient, key: str, path: Path, text: str) -> dict:
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"FILE: {path.name}\n\n{text[:8000]}"}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    r = await client.post(API_URL, json=body, headers=headers, timeout=60)
    r.raise_for_status()
    raw = r.json()["content"][0]["text"].strip()
    # Model may wrap in a code fence; strip to the first/last brace.
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s : e + 1])


async def worker(sem, client, key, path, out, skipped):
    async with sem:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            verdict = await classify(client, key, path, text)
        except Exception as exc:  # never let one file kill the run
            skipped.append((path.name, f"error: {exc}"))
            return
    if verdict.get("keep") and verdict.get("problem") and verdict.get("solution"):
        entry = {
            "problem": verdict["problem"],
            "solution": verdict["solution"],
            "tags": verdict.get("tags", []),
            "error_signature": verdict.get("error_signature", ""),
            "_source": path.name,
        }
        out.append(entry)
        print(f"KEEP  {path.name}")
    else:
        skipped.append((path.name, verdict.get("reason", "not generalizable")))
        print(f"skip  {path.name}  ({verdict.get('reason','')[:60]})")


async def run(memory: Path, limit: int | None) -> int:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ERROR: set ANTHROPIC_API_KEY")
        return 1
    files: list[Path] = []
    for b in BUCKETS:
        files.extend(sorted((memory / b).glob("*.md")))
    if limit:
        files = files[:limit]
    print(f"classifying {len(files)} memory files with {MODEL} ...")

    out: list[dict] = []
    skipped: list[tuple[str, str]] = []
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *(worker(sem, client, key, p, out, skipped) for p in files)
        )

    seeds_dir = Path(__file__).resolve().parent
    extracted = seeds_dir / "extracted.jsonl"
    skiplog = seeds_dir / "skipped.tsv"
    with extracted.open("w", encoding="utf-8") as f:
        for e in out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with skiplog.open("w", encoding="utf-8") as f:
        for name, reason in skipped:
            f.write(f"{name}\t{reason}\n")

    print(f"\nKEPT {len(out)} / {len(files)}  ->  {extracted}")
    print(f"skipped {len(skipped)}  ->  {skiplog}")
    print("REVIEW extracted.jsonl before posting. Nothing was posted.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only first N files (test run)")
    ap.add_argument("--memory", type=Path, default=DEFAULT_MEMORY)
    args = ap.parse_args()
    return asyncio.run(run(args.memory, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
