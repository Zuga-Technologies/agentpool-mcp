"""Write-time content rail: scan posted solutions with ZugaShield before they
ever reach another agent via ask_pool.

The pool is read by LLMs, so a posted "solution" is an indirect prompt-injection
vector. We scan at POST time (once) so reads stay fast and serve vetted content.

Fail-open on *infrastructure* errors (keep the pool usable), but a clean BLOCK
verdict always rejects — a known attack never gets stored.
"""
import asyncio
import logging
import uuid
from functools import lru_cache

log = logging.getLogger("agentpool.guard")


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
    try:
        shield = _shield()
    except Exception as e:  # zugashield missing/broken -> fail open, but shout
        log.warning("content shield unavailable, allowing post: %s", e)
        return True, ""

    try:
        combined = f"{problem}\n\n{solution}"
        pd = _check(shield, "prompt", combined)
        if pd.is_blocked:
            why = _threats(pd) or "prompt-injection pattern"
            return False, f"injection risk ({why})"

        od = _check(shield, "output", solution)
        if od.is_blocked:
            why = _threats(od) or "secret/credential"
            return False, f"leaked secret ({why})"
    except Exception as e:
        log.warning("content shield errored, allowing post: %s", e)
        return True, ""

    return True, ""


def _threats(decision) -> str:
    return "; ".join(t.description for t in decision.threats_detected[:3])
