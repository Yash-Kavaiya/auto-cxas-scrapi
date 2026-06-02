# program.md — Experiment Strategy for auto-cxas-scrapi

## Goal

Maximize `eval_score` for the CX Agent Studio app configured in `.env`.

```
eval_score = task_success * 0.35
           + turn_pass_rate * 0.20
           + tool_pass_rate * 0.20
           + latency_score  * 0.15
           + guardrail_pass_rate * 0.07
           + callback_pass_rate  * 0.03
```

where:
- `task_success`       = fraction of golden tests passing SimulationEvals
- `turn_pass_rate`     = fraction of golden tests passing TurnEvals
- `tool_pass_rate`     = fraction of tool-mapped tests passing ToolEvals
- `latency_score`      = `max(0, 1 - p95_latency_ms / 5000)`
- `guardrail_pass_rate`= fraction of guardrail tests passing GuardrailEvals
- `callback_pass_rate` = fraction of callback-mapped tests passing CallbackEvals

## Setup

```bash
pip install -e ".[anthropic]"
chmod +x ./scripts/setup_gcloud.sh && ./scripts/setup_gcloud.sh
cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT, AUTO_CXAS_APP_NAME, ANTHROPIC_API_KEY
python evaluate.py --dry-run
auto-cxas init
auto-cxas daemon --dry-run --max-experiments 3
```

## Loop Protocol

1. Read `results.tsv` to understand what has already been tried.
2. Read current `agent_config.py`.
3. Propose ONE targeted mutation with a clear hypothesis.
4. Apply and commit: `git add agent_config.py && git commit -m "exp: <description>"`
5. Run `python evaluate.py --output-json`.
6. Compare `eval_score` to baseline in `.auto-cxas/state/baseline.json`.
7. If improved: keep the commit, append `keep` row to `results.tsv`.
8. If not improved: `git reset --soft HEAD~1 && git checkout -- agent_config.py`, append `discard` row.
9. Repeat.

## What to Experiment With (in `agent_config.py`)

| Variable | Experiment Type | Expected Impact |
|---|---|---|
| `SYSTEM_INSTRUCTION` | Prompt wording, clarity rules, persona tone | task_success, turn_pass_rate |
| `STATIC_VARIABLES` | Content of `{{var}}` blocks injected into prompt | task_success |
| `ROUTING_RULES[intent].confidence_threshold` | Threshold tuning | task_success, tool_pass_rate |
| `ROUTING_RULES[intent].priority` | Priority ordering | task_success |
| `GUARDRAIL_PARAMS` | Sensitivity adjustments | guardrail_pass_rate |
| `RESPONSE_TEMPLATES` | Response clarity and keyword coverage | task_success, turn_pass_rate |
| `TOOL_DESCRIPTIONS` | Clearer descriptions for model routing | tool_pass_rate |
| `FALLBACK_POLICY` | Fewer turns before escalation | task_success |
| `CALLBACKS.before_model.deterministic_intents` | Which intents bypass LLM | latency_score |
| `CALLBACKS.before_tool.cacheable_tools` | Which tools are cached | latency_score |
| `TOOL_CACHE_CONFIG[tool].ttl_seconds` | Cache TTL per tool | latency_score |
| `CALLBACK_CONFIG[tool].timeout_ms` | Webhook timeout budget | callback_pass_rate |
| `CALLBACK_CONFIG[tool].retries` | Webhook retry count | callback_pass_rate |
| `VARIABLES` | Session variable defaults and scoping | task_success |

## Evaluation Dimensions (5 eval types, 6 score components)

| Metric key | Eval Type | Weight |
|---|---|---|
| `task_success` | SimulationEvals — multi-turn goal completion | 0.35 |
| `turn_pass_rate` | TurnEvals — single-turn response quality | 0.20 |
| `tool_pass_rate` | ToolEvals — tool call correctness | 0.20 |
| `latency_score` | p95 latency (implicit) | 0.15 |
| `guardrail_pass_rate` | GuardrailEvals — safety/topic blocking | 0.07 |
| `callback_pass_rate` | CallbackEvals — webhook validation | 0.03 |

## Golden Test Suite (54 tests across 6 categories)

| Category | Count | Test IDs |
|---|---|---|
| Happy path (single-turn) | 16 | gt_001 – gt_016 |
| Multi-turn flows | 8 | gt_017 – gt_024 |
| Ambiguous/overlapping intents | 8 | gt_025 – gt_032 |
| Edge cases | 7 | gt_033 – gt_039 |
| Guardrail triggers | 5 | gt_040 – gt_044 |
| Persona variants | 10 | gt_045 – gt_054 |

New test fields: `session_variables`, `persona`, `multi_turn_context`, `should_be_blocked`.

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

## Safety Rules

- **NEVER modify `evaluate.py`** — it is the fixed ground truth.
- Only the autonomous loop commits changes to `agent_config.py`.
- Do not install additional packages inside the loop.
- Always run `evaluate.py --output-json` after committing.
- Baseline is stored in `.auto-cxas/state/baseline.json` — do not edit manually.
- Git revert uses `--soft` reset + `git checkout -- agent_config.py` (never `--hard`).

## Quick Start

```bash
# Claude Code
claude --context AGENTS.md \
  --prompt "Read program.md, check the baseline, and start the experiment loop."

# With EMA smoothing (reduces noise on short runs)
python auto_loop.py --dry-run --max-experiments 10 --ema
```
