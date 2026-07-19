"""AgentPool — shielded shared fix-pool MCP server for coding agents."""

__version__ = "0.3.2"

EMBED_DIM = 384
# Vote weight by tier. `anon` exists but carries no weight and cannot vote.
TIER_WEIGHT = {"anon": 0, "free": 1, "paid": 2, "verified": 3}
# Tiers a user may self-register as (anon is internal-only).
VALID_TIERS = ("free", "paid", "verified")
ANON_HANDLE = "anonymous"
