"""Main orchestration service — wires all components together."""
from __future__ import annotations
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

from auto_cxas_scrapi.adapters.llm.factory import get_llm_adapter
from auto_cxas_scrapi.adapters.scrapi import ScrapiAdapter
from auto_cxas_scrapi.config.settings import Settings
from auto_cxas_scrapi.memory.store import ExperimentStore
from auto_cxas_scrapi.planners.llm_planner import LLMOptimizationPlanner
from auto_cxas_scrapi.policies.promotion import PromotionPolicy
from auto_cxas_scrapi.runners.dry_run import DryRunExperimentRunner
from auto_cxas_scrapi.runners.live_run import LiveExperimentRunner
from auto_cxas_scrapi.scorers.weighted import WeightedScorer

console = Console()


class AutoCXASOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = ExperimentStore(settings.runs_dir)
        self.scrapi = ScrapiAdapter(
            project_id=settings.google_cloud_project,
            location=settings.google_cloud_location,
            console=console,
        )
        self.llm = get_llm_adapter(
            provider=settings.llm_provider,
            model=settings.llm_model,
        )
        self.planner = LLMOptimizationPlanner(llm=self.llm, state_dir=settings.state_dir)
        self.scorer = WeightedScorer()
        self.policy = PromotionPolicy(
            min_score_delta=settings.min_score_delta,
            require_manual_approval=(settings.approval_mode == "manual"),
        )
        if settings.google_cloud_project and settings.app_name:
            self.runner = LiveExperimentRunner(
                scrapi=self.scrapi,
                state_dir=settings.state_dir,
            )
        else:
            self.runner = DryRunExperimentRunner()

    def get_baseline_score(self) -> float:
        path = self.settings.state_dir / "baseline.json"
        if path.exists():
            return float(json.loads(path.read_text("utf-8")).get("eval_score", 0.0))
        return 0.0

    def collect_baseline(self) -> dict:
        inv = self.scrapi.get_inventory(self.settings.app_name)
        console.print_json(json.dumps(inv))
        return inv

    def propose(self) -> list:
        context = {
            "app_name": self.settings.app_name,
            "project_id": self.settings.google_cloud_project,
        }
        candidates = self.planner.propose(context=context)
        for c in candidates:
            self.store.save_candidate(c)
        return candidates

    def run_experiment(self, experiment_id: str):
        data = self.store.load_candidate(experiment_id)
        from auto_cxas_scrapi.core.models import ExperimentCandidate
        candidate = ExperimentCandidate(
            experiment_id=data["experiment_id"],
            title=data["title"],
            hypothesis=data["hypothesis"],
            target_resource=data["target_resource"],
            mutation=data["mutation"],
            new_agent_config_content=data.get("new_agent_config_content", ""),
        )
        result = self.runner.run(candidate)
        self.store.save_result(result)
        return result

    def score_experiment(self, experiment_id: str) -> dict:
        result_data = self.store.load_result(experiment_id)
        from auto_cxas_scrapi.core.models import ExperimentResult, ExperimentStatus
        result = ExperimentResult(
            experiment_id=result_data["experiment_id"],
            status=ExperimentStatus(result_data["status"]),
            artifacts=result_data["artifacts"],
        )
        scorecard = self.scorer.score(result)
        self.store.save_scorecard(experiment_id, scorecard)
        baseline_score = self.get_baseline_score()
        decision = self.policy.evaluate(
            baseline_score=baseline_score,
            candidate_score=scorecard.score,
        )
        return {
            "experiment_id": experiment_id,
            "score": scorecard.score,
            "baseline_score": baseline_score,
            "delta": round(scorecard.score - baseline_score, 6),
            "metrics": scorecard.metrics,
            "rationale": scorecard.rationale,
            "policy": {"allowed": decision.allowed, "reasons": decision.reasons},
        }

    def print_history(self) -> None:
        experiments = self.store.list_experiments()
        if not experiments:
            console.print("[yellow]No experiments found.[/yellow]")
            return
        table = Table(title="Experiment History")
        table.add_column("ID")
        table.add_column("Status")
        table.add_column("Score")
        for exp_id in experiments:
            try:
                result = self.store.load_result(exp_id)
                sc_path = self.store.experiment_dir(exp_id) / "scorecard.json"
                score = "-"
                if sc_path.exists():
                    sc_data = json.loads(sc_path.read_text("utf-8"))
                    score = f"{sc_data['score']:.6f}"
                table.add_row(exp_id, result.get("status", "?"), score)
            except Exception:
                table.add_row(exp_id, "unknown", "-")
        console.print(table)
