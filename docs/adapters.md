# Adapters

All adapters live in `src/auto_cxas_scrapi/adapters/`.

---

## CXASEvalsAdapter

**File:** `adapters/cxas_evals.py`

Orchestrates all 5 eval types with tenacity retry (3 attempts, exponential backoff).

| Method | Returns | Description |
|---|---|---|
| `run_simulation_evals(cases)` | `list[dict]` | SimulationEvals.run_simulations() |
| `run_turn_evals(cases)` | `pd.DataFrame` | TurnEvals.run_turn_tests() |
| `run_tool_evals(cases)` | `pd.DataFrame` | ToolEvals.run_tool_tests() |
| `run_guardrail_evals(df)` | `pd.DataFrame` | GuardrailEvals.run_guardrail_tests() |
| `run_callback_evals(app_dir)` | `pd.DataFrame` | CallbackEvals.test_all_callbacks_in_app_dir() |

**Retry policy:** `stop_after_attempt(3)` + `wait_exponential(min=2, max=30)`. After 3 failures the exception propagates and auto_loop.py records an error row.

---

## CXASVersionsAdapter

**File:** `adapters/cxas_versions.py`

Wraps the `ces.googleapis.com/v1alpha1` Versions + Deployments REST API.

| Method | HTTP | Description |
|---|---|---|
| `list_versions()` | GET /versions | All versions for the app |
| `create_version(display_name)` | POST /versions | Create immutable snapshot |
| `get_version(version_id)` | GET /versions/{id} | Single version detail |
| `delete_version(version_id)` | DELETE /versions/{id} | Delete non-deployed version |
| `list_deployments()` | GET /deployments | All deployments |
| `deploy_version(version_id, traffic_pct)` | PATCH /deployments | Route traffic |
| `get_active_version()` | derived | Version at 100% live traffic |
| `is_available()` | — | Auth check |

```python
adapter = CXASVersionsAdapter(app_name="projects/p/locations/us/apps/a")
version = adapter.create_version(display_name="pre-experiment-2026-05-08")
# roll back if needed
adapter.deploy_version(version["name"].split("/")[-1], traffic_pct=100)
```

---

## CXASVariablesAdapter

**File:** `adapters/cxas_variables.py`

Syncs `STATIC_VARIABLES` and `VARIABLES` from `agent_config.py` to the live CXAS app after each kept experiment.

| Method | Description |
|---|---|
| `sync_static_variables(variables_dict)` | Upserts all `{{var}}` keys |
| `sync_session_variables(variables_dict)` | Upserts all `{var}` session-scoped keys |
| `get_current_variables()` | Returns current live variables |

---

## CXASCallbackAdapter

**File:** `adapters/cxas_callbacks.py`

Registers and manages the 5 CXAS agent lifecycle hooks.

| Hook | Fires | Common use |
|---|---|---|
| `before_model_callback` | Before LLM inference | Deterministic intent bypass |
| `after_model_callback` | After LLM response | Response normalization |
| `before_tool_callback` | Before tool execution | Cache lookup |
| `after_tool_callback` | After tool execution | Cache store |
| `after_agent_callback` | After full agent turn | Logging, audit |

| Method | Description |
|---|---|
| `register_callback(agent_name, hook_type, code)` | Deploy Python callback |
| `list_callbacks(agent_name)` | Get all callbacks for an agent |
| `delete_callback(agent_name, hook_type)` | Remove a callback |

---

## Error handling contract

1. Individual failures logged at WARNING level
2. Return empty `{}` or empty `pd.DataFrame` on non-critical failures
3. Re-raise after tenacity exhaustion for critical eval calls
4. `auto_loop.py` catches re-raised exceptions and records an error row in `results.tsv`

A single flaky API call never crashes the loop.
