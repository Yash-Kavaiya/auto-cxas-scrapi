# auto-cxas-scrapi

> Autonomous optimization loop for Google Cloud CX Agent Studio, powered by
> [cxas-scrapi](https://github.com/GoogleCloudPlatform/cxas-scrapi) and inspired by
> [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

---

## What it does

auto-cxas-scrapi runs an autonomous `propose → commit → eval → keep/discard` loop
that continuously improves your Dialogflow CX / CXAS agent configuration without
human intervention between experiments.

```
                    ┌───────────────────────────┐
                    │   agent_config.py      │  ← AI edits this
                    └─────────┬────────────────┘
                             │
              ┌──────────┴──────────┐
              │    evaluate.py (fixed)    │  ← READ-ONLY
              └──────────┬──────────┘
                         │
              ┌─────────┴─────────┐
              │    eval_score            │
              │    keep / discard        │
              └───────────────────┘
```

## Score formula

```
eval_score = task_success × 0.60 + latency_score × 0.25 + reliability_score × 0.15
```

## Quick start

```bash
bash scripts/install.sh
bash scripts/setup_gcloud.sh

python evaluate.py --dry-run    # sanity check
auto-cxas init                   # validate config
auto-cxas daemon --dry-run       # start experiment loop
```

## AI agent support

| Tool | Context file | Start command |
|---|---|---|
| Claude Code | `AGENTS.md` | `claude --context AGENTS.md` |
| Gemini CLI | `GEMINI.md` | `gemini run --context GEMINI.md` |
| GitHub Copilot | `.github/copilot-instructions.md` | VS Code Copilot Chat |
| OpenAI Codex | `AGENTS.md` | `codex --context AGENTS.md` |

## Project structure

```
auto-cxas-scrapi/
├── evaluate.py           # Fixed eval harness (READ-ONLY)
├── agent_config.py       # Agent configuration (AI edits this)
├── auto_loop.py          # Autonomous experiment loop
├── program.md            # Experiment strategy
├── golden_tests.yaml     # 10 built-in golden tests
├── results.tsv           # Run journal
├── AGENTS.md             # Claude Code / Codex context
├── GEMINI.md             # Gemini CLI context
├── src/auto_cxas_scrapi/ # Python package
│   ├── cli/               # Typer CLI (auto-cxas)
│   ├── adapters/          # cxas-scrapi, GitHub CLI, LLM backends
│   ├── planners/          # LLM experiment planner
│   ├── runners/           # dry-run and live experiment runners
│   ├── scorers/           # Weighted multi-objective scorer
│   ├── policies/          # Promotion safety gate
│   └── services/          # Orchestrator wiring all components
└── tests/                # pytest test suite
```

## License

Apache 2.0
