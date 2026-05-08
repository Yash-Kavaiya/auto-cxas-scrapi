# AGENTS.md — Context for Claude Code / Codex / AI Agents

This file is read automatically by Claude Code, OpenAI Codex CLI, and GitHub Copilot
agent mode. It tells AI coding agents what this repo is and how to operate safely.

## What this repo does

auto-cxas-scrapi is an autonomous optimization loop for Google Cloud CX Agent Studio.
The agent proposes changes to `agent_config.py`, runs `evaluate.py`, checks if
`eval_score` improved, keeps improvements and discards regressions.

## Files you should read first

1. `program.md` — experiment strategy, loop protocol, score formula
2. `evaluate.py` — fixed evaluation harness (READ-ONLY, never modify)
3. `agent_config.py` — the ONLY file you edit during experiments
4. `results.tsv` — experiment history

## Mutable targets in agent_config.py (v2)

| Variable | Type | Impact |
|---|---|---|
| `SYSTEM_INSTRUCTION` | str | task_success, turn_pass_rate |
| `STATIC_VARIABLES` | dict[str, str] | task_success (large prompt blocks) |
| `VARIABLES` | dict[str, dict] | session state scoping |
| `ROUTING_RULES` | dict | task_success, tool_pass_rate |
| `TOOL_DESCRIPTIONS` | dict | tool_pass_rate |
| `GUARDRAIL_PARAMS` | dict | guardrail_pass_rate |
| `RESPONSE_TEMPLATES` | dict | task_success, turn_pass_rate |
| `CALLBACKS` | dict | latency_score (deterministic bypass) |
| `TOOL_CACHE_CONFIG` | dict | latency_score (tool caching) |
| `CALLBACK_CONFIG` | dict | callback_pass_rate |
| `FALLBACK_POLICY` | dict | task_success |

## Ground rules

- `evaluate.py` is READ-ONLY. Modifying it invalidates all results.
- Only change `agent_config.py` — no other Python files.
- Do not install new packages. Use only what is in `pyproject.toml`.
- Always commit before running `evaluate.py`.
- Revert with `git reset --soft HEAD~1 && git checkout -- agent_config.py` (never `--hard`).
- Log every experiment result to `results.tsv` regardless of outcome.
- Never stop the loop to ask for permission — run until manually interrupted.

## Score formula

```
eval_score = task_success * 0.35 + turn_pass_rate * 0.20 + tool_pass_rate * 0.20
           + latency_score * 0.15 + guardrail_pass_rate * 0.07 + callback_pass_rate * 0.03
```

## Starting a session

```
Read program.md and let's start a new experiment run for today.
```

The agent will:
1. Confirm setup (credentials, baseline, branch)
2. Enter the experiment loop autonomously
3. Produce a `results.tsv` with every experiment outcome
