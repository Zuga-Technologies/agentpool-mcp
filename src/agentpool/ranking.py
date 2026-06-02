"""Pure ranking math. No I/O."""
from datetime import datetime, timezone

from . import TIER_WEIGHT

# Rerank blend weights
W_SIMILARITY = 0.6
W_SCORE = 0.3
W_RECENCY = 0.1

RECENCY_HALFLIFE_DAYS = 30.0


def voter_weight(tier: str) -> int:
    return TIER_WEIGHT.get(tier, 1)


def similarity_from_distance(cosine_distance: float) -> float:
    """sqlite-vec cosine distance is 0 (identical) .. 2 (opposite)."""
    return max(0.0, 1.0 - cosine_distance)


def _recency(created_at_iso: str, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(created_at_iso)
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS)


def _norm_score(score: float) -> float:
    """Squash an unbounded score into 0..1 via a soft logistic-ish curve."""
    if score <= 0:
        return 0.0
    return score / (score + 3.0)


def final_rank(
    cosine_distance: float, score: float, created_at_iso: str, now: datetime | None = None
) -> float:
    return (
        W_SIMILARITY * similarity_from_distance(cosine_distance)
        + W_SCORE * _norm_score(score)
        + W_RECENCY * _recency(created_at_iso, now)
    )
