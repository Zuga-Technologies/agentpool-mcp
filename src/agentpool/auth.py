"""API-key identity: minting, hashing, and request authentication."""
import hashlib
import secrets

from . import VALID_TIERS
from . import db as _db


def mint_key() -> str:
    return "ap_" + secrets.token_urlsafe(32)


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def register(conn, handle: str, tier: str = "free") -> dict:
    """Create an account, return the raw key once (only the hash is stored)."""
    handle = handle.strip()
    if not handle or len(handle) > 40:
        raise ValueError("handle must be 1-40 chars")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}")
    key = mint_key()
    account_id = _db.create_account(conn, handle, tier, hash_key(key))
    return {"id": account_id, "handle": handle, "tier": tier, "api_key": key}


class AuthError(Exception):
    """Raised when a request cannot be authenticated."""


def extract_key(headers: dict) -> str:
    """Pull the API key from either header.

    AgentPool's native MCP clients send `X-API-Key`; cq tooling sends
    `Authorization: Bearer <key>`. Accept both for interop.
    """
    h = headers or {}
    key = (h.get("x-api-key") or "").strip()
    if key:
        return key
    authz = (h.get("authorization") or "").strip()
    if authz.lower().startswith("bearer "):
        return authz[7:].strip()
    return ""


def authenticate(conn, headers: dict) -> dict:
    """Resolve the API key (X-API-Key or Bearer) to an account. Raises otherwise."""
    api_key = extract_key(headers)
    if not api_key:
        raise AuthError("missing X-API-Key or Authorization: Bearer header")
    row = _db.get_account_by_key_hash(conn, hash_key(api_key))
    if row is None:
        raise AuthError("unknown API key")
    if row["banned"]:
        raise AuthError("account suspended")
    return dict(row)


def authenticate_optional(conn, headers: dict) -> dict | None:
    """Like authenticate() but returns None when no key is present (anonymous).

    A present-but-invalid or banned key still raises — only the *absence* of a
    key yields None.
    """
    if not extract_key(headers):
        return None
    return authenticate(conn, headers)
