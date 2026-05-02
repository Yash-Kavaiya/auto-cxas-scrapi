"""auto-cxas CLI — Typer-based command interface."""
from __future__ import annotations

import json
import subprocess
import sys

import typer
from rich.console import Console

from auto_cxas_scrapi.config.settings import get_settings
from auto_cxas_scrapi.observability.logging import configure_logging
from auto_cxas_scrapi.services.orchestrator import AutoCXASOrchestrator

app = typer.Typer(
    name="auto-cxas",
    help="Autonomous CX Agent Studio optimization CLI",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _orch() -> AutoCXASOrchestrator:
    settings = get_settings()
    configure_logging(settings.log_level)
    return AutoCXASOrchestrator(settings)


@app.command()
def init() -> None:
    """Initialise directories and validate configuration."""
    settings = get_settings()
    console.print(f"[green]Initialized[/green] runs={settings.runs_dir} state={settings.state_dir}")
    console.print(f"  project: {settings.google_cloud_project or '[red]NOT SET[/red]'}")
    console.print(f"  app:     {settings.app_name or '[red]NOT SET[/red]'}")
    console.print(f"  llm:     {settings.llm_provider}/{settings.llm_model or 'auto'}")
    console.print(f"  mode:    {settings.approval_mode}")


@app.command()
def inventory() -> None:
    """List CXAS apps, agents, and tools from the live GCP project."""
    orch = _orch()
    data = orch.scrapi.get_inventory(orch.settings.app_name)
    console.print_json(json.dumps(data))


@app.command()
def lint() -> None:
    """Run cxas lint on the current agent_config.py."""
    orch = _orch()
    result = orch.scrapi.run_lint(orch.settings.app_name)
    console.print_json(json.dumps(result))
    if not result.get("lint_passed"):
        raise typer.Exit(1)


@app.command()
def baseline() -> None:
    """Capture a baseline eval_score from the current agent_config.py."""
    orch = _orch()
    orch.collect_baseline()
    console.print("[green]Baseline captured.[/green]")


@app.command()
def propose() -> None:
    """Generate experiment candidates using the configured LLM planner."""
    orch = _orch()
    candidates = orch.propose()
    for c in candidates:
        console.print(f"[cyan]{c.experiment_id}[/cyan] — {c.title}")
        console.print(f"  Hypothesis: {c.hypothesis}")


@app.command()
def run(
    experiment_id: str = typer.Argument(..., help="Experiment ID from `auto-cxas propose`"),
) -> None:
    """Execute a proposed experiment and record results."""
    orch = _orch()
    result = orch.run_experiment(experiment_id)
    console.print(f"Status: [bold]{result.status.value}[/bold]")


@app.command()
def score(
    experiment_id: str = typer.Argument(..., help="Experiment ID to score"),
) -> None:
    """Score a completed experiment and check promotion policy."""
    orch = _orch()
    report = orch.score_experiment(experiment_id)
    console.print_json(json.dumps(report))
    if report["policy"]["allowed"]:
        console.print("[green]Policy PASSED — run `auto-cxas promote` to apply.[/green]")
    else:
        console.print("[yellow]Policy BLOCKED:[/yellow]")
        for reason in report["policy"]["reasons"]:
            console.print(f"  * {reason}")


@app.command()
def promote(
    experiment_id: str = typer.Argument(..., help="Experiment ID to promote"),
) -> None:
    """Promote a passing experiment to the baseline state."""
    orch = _orch()
    try:
        result_data = orch.store.load_result(experiment_id)
    except FileNotFoundError:
        console.print(f"[red]No result found for {experiment_id}. Run `auto-cxas run {experiment_id}` first.[/red]")
        raise typer.Exit(1) from None
    report = orch.score_experiment(experiment_id)
    if not report["policy"]["allowed"] and orch.settings.approval_mode == "manual":
        console.print("[red]Promotion blocked by policy. Review score output first.[/red]")
        raise typer.Exit(1)
    baseline_path = orch.settings.state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps({**result_data.get("artifacts", {}),
                    "eval_score": report["score"]}, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]Promoted {experiment_id} as new baseline (score={report['score']:.6f}).[/green]")


@app.command()
def rollback(
    experiment_id: str = typer.Argument(..., help="Experiment ID to roll back"),
) -> None:
    """Revert an experiment by resetting to HEAD~1."""
    console.print(f"[yellow]Rolling back {experiment_id}...[/yellow]")
    try:
        subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print("[green]Rollback complete.[/green]")
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip()
        console.print(f"[red]Rollback failed: {error}[/red]")
        raise typer.Exit(1) from exc


@app.command()
def history() -> None:
    """Print the full experiment history as a rich table."""
    orch = _orch()
    orch.print_history()


@app.command()
def daemon(
    tag: str = typer.Option("", help="Run tag, e.g. apr30"),
    max_experiments: int = typer.Option(1000, help="Max experiments before stopping"),
    dry_run: bool = typer.Option(False, help="Simulate without live CXAS calls"),
) -> None:
    """Run the autonomous experiment loop indefinitely (Ctrl+C to stop)."""
    import subprocess
    cmd = [sys.executable, "auto_loop.py"]
    if tag:
        cmd += ["--tag", tag]
    cmd += ["--max-experiments", str(max_experiments)]
    if dry_run:
        cmd.append("--dry-run")
    console.print(f"[green]Starting daemon:[/green] {' '.join(cmd)}")
    subprocess.run(cmd)
