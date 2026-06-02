"""SQLite + sqlite-vec storage. All SQL lives here."""
import json
import sqlite3
from datetime import datetime, timezone

import sqlite_vec

from . import EMBED_DIM
from .config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT UNIQUE NOT NULL,
            handle       TEXT UNIQUE NOT NULL,
            tier         TEXT NOT NULL DEFAULT 'free',
            created_at   TEXT NOT NULL,
            banned       INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_text    TEXT NOT NULL,
            solution_text   TEXT NOT NULL,
            tags            TEXT NOT NULL DEFAULT '[]',
            error_signature TEXT NOT NULL DEFAULT '',
            author_id       INTEGER NOT NULL REFERENCES accounts(id),
            tier            TEXT NOT NULL,
            confirms        REAL NOT NULL DEFAULT 0,
            fails           REAL NOT NULL DEFAULT 0,
            score           REAL NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'active',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS confirmations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id   INTEGER NOT NULL REFERENCES entries(id),
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            worked     INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(entry_id, account_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_vec USING vec0(
            embedding float[{EMBED_DIM}] distance_metric=cosine
        );
        """
    )
    conn.commit()


# ---------- accounts ----------

def create_account(conn, handle: str, tier: str, api_key_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO accounts (api_key_hash, handle, tier, created_at) VALUES (?,?,?,?)",
        (api_key_hash, handle, tier, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_account_by_key_hash(conn, key_hash: str):
    return conn.execute(
        "SELECT * FROM accounts WHERE api_key_hash = ?", (key_hash,)
    ).fetchone()


def get_account_by_handle(conn, handle: str):
    return conn.execute(
        "SELECT * FROM accounts WHERE handle = ?", (handle,)
    ).fetchone()


def ensure_anon_account(conn) -> dict:
    """Singleton system account that owns anonymous posts (tier='anon')."""
    from . import ANON_HANDLE

    row = get_account_by_handle(conn, ANON_HANDLE)
    if row is None:
        # api_key_hash is unusable on purpose — no key maps to it.
        conn.execute(
            "INSERT INTO accounts (api_key_hash, handle, tier, created_at) VALUES (?,?,?,?)",
            (f"__anon__{ANON_HANDLE}", ANON_HANDLE, "anon", _now()),
        )
        conn.commit()
        row = get_account_by_handle(conn, ANON_HANDLE)
    return dict(row)


def account_counts(conn, account_id: int) -> tuple[int, int]:
    posts = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE author_id = ?", (account_id,)
    ).fetchone()[0]
    confirms = conn.execute(
        "SELECT COUNT(*) FROM confirmations WHERE account_id = ?", (account_id,)
    ).fetchone()[0]
    return posts, confirms


# ---------- entries ----------

def insert_entry(
    conn,
    problem_text: str,
    solution_text: str,
    tags: list[str],
    error_signature: str,
    author_id: int,
    tier: str,
    embedding: list[float],
) -> int:
    cur = conn.execute(
        """INSERT INTO entries
           (problem_text, solution_text, tags, error_signature, author_id, tier, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            problem_text,
            solution_text,
            json.dumps(tags),
            error_signature,
            author_id,
            tier,
            _now(),
        ),
    )
    entry_id = cur.lastrowid
    conn.execute(
        "INSERT INTO entries_vec (rowid, embedding) VALUES (?, ?)",
        (entry_id, sqlite_vec.serialize_float32(embedding)),
    )
    conn.commit()
    return entry_id


def get_entry(conn, entry_id: int):
    return conn.execute(
        "SELECT * FROM entries WHERE id = ?", (entry_id,)
    ).fetchone()


def fetch_entries(conn, ids: list[int]) -> dict[int, sqlite3.Row]:
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM entries WHERE id IN ({placeholders})", ids
    ).fetchall()
    return {r["id"]: r for r in rows}


def knn(conn, query_vec: list[float], n: int) -> list[tuple[int, float]]:
    """Return [(entry_id, cosine_distance)] for the n nearest, unfiltered."""
    rows = conn.execute(
        """SELECT rowid, distance FROM entries_vec
           WHERE embedding MATCH ? AND k = ?
           ORDER BY distance""",
        (sqlite_vec.serialize_float32(query_vec), n),
    ).fetchall()
    return [(r["rowid"], r["distance"]) for r in rows]


# ---------- confirmations ----------

def record_confirmation(
    conn, entry_id: int, account_id: int, worked: bool, voter_weight: int
):
    """Insert a vote (one per account per entry). Returns (inserted, new_score)."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO confirmations (entry_id, account_id, worked, created_at)
           VALUES (?,?,?,?)""",
        (entry_id, account_id, 1 if worked else 0, _now()),
    )
    inserted = cur.rowcount > 0
    if inserted:
        if worked:
            conn.execute(
                "UPDATE entries SET confirms = confirms + ?, score = (confirms + ?) - fails WHERE id = ?",
                (voter_weight, voter_weight, entry_id),
            )
        else:
            conn.execute(
                "UPDATE entries SET fails = fails + ?, score = confirms - (fails + ?) WHERE id = ?",
                (voter_weight, voter_weight, entry_id),
            )
    conn.commit()
    row = get_entry(conn, entry_id)
    return inserted, (row["score"] if row else 0.0)


# ---------- rate limiting ----------

def count_recent_posts(conn, account_id: int, since_iso: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM entries WHERE author_id = ? AND created_at >= ?",
        (account_id, since_iso),
    ).fetchone()[0]


def count_recent_confirms(conn, account_id: int, since_iso: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM confirmations WHERE account_id = ? AND created_at >= ?",
        (account_id, since_iso),
    ).fetchone()[0]


# ---------- moderation ----------

def remove_entries_by_tier_since(conn, tier: str, since_iso: str) -> int:
    cur = conn.execute(
        "UPDATE entries SET status='removed' WHERE tier = ? AND created_at >= ? AND status != 'removed'",
        (tier, since_iso),
    )
    conn.commit()
    return cur.rowcount


def purge_all(conn) -> dict:
    """Wipe all pool content + non-anon accounts. Pre-launch / hard-reset only."""
    from . import ANON_HANDLE

    counts = {
        "confirmations": conn.execute("DELETE FROM confirmations").rowcount,
        "entries_vec": conn.execute("DELETE FROM entries_vec").rowcount,
        "entries": conn.execute("DELETE FROM entries").rowcount,
        "accounts": conn.execute(
            "DELETE FROM accounts WHERE handle != ?", (ANON_HANDLE,)
        ).rowcount,
    }
    conn.commit()
    return counts
