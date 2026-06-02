"""Mint an AgentPool API key directly against the local DB (admin/dev use).

Usage:
    python scripts/register.py <handle> [free|paid|verified]
"""
import sys

from agentpool import auth, db


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/register.py <handle> [free|paid|verified]")
        return 1
    handle = sys.argv[1]
    tier = sys.argv[2] if len(sys.argv) > 2 else "free"
    conn = db.connect()
    db.init_db(conn)
    try:
        result = auth.register(conn, handle, tier)
    except ValueError as e:
        print(f"error: {e}")
        return 1
    finally:
        conn.close()
    print(f"handle : @{result['handle']}")
    print(f"tier   : {result['tier']}")
    print(f"api_key: {result['api_key']}")
    print("\nStore this key — it is not recoverable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
