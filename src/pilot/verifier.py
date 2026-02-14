from __future__ import annotations

import secrets
import subprocess
import time
from pathlib import Path

from .models import Config, QualityResult, utc_now_iso
from .state import VERIFIER_DIR, ensure_layout


def ensure_git_repo(cwd: Path | None = None) -> Path:
    root = git_root(cwd=cwd)
    if not root.exists():
        raise FileNotFoundError("Git root path does not exist.")
    return root


def git_root(cwd: Path | None = None) -> Path:
    completed = _run_git(
        ["rev-parse", "--show-toplevel"],
        cwd=cwd,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("Verifier lane requires a git repository.")
    path = (completed.stdout or "").strip()
    if not path:
        raise ValueError("Unable to resolve git root for verifier lane.")
    return Path(path)


def create_worktree(
    task_id: str, *, base_ref: str = "HEAD", cwd: Path | None = None
) -> Path:
    ensure_layout()
    root = ensure_git_repo(cwd=cwd)
    verifier_root = root / VERIFIER_DIR
    verifier_root.mkdir(parents=True, exist_ok=True)
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    lane_id = f"{task_id}-{stamp}-{secrets.token_hex(2)}"
    path = verifier_root / lane_id
    _run_git(["worktree", "add", "--detach", str(path), base_ref], cwd=root, check=True)
    return path


def remove_worktree(path: Path, *, cwd: Path | None = None) -> None:
    root = ensure_git_repo(cwd=cwd)
    _run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=True)


def run_quality_gates_in_dir(
    config: Config,
    *,
    cwd: Path,
    gate_name: str | None = None,
    dry_run: bool = False,
) -> list[QualityResult]:
    gates = config.quality_gates
    if gate_name:
        gates = [gate for gate in gates if gate.get("name") == gate_name]
        if not gates:
            raise ValueError(f"Gate '{gate_name}' not found in .pilot/config.json.")
    results: list[QualityResult] = []
    for gate in gates:
        name = gate["name"]
        command = gate["command"]
        if dry_run:
            results.append(
                QualityResult(
                    name=name,
                    command=command,
                    exit_code=0,
                    success=True,
                    duration_seconds=0.0,
                    ran_at=utc_now_iso(),
                    stdout="dry-run",
                    stderr="",
                )
            )
            continue
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
        elapsed = time.perf_counter() - started
        results.append(
            QualityResult(
                name=name,
                command=command,
                exit_code=completed.returncode,
                success=completed.returncode == 0,
                duration_seconds=round(elapsed, 3),
                ran_at=utc_now_iso(),
                stdout=(completed.stdout or "").strip(),
                stderr=(completed.stderr or "").strip(),
            )
        )
    return results


def _run_git(
    args: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"`{' '.join(command)}` failed: {stderr or completed.returncode}"
        )
    return completed
