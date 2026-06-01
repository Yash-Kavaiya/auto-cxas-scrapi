"""LLM-driven experiment planner — generates candidates using AI backends."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from auto_cxas_scrapi.adapters.llm.base import LLMAdapter
from auto_cxas_scrapi.core.contracts import Planner
from auto_cxas_scrapi.core.models import ExperimentCandidate
from auto_cxas_scrapi.planners.multi_objective_planner import load_last_metrics, rank_eval_types

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert Google Cloud CX Agent Studio optimization researcher.
Given the current agent_config.py and results history, propose ONE targeted
experiment to improve the weakest eval dimension indicated below.

eval_score = task_success * 0.60 + latency_score * 0.25 + reliability * 0.15

You MUST output ONLY valid JSON with this exact schema — no markdown fences, \
no extra text:
{
  "title": "Short experiment title",
  "hypothesis": "What you expect to happen and why",
  "target_eval": "simulation|tool|turn|guardrail|callback",
  "target_metric": "the metric key being improved",
  "mutation": {
    "type": "prompt_patch|config_update|threshold_tune|template_change",
    "path": "VARIABLE.key",
    "operation": "replace|append|prepend|adjust",
    "value": "<new value or delta>",
    "rationale": "Why this specific change"
  },
  "new_agent_config_content": "# complete valid Python text for agent_config.py"
}

The new_agent_config_content field MUST contain the full, valid Python source
for agent_config.py with your proposed mutation already applied.
"""


class LLMOptimizationPlanner(Planner):
    """Plans experiments using an LLM; targets the weakest eval dimension."""

    def __init__(
        self,
        *,
        llm: LLMAdapter,
        repo_root: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.llm = llm
        self.repo_root = repo_root or Path.cwd()
        self.state_dir = state_dir or self.repo_root / ".auto-cxas" / "state"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(self, *, context: dict) -> list[ExperimentCandidate]:
        target_eval, target_metric, current_score = self._find_weakest_eval()

        if not self.llm.is_available():
            return self._fallback_propose(context, target_eval)

        agent_config = self._read_agent_config()
        results_history = self._read_results_history()
        failing_cases = self._read_failing_cases()

        user_prompt = (
            f"WEAKEST EVAL: {target_eval} ({target_metric} = {current_score:.3f})\n"
            f"Target this eval dimension in your proposed mutation.\n\n"
            f"{failing_cases}"
            f"Current agent_config.py:\n```python\n{agent_config}\n```\n\n"
            f"Recent results (results.tsv):\n```\n{results_history}\n```\n\n"
            f"App context: {json.dumps(context, indent=2)}\n\n"
            f"Propose ONE experiment. Output only the JSON object."
        )

        try:
            response = self.llm.complete(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=2048,
            )
            raw = response.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            data = json.loads(raw)
            new_content = data.get("new_agent_config_content", "")
            if not new_content:
                new_content = self._patch_agent_config(agent_config, data.get("mutation", {}))
            return [ExperimentCandidate(
                experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
                title=data["title"],
                hypothesis=data["hypothesis"],
                target_resource=data.get("target_eval", target_eval),
                mutation=data["mutation"],
                new_agent_config_content=new_content,
            )]
        except Exception as exc:
            log.warning("LLM proposal failed: %s — using fallback", exc)
            return self._fallback_propose(context, target_eval)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_weakest_eval(self) -> tuple[str, str, float]:
        ranked = rank_eval_types(load_last_metrics(self.state_dir))
        if ranked:
            return ranked[0]
        return ("simulation", "task_success", 0.0)

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

    def _read_failing_cases(self, max_cases: int = 5) -> str:
        """Surface concrete failing test cases ("fix what failed") to the planner.

        Reads the per-test failures persisted by evaluate.py into last_result.json
        and renders the top few as a focused block. Returns "" when none exist.
        """
        p = self.state_dir / "last_result.json"
        if not p.exists():
            return ""
        try:
            data = json.loads(p.read_text("utf-8"))
        except Exception:
            return ""
        failures = data.get("failed_tests") or []
        if not failures:
            return ""
        lines = ["CONCRETE FAILING CASES (fix these specifically):"]
        for f in failures[:max_cases]:
            dims = ", ".join(f.get("failed_dimensions", [])) or "unknown"
            expects = ", ".join(f.get("expected_response_contains", []))
            lines.append(
                f'  - "{f.get("user_utterance", "")}" '
                f'(intent={f.get("expected_intent", "?")}, failed: {dims}'
                + (f"; expected response to mention: {expects}" if expects else "")
                + ")"
            )
        return "\n".join(lines) + "\n\n"

    def _patch_agent_config(self, content: str, mutation: dict) -> str:
        """Apply a simple string patch when LLM omits new_agent_config_content."""
        op = mutation.get("operation", "")
        path = mutation.get("path", "")
        value = mutation.get("value", "")
        if op == "append" and path == "SYSTEM_INSTRUCTION":
            return content.replace(
                'SYSTEM_INSTRUCTION: str = """',
                f'SYSTEM_INSTRUCTION: str = """\n{value}',
            )
        return content

    def _fallback_propose(
        self, context: dict, target_eval: str
    ) -> list[ExperimentCandidate]:
        clarity_rule = "Always confirm user intent before any irreversible action."
        agent_config = self._read_agent_config()
        mutation = {
            "type": "prompt_patch",
            "path": "SYSTEM_INSTRUCTION",
            "operation": "append",
            "value": clarity_rule,
            "rationale": f"Fallback: clarity improvement targeting {target_eval}",
        }
        new_content = self._patch_agent_config(agent_config, mutation)
        return [ExperimentCandidate(
            experiment_id=f"exp-{uuid.uuid4().hex[:8]}",
            title=f"Append clarity rule [{target_eval}]",
            hypothesis="More explicit instructions reduce ambiguous routing.",
            target_resource=context.get("app_name", "unknown"),
            mutation=mutation,
            new_agent_config_content=new_content,
        )]


# Keep old name as alias for backwards compatibility with any existing imports.
LLMExperimentPlanner = LLMOptimizationPlanner
