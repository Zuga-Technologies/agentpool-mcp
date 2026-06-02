"""Write-time content rail: scan posted solutions with ZugaShield before they
ever reach another agent via ask_pool.

The pool is read by LLMs, so a posted "solution" is an indirect prompt-injection
vector. We scan at POST time (once) so reads stay fast and serve vetted content.

Fail-open on *infrastructure* errors (keep the pool usable), but a clean BLOCK
verdict always rejects — a known attack never gets stored.
"""
import logging
from functools import lru_cache

log = logging.getLogger("agentpool.guard")


@lru_cache(maxsize=1)
def _shield():
    from zugashield import ZugaShield

    return ZugaShield()


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
        pd = shield.check_prompt_sync(combined)
        if pd.is_blocked:
            why = _threats(pd) or "prompt-injection pattern"
            return False, f"injection risk ({why})"

        od = shield.check_output_sync(solution)
        if od.is_blocked:
            why = _threats(od) or "secret/credential"
            return False, f"leaked secret ({why})"
    except Exception as e:
        log.warning("content shield errored, allowing post: %s", e)
        return True, ""

    return True, ""


def _threats(decision) -> str:
    return "; ".join(t.description for t in decision.threats_detected[:3])
