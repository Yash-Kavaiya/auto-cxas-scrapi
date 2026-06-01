# program.md — Experiment Strategy for auto-cxas-scrapi

## Goal

Maximize `eval_score` for the CX Agent Studio app configured in `.env`.

```
eval_score = task_success * 0.60 + latency_score * 0.25 + reliability_score * 0.15
```

where:
- `task_success` = fraction of golden tests that pass intent + response checks
- `latency_score` = `max(0, 1 - p95_latency_ms / 5000)`
- `reliability_score` = `max(0, 1 - tool_error_rate)`

## Setup

Run these steps once in your Cloud Shell terminal before starting the loop:

```bash
# 1. Install the package (makes `auto-cxas` CLI available)
pip install -e ".[anthropic]"

# 2. Run the setup script (handles gcloud config, skips ADC on Cloud Shell)
chmod +x ./scripts/setup_gcloud.sh && ./scripts/setup_gcloud.sh

# 3. Copy and fill in your environment
cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT, AUTO_CXAS_APP_NAME, ANTHROPIC_API_KEY

# 4. Verify the harness works
python evaluate.py --dry-run

# 5. Verify the CLI
auto-cxas init

# 6. Test the loop without live CXAS calls
auto-cxas daemon --dry-run --max-experiments 3
```

> **Cloud Shell note:** Cloud Shell on GCE uses VM service account credentials automatically —
> `gcloud auth application-default login` is neither needed nor allowed. The setup script
> detects Cloud Shell and skips that step.

## Loop Protocol

For each experiment iteration:

1. Read `results.tsv` to understand what has already been tried.
2. Read current `agent_config.py`.
3. Propose ONE targeted mutation to `agent_config.py` with a clear hypothesis.
4. Apply the mutation and commit: `git add agent_config.py && git commit -m "exp: <description>"`
5. Run `python evaluate.py --output-json` (add `--dry-run` for local testing).
6. Compare `eval_score` to the baseline in `.auto-cxas/state/baseline.json`.
7. If improved: keep the commit, append a `keep` row to `results.tsv`.
8. If not improved: `git reset --hard HEAD~1`, append a `discard` row to `results.tsv`.
9. Repeat from step 1.

## What to Experiment With (in `agent_config.py`)

| Variable | Experiment Type | Expected Impact |
|---|---|---|
| `SYSTEM_INSTRUCTION` | Prompt wording, clarity rules, persona tone | task_success |
| `ROUTING_RULES[intent].confidence_threshold` | Threshold tuning per intent | task_success, error_rate |
| `ROUTING_RULES[intent].priority` | Priority ordering for overlapping intents | task_success |
| `GUARDRAIL_PARAMS` | Sensitivity adjustments | reliability_score |
| `RESPONSE_TEMPLATES` | Response clarity and keyword coverage | task_success |
| `TOOL_DESCRIPTIONS` | Clearer descriptions for model tool routing | task_success |
| `FALLBACK_POLICY` | Fewer turns before escalation | task_success, latency |

## Evaluation Dimensions (5 eval types)

The `LLMOptimizationPlanner` reads `.auto-cxas/state/last_result.json` and targets
the *weakest* of these five dimensions each iteration:

| Key in `metrics` | Eval Type | Measured by |
|---|---|---|
| `task_success` | SimulationEvals — multi-turn goal completion | `evaluate.py` |
| `tool_pass_rate` | ToolEvals — tool call correctness | `evaluate.py` (live) |
| `turn_pass_rate` | TurnEvals — single-turn response quality | `evaluate.py` (live) |
| `guardrail_pass_rate` | GuardrailEvals — safety / topic blocking | `evaluate.py` (live) |
| `callback_pass_rate` | CallbackEvals — webhook / callback validation | `evaluate.py` (live) |

In `--dry-run` mode all five proxy from `task_success`. In live mode, extend
`evaluate.py`'s `main()` to call the other four eval types for full coverage.

## The Feedback Arrow — failures become new test cases

The eval loop only compounds if failures feed back into the benchmark. Without
this, the loop optimizes against a static set and plateaus once it saturates.
This is implemented by the `auto_cxas_scrapi.feedback` package and runs
automatically inside `auto_loop.py` every `AUTO_CXAS_FEEDBACK_INGEST_EVERY`
experiments (default 10).

Each feedback cycle:

1. **Harvest production failures** — `FeedbackIngestor` pulls recent CX Agent
   Studio conversations via `ScrapiAdapter.list_recent_conversations()` and keeps
   only failures (thumbs-down, rating `< 3`, escalation, or no-match).
2. **Stage as candidates** — new failing utterances are written to
   `golden_candidates.yaml` (same schema as `golden_tests.yaml` plus tracking
   counters), de-duped against both the candidate pool and the golden set.
3. **Re-grade candidates** — `BenchmarkManager.record_run()` grades every staged
   candidate against the *current* agent using the exact same grading logic as
   the official eval (`evaluate.grade_tests`), without polluting the official
   score. Reproductions increment `seen_failures`.
4. **Auto-promote** — once a candidate has reproduced as a failure
   `AUTO_CXAS_CANDIDATE_PROMOTE_THRESHOLD` times (default 2), it is moved into
   `golden_tests.yaml` and the benchmark grows.

Separately, `evaluate.py` now persists per-test failures (`failed_tests` in
`last_result.json`). The `LLMOptimizationPlanner` reads these and injects the
concrete failing utterances into its prompt — the "fix what failed" signal —
so mutations target real failures instead of guessing.

**Settings** (in `.env`):

| Var | Default | Meaning |
|---|---|---|
| `AUTO_CXAS_FEEDBACK_INGEST_EVERY` | 10 | Run a feedback cycle every N experiments (0 disables). |
| `AUTO_CXAS_CANDIDATE_PROMOTE_THRESHOLD` | 2 | Reproductions required before promotion. |
| `AUTO_CXAS_FEEDBACK_LOOKBACK_HOURS` | 24 | Conversation-history lookback window. |
| `AUTO_CXAS_FEEDBACK_MAX_CONVERSATIONS` | 200 | Cap on conversations fetched per cycle. |

> `golden_candidates.yaml` is generated and safe to delete; `golden_tests.yaml`
> is the official benchmark — promoted cases are appended to it automatically.

## Results TSV Format

```
commit  eval_score  task_success  latency_ms_p95  tool_error_rate  status  description
```

- `status`: `keep` | `discard` | `crashed` | `baseline`
- Append one row per experiment run, regardless of outcome.

## Safety Rules

- **NEVER modify `evaluate.py`** — it is the fixed ground truth for the optimization agent.
- Only the autonomous loop commits changes to `agent_config.py`.
- Do not install additional packages inside the loop.
- Always run `evaluate.py --output-json` after committing, before deciding keep/discard.
- Baseline is stored in `.auto-cxas/state/baseline.json` — do not edit manually.

## Claude Code Quick Start

```bash
claude --context AGENTS.md \
  --prompt "Read program.md, check the baseline, and start the experiment loop."
```

## Gemini CLI Quick Start

```bash
gemini run --context GEMINI.md \
  --prompt "Read program.md and begin optimizing agent_config.py."
```

## GitHub Copilot Quick Start

Open this repo in VS Code with Copilot enabled.
In Copilot Chat: *"@workspace Read program.md and AGENTS.md, then propose an experiment."*
