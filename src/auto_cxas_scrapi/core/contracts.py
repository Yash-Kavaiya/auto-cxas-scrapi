from __future__ import annotations

from abc import ABC, abstractmethod

from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentResult, ScoreCard


class Planner(ABC):
    @abstractmethod
    def propose(self, *, context: dict) -> list[ExperimentCandidate]:
        raise NotImplementedError


class Runner(ABC):
    @abstractmethod
    def run(self, candidate: ExperimentCandidate) -> ExperimentResult:
        raise NotImplementedError


class Scorer(ABC):
    @abstractmethod
    def score(self, result: ExperimentResult) -> ScoreCard:
        raise NotImplementedError
