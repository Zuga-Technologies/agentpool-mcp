"""Runtime configuration, read from environment with sane defaults."""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DB_PATH = os.environ.get("AGENTPOOL_DB", "agentpool.db")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = _int("PORT", 8000)
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
RATE_POSTS_PER_MIN = _int("RATE_POSTS_PER_MIN", 10)
RATE_CONFIRMS_PER_MIN = _int("RATE_CONFIRMS_PER_MIN", 30)

# When false (default), anonymous (no-key) connections are read-only.
ALLOW_ANON_POST = os.environ.get("ALLOW_ANON_POST", "false").lower() in ("1", "true", "yes")

# Opt-in LLM judge for hate speech / harassment / exploitation content that a
# deterministic pattern can't reliably catch (see guard.py). Off by default:
# requires ANTHROPIC_API_KEY and the `anthropic` package, and costs a model
# call per post. The deterministic CSAM-solicitation pattern check in guard.py
# is always on regardless of this flag -- it needs no API key.
CONTENT_JUDGE_ENABLED = os.environ.get("AGENTPOOL_CONTENT_JUDGE_ENABLED", "false").lower() in ("1", "true", "yes")
CONTENT_JUDGE_MODEL = os.environ.get("AGENTPOOL_CONTENT_JUDGE_MODEL", "claude-haiku-4-5-20251001")
