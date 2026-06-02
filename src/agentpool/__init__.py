"""AgentPool — agent-first Stack Overflow MCP server."""

__version__ = "0.1.0"

EMBED_DIM = 384
TIER_WEIGHT = {"free": 1, "paid": 2, "verified": 3}
VALID_TIERS = tuple(TIER_WEIGHT.keys())
