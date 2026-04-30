# GEMINI.md — Context for Gemini CLI

This file is read by `gemini run` when using the Gemini CLI in this repository.

## Repository purpose

auto-cxas-scrapi uses the Gemini CLI as one of its LLM backends for proposing
and explaining CX Agent Studio optimization experiments.

## Setup

```bash
# Install Gemini CLI
pip install google-generativeai

# Configure
export GOOGLE_CLOUD_PROJECT=your-project
gcloud auth application-default login

# Run with Gemini backend
AUTO_CXAS_LLM_PROVIDER=gemini auto-cxas daemon
```

## Gemini-specific considerations

- Use `gemini-2.0-flash` as the default model for fast experiment proposals.
- Use `gemini-2.5-pro` for deep reasoning when proposing complex structural changes.
- The `GOOGLE_CLOUD_LOCATION` env var controls which Vertex AI region is used.

## Starting a Gemini session

```bash
gemini run --context GEMINI.md \\
  --prompt "Read program.md and start the CXAS experiment loop."
```

The agent will enter the autonomous loop defined in `program.md`.
