from auto_cxas_scrapi.core.models import ExperimentResult, ExperimentStatus
from auto_cxas_scrapi.scorers.weighted import WeightedScorer


def _result(task_success: float, latency_p95: int, error_rate: float) -> ExperimentResult:
    return ExperimentResult(
        experiment_id="exp-test",
        status=ExperimentStatus.passed,
        artifacts={
            "simulation_summary": {
                "task_success": task_success,
                "latency_ms_p95": latency_p95,
                "tool_error_rate": error_rate,
            }
        },
    )


def test_perfect_score() -> None:
    scorer = WeightedScorer()
    sc = scorer.score(_result(1.0, 0, 0.0))
    assert sc.score == 1.0


def test_zero_score() -> None:
    scorer = WeightedScorer()
    sc = scorer.score(_result(0.0, 5000, 1.0))
    assert sc.score == 0.0


def test_typical_score_range() -> None:
    scorer = WeightedScorer()
    sc = scorer.score(_result(0.85, 1200, 0.02))
    assert 0.6 < sc.score < 1.0
    assert "task_success" in sc.metrics
    assert "rationale" in sc.rationale
