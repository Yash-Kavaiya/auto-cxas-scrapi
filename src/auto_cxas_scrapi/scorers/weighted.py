"""Multi-objective weighted scorer — all 5 CXAS eval dimensions."""
from __future__ import annotations

from auto_cxas_scrapi.core.contracts import Scorer
from auto_cxas_scrapi.core.models import ExperimentResult, ScoreCard


class WeightedScorer(Scorer):
    """Score = task*0.35 + turn*0.20 + tool*0.20 + latency*0.15 + guardrail*0.07 + callback*0.03."""

    def __init__(
        self, *,
        task_weight: float = 0.35,
        turn_weight: float = 0.20,
        tool_weight: float = 0.20,
        latency_weight: float = 0.15,
        guardrail_weight: float = 0.07,
        callback_weight: float = 0.03,
        max_latency_ms: float = 5000.0,
    ) -> None:
        self.task_weight     = task_weight
        self.turn_weight     = turn_weight
        self.tool_weight     = tool_weight
        self.latency_weight  = latency_weight
        self.guardrail_weight = guardrail_weight
        self.callback_weight = callback_weight
        self.max_latency_ms  = max_latency_ms

    def score(self, result: ExperimentResult) -> ScoreCard:
        sim = result.artifacts.get("simulation_summary", result.artifacts)
        task      = float(sim.get("task_success", 0.0))
        turn      = float(sim.get("turn_pass_rate", task))
        tool      = float(sim.get("tool_pass_rate", task))
        guardrail = float(sim.get("guardrail_pass_rate", 1.0))
        callback  = float(sim.get("callback_pass_rate", task))
        latency_p95 = float(sim.get("latency_ms_p95", 0.0))

        latency_score = max(0.0, 1.0 - min(latency_p95 / self.max_latency_ms, 1.0))

        total = round(
            task      * self.task_weight
            + turn      * self.turn_weight
            + tool      * self.tool_weight
            + latency_score * self.latency_weight
            + guardrail * self.guardrail_weight
            + callback  * self.callback_weight,
            6,
        )
        return ScoreCard(
            score=total,
            metrics={
                "task_success":       task,
                "turn_pass_rate":     turn,
                "tool_pass_rate":     tool,
                "guardrail_pass_rate": guardrail,
                "callback_pass_rate": callback,
                "latency_ms_p95":     latency_p95,
                "latency_score":      latency_score,
            },
            rationale=(
                f"score = task({task:.4f})x{self.task_weight}"
                f" + turn({turn:.4f})x{self.turn_weight}"
                f" + tool({tool:.4f})x{self.tool_weight}"
                f" + latency({latency_score:.4f})x{self.latency_weight}"
                f" + guardrail({guardrail:.4f})x{self.guardrail_weight}"
                f" + callback({callback:.4f})x{self.callback_weight}"
                f" = {total:.6f}"
            ),
        )
