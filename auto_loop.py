#!/usr/bin/env python3
"""
auto_loop.py — Autonomous experiment loop for auto-cxas-scrapi.

This is the standalone script that runs the full
  propose → commit → eval → keep/discard
loop indefinitely (or up to --max-experiments).

Usage::

    python auto_loop.py                          # default
    python auto_loop.py --dry-run                # no live CXAS calls
    python auto_loop.py --max-experiments 20     # stop after 20
    python auto_loop.py --tag "sprint-42"        # label runs in results.tsv

See program.md for the full strategy guide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from auto_cxas_scrapi.config.settings import get_settings
from auto_cxas_scrapi.feedback import BenchmarkManager, FeedbackIngestor
from auto_cxas_scrapi.observability.logging import configure_logging
from auto_cxas_scrapi.services.orchestrator import AutoCXASOrchestrator

console = Console()
RESULTS_TSV = Path("results.tsv")
TSV_HEADER = "commit\teval_score\ttask_success\tlatency_ms_p95\ttool_error_rate\tstatus\tdescription\ttimestamp\n"
TRIED_MUTATIONS_FILE = Path(".auto-cxas/state/tried_mutations.json")
GOLDEN_TESTS_FILE = Path("golden_tests.yaml")
GOLDEN_CANDIDATES_FILE = Path("golden_candidates.yaml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_results_tsv() -> None:
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text(TSV_HEADER, encoding="utf-8")


def _append_tsv(
    commit: str,
    eval_score: float,
    task_success: float,
    latency_p95: int,
    tool_error_rate: float,
    status: str,
    description: str,
) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = (
        f"{commit}\t{eval_score:.6f}\t{task_success:.4f}\t"
        f"{latency_p95}\t{tool_error_rate:.4f}\t"
        f"{status}\t{description}\t{ts}\n"
    )
    with RESULTS_TSV.open("a", encoding="utf-8") as fh:
        fh.write(row)


def _git_commit_hash() -> str:
    """Return the current HEAD commit short hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _git_commit_agent_config(description: str) -> bool:
    """Stage agent_config.py and commit.  Returns True on success."""
    try:
        subprocess.run(
            ["git", "add", "agent_config.py"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"exp: {description}"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        console.print(f"[yellow]git commit failed: {exc.stderr.decode().strip()}[/yellow]")
        return False


def _git_reset_last_commit() -> None:
    """Undo the last commit (keep working tree clean)."""
    try:
        subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]git reset failed: {exc.stderr.decode().strip()}[/red]")


def _load_tried_mutations() -> set[str]:
    """Load set of mutation signatures that have already been attempted."""
    if not TRIED_MUTATIONS_FILE.exists():
        return set()
    try:
        data = json.loads(TRIED_MUTATIONS_FILE.read_text("utf-8"))
        return set(data.get("signatures", []))
    except Exception:
        return set()


def _save_tried_mutation(signature: str) -> None:
    """Persist a mutation signature so we never re-try it."""
    tried = _load_tried_mutations()
    tried.add(signature)
    TRIED_MUTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRIED_MUTATIONS_FILE.write_text(
        json.dumps({"signatures": sorted(tried)}, indent=2),
        encoding="utf-8",
    )


def _mutation_signature(mutation: dict) -> str:
    """Deterministic hash of mutation fields for deduplication."""
    key = json.dumps({k: mutation.get(k, "") for k in ("type", "path", "operation", "value")}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _is_crashed_result(metrics: dict) -> bool:
    """Check if evaluation result indicates a crash or timeout."""
    error = metrics.get("error", "")
    if error:
        return True
    # If all metrics are at their worst possible values, likely a silent failure
    if metrics.get("eval_score", 1.0) == 0.0 and metrics.get("tool_error_rate", 0.0) == 1.0:
        return True
    return metrics.get("latency_ms_p95", 0) == 9999


def _run_evaluate(dry_run: bool) -> dict:
    """Run evaluate.py and return parsed metrics."""
    cmd = [sys.executable, "evaluate.py", "--output-json"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        state_dir = Path(".auto-cxas/state")
        result_path = state_dir / "last_result.json"
        if result_path.exists():
            metrics = json.loads(result_path.read_text("utf-8"))
            # Tag crashed results so they can be identified
            if _is_crashed_result(metrics):
                metrics["_crashed"] = True
            return metrics
        return {"eval_score": 0.0, "task_success": 0.0,
                "latency_ms_p95": 9999, "tool_error_rate": 1.0,
                "error": proc.stderr.strip(), "_crashed": True}
    except subprocess.TimeoutExpired:
        return {"eval_score": 0.0, "error": "evaluate.py timed out", "_crashed": True}
    except Exception as exc:
        return {"eval_score": 0.0, "error": str(exc), "_crashed": True}


def _run_feedback_cycle(
    orch: AutoCXASOrchestrator,
    bench: BenchmarkManager,
    ingestor: FeedbackIngestor,
    *,
    app_name: str,
    lookback_hours: int,
    max_conversations: int,
    dry_run: bool,
) -> None:
    """The missing eval-loop arrow: harvest failures → grow the benchmark.

    1. Pull recent CX Agent Studio conversations and stage production failures.
    2. Re-grade every staged candidate against the current agent (counts reproductions).
    3. Auto-promote candidates that have reproduced enough times into golden_tests.yaml.
    """
    try:
        new_candidates = ingestor.harvest(
            app_name=app_name,
            lookback_hours=lookback_hours,
            max_conversations=max_conversations,
        )
        added = bench.add_candidates(new_candidates)
        failed = bench.record_run(dry_run=dry_run)
        promoted = bench.promote()
    except Exception as exc:  # never let feedback harvesting break the loop
        console.print(f"[yellow]Feedback cycle failed (non-fatal): {exc}[/yellow]")
        return

    console.print(
        f"[magenta]Feedback:[/magenta] +{added} new candidate(s), "
        f"{failed} reproduced this run, {len(promoted)} promoted to benchmark."
    )
    if promoted:
        console.print(f"[green]Benchmark grew: {', '.join(promoted)}[/green]")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(
    *,
    tag: str = "",
    max_experiments: int = 1000,
    dry_run: bool = False,
    sleep_between: float = 2.0,
) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    orch = AutoCXASOrchestrator(settings)
    _ensure_results_tsv()

    # Feedback loop: failures (eval + production) become new benchmark tests.
    bench = BenchmarkManager(
        golden_path=GOLDEN_TESTS_FILE,
        candidates_path=GOLDEN_CANDIDATES_FILE,
        promote_threshold=settings.candidate_promote_threshold,
    )
    ingestor = FeedbackIngestor(orch.scrapi)

    console.print(Rule("[bold cyan]auto-cxas-scrapi autonomous loop[/bold cyan]"))
    console.print(f"  project : {settings.google_cloud_project or '[yellow]NOT SET[/yellow]'}")
    console.print(f"  app     : {settings.app_name or '[yellow]NOT SET[/yellow]'}")
    console.print(f"  llm     : {settings.llm_provider}/{settings.llm_model or 'auto'}")
    console.print(f"  mode    : {settings.approval_mode}  dry_run={dry_run}")
    console.print(f"  max_exp : {max_experiments}  tag={tag or 'none'}")
    console.print(Rule())

    # Capture baseline once
    baseline_score = orch.get_baseline_score()
    if baseline_score == 0.0:
        console.print("[yellow]No baseline found. Running initial evaluation...[/yellow]")
        metrics = _run_evaluate(dry_run)
        baseline_score = metrics.get("eval_score", 0.0)
        commit = _git_commit_hash()
        _append_tsv(
            commit=commit,
            eval_score=baseline_score,
            task_success=metrics.get("task_success", 0.0),
            latency_p95=metrics.get("latency_ms_p95", 0),
            tool_error_rate=metrics.get("tool_error_rate", 0.0),
            status="baseline",
            description="initial baseline",
        )
        console.print(f"[green]Baseline: {baseline_score:.6f}[/green]")

    n_exp = 0
    n_keep = 0
    n_discard = 0

    while n_exp < max_experiments:
        n_exp += 1
        console.print(Rule(f"[dim]Experiment {n_exp}/{max_experiments}[/dim]"))

        # --- Propose ---
        try:
            candidates = orch.propose()
        except Exception as exc:
            console.print(f"[red]propose() failed: {exc}[/red]")
            time.sleep(sleep_between)
            continue

        if not candidates:
            console.print("[yellow]No candidates proposed. Sleeping 10s...[/yellow]")
            time.sleep(10)
            continue

        candidate = candidates[0]
        console.print(f"[cyan]Candidate:[/cyan] {candidate.experiment_id}")
        console.print(f"  Title     : {candidate.title}")
        console.print(f"  Hypothesis: {candidate.hypothesis}")
        console.print(f"  Mutation  : {candidate.mutation}")

        # --- Deduplication: skip if this mutation signature was already tried ---
        mut_sig = _mutation_signature(candidate.mutation)
        tried_mutations = _load_tried_mutations()
        if mut_sig in tried_mutations:
            console.print(f"[yellow]Duplicate mutation detected (sig={mut_sig[:8]}...). Skipping.[/yellow]")
            continue

        # --- Write new agent_config.py from planner ---
        if candidate.new_agent_config_content:
            Path("agent_config.py").write_text(candidate.new_agent_config_content, encoding="utf-8")
            console.print("[dim]Wrote new agent_config.py from planner.[/dim]")

        # --- Commit mutation ---
        committed = _git_commit_agent_config(candidate.title)
        if not committed:
            console.print("[yellow]Nothing to commit (no diff). Skipping.[/yellow]")
            time.sleep(sleep_between)
            continue

        exp_commit = _git_commit_hash()

        # --- Evaluate ---
        console.print("[dim]Running evaluate.py...[/dim]")
        metrics = _run_evaluate(dry_run)
        candidate_score = metrics.get("eval_score", 0.0)
        task_success = metrics.get("task_success", 0.0)
        latency_p95 = metrics.get("latency_ms_p95", 0)
        tool_error_rate = metrics.get("tool_error_rate", 0.0)

        delta = candidate_score - baseline_score
        console.print(
            f"  [bold]score[/bold]={candidate_score:.6f}  "
            f"baseline={baseline_score:.6f}  "
            f"delta={delta:+.6f}"
        )

        # --- Check for crashed evaluations ---
        if metrics.get("_crashed"):
            console.print("[red]EVALUATION CRASHED — error in evaluate.py or timeout.[/red]")
            _git_reset_last_commit()
            _save_tried_mutation(mut_sig)
            status = "crashed"
            n_discard += 1
            desc = f"[{tag}] {candidate.title}" if tag else candidate.title
            _append_tsv(
                commit=exp_commit,
                eval_score=candidate_score,
                task_success=task_success,
                latency_p95=latency_p95,
                tool_error_rate=tool_error_rate,
                status=status,
                description=desc,
            )
            time.sleep(sleep_between)
            continue

        # --- Keep / Discard ---
        improved = delta >= settings.min_score_delta
        if improved:
            if settings.approval_mode == "auto":
                status = "keep"
                baseline_score = candidate_score
                n_keep += 1
                console.print("[green]KEEP — score improved.[/green]")
                _save_tried_mutation(mut_sig)  # Still record to prevent re-trying
            else:
                # manual mode: log the candidate but revert the commit
                # so the user can manually promote via CLI
                console.print(
                    "[yellow]Score improved but approval_mode=manual. "
                    "Reverting — apply with `auto-cxas promote --experiment <id>`.[/yellow]"
                )
                _git_reset_last_commit()
                status = "pending"
                baseline_score = candidate_score  # Track the improved baseline score
                n_keep += 1
        else:
            if not dry_run:
                console.print(
                    "[yellow]Warning: Live revert does NOT undo changes deployed to "
                    "CX Agent Studio. You may need to manually restore the previous "
                    "agent configuration in the GCP console.[/yellow]"
                )
            _git_reset_last_commit()
            _save_tried_mutation(mut_sig)
            status = "discard"
            n_discard += 1
            console.print("[red]DISCARD — no improvement. Reverted.[/red]")

        desc = f"[{tag}] {candidate.title}" if tag else candidate.title
        _append_tsv(
            commit=exp_commit,
            eval_score=candidate_score,
            task_success=task_success,
            latency_p95=latency_p95,
            tool_error_rate=tool_error_rate,
            status=status,
            description=desc,
        )

        console.print(
            f"  [dim]keep={n_keep}  discard={n_discard}  "
            f"total={n_exp}[/dim]"
        )

        # --- Feedback arrow: grow the benchmark from real failures ---
        if settings.feedback_ingest_every > 0 and n_exp % settings.feedback_ingest_every == 0:
            _run_feedback_cycle(
                orch,
                bench,
                ingestor,
                app_name=settings.app_name,
                lookback_hours=settings.feedback_lookback_hours,
                max_conversations=settings.feedback_max_conversations,
                dry_run=dry_run,
            )

        time.sleep(sleep_between)

    console.print(Rule("[bold green]Loop complete[/bold green]"))
    console.print(f"  experiments : {n_exp}")
    console.print(f"  keep        : {n_keep}")
    console.print(f"  discard     : {n_discard}")
    console.print(f"  final score : {baseline_score:.6f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Autonomous CXAS experiment loop",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--tag", default="", help="Run tag for TSV labeling")
    ap.add_argument("--max-experiments", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true",
                    help="Use dry-run evaluate.py (no live CXAS calls)")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="Seconds between experiments")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run_loop(
            tag=args.tag,
            max_experiments=args.max_experiments,
            dry_run=args.dry_run,
            sleep_between=args.sleep,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(0)
