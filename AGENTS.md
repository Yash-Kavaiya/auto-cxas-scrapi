# AGENTS.md — Context for Claude Code / Codex / AI Agents

This file is read automatically by Claude Code (`claude`), OpenAI Codex CLI (`codex`),
and GitHub Copilot agent mode. It tells AI coding agents what this repo is and how to
operate safely within it.

## What this repo does

auto-cxas-scrapi is an autonomous optimization loop for Google Cloud CX Agent Studio.
The agent proposes changes to `agent_config.py`, runs `evaluate.py`, checks if
`eval_score` improved, keeps improvements and discards regressions.

## Files you should read first

1. `program.md` — your experiment strategy and loop instructions
2. `evaluate.py` — fixed evaluation harness (READ-ONLY, never modify)
3. `agent_config.py` — the ONLY file you edit during experiments
4. `results.tsv` — experiment history

## Ground rules

- `evaluate.py` is READ-ONLY. Modifying it invalidates all results.
- Only change `agent_config.py` — no other Python files.
- Do not install new packages. Use only what is in `pyproject.toml`.
- Always commit before running `evaluate.py`.
- Log every experiment result to `results.tsv` regardless of outcome.
- Never stop the loop to ask for permission — run until manually interrupted.

## Starting a session

```
Read program.md and let's start a new experiment run for today.
```

The agent will:
1. Confirm setup (credentials, baseline, branch)
2. Enter the experiment loop autonomously
3. Produce a `results.tsv` with every experiment outcome
