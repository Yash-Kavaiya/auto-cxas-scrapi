from auto_cxas_scrapi.policies.promotion import PromotionPolicy


def test_insufficient_delta_blocked() -> None:
    policy = PromotionPolicy(min_score_delta=0.02, require_manual_approval=False)
    decision = policy.evaluate(baseline_score=0.80, candidate_score=0.81)
    assert decision.allowed is False
    assert any("delta" in r.lower() for r in decision.reasons)


def test_sufficient_delta_auto_allowed() -> None:
    policy = PromotionPolicy(min_score_delta=0.01, require_manual_approval=False)
    decision = policy.evaluate(baseline_score=0.80, candidate_score=0.82)
    assert decision.allowed is True


def test_manual_approval_always_blocks() -> None:
    policy = PromotionPolicy(min_score_delta=0.001, require_manual_approval=True)
    decision = policy.evaluate(baseline_score=0.80, candidate_score=0.90)
    assert decision.allowed is False
    assert any("manual" in r.lower() for r in decision.reasons)


def test_latency_regression_blocked() -> None:
    policy = PromotionPolicy(
        min_score_delta=0.01,
        require_manual_approval=False,
        max_latency_regression_ms=200,
    )
    decision = policy.evaluate(
        baseline_score=0.80, candidate_score=0.85,
        baseline_latency_p95=1000, candidate_latency_p95=1400,
    )
    assert decision.allowed is False
    assert any("latency" in r.lower() for r in decision.reasons)
