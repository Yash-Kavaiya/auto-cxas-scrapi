from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentStatus, ScoreCard


def test_scorecard_defaults() -> None:
    sc = ScoreCard(score=0.85)
    assert sc.score == 0.85
    assert sc.metrics == {}
    assert sc.rationale == ""


def test_experiment_status_values() -> None:
    assert ExperimentStatus("promoted").value == "promoted"
    assert ExperimentStatus("keep").value == "keep"


def test_candidate_fields() -> None:
    c = ExperimentCandidate(
        experiment_id="exp-001",
        title="Test",
        hypothesis="This will improve.",
        target_resource="my-app",
        mutation={"type": "prompt_patch"},
    )
    assert c.experiment_id == "exp-001"
    assert c.mutation["type"] == "prompt_patch"
    assert c.new_agent_config_content == ""
