"""GitHub CLI adapter — uses `gh` CLI for branch/PR management."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitHubAdapter:
    def __init__(self, *, repo_dir: Path | None = None) -> None:
        self.repo_dir = repo_dir or Path.cwd()

    def _gh(self, *args: str) -> str:
        result = subprocess.run(
            ["gh", *args],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh {args!r} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def is_available(self) -> bool:
        try:
            self._gh("--version")
            return True
        except (FileNotFoundError, RuntimeError):
            return False

    def create_pr(self, *, title: str, body: str, base: str = "main") -> str:
        return self._gh(
            "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base,
        )

    def get_pr_status(self, pr_number: int) -> dict:
        raw = self._gh("pr", "view", str(pr_number), "--json",
                       "state,title,headRefName,mergeable,statusCheckRollup")
        import json
        return json.loads(raw)

    def merge_pr(self, pr_number: int, method: str = "squash") -> str:
        return self._gh("pr", "merge", str(pr_number), f"--{method}")

    def label_pr(self, pr_number: int, label: str) -> str:
        return self._gh("pr", "edit", str(pr_number), "--add-label", label)
