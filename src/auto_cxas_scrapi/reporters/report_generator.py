"""Experiment report generator — produces Markdown + ANSI reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ReportGenerator:
    """Generates human-readable experiment reports from the runs store."""

    def __init__(self, runs_dir: Path, state_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.state_dir = state_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def experiment_summary(self, experiment_id: str) -> str:
        """Return a Markdown string summarising one experiment."""
        lines: list[str] = []
        lines.append(f"# Experiment Report: `{experiment_id}`")
        lines.append(f"_Generated: {datetime.now(UTC).isoformat()}_\n")

        candidate = self._load_json(experiment_id, "candidate.json")
        result = self._load_json(experiment_id, "result.json")
        scorecard = self._load_json(experiment_id, "scorecard.json")

        if candidate:
            lines.append("## Proposal")
            lines.append(f"- **Title**: {candidate.get('title', '?')}")
            lines.append(f"- **Hypothesis**: {candidate.get('hypothesis', '?')}")
            lines.append(f"- **Target resource**: `{candidate.get('target_resource', '?')}`")
            mut = candidate.get("mutation", {})
            lines.append(f"- **Mutation type**: `{mut.get('type', '?')}`")
            lines.append(f"- **Path**: `{mut.get('path', '?')}`")
            lines.append(f"- **Operation**: `{mut.get('operation', '?')}`")
            lines.append(f"- **Value**: `{mut.get('value', '?')}`")
            lines.append(f"- **Rationale**: {mut.get('rationale', '?')}\n")

        if result:
            lines.append("## Result")
            lines.append(f"- **Status**: `{result.get('status', '?')}`")
            if result.get("started_at"):
                lines.append(f"- **Started**: {result['started_at']}")
            if result.get("finished_at"):
                lines.append(f"- **Finished**: {result['finished_at']}\n")

        if scorecard:
            lines.append("## Score")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| **eval_score** | `{scorecard.get('score', 0):.6f}` |")
            for k, v in scorecard.get("metrics", {}).items():
                if isinstance(v, float):
                    lines.append(f"| {k} | `{v:.4f}` |")
                else:
                    lines.append(f"| {k} | `{v}` |")
            lines.append("")
            lines.append(f"**Rationale**: {scorecard.get('rationale', '?')}\n")

        return "\n".join(lines)

    def full_history_table(self) -> str:
        """Return a Markdown table of all experiments."""
        experiments = self._list_experiments()
        if not experiments:
            return "_No experiments found._"

        rows: list[tuple[str, str, str, str, str]] = []
        for exp_id in experiments:
            result = self._load_json(exp_id, "result.json") or {}
            sc = self._load_json(exp_id, "scorecard.json") or {}
            candidate = self._load_json(exp_id, "candidate.json") or {}
            score = f"{sc.get('score', 0):.6f}" if sc else "-"
            status = result.get("status", "?")
            title = candidate.get("title", "?")
            ts = result.get("started_at", "-")[:10] if result.get("started_at") else "-"
            rows.append((exp_id, title, score, status, ts))

        lines = [
            "# Experiment History",
            "",
            "| ID | Title | Score | Status | Date |",
            "|---|---|---|---|---|",
        ]
        for exp_id, title, score, status, ts in rows:
            lines.append(f"| `{exp_id}` | {title} | {score} | `{status}` | {ts} |")

        return "\n".join(lines)

    def save_experiment_report(self, experiment_id: str) -> Path:
        """Write `{runs_dir}/{experiment_id}/report.md` and return its path."""
        content = self.experiment_summary(experiment_id)
        path = self.runs_dir / experiment_id / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_history_report(self) -> Path:
        """Write `.auto-cxas/history.md` and return its path."""
        content = self.full_history_table()
        path = self.state_dir / "history.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def build_json_summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of all experiment outcomes."""
        experiments = self._list_experiments()
        results: list[dict[str, Any]] = []
        for exp_id in experiments:
            result = self._load_json(exp_id, "result.json") or {}
            sc = self._load_json(exp_id, "scorecard.json") or {}
            candidate = self._load_json(exp_id, "candidate.json") or {}
            results.append({
                "experiment_id": exp_id,
                "title": candidate.get("title", ""),
                "hypothesis": candidate.get("hypothesis", ""),
                "status": result.get("status", "unknown"),
                "score": sc.get("score", 0.0),
                "metrics": sc.get("metrics", {}),
                "started_at": result.get("started_at", ""),
                "finished_at": result.get("finished_at", ""),
            })
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_experiments": len(results),
            "experiments": results,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _list_experiments(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())

    def _load_json(self, experiment_id: str, filename: str) -> dict | None:
        path = self.runs_dir / experiment_id / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return None
