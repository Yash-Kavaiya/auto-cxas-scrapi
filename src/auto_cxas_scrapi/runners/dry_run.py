"""Dry-run experiment runner — no live CXAS calls."""
from __future__ import annotations

from datetime import UTC, datetime

from auto_cxas_scrapi.core.contracts import Runner
from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentResult, ExperimentStatus


class DryRunExperimentRunner(Runner):
    def run(self, candidate: ExperimentCandidate) -> ExperimentResult:
        return ExperimentResult(
            experiment_id=candidate.experiment_id,
            status=ExperimentStatus.passed,
            artifacts={
                "mode": "dry-run",
                "mutation": candidate.mutation,
                "lint_passed": True,
                "simulation_summary": {
                    "task_success": 0.84,
                    "latency_ms_p50": 720,
                    "latency_ms_p95": 1480,
                    "tool_error_rate": 0.01,
                },
            },
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
