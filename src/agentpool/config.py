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
