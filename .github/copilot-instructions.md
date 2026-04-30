# GitHub Copilot Instructions

## Repository context

This is the auto-cxas-scrapi autonomous optimization repository for Google Cloud
CX Agent Studio. Copilot should assist with experiment proposals, code changes to
`agent_config.py`, and interpretation of `results.tsv`.

## Copilot workspace rules

- Only suggest changes to `agent_config.py` during experiment sessions.
- `evaluate.py` is READ-ONLY — never suggest changes to it.
- When proposing changes, explain the hypothesis and expected metric impact.
- Reference `results.tsv` history before proposing previously tried ideas.
