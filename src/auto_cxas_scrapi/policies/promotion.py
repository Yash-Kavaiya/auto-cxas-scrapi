"""Promotion safety policy gate."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reasons: list[str]


class PromotionPolicy:
    """
    Promotion safety policy gate.

    Evaluates objective quality criteria (score delta, latency, error rate).
    Manual approval is NOT part of the policy evaluation — it is handled by
    the CLI/loop layer via settings.approval_mode.
    """

    def __init__(
        self, *,
        min_score_delta: float = 0.01,
        max_latency_regression_ms: int = 500,
        max_error_rate_increase: float = 0.05,
    ) -> None:
        self.min_score_delta = min_score_delta
        self.max_latency_regression_ms = max_latency_regression_ms
        self.max_error_rate_increase = max_error_rate_increase

    def evaluate(
        self, *,
        baseline_score: float,
        candidate_score: float,
        baseline_latency_p95: int = 0,
        candidate_latency_p95: int = 0,
        baseline_error_rate: float = 0.0,
        candidate_error_rate: float = 0.0,
    ) -> PolicyDecision:
        """
        Evaluate objective quality criteria.

        Returns allowed=True only when ALL checks pass (score improved
        within acceptable latency and error-rate bounds).
        """
        reasons: list[str] = []
        delta = candidate_score - baseline_score
        if delta < self.min_score_delta:
            reasons.append(
                f"Score delta {delta:.4f} below minimum threshold {self.min_score_delta:.4f}."
            )
        latency_delta = candidate_latency_p95 - baseline_latency_p95
        if latency_delta > self.max_latency_regression_ms:
            reasons.append(
                f"Latency regression +{latency_delta}ms exceeds limit {self.max_latency_regression_ms}ms."
            )
        error_delta = candidate_error_rate - baseline_error_rate
        if error_delta > self.max_error_rate_increase:
            reasons.append(
                f"Error rate increase +{error_delta:.4f} exceeds limit {self.max_error_rate_increase:.4f}."
            )
        return PolicyDecision(allowed=len(reasons) == 0, reasons=reasons)
