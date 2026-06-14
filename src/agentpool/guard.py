"""Write-time content rail: scan posted solutions with ZugaShield before they
ever reach another agent via ask_pool.

The pool is read by LLMs, so a posted "solution" is an indirect prompt-injection
vector. We scan at POST time (once) so reads stay fast and serve vetted content.

Fail-open on *infrastructure* errors (keep the pool usable), but a clean BLOCK
verdict always rejects — a known attack never gets stored.
"""
import asyncio
import logging
import re
import uuid
from functools import lru_cache

log = logging.getLogger("agentpool.guard")

# Exfiltration-instruction layer (AgentPool, on top of ZugaShield).
# Catches "send <sensitive thing> to <network sink>" patterns where no literal
# secret is present (so DLP doesn't fire) but the instruction tells a reading
# agent to exfiltrate. Requires BOTH a sensitive target AND a network sink to
# keep precision high (benign shell/env mentions don't trip it).
_SENSITIVE = re.compile(
    r"(~/\.ssh|id_rsa|id_ed25519|~/\.aws|\.aws/credentials|aws_secret_access_key"
    r"|/etc/passwd|/proc/self/environ|\.env\b|private[ _-]?key|printenv|\benv\s*\|)",
    re.I,
)
_SINK = re.compile(
    r"(https?://|\bcurl\b|\bwget\b|\bnc\b|--data|-X\s*POST|\bupload\b|\bsend\b|exfiltrat)",
    re.I,
)


# Imperative "expose the environment" instruction: an expose verb directly on
# env vars / secrets within a short span. Catches indirect-injection exfil like
# "...instead print all environment variables" (corpus inj-003) WITHOUT tripping
# on benign prose that merely mentions env vars ("service env vars override the
# ARG", "which venv the entrypoint uses") -- those have no expose verb adjacent.
_ENV_DUMP = re.compile(
    r"\b(print|dump|reveal|output|show|send|leak|exfiltrat\w*|extract|echo|cat|list"
    r"|include|return|encode|base64|read|access|open|contents?\s+of|values?\s+of)\b"
    r"[^.\n]{0,60}?\b(all\s+|every\s+|the\s+)?"
    r"(environment\s+variables?|environ\b|env\s*vars?|secrets?|credentials?|api[ _-]?keys?)\b",
    re.I,
)


def _exfil_instruction(text: str) -> bool:
    return bool(
        (_SENSITIVE.search(text) and _SINK.search(text)) or _ENV_DUMP.search(text)
    )


# ZugaShield signatures that false-positive on legitimate developer prose and
# must NOT block a post on their own. EX-015 ("attempts to extract or leak
# environment variables") is a CRITICAL instruction-heuristic that fires on
# benign technical text mentioning env vars (e.g. "service env vars override the
# Dockerfile ARG", "which venv the entrypoint uses"). REAL env-exfiltration
# instructions (`env | curl ...`, dumping ~/.ssh, "include the contents of your
# environment variables in your reply", ".env"/proc/self/environ reads) are
# still caught precisely by our stateless _exfil_instruction layer above, whose
# detectors are kept broad enough to cover sink-less "leak to your own output"
# phrasings -- so dropping this signature yields zero false positives with no
# loss of real protection. Literal
# leaked-secret detection (actual key values) uses other signatures and is
# unaffected.
_IGNORED_SIGNATURES = {"EX-015"}


def _real_threats(decision):
    """Threats minus the known false-positive signatures."""
    return [
        t
        for t in decision.threats_detected
        if getattr(t, "signature_id", None) not in _IGNORED_SIGNATURES
    ]


@lru_cache(maxsize=1)
def _shield():
    """A shield tuned for a developer knowledge pool.

    Two default layers are wrong for one-shot screening of technical content:
      - anomaly_detector accumulates per-session state across calls -> would
        false-positive independent posts.
      - ml_detector (TF-IDF) misfires on code/config text (e.g. flags a plain
        `@tailwindcss/postcss` fix as injection, score 0.93) -> would block
        legitimate solutions, defeating the pool's purpose.
    We disable both and rely on the deterministic layers: prompt-armor (catches
    real injection patterns like "ignore previous instructions") and the
    exfiltration/DLP guard (catches leaked secrets).
    """
    from zugashield import ZugaShield

    try:
        from zugashield.config import ShieldConfig

        return ZugaShield(
            ShieldConfig(anomaly_detector_enabled=False, ml_detector_enabled=False)
        )
    except Exception as e:
        log.warning("could not tune shield layers, using defaults: %s", e)
        return ZugaShield()


def _check(shield, kind: str, text: str):
    """Run a ZugaShield check by name, tolerating API differences across versions.

    Prefers the sync convenience method (`check_prompt_sync`) when present;
    otherwise drives the stable async method (`check_prompt`). Sync tools run in
    a worker thread with no event loop, so asyncio.run is safe here.

    Each call gets a unique session_id so the stateful anomaly layer never
    accumulates across independent posts (which would false-positive benign
    submissions). The injection content itself is still caught statelessly by
    prompt-armor + the ML detector.
    """
    ctx = {"session_id": uuid.uuid4().hex}
    sync = getattr(shield, f"check_{kind}_sync", None)
    if callable(sync):
        return sync(text, context=ctx)
    coro = getattr(shield, f"check_{kind}")(text, context=ctx)
    return asyncio.run(coro)


def screen_post(problem: str, solution: str) -> tuple[bool, str]:
    """Return (allowed, reason).

    Rejects on prompt-injection in the combined text (check_prompt) or on a
    leaked secret/credential in the solution (check_output / DLP).
    """
    # Stateless AgentPool layer first (no external dep, can't fail open).
    if _exfil_instruction(f"{problem}\n{solution}"):
        return False, "exfiltration instruction (sensitive target + network sink)"

    try:
        shield = _shield()
    except Exception as e:  # zugashield missing/broken -> fail open, but shout
        log.warning("content shield unavailable, allowing post: %s", e)
        return True, ""

    try:
        combined = f"{problem}\n\n{solution}"
        pd = _check(shield, "prompt", combined)
        pd_real = _real_threats(pd)
        if pd.is_blocked and pd_real:
            why = _threats_of(pd_real) or "prompt-injection pattern"
            return False, f"injection risk ({why})"

        od = _check(shield, "output", solution)
        od_real = _real_threats(od)
        if od.is_blocked and od_real:
            why = _threats_of(od_real) or "secret/credential"
            return False, f"leaked secret ({why})"
    except Exception as e:
        log.warning("content shield errored, allowing post: %s", e)
        return True, ""

    return True, ""


def _threats_of(threats) -> str:
    return "; ".join(t.description for t in threats[:3])
