"""LLM-driven experiment planner — generates candidates using AI backends."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from auto_cxas_scrapi.adapters.llm.base import LLMAdapter
from auto_cxas_scrapi.core.contracts import Planner
from auto_cxas_scrapi.core.models import ExperimentCandidate

PLANNER_SYSTEM_PROMPT = """
You are an expert Google Cloud CX Agent Studio optimization researcher.
Given the current agent_config.py content and results history, propose
ONE targeted experiment to improve the eval_score.

eval_score = task_success * 0.60 + latency_score * 0.25 + reliability * 0.15

Respond ONLY with valid JSON in this exact format:
{
  "title": "Short experiment title",
  "hypothesis": "What you expect to happen and why",
  "target_resource": "agent_config variable name being changed",
  "mutation": {
    "type": "prompt_patch|config_update|threshold_tune|template_change",
    "path": "VARIABLE.key",
    "operation": "replace|append|prepend|adjust",
    "value": "<new value or delta>",
    "rationale": "Why this specific change"
  }
}
"""


class LLMExperimentPlanner(Planner):
    def __init__(self, *, llm: LLMAdapter, repo_root: Path | None = None) -> None:
        self.llm = llm
        self.repo_root = repo_root or Path.cwd()

    def _read_agent_config(self) -> str:
        p = self.repo_root / "agent_config.py"
        return p.read_text("utf-8") if p.exists() else "# agent_config.py not found"

    def _read_results_history(self, max_rows: int = 10) -> str:
        p = self.repo_root / "results.tsv"
        if not p.exists():
            return "No results history yet."
        lines = p.read_text("utf-8").splitlines()
        header = lines[0] if lines else ""
        recent = lines[-max_rows:] if len(lines) > 1 else []
        return "\n".join([header] + recent)

    def propose(self, *, context: dict) -> list[ExperimentCandidate]:
        if not self.llm.is_available():
            return self._fallback_propose(context)

        agent_config_content = self._read_agent_config()
        results_history = self._read_results_history()

        user_prompt = f"""
Current agent_config.py:
```python
{agent_config_content}
```

Recent results history (results.tsv):
```
{results_history}
```

App context: {json.dumps(context, indent=2)}

Propose ONE experiment to improve eval_score.
"""
        try:
            response = self.llm.complete(
                system=PLANNER_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=1024,
            )
            raw = response.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            data = json.loads(raw)
            return [ExperimentCandidate(
                experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
                title=data["title"],
                hypothesis=data["hypothesis"],
                target_resource=data.get("target_resource", context.get("app_name", "")),
                mutation=data["mutation"],
            )]
        except Exception as exc:
            print(f"[Planner] LLM proposal failed: {exc} -- using fallback")
            return self._fallback_propose(context)

    def _fallback_propose(self, context: dict) -> list[ExperimentCandidate]:
        return [ExperimentCandidate(
            experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
            title="Append clarity rule to system instruction",
            hypothesis="More explicit instructions reduce ambiguous routing.",
            target_resource=context.get("app_name", "unknown"),
            mutation={
                "type": "prompt_patch",
                "path": "SYSTEM_INSTRUCTION",
                "operation": "append",
                "value": "Always confirm user intent before any irreversible action.",
                "rationale": "Fallback: standard clarity improvement",
            },
        )]
