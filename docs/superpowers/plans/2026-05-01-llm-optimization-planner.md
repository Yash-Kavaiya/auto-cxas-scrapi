# LLMOptimizationPlanner + Bug Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 11 failing tests, wire multi-objective eval targeting, and implement autoresearch-style LLM-driven `agent_config.py` rewriting so the loop actually mutates the file before each experiment.

**Architecture:** A single `LLMOptimizationPlanner` replaces the two orphaned planners. It reads `last_result.json` to find the weakest eval dimension, builds a rich prompt with the current `agent_config.py` + results history, and asks the LLM to output the complete new file content. `auto_loop.py` writes that content to disk before committing.

**Tech Stack:** Python 3.11+, pytest, unittest.mock, rich, typer, pydantic-settings, cxas-scrapi (optional), Anthropic/Gemini/OpenAI SDK (optional).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/auto_cxas_scrapi/adapters/cxas_evals.py` | Modify | Add module-level try/except imports; remove lazy imports inside methods |
| `src/auto_cxas_scrapi/adapters/scrapi.py` | Modify | Add module-level try/except imports; remove lazy imports inside methods |
| `src/auto_cxas_scrapi/adapters/llm/anthropic.py` | Modify | Update `DEFAULT_MODEL` to `claude-sonnet-4-6` |
| `src/auto_cxas_scrapi/core/models.py` | Modify | Add `new_agent_config_content: str = ""` field to `ExperimentCandidate` |
| `src/auto_cxas_scrapi/memory/store.py` | Modify | Serialize/deserialize `new_agent_config_content` |
| `src/auto_cxas_scrapi/planners/multi_objective_planner.py` | Modify | Extract `EVAL_WEIGHTS`, `load_last_metrics`, `rank_eval_types` as module-level functions; remove `propose()`, `_build_candidate()`, `_MUTATION_TEMPLATES` |
| `src/auto_cxas_scrapi/planners/llm_planner.py` | Replace | New `LLMOptimizationPlanner` class |
| `src/auto_cxas_scrapi/services/orchestrator.py` | Modify | Import `LLMOptimizationPlanner`; pass `state_dir` to constructor |
| `src/auto_cxas_scrapi/runners/live_run.py` | Modify | Remove `_apply_mutation`; simplify `run()` |
| `src/auto_cxas_scrapi/cli/main.py` | Modify | Fix `rollback` command to execute git reset; add `import subprocess` |
| `auto_loop.py` | Modify | Add write step between propose and commit |
| `tests/test_scorer.py` | Modify | Fix wrong `assert "rationale" in sc.rationale` |
| `tests/test_multi_objective_planner.py` | Modify | Remove 7 tests that called `propose()`; keep `test_top_priority_eval`, `test_score_summary_all_keys` |
| `tests/test_llm_planner.py` | Create | 4 tests for `LLMOptimizationPlanner` |

---

## Task 1 — Fix `cxas_evals.py` module-level imports

Tests currently fail because `patch("auto_cxas_scrapi.adapters.cxas_evals.SimulationEvals")` can't
find the name at module level — it's only defined inside method bodies.

**Files:**
- Modify: `src/auto_cxas_scrapi/adapters/cxas_evals.py`
- Test: `tests/test_cxas_evals.py` (6 tests, already written)

- [ ] **Step 1.1: Run the 6 failing tests to confirm baseline**

```
pytest tests/test_cxas_evals.py -v -k "not test_is_unavailable"
```

Expected: 6 FAILED with `AttributeError: ... does not have the attribute 'SimulationEvals'`

- [ ] **Step 1.2: Replace `cxas_evals.py` with module-level imports**

Full replacement of `src/auto_cxas_scrapi/adapters/cxas_evals.py`:

```python
"""cxas-scrapi eval adapter — wraps all 5 eval types.

Eval classes (from cxas_scrapi.__init__):
  SimulationEvals(app_name)  — multi-turn goal-based LLM simulation
  ToolEvals(app_name)        — direct tool call evaluation
  GuardrailEvals(app_name)   — safety/guardrail policy evaluation
  TurnEvals(app_name)        — single-turn agent response evaluation
  CallbackEvals(app_name)    — webhook/callback evaluation
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Module-level imports so tests can patch these names with unittest.mock.patch().
try:
    from cxas_scrapi import (  # type: ignore[import-untyped]
        CallbackEvals,
        GuardrailEvals,
        SimulationEvals,
        ToolEvals,
        TurnEvals,
    )
except ImportError:
    SimulationEvals = ToolEvals = GuardrailEvals = TurnEvals = CallbackEvals = None  # type: ignore[assignment]


class CXASEvalsAdapter:
    """Unified adapter that exposes all 5 cxas-scrapi eval types."""

    def __init__(self, *, full_app_name: str) -> None:
        self.full_app_name = full_app_name

    def is_available(self) -> bool:
        return SimulationEvals is not None

    # ------------------------------------------------------------------
    # SimulationEvals
    # ------------------------------------------------------------------

    def run_simulation_evals(
        self,
        test_cases: list[dict],
        *,
        runs: int = 1,
        parallel: int = 1,
        model: str = "gemini-2.0-flash",
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("SimulationEvals")
        try:
            client = SimulationEvals(app_name=self.full_app_name)
            results = client.run_simulations(
                test_cases=test_cases,
                runs=runs,
                parallel=parallel,
                model=model,
                verbose=verbose,
            )
            return self._aggregate_simulation(results)
        except Exception as exc:
            log.warning("SimulationEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    @staticmethod
    def _aggregate_simulation(results: list[dict]) -> dict[str, Any]:
        if not results:
            return {"available": True, "eval_type": "simulation", "pass_rate": 0.0, "total": 0}
        passed = sum(1 for r in results if r.get("passed", False))
        durations_ms = sorted(r.get("duration_s", 0) * 1000 for r in results)
        p95_idx = max(0, int(len(durations_ms) * 0.95) - 1)
        return {
            "available": True,
            "eval_type": "simulation",
            "total": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 4),
            "latency_ms_p95": int(durations_ms[p95_idx]) if durations_ms else 0,
            "raw": results,
        }

    # ------------------------------------------------------------------
    # ToolEvals
    # ------------------------------------------------------------------

    def run_tool_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("ToolEvals")
        try:
            client = ToolEvals(app_name=self.full_app_name)
            results = client.run_evals(eval_dataset=eval_dataset, parallel=parallel, verbose=verbose)
            return self._aggregate_generic(results, "tool")
        except Exception as exc:
            log.warning("ToolEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # GuardrailEvals
    # ------------------------------------------------------------------

    def run_guardrail_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("GuardrailEvals")
        try:
            client = GuardrailEvals(app_name=self.full_app_name)
            results = client.run_evals(eval_dataset=eval_dataset, parallel=parallel, verbose=verbose)
            return self._aggregate_generic(results, "guardrail")
        except Exception as exc:
            log.warning("GuardrailEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # TurnEvals
    # ------------------------------------------------------------------

    def run_turn_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        model: str = "gemini-2.0-flash",
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("TurnEvals")
        try:
            client = TurnEvals(app_name=self.full_app_name)
            results = client.run_evals(
                eval_dataset=eval_dataset, parallel=parallel, model=model, verbose=verbose
            )
            return self._aggregate_generic(results, "turn")
        except Exception as exc:
            log.warning("TurnEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # CallbackEvals
    # ------------------------------------------------------------------

    def run_callback_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("CallbackEvals")
        try:
            client = CallbackEvals(app_name=self.full_app_name)
            results = client.run_evals(eval_dataset=eval_dataset, parallel=parallel, verbose=verbose)
            return self._aggregate_generic(results, "callback")
        except Exception as exc:
            log.warning("CallbackEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_generic(results: list[dict], eval_type: str) -> dict[str, Any]:
        if not results:
            return {"available": True, "eval_type": eval_type, "pass_rate": 0.0, "total": 0}
        passed = sum(
            1 for r in results
            if r.get("passed", False) or r.get("result", "") == "PASS"
        )
        return {
            "available": True,
            "eval_type": eval_type,
            "total": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 4),
            "raw": results,
        }

    @staticmethod
    def _unavailable_result(cls_name: str) -> dict[str, Any]:
        return {
            "available": False,
            "eval_type": cls_name,
            "reason": "cxas-scrapi not installed",
        }
```

- [ ] **Step 1.3: Run the 6 tests to confirm they pass**

```
pytest tests/test_cxas_evals.py -v -k "not test_is_unavailable"
```

Expected: 6 PASSED

- [ ] **Step 1.4: Run the full cxas_evals test file**

```
pytest tests/test_cxas_evals.py -v
```

Expected: 8 PASSED (including `test_is_unavailable_returns_false`)

- [ ] **Step 1.5: Commit**

```
git add src/auto_cxas_scrapi/adapters/cxas_evals.py
git commit -m "fix: add module-level cxas_scrapi imports to cxas_evals.py for test patchability"
```

---

## Task 2 — Fix `scrapi.py` module-level imports

Tests fail because `patch("auto_cxas_scrapi.adapters.scrapi.Apps")` and
`patch("auto_cxas_scrapi.adapters.scrapi.SimulationEvals")` can't find those names at module level.

**Files:**
- Modify: `src/auto_cxas_scrapi/adapters/scrapi.py`
- Test: `tests/test_scrapi_adapter.py` (2 failing tests)

- [ ] **Step 2.1: Run the 2 failing scrapi tests**

```
pytest tests/test_scrapi_adapter.py::test_get_inventory_available tests/test_scrapi_adapter.py::test_run_simulation_eval_aggregates -v
```

Expected: 2 FAILED with `AttributeError`

- [ ] **Step 2.2: Add module-level imports to `scrapi.py`**

Replace the top section of `src/auto_cxas_scrapi/adapters/scrapi.py` (after the docstring, before `_full_app_name`):

```python
from __future__ import annotations

import json
import logging
from typing import Any

from rich.console import Console

log = logging.getLogger(__name__)

# Module-level imports so tests can patch these names.
try:
    from cxas_scrapi import Agents, Apps, SimulationEvals  # type: ignore[import-untyped]
except ImportError:
    Apps = Agents = SimulationEvals = None  # type: ignore[assignment]
```

Then update `is_available()`:

```python
def is_available(self) -> bool:
    return Apps is not None
```

Then update `get_inventory()` — remove the inner `from cxas_scrapi import Apps, Agents` line and use module-level names:

```python
def get_inventory(self, app_name: str = "") -> dict[str, Any]:
    short = app_name or self._app_short
    full = _full_app_name(self.project_id, self.location, short)

    if not self.is_available():
        return {
            "app_name": short, "full_app_name": full,
            "project_id": self.project_id, "location": self.location,
            "available": False, "reason": "cxas-scrapi not installed",
        }

    try:
        apps_client = Apps(project_id=self.project_id, location=self.location)
        apps_map = apps_client.get_apps_map()
        agents_client = Agents(app_name=full)
        agents_map = agents_client.get_agents_map()
        return {
            "app_name": short, "full_app_name": full,
            "project_id": self.project_id, "location": self.location,
            "available": True,
            "apps_count": len(apps_map), "agents_count": len(agents_map),
            "apps": list(apps_map.values()), "agents": list(agents_map.values()),
        }
    except Exception as exc:
        log.warning("get_inventory failed: %s", exc)
        return {"app_name": short, "full_app_name": full, "available": False, "error": str(exc)}
```

Update `run_lint()` — remove inner import, use module-level `Agents`:

```python
def run_lint(self, app_name: str = "") -> dict[str, Any]:
    short = app_name or self._app_short
    full = _full_app_name(self.project_id, self.location, short)
    if not self.is_available():
        return {"lint_passed": False, "reason": "cxas-scrapi not installed"}
    try:
        agents = Agents(app_name=full)
        agents.list_agents()
        return {"lint_passed": True, "app": short}
    except Exception as exc:
        return {"lint_passed": False, "error": str(exc)}
```

Update `run_simulation_eval()` — remove inner import, use module-level `SimulationEvals`:

```python
def run_simulation_eval(
    self,
    app_name: str = "",
    test_cases: list[dict] | None = None,
    runs: int = 1,
    parallel: int = 1,
) -> dict[str, Any]:
    short = app_name or self._app_short
    full = _full_app_name(self.project_id, self.location, short)
    cases = test_cases or []

    if not self.is_available() or not cases:
        return {
            "available": False,
            "task_success": 0.80, "latency_ms_p95": 1200, "tool_error_rate": 0.02,
            "reason": "cxas-scrapi unavailable or no test_cases provided",
        }

    try:
        sim = SimulationEvals(app_name=full)
        results = sim.run_simulations(
            test_cases=cases, runs=runs, parallel=parallel, verbose=False,
        )
        passed = sum(1 for r in results if r.get("passed", False))
        task_success = passed / len(results) if results else 0.0
        durations_ms = sorted(r.get("duration_s", 0) * 1000 for r in results)
        p95_idx = max(0, int(len(durations_ms) * 0.95) - 1)
        p95 = durations_ms[p95_idx] if durations_ms else 0
        return {
            "available": True,
            "task_success": round(task_success, 4),
            "latency_ms_p95": int(p95),
            "tool_error_rate": 0.0,
            "total": len(results), "passed": passed, "raw": results,
        }
    except Exception as exc:
        log.warning("run_simulation_eval failed: %s", exc)
        return {
            "available": False, "error": str(exc),
            "task_success": 0.0, "latency_ms_p95": 0, "tool_error_rate": 1.0,
        }
```

- [ ] **Step 2.3: Run the 2 scrapi tests to confirm pass**

```
pytest tests/test_scrapi_adapter.py -v
```

Expected: 8 PASSED

- [ ] **Step 2.4: Run all tests to check no regressions**

```
pytest tests/ -v --tb=short
```

Expected: previously-passing tests still pass; now 9 fewer failures.

- [ ] **Step 2.5: Commit**

```
git add src/auto_cxas_scrapi/adapters/scrapi.py
git commit -m "fix: add module-level cxas_scrapi imports to scrapi.py for test patchability"
```

---

## Task 3 — Fix `test_scorer.py` wrong assertion

`assert "rationale" in sc.rationale` checks if the *word* "rationale" appears in the rationale
string, but the string is `"score = 0.85x0.6 + ..."` — it never contains the word "rationale".

**Files:**
- Modify: `tests/test_scorer.py`

- [ ] **Step 3.1: Run the failing test**

```
pytest tests/test_scorer.py::test_typical_score_range -v
```

Expected: FAILED with `AssertionError: assert 'rationale' in 'score = ...'`

- [ ] **Step 3.2: Fix the assertion in `tests/test_scorer.py`**

Replace:
```python
assert "rationale" in sc.rationale
```
With:
```python
assert "score" in sc.rationale
assert "task_success" in sc.metrics
```

The full fixed test function:
```python
def test_typical_score_range() -> None:
    scorer = WeightedScorer()
    sc = scorer.score(_result(0.85, 1200, 0.02))
    assert 0.6 < sc.score < 1.0
    assert "task_success" in sc.metrics
    assert "score" in sc.rationale
```

- [ ] **Step 3.3: Run the test to confirm pass**

```
pytest tests/test_scorer.py -v
```

Expected: 3 PASSED

- [ ] **Step 3.4: Commit**

```
git add tests/test_scorer.py
git commit -m "fix: correct wrong assertion in test_typical_score_range"
```

---

## Task 4 — Update `AnthropicAdapter` default model

**Files:**
- Modify: `src/auto_cxas_scrapi/adapters/llm/anthropic.py`

- [ ] **Step 4.1: Update `DEFAULT_MODEL`**

In `src/auto_cxas_scrapi/adapters/llm/anthropic.py`, replace:
```python
DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
```
With:
```python
DEFAULT_MODEL = "claude-sonnet-4-6"
```

- [ ] **Step 4.2: Run tests to confirm no regressions**

```
pytest tests/ -q
```

Expected: same pass count as before (no tests directly test the model name string).

- [ ] **Step 4.3: Commit**

```
git add src/auto_cxas_scrapi/adapters/llm/anthropic.py
git commit -m "fix: update AnthropicAdapter default model to claude-sonnet-4-6"
```

---

## Task 5 — Extend `ExperimentCandidate` and `ExperimentStore`

`new_agent_config_content` must travel from the planner through the store so `auto_loop.py` can
write it to disk.

**Files:**
- Modify: `src/auto_cxas_scrapi/core/models.py`
- Modify: `src/auto_cxas_scrapi/memory/store.py`
- Test: `tests/test_models.py` (add one test)

- [ ] **Step 5.1: Write a failing test for the new field**

Add to `tests/test_models.py`:
```python
def test_candidate_new_agent_config_content_default() -> None:
    c = ExperimentCandidate(
        experiment_id="exp-001",
        title="t",
        hypothesis="h",
        target_resource="app",
        mutation={},
    )
    assert c.new_agent_config_content == ""


def test_candidate_new_agent_config_content_set() -> None:
    c = ExperimentCandidate(
        experiment_id="exp-001",
        title="t",
        hypothesis="h",
        target_resource="app",
        mutation={},
        new_agent_config_content="# new file",
    )
    assert c.new_agent_config_content == "# new file"
```

- [ ] **Step 5.2: Run to confirm it fails**

```
pytest tests/test_models.py::test_candidate_new_agent_config_content_default -v
```

Expected: FAILED with `TypeError: ExperimentCandidate.__init__() got an unexpected keyword argument`
or `TypeError` about slots.

- [ ] **Step 5.3: Add the field to `ExperimentCandidate` in `core/models.py`**

Replace the `ExperimentCandidate` dataclass:
```python
@dataclass(slots=True)
class ExperimentCandidate:
    experiment_id: str
    title: str
    hypothesis: str
    target_resource: str
    mutation: dict[str, Any]
    new_agent_config_content: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

- [ ] **Step 5.4: Update `ExperimentStore.save_candidate` to persist the new field**

In `src/auto_cxas_scrapi/memory/store.py`, replace `save_candidate`:
```python
def save_candidate(self, candidate: ExperimentCandidate) -> Path:
    path = self.experiment_dir(candidate.experiment_id) / "candidate.json"
    path.write_text(json.dumps({
        "experiment_id": candidate.experiment_id,
        "title": candidate.title,
        "hypothesis": candidate.hypothesis,
        "target_resource": candidate.target_resource,
        "mutation": candidate.mutation,
        "new_agent_config_content": candidate.new_agent_config_content,
        "created_at": candidate.created_at.isoformat(),
    }, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 5.5: Update `orchestrator.py` `run_experiment` to pass the new field when loading**

In `src/auto_cxas_scrapi/services/orchestrator.py`, inside `run_experiment`, update the
`ExperimentCandidate(...)` construction to include the new field:
```python
candidate = ExperimentCandidate(
    experiment_id=data["experiment_id"],
    title=data["title"],
    hypothesis=data["hypothesis"],
    target_resource=data["target_resource"],
    mutation=data["mutation"],
    new_agent_config_content=data.get("new_agent_config_content", ""),
)
```

- [ ] **Step 5.6: Run tests**

```
pytest tests/test_models.py tests/test_scrapi_adapter.py tests/test_scorer.py -v
```

Expected: all pass

- [ ] **Step 5.7: Commit**

```
git add src/auto_cxas_scrapi/core/models.py src/auto_cxas_scrapi/memory/store.py src/auto_cxas_scrapi/services/orchestrator.py tests/test_models.py
git commit -m "feat: add new_agent_config_content field to ExperimentCandidate and ExperimentStore"
```

---

## Task 6 — Trim `MultiObjectivePlanner` to utility module

Extract `EVAL_WEIGHTS`, `load_last_metrics`, `rank_eval_types` as module-level functions so
`LLMOptimizationPlanner` can import them. Remove `propose()`, `_build_candidate()`,
`_MUTATION_TEMPLATES`. Remove the 7 tests that called `propose()`.

**Files:**
- Modify: `src/auto_cxas_scrapi/planners/multi_objective_planner.py`
- Modify: `tests/test_multi_objective_planner.py`

- [ ] **Step 6.1: Replace `multi_objective_planner.py`**

Full replacement of `src/auto_cxas_scrapi/planners/multi_objective_planner.py`:

```python
"""Multi-objective eval dimension utilities.

Provides:
  EVAL_WEIGHTS        — ordered list of (eval_type, metric_key, weight)
  load_last_metrics() — read metrics dict from last_result.json
  rank_eval_types()   — sort eval dimensions by current score ascending (worst first)
  MultiObjectivePlanner — thin wrapper for score_summary() / top_priority_eval()
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Ordered by weight descending; used by LLMOptimizationPlanner and MultiObjectivePlanner.
EVAL_WEIGHTS: list[tuple[str, str, float]] = [
    # (eval_type,   metric_key_in_scorecard,  weight)
    ("simulation",  "task_success",            0.60),
    ("tool",        "tool_pass_rate",          0.25),
    ("turn",        "turn_pass_rate",          0.10),
    ("guardrail",   "guardrail_pass_rate",     0.03),
    ("callback",    "callback_pass_rate",      0.02),
]


def load_last_metrics(state_dir: Path) -> dict[str, float]:
    """Return the metrics dict from last_result.json, or {} if missing/unreadable."""
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
    """Return eval dimensions sorted by current score ascending (worst-performing first).

    Missing metric keys default to 0.0 (treated as worst-case).

    Returns list of (eval_type, metric_key, current_score).
    """
    w = weights or EVAL_WEIGHTS
    ranked = [
        (eval_type, metric_key, metrics.get(metric_key, 0.0))
        for eval_type, metric_key, _ in w
    ]
    return sorted(ranked, key=lambda x: x[2])


@dataclass
class MultiObjectiveCandidate:
    """Lightweight record for a multi-objective experiment proposal."""
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
    """Utility wrapper: read current eval scores and surface top-priority dimension.

    Note: propose() has been removed. Use LLMOptimizationPlanner for experiment
    proposal — it calls rank_eval_types() internally to target the weakest dimension.
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
        metrics = load_last_metrics(self.state_dir)
        ranked = rank_eval_types(metrics, self.eval_weights)
        return ranked[0][0] if ranked else "simulation"

    def score_summary(self) -> dict[str, float]:
        """Return {metric_key: current_score} for all 5 eval dimensions."""
        metrics = load_last_metrics(self.state_dir)
        return {
            metric_key: metrics.get(metric_key, 0.0)
            for _, metric_key, _ in self.eval_weights
        }
```

- [ ] **Step 6.2: Trim `tests/test_multi_objective_planner.py`**

Remove the 7 tests that called `planner.propose(...)`. Keep only the 2 tests that use
`top_priority_eval()` and `score_summary()`. Replace the full file:

```python
"""Tests for MultiObjectivePlanner utility functions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.planners.multi_objective_planner import MultiObjectivePlanner


@pytest.fixture()
def planner_with_metrics(tmp_path: Path) -> MultiObjectivePlanner:
    state = tmp_path / "state"
    state.mkdir()
    (state / "last_result.json").write_text(json.dumps({
        "metrics": {
            "task_success": 0.90,
            "tool_pass_rate": 0.40,
            "turn_pass_rate": 0.80,
            "guardrail_pass_rate": 0.95,
            "callback_pass_rate": 0.98,
        }
    }), encoding="utf-8")
    return MultiObjectivePlanner(state_dir=state)


def test_top_priority_eval(planner_with_metrics: MultiObjectivePlanner) -> None:
    top = planner_with_metrics.top_priority_eval()
    assert top == "tool"  # tool_pass_rate=0.40 is lowest


def test_score_summary_all_keys(planner_with_metrics: MultiObjectivePlanner) -> None:
    summary = planner_with_metrics.score_summary()
    expected_keys = {
        "task_success", "tool_pass_rate", "turn_pass_rate",
        "guardrail_pass_rate", "callback_pass_rate",
    }
    assert expected_keys == set(summary.keys())
    assert summary["tool_pass_rate"] == pytest.approx(0.40)
```

- [ ] **Step 6.3: Run the trimmed tests**

```
pytest tests/test_multi_objective_planner.py -v
```

Expected: 2 PASSED

- [ ] **Step 6.4: Run full test suite**

```
pytest tests/ -q
```

Expected: no new failures.

- [ ] **Step 6.5: Commit**

```
git add src/auto_cxas_scrapi/planners/multi_objective_planner.py tests/test_multi_objective_planner.py
git commit -m "refactor: extract rank_eval_types/load_last_metrics as module-level utilities; remove MultiObjectivePlanner.propose()"
```

---

## Task 7 — Implement `LLMOptimizationPlanner` (TDD)

This is the main new component. Write the tests first, then implement.

**Files:**
- Create: `tests/test_llm_planner.py`
- Replace: `src/auto_cxas_scrapi/planners/llm_planner.py`

- [ ] **Step 7.1: Create `tests/test_llm_planner.py` with 4 failing tests**

```python
"""Tests for LLMOptimizationPlanner."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.adapters.llm.base import LLMResponse
from auto_cxas_scrapi.planners.llm_planner import LLMOptimizationPlanner

_MINIMAL_AGENT_CONFIG = '''\
"""agent_config.py"""
from __future__ import annotations

SYSTEM_INSTRUCTION: str = """
You are a helpful assistant.
"""

TOOL_DESCRIPTIONS: dict = {}
ROUTING_RULES: dict = {"hours_inquiry": {"confidence_threshold": 0.70}}
GUARDRAIL_PARAMS: dict = {}
RESPONSE_TEMPLATES: dict = {}
FALLBACK_POLICY: dict = {}
'''

_LLM_JSON = json.dumps({
    "title": "Improve system instruction clarity",
    "hypothesis": "Adding step confirmation will improve task_success.",
    "target_eval": "simulation",
    "target_metric": "task_success",
    "mutation": {
        "type": "prompt_patch",
        "path": "SYSTEM_INSTRUCTION",
        "operation": "append",
        "value": "Always confirm before acting.",
        "rationale": "Reduces ambiguous routing",
    },
    "new_agent_config_content": _MINIMAL_AGENT_CONFIG + "\n# updated by llm\n",
})


def _mock_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete.return_value = LLMResponse(content=response, model="test-model")
    return llm


def test_propose_returns_candidate_with_new_content(tmp_path: Path) -> None:
    """propose() returns a candidate whose new_agent_config_content is non-empty on LLM success."""
    (tmp_path / "agent_config.py").write_text(_MINIMAL_AGENT_CONFIG)
    planner = LLMOptimizationPlanner(
        llm=_mock_llm(_LLM_JSON), repo_root=tmp_path, state_dir=tmp_path,
    )
    candidates = planner.propose(context={"app_name": "my-app", "project_id": "proj"})

    assert len(candidates) == 1
    c = candidates[0]
    assert c.title == "Improve system instruction clarity"
    assert "# updated by llm" in c.new_agent_config_content
    assert c.experiment_id.startswith("exp-")


def test_propose_fallback_when_llm_unavailable(tmp_path: Path) -> None:
    """propose() returns a non-empty fallback candidate when the LLM is unavailable."""
    (tmp_path / "agent_config.py").write_text(_MINIMAL_AGENT_CONFIG)
    llm = MagicMock()
    llm.is_available.return_value = False
    planner = LLMOptimizationPlanner(llm=llm, repo_root=tmp_path, state_dir=tmp_path)
    candidates = planner.propose(context={"app_name": "my-app", "project_id": "proj"})

    assert len(candidates) == 1
    assert candidates[0].new_agent_config_content != ""


def test_propose_fallback_on_invalid_json(tmp_path: Path) -> None:
    """propose() falls back to deterministic candidate when LLM returns non-JSON."""
    (tmp_path / "agent_config.py").write_text(_MINIMAL_AGENT_CONFIG)
    planner = LLMOptimizationPlanner(
        llm=_mock_llm("This is not JSON at all!"), repo_root=tmp_path, state_dir=tmp_path,
    )
    candidates = planner.propose(context={"app_name": "my-app", "project_id": "proj"})

    assert len(candidates) == 1
    assert candidates[0].new_agent_config_content != ""


def test_weakest_eval_injected_into_llm_prompt(tmp_path: Path) -> None:
    """The user prompt sent to the LLM contains the weakest eval dimension."""
    (tmp_path / "agent_config.py").write_text(_MINIMAL_AGENT_CONFIG)
    # tool_pass_rate=0.10 is the weakest
    (tmp_path / "last_result.json").write_text(json.dumps({
        "metrics": {
            "task_success": 0.90,
            "tool_pass_rate": 0.10,
            "turn_pass_rate": 0.80,
            "guardrail_pass_rate": 0.90,
            "callback_pass_rate": 0.95,
        }
    }))
    mock_llm = _mock_llm(_LLM_JSON)
    planner = LLMOptimizationPlanner(llm=mock_llm, repo_root=tmp_path, state_dir=tmp_path)
    planner.propose(context={"app_name": "my-app", "project_id": "proj"})

    call_args = mock_llm.complete.call_args
    user_prompt: str = call_args.kwargs.get("user") or call_args[1]["user"]
    assert "tool" in user_prompt
    assert "tool_pass_rate" in user_prompt
    assert "0.100" in user_prompt
```

- [ ] **Step 7.2: Run the 4 tests to confirm they all fail**

```
pytest tests/test_llm_planner.py -v
```

Expected: 4 FAILED (ImportError or AttributeError — `LLMOptimizationPlanner` doesn't exist yet)

- [ ] **Step 7.3: Replace `src/auto_cxas_scrapi/planners/llm_planner.py`**

```python
"""LLMOptimizationPlanner — unified planner: multi-objective targeting + LLM file rewrite.

Replaces both LLMExperimentPlanner and MultiObjectivePlanner.propose().
Flow per iteration:
  1. Read last_result.json → find weakest eval dimension.
  2. Read current agent_config.py + results.tsv history.
  3. Call LLM with directive to improve that dimension.
  4. LLM returns full new agent_config.py content.
  5. Caller writes content to disk, commits, evaluates.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from auto_cxas_scrapi.adapters.llm.base import LLMAdapter
from auto_cxas_scrapi.core.contracts import Planner
from auto_cxas_scrapi.core.models import ExperimentCandidate
from auto_cxas_scrapi.planners.multi_objective_planner import load_last_metrics, rank_eval_types

SYSTEM_PROMPT = """\
You are an expert Google Cloud CX Agent Studio optimization researcher.

eval_score = task_success * 0.60 + latency_score * 0.25 + reliability * 0.15

The 5 eval dimensions and weights:
  simulation   — task_success        (0.60)
  tool         — tool_pass_rate      (0.25)
  turn         — turn_pass_rate      (0.10)
  guardrail    — guardrail_pass_rate (0.03)
  callback     — callback_pass_rate  (0.02)

You will be told the weakest eval dimension. Your task:
1. Propose ONE targeted change to agent_config.py that will improve the weakest dimension.
2. Output the COMPLETE new content of agent_config.py incorporating only that change.

agent_config.py defines these top-level variables (evaluate.py reads them by exact name):
  SYSTEM_INSTRUCTION, TOOL_DESCRIPTIONS, ROUTING_RULES, GUARDRAIL_PARAMS,
  RESPONSE_TEMPLATES, FALLBACK_POLICY

Constraints:
  - Keep all top-level variable names intact.
  - Do not import external packages not already in the file.
  - ROUTING_RULES keys must exactly match golden test expected_intent values.
  - Make exactly ONE coherent, targeted change — do not rewrite everything.

Respond ONLY with valid JSON in this exact format:
{
  "title": "Short experiment title (<=60 chars)",
  "hypothesis": "What you expect to happen and why",
  "target_eval": "simulation|tool|turn|guardrail|callback",
  "target_metric": "the metric key being improved",
  "mutation": {
    "type": "prompt_patch|config_update|threshold_tune|template_change|guardrail_config_patch",
    "path": "VARIABLE_NAME or VARIABLE.key",
    "operation": "replace|append|prepend|adjust|extend",
    "value": "<new value or delta>",
    "rationale": "Why this specific change"
  },
  "new_agent_config_content": "<complete valid Python file content as a string>"
}
"""

_FALLBACK_CLARITY_RULE = (
    "Always confirm you understand the user's intent before responding."
)


class LLMOptimizationPlanner(Planner):
    """Proposes agent_config.py experiments targeting the weakest eval dimension."""

    def __init__(
        self,
        *,
        llm: LLMAdapter,
        repo_root: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.llm = llm
        self.repo_root = repo_root or Path.cwd()
        self.state_dir = state_dir or self.repo_root / ".auto-cxas" / "state"

    # ------------------------------------------------------------------
    # Public API (implements Planner contract)
    # ------------------------------------------------------------------

    def propose(self, *, context: dict) -> list[ExperimentCandidate]:
        """Return a list of one ExperimentCandidate with new_agent_config_content set."""
        target_eval, target_metric, current_score = self._find_weakest_eval()

        if not self.llm.is_available():
            return self._fallback_propose(context, target_eval)

        agent_config = self._read_agent_config()
        history = self._read_results_history()

        user_prompt = (
            f"Target eval dimension: {target_eval} — "
            f"metric: {target_metric} (current score: {current_score:.3f})\n\n"
            f"Current agent_config.py:\n```python\n{agent_config}\n```\n\n"
            f"Recent results history (results.tsv):\n```\n{history}\n```\n\n"
            f"App context: {json.dumps(context, indent=2)}\n\n"
            f"Propose ONE experiment targeting {target_eval} ({target_metric}) improvement. "
            f"Write the complete new agent_config.py."
        )

        try:
            response = self.llm.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=4096,
            )
            raw = response.content.strip()
            # Strip markdown code fences if the LLM wraps its JSON.
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif raw.startswith("```"):
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)
            new_content = data.get("new_agent_config_content", "")
            if not new_content.strip():
                print("[Planner] LLM returned empty new_agent_config_content — using fallback")
                return self._fallback_propose(context, target_eval)

            return [ExperimentCandidate(
                experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
                title=data["title"],
                hypothesis=data["hypothesis"],
                target_resource=data.get("target_eval", context.get("app_name", "")),
                mutation=data["mutation"],
                new_agent_config_content=new_content,
            )]
        except Exception as exc:
            print(f"[Planner] LLM proposal failed: {exc} — using fallback")
            return self._fallback_propose(context, target_eval)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_weakest_eval(self) -> tuple[str, str, float]:
        metrics = load_last_metrics(self.state_dir)
        ranked = rank_eval_types(metrics)
        return ranked[0] if ranked else ("simulation", "task_success", 0.0)

    def _read_agent_config(self) -> str:
        p = self.repo_root / "agent_config.py"
        return p.read_text("utf-8") if p.exists() else "# agent_config.py not found"

    def _read_results_history(self, max_rows: int = 10) -> str:
        p = self.repo_root / "results.tsv"
        if not p.exists():
            return "No results history yet."
        lines = p.read_text("utf-8").splitlines()
        header = lines[0] if lines else ""
        recent = lines[-max_rows:] if len(lines) > 1 else []
        return "\n".join([header] + recent)

    def _fallback_propose(
        self,
        context: dict,
        target_eval: str = "simulation",
    ) -> list[ExperimentCandidate]:
        current_content = self._read_agent_config()
        marker = 'SYSTEM_INSTRUCTION: str = """\n'
        if marker in current_content:
            new_content = current_content.replace(
                marker, f"{marker}{_FALLBACK_CLARITY_RULE}\n", 1
            )
        else:
            new_content = current_content
        return [ExperimentCandidate(
            experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
            title="Append intent-confirmation rule to SYSTEM_INSTRUCTION",
            hypothesis="Explicit intent confirmation reduces ambiguous routing.",
            target_resource=context.get("app_name", "unknown"),
            mutation={
                "type": "prompt_patch",
                "path": "SYSTEM_INSTRUCTION",
                "operation": "prepend",
                "value": _FALLBACK_CLARITY_RULE,
                "rationale": f"Fallback: standard clarity improvement targeting {target_eval}",
            },
            new_agent_config_content=new_content,
        )]
```

- [ ] **Step 7.4: Run the 4 tests to confirm they pass**

```
pytest tests/test_llm_planner.py -v
```

Expected: 4 PASSED

- [ ] **Step 7.5: Run full test suite**

```
pytest tests/ -q
```

Expected: all previously-passing tests still pass.

- [ ] **Step 7.6: Commit**

```
git add src/auto_cxas_scrapi/planners/llm_planner.py tests/test_llm_planner.py
git commit -m "feat: implement LLMOptimizationPlanner — merges multi-objective targeting with LLM file rewrite"
```

---

## Task 8 — Update `Orchestrator` to use `LLMOptimizationPlanner`

**Files:**
- Modify: `src/auto_cxas_scrapi/services/orchestrator.py`

- [ ] **Step 8.1: Update the import and planner construction**

In `src/auto_cxas_scrapi/services/orchestrator.py`:

Replace:
```python
from auto_cxas_scrapi.planners.llm_planner import LLMExperimentPlanner
```
With:
```python
from auto_cxas_scrapi.planners.llm_planner import LLMOptimizationPlanner
```

Replace:
```python
self.planner = LLMExperimentPlanner(llm=self.llm)
```
With:
```python
self.planner = LLMOptimizationPlanner(
    llm=self.llm,
    state_dir=settings.state_dir,
)
```

- [ ] **Step 8.2: Run tests**

```
pytest tests/ -q
```

Expected: all pass; no import errors.

- [ ] **Step 8.3: Commit**

```
git add src/auto_cxas_scrapi/services/orchestrator.py
git commit -m "fix: wire LLMOptimizationPlanner into orchestrator; pass state_dir"
```

---

## Task 9 — Simplify `LiveExperimentRunner`

Remove `_apply_mutation` (the planner now writes `agent_config.py` before this runs).
Add a guard for missing `agent_config.py`.

**Files:**
- Modify: `src/auto_cxas_scrapi/runners/live_run.py`

- [ ] **Step 9.1: Replace `live_run.py`**

```python
"""Live experiment runner — runs real CXAS evals against the already-mutated agent_config.py."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

from auto_cxas_scrapi.adapters.scrapi import ScrapiAdapter
from auto_cxas_scrapi.core.contracts import Runner
from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentResult, ExperimentStatus


class LiveExperimentRunner(Runner):
    def __init__(
        self,
        *,
        scrapi: ScrapiAdapter,
        repo_root: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.scrapi = scrapi
        self.repo_root = repo_root or Path.cwd()
        self.state_dir = state_dir or self.repo_root / ".auto-cxas" / "state"

    def run(self, candidate: ExperimentCandidate) -> ExperimentResult:
        started = datetime.now(UTC)
        config_path = self.repo_root / "agent_config.py"

        if not config_path.exists():
            return ExperimentResult(
                experiment_id=candidate.experiment_id,
                status=ExperimentStatus.failed,
                artifacts={"error": "agent_config.py not found"},
                started_at=started,
                finished_at=datetime.now(UTC),
            )

        result_path = self.state_dir / "last_result.json"
        cmd = [sys.executable, str(self.repo_root / "evaluate.py"), "--output-json"]
        try:
            subprocess.run(
                cmd, cwd=self.repo_root, capture_output=True, text=True, timeout=180,
            )
            artifacts: dict = {}
            if result_path.exists():
                artifacts = json.loads(result_path.read_text("utf-8"))
            status = (
                ExperimentStatus.passed
                if not artifacts.get("error")
                else ExperimentStatus.failed
            )
        except subprocess.TimeoutExpired:
            artifacts = {"error": "evaluate.py timed out"}
            status = ExperimentStatus.failed

        return ExperimentResult(
            experiment_id=candidate.experiment_id,
            status=status,
            artifacts=artifacts,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
```

- [ ] **Step 9.2: Run tests**

```
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 9.3: Commit**

```
git add src/auto_cxas_scrapi/runners/live_run.py
git commit -m "refactor: remove _apply_mutation from LiveExperimentRunner; planner writes agent_config.py"
```

---

## Task 10 — Fix `auto_loop.py` — write mutation before commit

This is the critical missing step: the planner proposes a new `agent_config.py` content but
it was never written to disk before the git commit.

**Files:**
- Modify: `auto_loop.py`

- [ ] **Step 10.1: Add the write step in `run_loop`**

In `auto_loop.py`, find the block:

```python
        # --- Commit mutation ---
        committed = _git_commit_agent_config(candidate.title)
```

Insert immediately before it:

```python
        # --- Write mutation to agent_config.py ---
        if candidate.new_agent_config_content:
            Path("agent_config.py").write_text(
                candidate.new_agent_config_content, encoding="utf-8"
            )
            console.print("[dim]Wrote new agent_config.py from planner.[/dim]")
```

The result should look like:

```python
        # --- Write mutation to agent_config.py ---
        if candidate.new_agent_config_content:
            Path("agent_config.py").write_text(
                candidate.new_agent_config_content, encoding="utf-8"
            )
            console.print("[dim]Wrote new agent_config.py from planner.[/dim]")

        # --- Commit mutation ---
        committed = _git_commit_agent_config(candidate.title)
```

- [ ] **Step 10.2: Verify `Path` is already imported at top of `auto_loop.py`**

Check line 10: `from pathlib import Path` — it is already there. No import change needed.

- [ ] **Step 10.3: Run a dry-run of the loop to confirm it works end-to-end**

```
python auto_loop.py --dry-run --max-experiments 1
```

Expected output includes:
- `Wrote new agent_config.py from planner.`
- `Running evaluate.py...`
- Either `KEEP` or `DISCARD` with a score

If you see `[yellow]No LLM available[/yellow]` that is fine — it means the fallback ran and still
wrote the file (the fallback always sets `new_agent_config_content`).

- [ ] **Step 10.4: Commit**

```
git add auto_loop.py
git commit -m "fix: write candidate.new_agent_config_content to agent_config.py before git commit"
```

---

## Task 11 — Fix `rollback` CLI command

Currently `rollback` only prints instructions. It should execute `git reset --hard HEAD~1`.

**Files:**
- Modify: `src/auto_cxas_scrapi/cli/main.py`

- [ ] **Step 11.1: Add `import subprocess` to `cli/main.py`**

The current imports are:
```python
import json
import sys
```

Add `import subprocess` after `import json`:
```python
import json
import subprocess
import sys
```

- [ ] **Step 11.2: Replace the `rollback` command**

Replace:
```python
@app.command()
def rollback(
    experiment_id: str = typer.Argument(..., help="Experiment ID to roll back"),
) -> None:
    """Revert an experiment by restoring the pre-experiment baseline."""
    console.print(f"[yellow]Rolling back {experiment_id}...[/yellow]")
    console.print("Run: git reset --hard HEAD~1  (or to the specific pre-experiment commit)")
```

With:
```python
@app.command()
def rollback(
    experiment_id: str = typer.Argument(..., help="Experiment ID to roll back"),
) -> None:
    """Revert the last commit to undo an experiment (git reset --hard HEAD~1)."""
    console.print(f"[yellow]Rolling back {experiment_id}...[/yellow]")
    try:
        result = subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            capture_output=True,
            text=True,
            check=True,
        )
        console.print(f"[green]Rolled back successfully.[/green]")
        if result.stdout.strip():
            console.print(f"[dim]{result.stdout.strip()}[/dim]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]git reset failed: {exc.stderr.strip()}[/red]")
        raise typer.Exit(1)
```

- [ ] **Step 11.3: Run tests**

```
pytest tests/ -q
```

Expected: all pass (no tests directly test rollback behavior).

- [ ] **Step 11.4: Commit**

```
git add src/auto_cxas_scrapi/cli/main.py
git commit -m "fix: rollback CLI command now executes git reset --hard HEAD~1"
```

---

## Task 12 — Final verification

- [ ] **Step 12.1: Run the complete test suite**

```
pytest tests/ -v
```

Expected: **48 PASSED, 0 FAILED** (or more if new tests were added).

- [ ] **Step 12.2: Run a full dry-run loop for 3 experiments**

```
python auto_loop.py --dry-run --max-experiments 3 --sleep 0
```

Expected: 3 iterations complete, each printing "Wrote new agent_config.py from planner."

- [ ] **Step 12.3: Check `auto-cxas init` still works**

```
python -m auto_cxas_scrapi init
```

or:

```
auto-cxas init
```

Expected: prints project/app/llm/mode summary without errors.

- [ ] **Step 12.4: Final commit if any cleanup needed**

```
git add -p   # review any remaining changes
git commit -m "chore: final cleanup and verification"
```
