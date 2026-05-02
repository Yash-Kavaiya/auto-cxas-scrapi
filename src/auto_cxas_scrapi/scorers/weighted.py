"""Multi-objective weighted scorer."""
from __future__ import annotations

from auto_cxas_scrapi.core.contracts import Scorer
from auto_cxas_scrapi.core.models import ExperimentResult, ScoreCard


class WeightedScorer(Scorer):
    def __init__(
        self, *,
        task_weight: float = 0.60,
        latency_weight: float = 0.25,
        reliability_weight: float = 0.15,
        max_latency_ms: float = 5000.0,
    ) -> None:
        self.task_weight = task_weight
        self.latency_weight = latency_weight
        self.reliability_weight = reliability_weight
        self.max_latency_ms = max_latency_ms

    def score(self, result: ExperimentResult) -> ScoreCard:
        sim = result.artifacts.get("simulation_summary", result.artifacts)
        task_success = float(sim.get("task_success", 0.0))
        latency_p95  = float(sim.get("latency_ms_p95", 0.0))
        error_rate   = float(sim.get("tool_error_rate", 1.0))

        latency_score     = max(0.0, 1.0 - min(latency_p95 / self.max_latency_ms, 1.0))
        reliability_score = max(0.0, 1.0 - min(error_rate, 1.0))

        total = round(
            task_success * self.task_weight
            + latency_score * self.latency_weight
            + reliability_score * self.reliability_weight,
            6,
        )
        return ScoreCard(
            score=total,
            metrics={
                "task_success": task_success,
                "latency_ms_p95": latency_p95,
                "tool_error_rate": error_rate,
                "latency_score": latency_score,
                "reliability_score": reliability_score,
            },
            rationale=(
                f"score = {task_success:.4f}x{self.task_weight} "
                f"+ {latency_score:.4f}x{self.latency_weight} "
                f"+ {reliability_score:.4f}x{self.reliability_weight} "
                f"= {total:.6f}"
            ),
        )
