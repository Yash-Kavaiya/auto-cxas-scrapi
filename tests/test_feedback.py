"""Tests for the feedback loop — ingestion + growing-benchmark promotion."""
from __future__ import annotations

from pathlib import Path

import yaml

from auto_cxas_scrapi.feedback import (
    BenchmarkManager,
    FeedbackIngestor,
    candidate_signature,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeScrapi:
    def __init__(self, conversations: list[dict]) -> None:
        self._conversations = conversations
        self.calls: list[dict] = []

    def list_recent_conversations(
        self, app_name: str = "", *, lookback_hours: int = 24, max_conversations: int = 200
    ) -> list[dict]:
        self.calls.append(
            {"app_name": app_name, "lookback_hours": lookback_hours, "max": max_conversations}
        )
        return self._conversations


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text("utf-8")) or {}).get("tests", [])


# ---------------------------------------------------------------------------
# FeedbackIngestor
# ---------------------------------------------------------------------------

def test_ingestor_flags_only_failures() -> None:
    convos = [
        {"user_utterance": "happy path", "rating": 5.0},                       # ok
        {"user_utterance": "this is broken", "thumbs_down": True},             # fail
        {"user_utterance": "get me a person", "escalated": True},              # fail
        {"user_utterance": "??", "no_match": True},                           # fail
        {"user_utterance": "meh", "rating": 2.0},                            # fail (low rating)
        {"user_utterance": "", "thumbs_down": True},                         # skipped (no utterance)
    ]
    ingestor = FeedbackIngestor(FakeScrapi(convos))
    cands = ingestor.harvest(app_name="app", lookback_hours=12, max_conversations=50)

    utterances = {c["user_utterance"] for c in cands}
    assert utterances == {"this is broken", "get me a person", "??", "meh"}
    assert all(c["source"] == "production" for c in cands)


def test_ingestor_infers_intent_from_signal() -> None:
    ingestor = FeedbackIngestor(
        FakeScrapi([{"user_utterance": "agent now", "escalated": True}])
    )
    (cand,) = ingestor.harvest()
    assert cand["expected_intent"] == "escalation"


def test_ingestor_handles_empty_history() -> None:
    assert FeedbackIngestor(FakeScrapi([])).harvest() == []


# ---------------------------------------------------------------------------
# BenchmarkManager
# ---------------------------------------------------------------------------

def _manager(tmp_path: Path, threshold: int = 2) -> BenchmarkManager:
    return BenchmarkManager(
        golden_path=tmp_path / "golden_tests.yaml",
        candidates_path=tmp_path / "golden_candidates.yaml",
        promote_threshold=threshold,
    )


def test_add_candidates_dedups(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    cand = {"user_utterance": "Where is my refund?", "source": "production"}
    assert mgr.add_candidates([cand]) == 1
    # same utterance (case/spacing-insensitive) is not staged twice
    assert mgr.add_candidates([{"user_utterance": "where is my   REFUND?"}]) == 0
    assert len(_load(tmp_path / "golden_candidates.yaml")) == 1


def test_add_candidates_skips_existing_golden(tmp_path: Path) -> None:
    golden = tmp_path / "golden_tests.yaml"
    golden.write_text(
        yaml.safe_dump({"tests": [{"test_id": "gt_001", "user_utterance": "Hi there"}]}),
        encoding="utf-8",
    )
    mgr = _manager(tmp_path)
    assert mgr.add_candidates([{"user_utterance": "hi there"}]) == 0


def test_record_run_increments_only_failures(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    mgr.add_candidates([
        {"user_utterance": "still broken"},
        {"user_utterance": "actually fixed"},
    ])
    broken_sig = candidate_signature("still broken")

    def grader(tests):  # only the "still broken" candidate fails
        return [{"test_id": t.test_id} for t in tests if t.user_utterance == "still broken"]

    failed = mgr.record_run(grader=grader)
    assert failed == 1
    staged = {c["signature"]: c for c in _load(tmp_path / "golden_candidates.yaml")}
    assert staged[broken_sig]["seen_failures"] == 1
    assert staged[broken_sig]["runs_observed"] == 1
    other = next(c for c in staged.values() if c["signature"] != broken_sig)
    assert other["seen_failures"] == 0
    assert other["runs_observed"] == 1


def test_promote_after_threshold(tmp_path: Path) -> None:
    mgr = _manager(tmp_path, threshold=2)
    mgr.add_candidates([{"user_utterance": "reproducible failure", "expected_intent": "refund_request"}])

    def always_fail(tests):
        return [{"test_id": t.test_id} for t in tests]

    # First reproduction — not yet ripe.
    mgr.record_run(grader=always_fail)
    assert mgr.promote() == []
    assert _load(tmp_path / "golden_tests.yaml") == []

    # Second reproduction — now promotes.
    mgr.record_run(grader=always_fail)
    promoted = mgr.promote()
    assert len(promoted) == 1

    golden = _load(tmp_path / "golden_tests.yaml")
    assert len(golden) == 1
    entry = golden[0]
    # promoted entry keeps only GoldenTest fields (tracking metadata stripped)
    assert set(entry) <= {
        "test_id", "user_utterance", "expected_intent",
        "expected_response_contains", "max_latency_ms",
    }
    assert entry["expected_intent"] == "refund_request"
    # candidate pool no longer holds the promoted case
    assert _load(tmp_path / "golden_candidates.yaml") == []


def test_promoted_entry_loads_as_golden_test(tmp_path: Path) -> None:
    """A promoted entry must be consumable by evaluate._load_golden_tests's GoldenTest(**t)."""
    from evaluate import GoldenTest

    mgr = _manager(tmp_path, threshold=1)
    mgr.add_candidates([{"user_utterance": "load me", "expected_intent": "x"}])
    mgr.record_run(grader=lambda tests: [{"test_id": t.test_id} for t in tests])
    mgr.promote()

    for t in _load(tmp_path / "golden_tests.yaml"):
        GoldenTest(**t)  # must not raise
