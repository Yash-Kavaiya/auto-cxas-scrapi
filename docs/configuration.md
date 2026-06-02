# Configuration

All settings are loaded from environment variables (or `.env`) via
`src/auto_cxas_scrapi/config/settings.py` (Pydantic `BaseSettings`).

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
| `AUTO_CXAS_APPROVAL_MODE` | `str` | `manual` | `auto` keeps improvements without prompting |
| `AUTO_CXAS_MIN_SCORE_DELTA` | `float` | `0.01` | Minimum eval_score improvement to keep an experiment |
| `AUTO_CXAS_MAX_PARALLEL_EVALS` | `int` | `3` | Eval types to run concurrently per iteration |
| `AUTO_CXAS_EVAL_TIMEOUT_SECONDS` | `int` | `180` | Per-eval-type timeout in seconds |
| `AUTO_CXAS_STATE_DIR` | `str` | `.auto-cxas/state` | Directory for state files |

---

## Convergence

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_CONVERGENCE_WINDOW` | `int` | `10` | Number of recent scores in the sliding window |
| `AUTO_CXAS_CONVERGENCE_THRESHOLD` | `float` | `0.002` | Stop when `max(window) - min(window) < threshold` |

To disable convergence detection: `AUTO_CXAS_CONVERGENCE_THRESHOLD=0`

---

## Mutation diversity

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_DIVERSITY_WINDOW` | `int` | `5` | Last N mutations tracked to guide type selection |

---

## Reporting

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_CXAS_GENERATE_HTML_REPORT` | `bool` | `false` | Generate HTML report when loop ends |
| `AUTO_CXAS_REPORT_DIR` | `str` | `.auto-cxas/reports` | Directory for HTML report files |
| `AUTO_CXAS_GCS_RESULTS_BUCKET` | `str` | `""` | GCS bucket name to upload `results.tsv` |

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
