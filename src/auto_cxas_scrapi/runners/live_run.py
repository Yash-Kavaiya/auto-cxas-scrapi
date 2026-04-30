"""Live experiment runner — applies mutations and runs real CXAS evals."""
from __future__ import annotations
import subprocess
import sys
import json
from datetime import datetime, UTC
from pathlib import Path

from auto_cxas_scrapi.adapters.scrapi import ScrapiAdapter
from auto_cxas_scrapi.core.contracts import Runner
from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentResult, ExperimentStatus


class LiveExperimentRunner(Runner):
    def __init__(
        self, *,
        scrapi: ScrapiAdapter,
        repo_root: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.scrapi = scrapi
        self.repo_root = repo_root or Path.cwd()
        self.state_dir = state_dir or self.repo_root / ".auto-cxas" / "state"

    def _apply_mutation(self, candidate: ExperimentCandidate) -> bool:
        mutation = candidate.mutation
        config_path = self.repo_root / "agent_config.py"
        if not config_path.exists():
            return False
        content = config_path.read_text("utf-8")
        op = mutation.get("operation", "replace")
        path = mutation.get("path", "")
        value = mutation.get("value", "")
        if op == "append" and path == "SYSTEM_INSTRUCTION":
            content = content.replace(
                'SYSTEM_INSTRUCTION: str = """',
                f'SYSTEM_INSTRUCTION: str = """\n{value}',
            )
            config_path.write_text(content, "utf-8")
            return True
        return True

    def run(self, candidate: ExperimentCandidate) -> ExperimentResult:
        started = datetime.now(UTC)
        self._apply_mutation(candidate)

        result_path = self.state_dir / "last_result.json"
        cmd = [sys.executable, str(self.repo_root / "evaluate.py"), "--output-json"]
        try:
            subprocess.run(
                cmd, cwd=self.repo_root, capture_output=True,
                text=True, timeout=180,
            )
            artifacts: dict = {}
            if result_path.exists():
                artifacts = json.loads(result_path.read_text("utf-8"))
            status = ExperimentStatus.passed if not artifacts.get("error") else ExperimentStatus.failed
        except subprocess.TimeoutExpired:
            artifacts = {"error": "evaluate.py timed out"}
            status = ExperimentStatus.failed

        return ExperimentResult(
            experiment_id=candidate.experiment_id,
            status=status,
            artifacts=artifacts,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
