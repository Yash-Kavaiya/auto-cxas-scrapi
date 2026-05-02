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
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from auto_cxas_scrapi.config.settings import get_settings
from auto_cxas_scrapi.observability.logging import configure_logging
from auto_cxas_scrapi.services.orchestrator import AutoCXASOrchestrator

console = Console()
RESULTS_TSV = Path("results.tsv")
TSV_HEADER = "commit\teval_score\ttask_success\tlatency_ms_p95\ttool_error_rate\tstatus\tdescription\ttimestamp\n"


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
            return json.loads(result_path.read_text("utf-8"))
        return {"eval_score": 0.0, "task_success": 0.0,
                "latency_ms_p95": 9999, "tool_error_rate": 1.0,
                "error": proc.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"eval_score": 0.0, "error": "evaluate.py timed out"}
    except Exception as exc:
        return {"eval_score": 0.0, "error": str(exc)}


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

        # --- Keep / Discard ---
        improved = delta >= settings.min_score_delta
        if improved and settings.approval_mode == "auto":
            status = "keep"
            baseline_score = candidate_score
            n_keep += 1
            console.print("[green]KEEP — score improved.[/green]")
        elif improved and settings.approval_mode == "manual":
            console.print(
                "[yellow]Score improved but approval_mode=manual. "
                "Run `auto-cxas promote` to apply.[/yellow]"
            )
            status = "keep"
            n_keep += 1
        else:
            _git_reset_last_commit()
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
