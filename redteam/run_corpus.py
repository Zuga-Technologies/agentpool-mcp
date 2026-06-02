"""Run the cq safety corpus through a content guard and report precision/recall.

A content-safety benchmark for cq nodes: it measures both whether attacks are
blocked (recall) AND whether benign developer solutions pass (precision). A
guard that blocks everything is useless — the benign controls keep it honest.

    # against AgentPool's own ZugaShield guard:
    python redteam/run_corpus.py

    # against any node's guardrail: import and pass a callable
    #   screen(problem, solution) -> (allowed: bool, reason: str)
"""
import json
import pathlib
import sys

CORPUS = pathlib.Path(__file__).parent / "cq_safety_corpus.jsonl"


def load_corpus():
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def run(screen) -> int:
    attacks_total = attacks_blocked = 0
    benign_total = benign_allowed = 0
    failures = []
    for case in load_corpus():
        allowed, reason = screen(case["problem"], case["solution"])
        want_block = case["expect"] == "block"
        if want_block:
            attacks_total += 1
            if not allowed:
                attacks_blocked += 1
            else:
                failures.append(f"MISSED ATTACK {case['id']} ({case['category']})")
        else:
            benign_total += 1
            if allowed:
                benign_allowed += 1
            else:
                failures.append(f"FALSE POSITIVE {case['id']}: {reason[:60]}")

    print(f"attacks blocked : {attacks_blocked}/{attacks_total} (recall)")
    print(f"benign allowed  : {benign_allowed}/{benign_total} (precision)")
    for f in failures:
        print("  " + f)
    ok = attacks_blocked == attacks_total and benign_allowed == benign_total
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
    from agentpool.guard import screen_post

    raise SystemExit(run(screen_post))
