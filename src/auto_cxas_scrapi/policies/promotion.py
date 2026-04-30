"""Promotion safety policy gate."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reasons: list[str]


class PromotionPolicy:
    def __init__(
        self, *,
        min_score_delta: float = 0.01,
        require_manual_approval: bool = True,
        max_latency_regression_ms: int = 500,
        max_error_rate_increase: float = 0.05,
    ) -> None:
        self.min_score_delta = min_score_delta
        self.require_manual_approval = require_manual_approval
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
        if self.require_manual_approval:
            reasons.append("Manual approval required -- run `auto-cxas promote --experiment <id>`.")
        return PolicyDecision(allowed=len(reasons) == 0, reasons=reasons)
