# Adapters

Adapters are thin wrappers that translate between `auto-cxas-scrapi`'s
internal models and the `cxas-scrapi` / CXAS REST API. All live in
`src/auto_cxas_scrapi/adapters/`.

---

## CXASEvalsAdapter

**File:** `adapters/cxas_evals.py`

Orchestrates all 5 eval types with tenacity retry (3 attempts, exponential
backoff) on every call.

### Methods

| Method | Returns | Description |
|---|---|---|
| `run_simulation_evals(cases)` | `list[dict]` | SimulationEvals.run_simulations() |
| `run_turn_evals(cases)` | `pd.DataFrame` | TurnEvals.run_turn_tests() |
| `run_tool_evals(cases)` | `pd.DataFrame` | ToolEvals.run_tool_tests() |
| `run_guardrail_evals(df)` | `pd.DataFrame` | GuardrailEvals.run_guardrail_tests() |
| `run_callback_evals(app_dir)` | `pd.DataFrame` | CallbackEvals.test_all_callbacks_in_app_dir() |

### Retry policy

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def run_simulation_evals(self, cases): ...
```

All 5 runners are wrapped identically. After 3 failures the exception
propagates; `auto_loop.py` records it as an error row in `results.tsv`.

---

## CXASVersionsAdapter

**File:** `adapters/cxas_versions.py`

Wraps the `ces.googleapis.com/v1alpha1` Versions + Deployments REST API.
Useful for creating immutable snapshots before experiments and rolling back
if convergence isn't reached.

### Methods

| Method | HTTP | Description |
|---|---|---|
| `list_versions()` | `GET /versions` | All versions for the app |
| `create_version(display_name)` | `POST /versions` | Create immutable snapshot |
| `get_version(version_id)` | `GET /versions/{id}` | Single version detail |
| `delete_version(version_id)` | `DELETE /versions/{id}` | Delete non-deployed version |
| `list_deployments()` | `GET /deployments` | All deployments across environments |
| `deploy_version(version_id, traffic_pct)` | `PATCH /deployments` | Route traffic to version |
| `get_active_version()` | derived | Version receiving 100% live traffic |
| `is_available()` | — | Auth check (returns bool) |

### Usage

```python
from auto_cxas_scrapi.adapters.cxas_versions import CXASVersionsAdapter

adapter = CXASVersionsAdapter(app_name="projects/p/locations/us/apps/a")

# Snapshot before a risky experiment run
version = adapter.create_version(display_name="pre-experiment-2026-05-08")

# Roll back to that snapshot if needed
adapter.deploy_version(version["name"].split("/")[-1], traffic_pct=100)
```

---

## CXASVariablesAdapter

**File:** `adapters/cxas_variables.py`

Syncs `STATIC_VARIABLES` (`{{var}}` zero-history blocks) and `VARIABLES`
(`{var}` session-state slots) from `agent_config.py` to the live CXAS app
after each kept experiment.

### Methods

| Method | Description |
|---|---|
| `sync_static_variables(variables_dict)` | Upserts all `{{var}}` keys in the CXAS app |
| `sync_session_variables(variables_dict)` | Upserts all `{var}` session-scoped keys |
| `get_current_variables()` | Returns current live variables as a dict |

---

## CXASCallbackAdapter

**File:** `adapters/cxas_callbacks.py`

Registers and manages the 5 CXAS agent lifecycle hooks. Hooks can implement
deterministic intent bypass (reducing LLM calls for known intents) or
short-circuit tool caching.

### Hook types

| Hook | Fires | Common use |
|---|---|---|
| `before_model_callback` | Before LLM inference | Deterministic intent bypass |
| `after_model_callback` | After LLM response | Response normalization |
| `before_tool_callback` | Before tool execution | Cache lookup |
| `after_tool_callback` | After tool execution | Cache store |
| `after_agent_callback` | After full agent turn | Logging, audit |

### Methods

| Method | Description |
|---|---|
| `register_callback(agent_name, hook_type, code)` | Deploy Python callback code to CXAS |
| `list_callbacks(agent_name)` | Get all callbacks for an agent |
| `delete_callback(agent_name, hook_type)` | Remove a callback |

---

## ScrapiAdapter

**File:** `adapters/scrapi.py`

Low-level wrapper around `cxas-scrapi` core clients (`Apps`, `Agents`,
`Sessions`, etc.). Provides a single authenticated client pool reused across
all adapters, avoiding redundant credential lookups.

### Usage

```python
from auto_cxas_scrapi.adapters.scrapi import ScrapiAdapter

client = ScrapiAdapter(app_name="projects/p/locations/us/apps/a")
agent = client.get_agent("my-agent")
```

---

## Error handling

All adapters follow the same error contract:

1. Individual method failures are logged at `WARNING` level
2. Return empty dict `{}` or empty `pd.DataFrame` on non-critical failures
3. Re-raise after tenacity exhaustion (3 attempts) for critical eval calls
4. `auto_loop.py` catches re-raised exceptions and records an error row in `results.tsv`

This means a single flaky API call never crashes the loop — the experiment
is marked as errored and the next iteration starts.
