"""cq compatibility — map AgentPool entries to Mozilla cq Knowledge Units.

cq (github.com/mozilla-ai/cq) is an Apache-2.0 open standard for shared agent
knowledge. A cq-compatible node serves the Knowledge Unit (KU) schema and a
`/.well-known/cq-node.json` discovery document so cq tooling can point at it.

Schema reference: https://mozilla-ai.github.io/cq/schema/knowledge_unit.json
NOTE: validated against the published KU schema (id/domains/insight/context/
evidence/tier/created_by/flags). The exact propose/query HTTP wire shapes are
followed from cq's documented MCP tool params; final byte-compat should be
verified against the cq reference server before claiming certification.
"""
import hashlib
import json

KU_RE = r"^ku_[0-9a-f]{32}$"


def ku_id_for(entry_id: int) -> str:
    """Deterministic KU id for an AgentPool entry. Matches cq's ^ku_[0-9a-f]{32}$."""
    digest = hashlib.md5(f"agentpool:{entry_id}".encode("utf-8")).hexdigest()
    return f"ku_{digest}"


def _tags(tags_json: str) -> list[str]:
    try:
        t = json.loads(tags_json)
        return [str(x) for x in t] if isinstance(t, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def entry_to_ku(entry: dict, public_url: str = "") -> dict:
    """Render an AgentPool entry row (dict) as a cq Knowledge Unit."""
    tags = _tags(entry.get("tags", "[]"))
    confirms = int(entry.get("confirms", 0) or 0)
    # AgentPool score is unbounded; squash into cq's 0..1 confidence.
    score = float(entry.get("score", 0) or 0)
    confidence = round(score / (score + 3.0), 3) if score > 0 else 0.5

    # STRICT: knowledge_unit.json declares additionalProperties=false, so the KU
    # must contain ONLY spec fields. AgentPool-specific signals (shield verdict,
    # provenance) are exposed out-of-band via /shield/stats, never inside a KU.
    return {
        "id": entry.get("ku_id") or ku_id_for(entry["id"]),
        "version": 1,
        "domains": tags or ["general"],
        "insight": {
            "summary": _clip(entry["problem_text"], 200),
            "detail": entry["problem_text"],
            "action": entry["solution_text"],
        },
        "context": {
            "languages": [],
            "frameworks": [],
            "pattern": entry.get("error_signature", "") or "",
        },
        "evidence": _evidence(confidence, confirms, entry.get("created_at", "")),
        "tier": "public",
        "created_by": f"agentpool:{entry.get('tier', '')}",
        "flags": [],
    }


def _evidence(confidence: float, confirms: int, created_at: str) -> dict:
    ev = {"confidence": confidence, "confirmations": max(1, confirms)}
    if created_at:  # date-time fields omitted when unknown (schema is strict)
        ev["first_observed"] = created_at
        ev["last_confirmed"] = created_at
    return ev


def node_document(public_url: str) -> dict:
    """The /.well-known/cq-node.json discovery document.

    node_discovery.json declares additionalProperties=false, so ONLY the spec
    fields are allowed (version/api_base_url/api_version/node_name).
    """
    base = public_url.rstrip("/") if public_url else "http://localhost:8000"
    return {
        "version": 1,
        "api_base_url": f"{base}/api/v1",
        "api_version": "v1",
        "node_name": "AgentPool",
    }


def stats_document(total: int, domain_counts: dict, recent_kus: list) -> dict:
    """cq /stats response shape (stats.json)."""
    return {
        "total_count": total,
        "domain_counts": domain_counts,
        "recent": recent_kus,
    }


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
