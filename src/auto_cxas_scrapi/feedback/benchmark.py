"""Growing-benchmark manager — the missing "failures become new test cases" arrow.

Harvested failures (from eval runs and from production conversations) are staged
in ``golden_candidates.yaml`` with reproduction counters. A candidate is only
auto-promoted into the official ``golden_tests.yaml`` once it has reproduced as a
failure at least ``promote_threshold`` times — this keeps the benchmark clean
while still letting it compound over time.

The candidate file uses the SAME schema as golden_tests.yaml plus tracking
fields (``signature``, ``source``, ``seen_failures``, ``runs_observed``,
``first_seen``). Promotion strips the tracking fields so the official benchmark
stays loadable by ``evaluate._load_golden_tests``.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Fields that belong to the GoldenTest schema (everything else is tracking metadata).
_GOLDEN_FIELDS = (
    "test_id",
    "user_utterance",
    "expected_intent",
    "expected_response_contains",
    "max_latency_ms",
)


def candidate_signature(utterance: str) -> str:
    """Stable de-dup key for a candidate, derived from its trigger utterance."""
    norm = " ".join(utterance.strip().lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class BenchmarkManager:
    """Stage harvested failures, track reproductions, and auto-promote winners."""

    def __init__(
        self,
        *,
        golden_path: Path,
        candidates_path: Path,
        promote_threshold: int = 2,
    ) -> None:
        self.golden_path = Path(golden_path)
        self.candidates_path = Path(candidates_path)
        self.promote_threshold = max(1, promote_threshold)

    # ------------------------------------------------------------------
    # YAML helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_tests(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text("utf-8")) or {}
        except Exception as exc:
            log.warning("Could not parse %s: %s", path, exc)
            return []
        return list(data.get("tests", []) or [])

    @staticmethod
    def _write_tests(path: Path, tests: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({"tests": tests}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _known_signatures(self) -> set[str]:
        """Signatures already present in either the candidate pool or the golden set."""
        sigs: set[str] = set()
        for t in self._load_tests(self.candidates_path):
            sigs.add(t.get("signature") or candidate_signature(t.get("user_utterance", "")))
        for t in self._load_tests(self.golden_path):
            sigs.add(candidate_signature(t.get("user_utterance", "")))
        return sigs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_candidates(self, candidates: list[dict[str, Any]]) -> int:
        """Stage new failure candidates, skipping any already known. Returns count added."""
        if not candidates:
            return 0
        known = self._known_signatures()
        staged = self._load_tests(self.candidates_path)
        added = 0
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for cand in candidates:
            utterance = (cand.get("user_utterance") or "").strip()
            if not utterance:
                continue
            sig = candidate_signature(utterance)
            if sig in known:
                continue
            known.add(sig)
            staged.append({
                "test_id": f"cand_{sig[:8]}",
                "user_utterance": utterance,
                "expected_intent": cand.get("expected_intent") or "unknown",
                "expected_response_contains": list(cand.get("expected_response_contains") or []),
                "max_latency_ms": int(cand.get("max_latency_ms") or 3000),
                "signature": sig,
                "source": cand.get("source") or "unknown",
                "seen_failures": 0,
                "runs_observed": 0,
                "first_seen": now,
            })
            added += 1
        if added:
            self._write_tests(self.candidates_path, staged)
            log.info("Staged %d new benchmark candidate(s).", added)
        return added

    def record_run(
        self,
        *,
        grader: Callable[[list[Any]], list[dict[str, Any]]] | None = None,
        dry_run: bool = False,
    ) -> int:
        """Re-grade every staged candidate against the current agent.

        Increments ``runs_observed`` for all candidates and ``seen_failures`` for
        those that still fail. Returns the number of candidates that failed this run.

        ``grader`` is injectable for testing; by default it lazily reuses
        ``evaluate.grade_tests`` so reproduction is judged by the exact same
        grading logic as the official benchmark.
        """
        staged = self._load_tests(self.candidates_path)
        if not staged:
            return 0

        grade = grader or self._default_grader(dry_run)
        golden_tests = [self._to_golden_test(c) for c in staged]
        try:
            failed = grade(golden_tests)
        except Exception as exc:
            log.warning("Candidate grading failed: %s", exc)
            return 0
        failed_ids = {f.get("test_id") for f in failed}

        for cand in staged:
            cand["runs_observed"] = int(cand.get("runs_observed", 0)) + 1
            if cand.get("test_id") in failed_ids:
                cand["seen_failures"] = int(cand.get("seen_failures", 0)) + 1
        self._write_tests(self.candidates_path, staged)
        return len(failed_ids)

    def promote(self) -> list[str]:
        """Move candidates that have reproduced enough times into golden_tests.yaml.

        Returns the list of promoted test_ids.
        """
        staged = self._load_tests(self.candidates_path)
        if not staged:
            return []

        ripe = [c for c in staged if int(c.get("seen_failures", 0)) >= self.promote_threshold]
        if not ripe:
            return []

        golden = self._load_tests(self.golden_path)
        existing_ids = {t.get("test_id") for t in golden}
        existing_sigs = {candidate_signature(t.get("user_utterance", "")) for t in golden}
        promoted: list[str] = []
        for cand in ripe:
            sig = cand.get("signature") or candidate_signature(cand.get("user_utterance", ""))
            if sig in existing_sigs:
                continue
            entry = {k: cand[k] for k in _GOLDEN_FIELDS if k in cand}
            entry["test_id"] = self._unique_golden_id(cand, existing_ids)
            existing_ids.add(entry["test_id"])
            existing_sigs.add(sig)
            golden.append(entry)
            promoted.append(entry["test_id"])

        if promoted:
            self._write_tests(self.golden_path, golden)
            remaining = [c for c in staged if c not in ripe]
            self._write_tests(self.candidates_path, remaining)
            log.info("Promoted %d candidate(s) into golden_tests.yaml: %s", len(promoted), promoted)
        return promoted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _unique_golden_id(cand: dict[str, Any], existing_ids: set[str | None]) -> str:
        base = f"gt_harvested_{(cand.get('signature') or '')[:8]}"
        candidate_id = base
        n = 2
        while candidate_id in existing_ids:
            candidate_id = f"{base}_{n}"
            n += 1
        return candidate_id

    @staticmethod
    def _to_golden_test(cand: dict[str, Any]) -> Any:
        """Build an evaluate.GoldenTest from a candidate dict (lazy import to avoid cycle)."""
        from evaluate import GoldenTest  # noqa: PLC0415 — root-level harness module
        return GoldenTest(
            test_id=cand["test_id"],
            user_utterance=cand["user_utterance"],
            expected_intent=cand.get("expected_intent", "unknown"),
            expected_response_contains=list(cand.get("expected_response_contains") or []),
            max_latency_ms=int(cand.get("max_latency_ms") or 3000),
        )

    @staticmethod
    def _default_grader(dry_run: bool) -> Callable[[list[Any]], list[dict[str, Any]]]:
        def grade(tests: list[Any]) -> list[dict[str, Any]]:
            from evaluate import grade_tests  # noqa: PLC0415 — root-level harness module
            return grade_tests(tests, dry_run=dry_run)
        return grade
