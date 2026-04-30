from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any


class ExperimentStatus(str, Enum):
    proposed  = "proposed"
    running   = "running"
    passed    = "passed"
    failed    = "failed"
    promoted  = "promoted"
    rejected  = "rejected"
    crashed   = "crashed"
    keep      = "keep"
    discard   = "discard"


@dataclass(slots=True)
class ScoreCard:
    score: float
    metrics: dict[str, float] = field(default_factory=dict)
    rationale: str = ""


@dataclass(slots=True)
class ExperimentCandidate:
    experiment_id: str
    title: str
    hypothesis: str
    target_resource: str
    mutation: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ExperimentResult:
    experiment_id: str
    status: ExperimentStatus
    scorecard: ScoreCard | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
