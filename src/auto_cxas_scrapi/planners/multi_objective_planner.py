"""Multi-objective planner utilities — eval ranking and score utilities.

Weights match WeightedScorer and evaluate.py._compute_eval_score:
  simulation  task_success      0.35
  turn        turn_pass_rate    0.20
  tool        tool_pass_rate    0.20
  latency     (implicit)        0.15
  guardrail   guardrail_pass_rate 0.07
  callback    callback_pass_rate  0.03
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

EVAL_WEIGHTS: list[tuple[str, str, float]] = [
    ("simulation", "task_success",        0.35),
    ("turn",       "turn_pass_rate",       0.20),
    ("tool",       "tool_pass_rate",       0.20),
    ("guardrail",  "guardrail_pass_rate",  0.07),
    ("callback",   "callback_pass_rate",   0.03),
]


def load_last_metrics(state_dir: Path) -> dict[str, float]:
    """Load metric scores from last_result.json; returns {} on failure."""
    result_path = state_dir / "last_result.json"
    if not result_path.exists():
        return {}
    try:
        data = json.loads(result_path.read_text("utf-8"))
        metrics = data.get("metrics", {})
        return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
    except Exception as exc:
        log.warning("Failed to load last_result.json: %s", exc)
        return {}


def rank_eval_types(
    metrics: dict[str, float],
    weights: list[tuple[str, str, float]] | None = None,
) -> list[tuple[str, str, float]]:
    """Return eval dimensions sorted ascending by score (worst first).

    Each entry: (eval_type, metric_key, current_score).
    """
    w = weights or EVAL_WEIGHTS
    ranked = [
        (eval_type, metric_key, metrics.get(metric_key, 0.0))
        for eval_type, metric_key, _ in w
    ]
    return sorted(ranked, key=lambda x: x[2])


@dataclass
class MultiObjectiveCandidate:
    experiment_id: str
    title: str
    hypothesis: str
    target_eval: str
    target_metric: str
    current_score: float
    mutation: dict[str, Any]
    priority: int
    rationale: str
    parent_experiment_id: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "target_eval": self.target_eval,
            "target_metric": self.target_metric,
            "current_score": self.current_score,
            "mutation": self.mutation,
            "priority": self.priority,
            "rationale": self.rationale,
            "parent_experiment_id": self.parent_experiment_id,
            "tags": self.tags,
        }


class MultiObjectivePlanner:
    """Utility class for multi-objective eval targeting."""

    def __init__(
        self,
        state_dir: Path,
        eval_weights: list[tuple[str, str, float]] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.eval_weights = eval_weights or EVAL_WEIGHTS

    def top_priority_eval(self) -> str:
        ranked = rank_eval_types(load_last_metrics(self.state_dir), self.eval_weights)
        return ranked[0][0] if ranked else "simulation"

    def score_summary(self) -> dict[str, float]:
        last_metrics = load_last_metrics(self.state_dir)
        return {
            metric_key: last_metrics.get(metric_key, 0.0)
            for _, metric_key, _ in self.eval_weights
        }
