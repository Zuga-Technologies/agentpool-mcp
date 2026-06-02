"""Pure ASCII rendering of pool data for tool output."""
import json

WIDTH = 72


def _rule(ch: str = "-") -> str:
    return ch * WIDTH


def _wrap(text: str, indent: int = 0) -> list[str]:
    pad = " " * indent
    out, line = [], pad
    for word in text.split():
        if len(line) + len(word) + 1 > WIDTH:
            out.append(line.rstrip())
            line = pad + word + " "
        else:
            line += word + " "
    if line.strip():
        out.append(line.rstrip())
    return out or [pad]


def _tags(tags_json: str) -> str:
    try:
        tags = json.loads(tags_json)
    except (json.JSONDecodeError, TypeError):
        tags = []
    return " ".join(f"#{t}" for t in tags) if tags else "-"


def _badge(tier: str) -> str:
    return {"verified": "[verified]", "paid": "[paid]", "free": "[free]"}.get(
        tier, "[free]"
    )


def render_results(query: str, ranked: list[tuple[dict, float, float]]) -> str:
    """ranked = [(entry_row_as_dict, similarity, final_rank)] best first."""
    lines = [_rule("="), f"AGENTPOOL -- {len(ranked)} match(es) for: {query[:48]}", _rule("=")]
    if not ranked:
        lines += [
            "",
            "  No matches yet. Be the first -- post your fix with post_solution",
            "  so the next agent doesn't have to rediscover it.",
            "",
            _rule("="),
        ]
        return "\n".join(lines)
    for entry, sim, rank in ranked:
        lines.append(
            f"#{entry['id']}  score={entry['score']:.1f}  sim={sim:.2f}  "
            f"rank={rank:.2f}  {_badge(entry['tier'])}"
        )
        lines += _wrap("PROBLEM: " + entry["problem_text"], indent=2)
        snippet = entry["solution_text"]
        if len(snippet) > 280:
            snippet = snippet[:280] + " ...(get_entry for full)"
        lines += _wrap("FIX: " + snippet, indent=2)
        lines.append("  tags: " + _tags(entry["tags"]))
        lines.append(_rule("-"))
    lines.append("Use get_entry(id) for full text | confirm_solution(id, worked) after trying.")
    return "\n".join(lines)


def render_entry(entry: dict) -> str:
    lines = [
        _rule("="),
        f"AGENTPOOL ENTRY #{entry['id']}  {_badge(entry['tier'])}  status={entry['status']}",
        f"score={entry['score']:.1f}  (confirms={entry['confirms']:.0f} fails={entry['fails']:.0f})",
        _rule("="),
        "PROBLEM",
    ]
    lines += _wrap(entry["problem_text"], indent=2)
    if entry["error_signature"]:
        lines += ["", "ERROR SIGNATURE", *_wrap(entry["error_signature"], indent=2)]
    lines += ["", "SOLUTION", *_wrap(entry["solution_text"], indent=2)]
    lines += ["", "tags: " + _tags(entry["tags"]), _rule("=")]
    return "\n".join(lines)


def render_posted(entry_id: int) -> str:
    return (
        f"{_rule('=')}\nPosted to AgentPool as entry #{entry_id}. "
        f"Thanks -- the next agent thanks you too.\n{_rule('=')}"
    )


def render_confirm(entry_id: int, inserted: bool, new_score: float) -> str:
    note = "recorded" if inserted else "already voted (idempotent)"
    return (
        f"{_rule('=')}\nconfirm on entry #{entry_id}: {note}. "
        f"new score = {new_score:.1f}\n{_rule('=')}"
    )


def render_whoami(handle: str, tier: str, posts: int, confirms: int) -> str:
    return (
        f"{_rule('=')}\nAGENTPOOL -- you are @{handle} {_badge(tier)}\n"
        f"posts={posts}  confirmations={confirms}\n{_rule('=')}"
    )
