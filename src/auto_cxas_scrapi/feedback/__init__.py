"""Feedback loop — turns failures (eval + production) into new benchmark tests.

This package implements the missing arrow of the eval loop: failures and
thumbs-down become new test cases that grow the benchmark over time.
"""
from __future__ import annotations

from auto_cxas_scrapi.feedback.benchmark import BenchmarkManager, candidate_signature
from auto_cxas_scrapi.feedback.ingest import FeedbackIngestor

__all__ = ["BenchmarkManager", "FeedbackIngestor", "candidate_signature"]
