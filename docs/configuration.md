# Configuration

All settings are loaded from environment variables (or `.env`) via
`src/auto_cxas_scrapi/config/settings.py` (Pydantic `BaseSettings`).

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

---

## Required

| Variable | Type | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `str` | GCP project ID containing your CXAS app |
| `AUTO_CXAS_APP_NAME` | `str` | CXAS app display name (e.g. `my-support-bot`) |

---

## LLM provider

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_LLM_PROVIDER` | `str` | `gemini` | `gemini` \| `openai` \| `anthropic` |
| `GEMINI_API_KEY` | `str` | — | Required if provider = `gemini` |
| `OPENAI_API_KEY` | `str` | — | Required if provider = `openai` |
| `ANTHROPIC_API_KEY` | `str` | — | Required if provider = `anthropic` |

---

## Loop behaviour

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_APPROVAL_MODE` | `str` | `manual` | `auto` keeps improvements without prompting; `manual` asks |
| `AUTO_CXAS_MIN_SCORE_DELTA` | `float` | `0.01` | Minimum eval_score improvement to keep an experiment |
| `AUTO_CXAS_MAX_PARALLEL_EVALS` | `int` | `3` | Eval types to run concurrently in each iteration |
| `AUTO_CXAS_EVAL_TIMEOUT_SECONDS` | `int` | `180` | Per-eval-type timeout in seconds |
| `AUTO_CXAS_STATE_DIR` | `str` | `.auto-cxas/state` | Directory for baseline.json, last_result.json, etc. |

---

## Convergence

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_CONVERGENCE_WINDOW` | `int` | `10` | Number of recent scores tracked in the sliding window |
| `AUTO_CXAS_CONVERGENCE_THRESHOLD` | `float` | `0.002` | Loop stops when `max(window) − min(window) < threshold` |

**Example:** with defaults, the loop stops after 10 consecutive experiments
whose scores all fall within a 0.2% band.

To disable convergence detection (run until `--max-experiments`):
```bash
AUTO_CXAS_CONVERGENCE_THRESHOLD=0
```

---

## Mutation diversity

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_DIVERSITY_WINDOW` | `int` | `5` | Last N mutations tracked to guide type selection |

The planner reads `.auto-cxas/state/mutation_history.json` and prefers
mutation types not seen in the last `diversity_window` experiments.

---

## Reporting

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_GENERATE_HTML_REPORT` | `bool` | `false` | Generate a self-contained HTML report when the loop ends |
| `AUTO_CXAS_REPORT_DIR` | `str` | `.auto-cxas/reports` | Directory to write HTML report files |
| `AUTO_CXAS_GCS_RESULTS_BUCKET` | `str` | `""` | GCS bucket name (without `gs://`) to upload `results.tsv` |

Report files are named `report_YYYYMMDD_HHMMSS.html` and are fully
self-contained (no external JS/CSS dependencies).

---

## Callbacks & webhooks

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_CALLBACK_SERVER_URL` | `str` | `""` | Base URL for live `CallbackEvals` webhook tests |

---

## Baseline cache

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_BASELINE_CACHE_TTL_SECONDS` | `int` | `3600` | How long baseline.json is reused before a fresh eval |

---

## Full `.env.example`

```bash
# Required
GOOGLE_CLOUD_PROJECT=my-gcp-project
AUTO_CXAS_APP_NAME=my-support-bot

# LLM
AUTO_CXAS_LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...

# Loop
AUTO_CXAS_APPROVAL_MODE=auto
AUTO_CXAS_MIN_SCORE_DELTA=0.01
AUTO_CXAS_MAX_PARALLEL_EVALS=3
AUTO_CXAS_EVAL_TIMEOUT_SECONDS=180

# Convergence
AUTO_CXAS_CONVERGENCE_WINDOW=10
AUTO_CXAS_CONVERGENCE_THRESHOLD=0.002

# Diversity
AUTO_CXAS_DIVERSITY_WINDOW=5

# Reporting
AUTO_CXAS_GENERATE_HTML_REPORT=true
AUTO_CXAS_REPORT_DIR=.auto-cxas/reports
AUTO_CXAS_GCS_RESULTS_BUCKET=my-bucket-name

# Optional
AUTO_CXAS_CALLBACK_SERVER_URL=https://my-server.example.com
AUTO_CXAS_BASELINE_CACHE_TTL_SECONDS=3600
```
