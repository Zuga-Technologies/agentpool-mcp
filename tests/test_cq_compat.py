"""Validate AgentPool's cq output against Mozilla cq's ACTUAL published schemas.

The schemas in tests/cq_schemas/ are copied verbatim from
github.com/mozilla-ai/cq (main). This is the real wire-compatibility check —
if these pass, our KUs and discovery doc satisfy cq's strict
(additionalProperties=false) contract.
"""
import json
import pathlib

import jsonschema
from referencing import Registry, Resource

from agentpool import cq

SCHEMA_DIR = pathlib.Path(__file__).parent / "cq_schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    # Register every cq schema by its $id so cross-file $refs (e.g. stats.json
    # -> knowledge_unit.json) resolve.
    resources = []
    for p in SCHEMA_DIR.glob("*.json"):
        s = json.loads(p.read_text(encoding="utf-8"))
        resources.append((s["$id"], Resource.from_contents(s)))
    return Registry().with_resources(resources)


def _validate(instance: dict, schema_name: str) -> None:
    schema = _schema(schema_name)
    jsonschema.Draft202012Validator(schema, registry=_registry()).validate(instance)


def _entry(**kw):
    base = dict(
        id=42, problem_text="pnpm dev fails with tailwind v4 postcss error",
        solution_text="install @tailwindcss/postcss and update postcss.config",
        tags='["pnpm","tailwind"]', error_signature="ERR_X", author_id=1,
        tier="verified", confirms=3, fails=0, score=3.0, status="active",
        created_at="2026-06-01T00:00:00+00:00", ku_id="", shield_verdict="allow",
    )
    base.update(kw)
    return base


def test_ku_validates_against_real_cq_schema():
    ku = cq.entry_to_ku(_entry(), "https://agentpool.example")
    _validate(ku, "knowledge_unit.json")


def test_ku_with_empty_tags_and_no_dates_validates():
    ku = cq.entry_to_ku(_entry(tags="[]", created_at="", score=0))
    _validate(ku, "knowledge_unit.json")


def test_ku_has_no_forbidden_extension_keys():
    # additionalProperties=false — our KU must contain ONLY spec keys
    ku = cq.entry_to_ku(_entry())
    allowed = {
        "id", "version", "domains", "insight", "context",
        "evidence", "tier", "created_by", "superseded_by", "flags",
    }
    assert set(ku) <= allowed, f"forbidden keys: {set(ku) - allowed}"


def test_node_document_validates():
    doc = cq.node_document("https://agentpool.example")
    _validate(doc, "node_discovery.json")


def test_stats_document_validates():
    ku = cq.entry_to_ku(_entry())
    doc = cq.stats_document(1, {"pnpm": 1, "tailwind": 1}, [ku])
    _validate(doc, "stats.json")
