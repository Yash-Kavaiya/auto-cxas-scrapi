"""Experiment artifact store and run journal."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentResult, ExperimentStatus, ScoreCard


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def experiment_dir(self, experiment_id: str) -> Path:
        p = self.root / experiment_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_candidate(self, candidate: ExperimentCandidate) -> Path:
        path = self.experiment_dir(candidate.experiment_id) / "candidate.json"
        path.write_text(json.dumps({
            "experiment_id": candidate.experiment_id,
            "title": candidate.title,
            "hypothesis": candidate.hypothesis,
            "target_resource": candidate.target_resource,
            "mutation": candidate.mutation,
            "new_agent_config_content": candidate.new_agent_config_content,
            "created_at": candidate.created_at.isoformat(),
        }, indent=2), encoding="utf-8")
        return path

    def save_result(self, result: ExperimentResult) -> Path:
        path = self.experiment_dir(result.experiment_id) / "result.json"
        scorecard = None
        if result.scorecard:
            scorecard = {
                "score": result.scorecard.score,
                "metrics": result.scorecard.metrics,
                "rationale": result.scorecard.rationale,
            }
        path.write_text(json.dumps({
            "experiment_id": result.experiment_id,
            "status": result.status.value,
            "scorecard": scorecard,
            "artifacts": result.artifacts,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        }, indent=2), encoding="utf-8")
        return path

    def save_scorecard(self, experiment_id: str, scorecard: ScoreCard) -> Path:
        path = self.experiment_dir(experiment_id) / "scorecard.json"
        path.write_text(json.dumps({
            "score": scorecard.score,
            "metrics": scorecard.metrics,
            "rationale": scorecard.rationale,
        }, indent=2), encoding="utf-8")
        return path

    def update_status(self, experiment_id: str, status: ExperimentStatus) -> Path:
        path = self.experiment_dir(experiment_id) / "status.txt"
        path.write_text(status.value, encoding="utf-8")
        return path

    def load_candidate(self, experiment_id: str) -> dict[str, Any]:
        path = self.experiment_dir(experiment_id) / "candidate.json"
        return json.loads(path.read_text("utf-8"))

    def load_result(self, experiment_id: str) -> dict[str, Any]:
        path = self.experiment_dir(experiment_id) / "result.json"
        return json.loads(path.read_text("utf-8"))

    def list_experiments(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())
