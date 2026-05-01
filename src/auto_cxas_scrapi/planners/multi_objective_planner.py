"""Multi-objective planner utilities — eval ranking and score utilities.

Module-level functions are used by LLMOptimizationPlanner to determine
which eval dimension to target next.

Priority order (configurable):
  1. simulation   — task_success     (weight: 0.60)
  2. tool         — tool_pass_rate   (weight: 0.25)
  3. turn         — turn_pass_rate   (weight: 0.10)
  4. guardrail    — guardrail_pass_rate (weight: 0.03)
  5. callback     — callback_pass_rate  (weight: 0.02)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default weights matching weighted.py scorer
EVAL_WEIGHTS: list[tuple[str, str, float]] = [
    # (eval_type, metric_key_in_scorecard, weight)
    ("simulation", "task_success", 0.60),
    ("tool", "tool_pass_rate", 0.25),
    ("turn", "turn_pass_rate", 0.10),
    ("guardrail", "guardrail_pass_rate", 0.03),
    ("callback", "callback_pass_rate", 0.02),
]


def load_last_metrics(state_dir: Path) -> dict[str, float]:
    """Load metric scores from last_result.json; returns {} on any failure."""
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
    """Return eval dimensions sorted by score ascending (worst first).

    Each entry is (eval_type, metric_key, current_score).
    """
    w = weights or EVAL_WEIGHTS
    ranked = [
        (eval_type, metric_key, metrics.get(metric_key, 0.0))
        for eval_type, metric_key, _ in w
    ]
    return sorted(ranked, key=lambda x: x[2])


@dataclass
class MultiObjectiveCandidate:
    """A proposed experiment targeting a specific eval dimension."""
    experiment_id: str
    title: str
    hypothesis: str
    target_eval: str          # simulation | tool | turn | guardrail | callback
    target_metric: str        # the specific metric being improved
    current_score: float      # score for this metric in the last run
    mutation: dict[str, Any]
    priority: int             # 1 = highest priority target
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
    """Utility class for multi-objective eval targeting.

    propose() has been removed; use LLMOptimizationPlanner for candidate
    generation.  This class retains top_priority_eval() and score_summary()
    as convenience helpers.
    """

    def __init__(
        self,
        state_dir: Path,
        eval_weights: list[tuple[str, str, float]] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.eval_weights = eval_weights or EVAL_WEIGHTS

    def top_priority_eval(self) -> str:
        """Return the eval type with the lowest current score."""
        ranked = rank_eval_types(load_last_metrics(self.state_dir), self.eval_weights)
        return ranked[0][0] if ranked else "simulation"

    def score_summary(self) -> dict[str, float]:
        """Return current metric scores for all 5 eval dimensions."""
        last_metrics = load_last_metrics(self.state_dir)
        return {
            metric_key: last_metrics.get(metric_key, 0.0)
            for _, metric_key, _ in self.eval_weights
        }
