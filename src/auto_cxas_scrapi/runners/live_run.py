"""Live experiment runner — runs real CXAS evals against agent_config.py."""
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

    def run(self, candidate: ExperimentCandidate) -> ExperimentResult:
        started = datetime.now(UTC)

        config_path = self.repo_root / "agent_config.py"
        if not config_path.exists():
            return ExperimentResult(
                experiment_id=candidate.experiment_id,
                status=ExperimentStatus.failed,
                artifacts={"error": "agent_config.py not found"},
                started_at=started,
                finished_at=datetime.now(UTC),
            )

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
