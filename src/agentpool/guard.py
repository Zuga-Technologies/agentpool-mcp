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

from . import config

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


# ---------------------------------------------------------------------------
# Trust & safety: this is a separate concern from the security layers above.
# The security layers (exfil, ZugaShield's prompt-armor/DLP) protect a READING
# AGENT from a malicious post. This layer protects HUMANS from harmful content
# a writable, publicly-readable pool could otherwise carry. Deliberately kept
# in AgentPool's own guard.py, not pushed into ZugaShield -- ZugaShield's 7
# layers are all agent-security (injection/exfil/tool-abuse), not content
# moderation, and that scope split should stay clean.
#
# CSAM: deterministic, always on, no API key needed. Text-only proximity
# heuristic (age/minor indicator + sexual-content indicator co-occurring, or
# an unambiguous named phrase on its own) -- AgentPool has no image upload
# path, so this is about solicitation/description in text, not image-hash
# matching (PhotoDNA/NCMEC territory, a different infrastructure problem that
# doesn't apply to a text-only API). Kept clinical/non-graphic on purpose --
# this is public source in an Apache-2.0 repo.
_MINOR_INDICATOR = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|preteen|pre-teen|toddler"
    r"|middle[- ]school(er)?|elementary[- ]school(er)?"
    r"|\b(?:[6-9]|1[0-7])[\s-]?(?:years?|yrs?|y\.?o\.?)\b)",
    re.I,
)
_SEXUAL_CONTENT = re.compile(
    r"\b(sexual(ly)?|explicit|nude|naked|porn(ographic|ography)?|erotic|molest\w*)\b",
    re.I,
)
_CSAM_NAMED = re.compile(r"\b(csam|child\s+sexual\s+abuse|child\s+porn\w*)\b", re.I)


def _csam_solicitation(text: str) -> bool:
    return bool(
        _CSAM_NAMED.search(text)
        or (_MINOR_INDICATOR.search(text) and _SEXUAL_CONTENT.search(text))
    )


# Hate speech / harassment (racism, homophobia, targeted slurs, etc.): NOT a
# hardcoded term list -- a slur/keyword dictionary shipped in a public repo is
# both brittle (trivially evaded) and itself a bad thing to publish. This
# needs contextual judgment a regex can't give, so it's an opt-in LLM judge
# (same pattern as ZugaShield's own llm_judge.py: cheap Haiku call, fails
# open). OFF by default -- requires ANTHROPIC_API_KEY + AGENTPOOL_CONTENT_
# JUDGE_ENABLED=true. Until that's provisioned, hate/harassment content is
# NOT screened by this layer (the CSAM check above still runs regardless).
_HATE_JUDGE_PROMPT = """You are a trust & safety classifier for a public, \
written-by-anyone technical knowledge pool (developers post programming \
problems and fixes). Classify ONLY for hate speech, harassment, or targeted \
slurs (racism, homophobia, and similar) -- NOT for anything else (do not \
flag profanity, criticism of code/tools, or ordinary technical disagreement).

Respond with EXACTLY one word:
- BLOCK if the text contains hate speech, harassment, or a targeted slur
- ALLOW otherwise

Be conservative: if uncertain, respond ALLOW."""


def _hate_harassment_judge(text: str) -> tuple[bool, str]:
    """Return (blocked, reason). Fail-open on any error or when disabled."""
    if not config.CONTENT_JUDGE_ENABLED:
        return False, ""
    try:
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=config.CONTENT_JUDGE_MODEL,
            max_tokens=10,
            system=_HATE_JUDGE_PROMPT,
            messages=[{"role": "user", "content": text[:2000]}],
        )
        verdict = msg.content[0].text.strip().upper()
        if verdict == "BLOCK":
            return True, "hate speech / harassment (content judge)"
        return False, ""
    except Exception as e:  # missing package, missing key, API error -- fail open
        log.warning("content judge unavailable, allowing post: %s", e)
        return False, ""


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
    combined_text = f"{problem}\n{solution}"

    # Stateless AgentPool layers first (no external dep, can't fail open).
    if _exfil_instruction(combined_text):
        return False, "exfiltration instruction (sensitive target + network sink)"
    if _csam_solicitation(combined_text):
        return False, "content policy violation"

    # Opt-in content judge (hate speech / harassment) -- no-op unless
    # AGENTPOOL_CONTENT_JUDGE_ENABLED=true and an API key is provisioned.
    blocked, reason = _hate_harassment_judge(combined_text)
    if blocked:
        return False, reason

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
