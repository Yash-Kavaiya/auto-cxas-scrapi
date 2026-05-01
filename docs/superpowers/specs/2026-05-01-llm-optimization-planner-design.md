# Design: LLMOptimizationPlanner + Bug Fixes
_Date: 2026-05-01_

## Goal

Fix all 11 failing tests, close the mutation-application gap (mutations are proposed but never written
to `agent_config.py`), wire `MultiObjectivePlanner` as the primary loop driver, and merge the two
broken/orphaned planners into one cohesive `LLMOptimizationPlanner` — autoresearch-style.

---

## Problems Being Solved

| # | Problem | Impact |
|---|---------|--------|
| 1 | `auto_loop.py` proposes mutations but never writes them to `agent_config.py` before committing | Loop runs but never actually changes anything |
| 2 | `LiveExperimentRunner._apply_mutation` only handles one of many mutation types | Mutations silently no-op |
| 3 | Adapters use lazy `from cxas_scrapi import X` inside methods; tests can't `patch()` them | 11 test failures |
| 4 | `MultiObjectivePlanner` fully implemented but never wired into the loop | Weakest-eval targeting goes unused |
| 5 | `test_scorer.py::test_typical_score_range` asserts `"rationale" in sc.rationale` — string never contains the word "rationale" | Test always fails |
| 6 | `AnthropicAdapter.DEFAULT_MODEL` is `claude-3-5-sonnet-20241022` (stale) | Uses outdated model |
| 7 | `auto-cxas rollback` only prints instructions; does not execute git reset | Rollback is a no-op |

---

## Architecture

### Data Flow (post-change)

```
auto_loop.py  run_loop()
  │
  ├─ orch.propose(context)
  │    └─ LLMOptimizationPlanner.propose(context)
  │         ├─ _find_weakest_eval(last_result.json)   ← from MultiObjectivePlanner logic
  │         ├─ _read_agent_config()                   ← current agent_config.py text
  │         ├─ _read_results_history()                ← last 10 rows of results.tsv
  │         └─ llm.complete(system, user)
  │              └─ returns JSON:
  │                   title, hypothesis, target_eval,
  │                   target_metric, mutation (spec),
  │                   new_agent_config_content         ← FULL new file text
  │
  ├─ Path("agent_config.py").write_text(candidate.new_agent_config_content)   ← NEW
  ├─ _git_commit_agent_config(candidate.title)
  ├─ _run_evaluate(dry_run)
  └─ keep (update baseline) / discard (_git_reset_last_commit)
```

### Component Map

```
src/auto_cxas_scrapi/
  planners/
    llm_planner.py          ← becomes LLMOptimizationPlanner (replaces both old planners)
    multi_objective_planner.py  ← kept as pure utility: EvalWeights + _rank_eval_types()
                                   MultiObjectivePlanner.propose() retired
  adapters/
    cxas_evals.py           ← add module-level try/except imports
    scrapi.py               ← add module-level try/except imports
    llm/anthropic.py        ← update DEFAULT_MODEL
  services/
    orchestrator.py         ← swap to LLMOptimizationPlanner
  cli/
    main.py                 ← fix rollback command
  runners/
    live_run.py             ← _apply_mutation retired; runner reads agent_config.py
                               as already written by the planner
auto_loop.py                ← add write step between propose and commit
tests/
  test_scorer.py            ← fix wrong assertion
```

---

## Detailed Component Design

### 1. `LLMOptimizationPlanner` (`planners/llm_planner.py`)

Replaces `LLMExperimentPlanner`. Constructor: `(llm, repo_root, state_dir)`.

**System prompt additions over the old planner:**
- Instructs the LLM to identify the weakest eval dimension (injected as `target_eval` / `target_metric`
  from the pre-computed ranking).
- Requires the LLM to output `new_agent_config_content` — the complete, valid Python text for
  `agent_config.py` — alongside the structured mutation spec.

**LLM output schema (JSON):**
```json
{
  "title": "...",
  "hypothesis": "...",
  "target_eval": "simulation|tool|turn|guardrail|callback",
  "target_metric": "task_success|tool_pass_rate|...",
  "mutation": {
    "type": "...",
    "path": "...",
    "operation": "...",
    "value": "...",
    "rationale": "..."
  },
  "new_agent_config_content": "# full Python file text..."
}
```

**Fallback:** If the LLM is unavailable or JSON parse fails, generate a deterministic fallback
that appends a clarity rule to `SYSTEM_INSTRUCTION` (same as current fallback). The fallback
also produces `new_agent_config_content` by string-patching the current file.

**`ExperimentCandidate` extension:** Add `new_agent_config_content: str = ""` field so the content
travels with the candidate through the store and loop.

### 2. `MultiObjectivePlanner` (utility-only)

Retain the `EvalWeights`, `_rank_eval_types()`, and `score_summary()` functions as a pure utility.
Remove the `propose()` method (its logic moves into `LLMOptimizationPlanner`).
`MultiObjectiveCandidate` dataclass can stay for future use.

### 3. `auto_loop.py` — write step

Between `orch.propose()` and `_git_commit_agent_config()`, add:
```python
if candidate.new_agent_config_content:
    Path("agent_config.py").write_text(candidate.new_agent_config_content, "utf-8")
```

This is the only change to `auto_loop.py`'s main loop body.

### 4. Adapter module-level imports (patchability fix)

Pattern applied to `cxas_evals.py` and `scrapi.py`:
```python
try:
    from cxas_scrapi import SimulationEvals, ToolEvals, GuardrailEvals, TurnEvals, CallbackEvals
except ImportError:
    SimulationEvals = ToolEvals = GuardrailEvals = TurnEvals = CallbackEvals = None  # type: ignore
```

Each method body currently has a lazy `from cxas_scrapi import X` import — remove those, since
the name is now available at module scope. Keep `is_available()` as the guard for external callers
and for the early-return check at the top of each method (it already tests the same condition).
`patch("auto_cxas_scrapi.adapters.cxas_evals.SimulationEvals", ...)` now works because the name
exists at module level.

### 5. `LiveExperimentRunner._apply_mutation` — retire

Since the planner now writes `agent_config.py` before the runner is called, `_apply_mutation` is
no longer needed. Replace it with a simple existence check: if `agent_config.py` doesn't exist,
return a `failed` result. Remove the partial string-patching logic entirely.

### 6. `AnthropicAdapter` model update

Change `DEFAULT_MODEL = "claude-3-5-sonnet-20241022"` → `DEFAULT_MODEL = "claude-sonnet-4-6"`.

### 7. `rollback` CLI command

Replace the print-only implementation with:
```python
subprocess.run(["git", "reset", "--hard", "HEAD~1"], check=True)
```
Add error handling for the case where HEAD has no parent.

### 8. `test_scorer.py` assertion fix

```python
# Before (wrong):
assert "rationale" in sc.rationale

# After (correct):
assert "score" in sc.rationale
assert "task_success" in sc.rationale  # or any string actually in the rationale
```

---

## Data Model Changes

`ExperimentCandidate` gains one optional field:

```python
@dataclass(slots=True)
class ExperimentCandidate:
    experiment_id: str
    title: str
    hypothesis: str
    target_resource: str
    mutation: dict[str, Any]
    new_agent_config_content: str = ""          # ← new
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

`ExperimentStore.save_candidate` serialises the new field. `load_candidate` deserialises it.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| LLM returns malformed JSON | Fall back to deterministic mutation; log warning |
| LLM omits `new_agent_config_content` | Fall back; do not write empty string to `agent_config.py` |
| `agent_config.py` write fails (permissions) | Raise; loop catches and logs, continues to next iteration |
| git commit of identical file (no diff) | Existing "Nothing to commit" guard handles this |

---

## Test Plan

- All 11 currently-failing tests pass after adapter module-level import fix + scorer assertion fix.
- New unit tests for `LLMOptimizationPlanner`:
  - `test_propose_calls_llm_and_returns_candidate_with_content`
  - `test_propose_fallback_when_llm_unavailable`
  - `test_propose_fallback_on_json_parse_error`
  - `test_weakest_eval_injected_into_prompt` (assert the prompt string contains the target eval)
- Existing `test_multi_objective_planner.py` tests that exercise `propose()` are removed or adapted
  to test the utility functions only.
- `test_auto_loop_writes_agent_config` — stretch/integration test: since `auto_loop.py` is a
  script, this requires patching `orch.propose` and asserting the write; implement only if time
  permits after all unit tests pass.

---

## Files Changed Summary

| File | Change type |
|------|-------------|
| `src/.../planners/llm_planner.py` | Replace — new `LLMOptimizationPlanner` |
| `src/.../planners/multi_objective_planner.py` | Trim — remove `propose()`, keep utility |
| `src/.../core/models.py` | Extend — add `new_agent_config_content` field |
| `src/.../adapters/cxas_evals.py` | Fix — module-level imports |
| `src/.../adapters/scrapi.py` | Fix — module-level imports |
| `src/.../adapters/llm/anthropic.py` | Fix — model name |
| `src/.../services/orchestrator.py` | Fix — import new planner |
| `src/.../runners/live_run.py` | Simplify — remove `_apply_mutation` |
| `src/.../cli/main.py` | Fix — rollback command |
| `auto_loop.py` | Fix — add write step |
| `tests/test_scorer.py` | Fix — wrong assertion |
| `tests/test_llm_planner.py` | New — 4 tests for `LLMOptimizationPlanner` |
| `tests/test_multi_objective_planner.py` | Trim — remove tests that called `propose()` |
