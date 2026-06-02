"""CI gate: the content guard must pass the open safety corpus (recall + precision)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "redteam"))

from run_corpus import load_corpus  # noqa: E402

from agentpool.guard import screen_post  # noqa: E402


def test_corpus_full_recall_and_precision():
    missed, false_positives = [], []
    for case in load_corpus():
        allowed, reason = screen_post(case["problem"], case["solution"])
        if case["expect"] == "block" and allowed:
            missed.append(case["id"])
        if case["expect"] == "allow" and not allowed:
            false_positives.append(f"{case['id']}: {reason}")
    assert not missed, f"missed attacks: {missed}"
    assert not false_positives, f"false positives: {false_positives}"
