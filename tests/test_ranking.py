from datetime import datetime, timedelta, timezone

from agentpool import ranking


def test_voter_weight_by_tier():
    assert ranking.voter_weight("free") == 1
    assert ranking.voter_weight("paid") == 2
    assert ranking.voter_weight("verified") == 3
    assert ranking.voter_weight("bogus") == 1


def test_similarity_from_distance():
    assert ranking.similarity_from_distance(0.0) == 1.0
    assert ranking.similarity_from_distance(1.0) == 0.0
    assert ranking.similarity_from_distance(2.0) == 0.0  # clamped


def test_recency_decays():
    now = datetime.now(timezone.utc)
    fresh = ranking._recency(now.isoformat(), now)
    old = ranking._recency((now - timedelta(days=30)).isoformat(), now)
    assert fresh > old
    assert abs(old - 0.5) < 0.01  # one half-life


def test_norm_score_monotonic_and_bounded():
    assert ranking._norm_score(0) == 0.0
    assert ranking._norm_score(-5) == 0.0
    assert 0 < ranking._norm_score(3) < 1
    assert ranking._norm_score(100) < 1
    assert ranking._norm_score(10) > ranking._norm_score(3)


def test_final_rank_prefers_closer_and_higher_score():
    now = datetime.now(timezone.utc)
    iso = now.isoformat()
    close_high = ranking.final_rank(0.1, 10, iso, now)
    far_low = ranking.final_rank(0.9, 0, iso, now)
    assert close_high > far_low


def test_min_similarity_sits_between_observed_hit_and_miss_bands():
    # Calibrated 2026-07-18 against a real pilot: true matches scored
    # 0.76-0.87, confirmed non-matches scored 0.57-0.67. The floor must sit
    # strictly between both observed bands or it isn't doing its job.
    observed_true_matches = [0.76, 0.79, 0.84, 0.86, 0.87]
    observed_false_positives = [0.57, 0.60, 0.66, 0.67]
    assert all(s >= ranking.MIN_SIMILARITY for s in observed_true_matches)
    assert all(s < ranking.MIN_SIMILARITY for s in observed_false_positives)
