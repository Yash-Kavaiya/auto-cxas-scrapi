"""Multi-objective planner — targets all 5 eval types.

Inspects current metric scores from the last experiment and proposes
a mutation that targets the *weakest* eval dimension first:

  Priority order (configurable):
    1. simulation   — task_success     (weight: 0.60)
    2. tool         — tool_error_rate  (weight: 0.25)
    3. turn         — turn_pass_rate   (weight: 0.10)
    4. guardrail    — guardrail_pass_rate (weight: 0.03)
    5. callback     — callback_pass_rate  (weight: 0.02)

The planner reads the last scorecard from .auto-cxas/state/last_result.json
and produces a targeted ExperimentCandidate whose mutation is scoped to
improve the worst-performing eval dimension.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default weights matching weighted.py scorer
_EVAL_WEIGHTS: list[tuple[str, str, float]] = [
    # (eval_type, metric_key_in_scorecard, weight)
    ("simulation", "task_success", 0.60),
    ("tool", "tool_pass_rate", 0.25),
    ("turn", "turn_pass_rate", 0.10),
    ("guardrail", "guardrail_pass_rate", 0.03),
    ("callback", "callback_pass_rate", 0.02),
]

# Mutation templates per eval type
_MUTATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "simulation": {
        "type": "prompt_patch",
        "path": "SYSTEM_INSTRUCTION",
        "operation": "append",
        "value": "Always confirm you have completed each step before moving on.",
        "rationale": "Encourage step completion — targets task_success in simulation evals.",
    },
    "tool": {
        "type": "tool_schema_patch",
        "path": "tools[*].description",
        "operation": "clarify",
        "value": "Ensure tool parameter descriptions match expected types exactly.",
        "rationale": "Reduces tool argument errors — targets tool_error_rate.",
    },
    "turn": {
        "type": "prompt_patch",
        "path": "SYSTEM_INSTRUCTION",
        "operation": "prepend",
        "value": "Be concise and directly answer the user's question in the first sentence.",
        "rationale": "Improves single-turn response quality — targets turn_pass_rate.",
    },
    "guardrail": {
        "type": "guardrail_config_patch",
        "path": "guardrails[blocked_topics].topics",
        "operation": "extend",
        "value": "competitor pricing, legal advice",
        "rationale": "Tightens topic blocking — targets guardrail_pass_rate.",
    },
    "callback": {
        "type": "callback_schema_patch",
        "path": "callbacks[*].response_schema",
        "operation": "add_required_field",
        "value": "status",
        "rationale": "Ensures webhook responses include required fields — targets callback_pass_rate.",
    },
}


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
    """Plans experiments that target all 5 cxas-scrapi eval dimensions.

    Reads the last result JSON to find the weakest eval dimension and
    generates a mutation targeting it.
    """

    def __init__(
        self,
        state_dir: Path,
        eval_weights: list[tuple[str, str, float]] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.eval_weights = eval_weights or _EVAL_WEIGHTS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(
        self,
        n: int = 1,
        exclude_eval_types: list[str] | None = None,
    ) -> list[MultiObjectiveCandidate]:
        """Return up to *n* candidates sorted by eval priority.

        Args:
            n: Max number of candidates to return.
            exclude_eval_types: Eval types to skip (e.g. ['guardrail'])
        """
        exclude = set(exclude_eval_types or [])
        last_metrics = self._load_last_metrics()
        
        priorities = self._rank_eval_types(last_metrics)
        candidates: list[MultiObjectiveCandidate] = []

        for rank, (eval_type, metric_key, current_score) in enumerate(priorities, start=1):
            if eval_type in exclude:
                continue
            if len(candidates) >= n:
                break

            candidate = self._build_candidate(
                eval_type=eval_type,
                metric_key=metric_key,
                current_score=current_score,
                priority=rank,
            )
            candidates.append(candidate)

        return candidates

    def top_priority_eval(self) -> str:
        """Return the eval type with the lowest current score."""
        last_metrics = self._load_last_metrics()
        ranked = self._rank_eval_types(last_metrics)
        return ranked[0][0] if ranked else "simulation"

    def score_summary(self) -> dict[str, float]:
        """Return current metric scores for all 5 eval dimensions."""
        last_metrics = self._load_last_metrics()
        return {
            metric_key: last_metrics.get(metric_key, 0.0)
            for _, metric_key, _ in self.eval_weights
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_last_metrics(self) -> dict[str, float]:
        result_path = self.state_dir / "last_result.json"
        if not result_path.exists():
            return {}
        try:
            data = json.loads(result_path.read_text("utf-8"))
            metrics = data.get("metrics", {})
            return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
        except Exception as exc:
            log.warning("Failed to load last_result.json: %s", exc)
            return {}

    def _rank_eval_types(
        self, metrics: dict[str, float]
    ) -> list[tuple[str, str, float]]:
        """Return eval dimensions sorted by score ascending (worst first)."""
        ranked = []
        for eval_type, metric_key, _weight in self.eval_weights:
            # Default to 0 if not yet measured (meaning: most urgent)
            score = metrics.get(metric_key, 0.0)
            ranked.append((eval_type, metric_key, score))
        # Worst score first
        return sorted(ranked, key=lambda x: x[2])

    def _build_candidate(
        self,
        eval_type: str,
        metric_key: str,
        current_score: float,
        priority: int,
    ) -> MultiObjectiveCandidate:
        import uuid
        exp_id = f"exp-{uuid.uuid4().hex[:8]}"
        mutation = _MUTATION_TEMPLATES.get(eval_type, {
            "type": "prompt_patch",
            "path": "SYSTEM_INSTRUCTION",
            "operation": "append",
            "value": f"Improve {eval_type} performance.",
            "rationale": f"Generic improvement targeting {metric_key}.",
        })

        return MultiObjectiveCandidate(
            experiment_id=exp_id,
            title=f"Improve {eval_type} [{metric_key}={current_score:.3f}]",
            hypothesis=(
                f"Applying '{mutation['operation']}' to '{mutation['path']}' "
                f"will improve {metric_key} from {current_score:.3f} toward 1.0."
            ),
            target_eval=eval_type,
            target_metric=metric_key,
            current_score=current_score,
            mutation=mutation,
            priority=priority,
            rationale=mutation.get("rationale", ""),
            tags=[eval_type, f"priority-{priority}"],
        )
