from __future__ import annotations

import subprocess
import time

from .ideas import task_idea_compliance
from .models import Config, QualityResult, Task, utc_now_iso
from .providers import command_hint

VALID_STATUSES = {"planned", "in_progress", "blocked", "verifying", "completed"}
SPEC_PHASES = ("discover", "plan", "implement", "verify", "complete")
PHASE_TO_STATUS = {
    "discover": "planned",
    "plan": "planned",
    "implement": "in_progress",
    "verify": "verifying",
    "complete": "completed",
}


def set_status(task: Task, status: str) -> None:
    if status not in VALID_STATUSES:
        valid = ", ".join(sorted(VALID_STATUSES))
        raise ValueError(f"Invalid status '{status}'. Valid statuses: {valid}.")
    task.status = status
    if status == "completed":
        task.phase = "complete"
    elif status == "verifying":
        task.phase = "verify"
    elif status == "in_progress" and _phase_index(task.phase) < _phase_index(
        "implement"
    ):
        task.phase = "implement"
    elif status == "planned" and _phase_index(task.phase) > _phase_index("plan"):
        task.phase = "plan"
    task.touch()


def add_plan_step(task: Task, step: str) -> None:
    task.plan_steps.append(step)
    task.touch()


def add_note(task: Task, note: str) -> None:
    task.notes.append(note)
    task.touch()


def phase_report(task: Task, config: Config | None = None) -> dict[str, object]:
    current = normalize_phase(task.phase)
    next_phase = next_phase_name(current)
    blocking_reasons: list[str] = []
    if next_phase == "implement":
        if not task.plan_steps:
            blocking_reasons.append(
                "At least one plan step is required before entering implement."
            )
        idea_ok, idea_detail = task_idea_compliance(task.id)
        if not idea_ok:
            blocking_reasons.append(f"Idea pipeline is incomplete. {idea_detail}")
    if next_phase == "verify":
        tdd_ok, tdd_detail = tdd_readiness(task)
        if not tdd_ok:
            blocking_reasons.append(tdd_detail)
    if next_phase == "complete":
        tdd_ok, tdd_detail = tdd_readiness(task)
        if not tdd_ok:
            blocking_reasons.append(tdd_detail)
        if task.status == "blocked":
            blocking_reasons.append("Task status is blocked.")
        if config is None:
            blocking_reasons.append("Config is required to evaluate completion gates.")
        else:
            _, reasons = completion_readiness(task, config)
            blocking_reasons.extend(reasons)
    return {
        "phase": current,
        "status": task.status,
        "next_phase": next_phase,
        "blocking_reasons": blocking_reasons,
    }


def advance_phase(task: Task, config: Config, force: bool = False) -> str:
    current = normalize_phase(task.phase)
    target = next_phase_name(current)
    if target is None:
        raise ValueError("Task is already in final phase 'complete'.")
    return set_phase(task, target, config=config, force=force)


def set_phase(task: Task, phase: str, config: Config, force: bool = False) -> str:
    current = normalize_phase(task.phase)
    target = normalize_phase(phase)
    if current == target:
        return f"Task already in phase '{target}'."

    current_index = _phase_index(current)
    target_index = _phase_index(target)
    if not force:
        if target_index < current_index:
            raise ValueError(
                f"Cannot move backward from '{current}' to '{target}' without --force."
            )
        if target_index > current_index + 1:
            raise ValueError(
                f"Cannot skip phases from '{current}' to '{target}'. Advance sequentially or use --force."
            )
        _validate_phase_gate(task, target, config)

    task.phase = target
    task.status = PHASE_TO_STATUS[target]
    task.touch()
    return f"{current} -> {target}"


def completion_readiness(task: Task, config: Config) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    required_gate_names = [
        gate.get("name", "") for gate in config.quality_gates if gate.get("name")
    ]
    if not required_gate_names:
        return True, reasons

    latest_by_name: dict[str, QualityResult] = {}
    for result in task.quality_results:
        latest_by_name[result.name] = result

    for gate_name in required_gate_names:
        result = latest_by_name.get(gate_name)
        if result is None:
            reasons.append(f"Quality gate '{gate_name}' has not been run.")
            continue
        if not result.success:
            reasons.append(
                f"Quality gate '{gate_name}' is failing (exit code {result.exit_code})."
            )

    return len(reasons) == 0, reasons


def tdd_readiness(task: Task) -> tuple[bool, str]:
    for cycle in reversed(task.tdd_cycles):
        if not isinstance(cycle, dict):
            continue
        if cycle.get("status") == "completed":
            cycle_id = str(cycle.get("id", "(unknown)"))
            return True, f"Completed TDD cycle `{cycle_id}` found."
    return (
        False,
        "No completed TDD cycle found. Run `pilot tdd red`, `pilot tdd green`, and `pilot tdd refactor`.",
    )


def run_quality_gates(
    config: Config, gate_name: str | None = None, dry_run: bool = False
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
            result = QualityResult(
                name=name,
                command=command,
                exit_code=0,
                success=True,
                duration_seconds=0.0,
                ran_at=utc_now_iso(),
                stdout="dry-run",
                stderr="",
            )
            results.append(result)
            continue

        started = time.perf_counter()
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
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
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        )
    return results


def apply_quality_results(task: Task, results: list[QualityResult]) -> None:
    task.quality_results.extend(results)
    task.touch()
    if not results:
        return
    if all(result.success for result in results):
        if task.status in {"planned", "in_progress", "blocked"}:
            task.status = "verifying"
            if _phase_index(task.phase) < _phase_index("verify"):
                task.phase = "verify"
    else:
        task.status = "blocked"


def render_handoff(
    task: Task, provider: str, handoff_file: str, extra_notes: str = ""
) -> str:
    plan_lines = (
        [f"- {item}" for item in task.plan_steps] if task.plan_steps else ["- (none)"]
    )
    note_lines = (
        [f"- {item}" for item in task.notes[-10:]] if task.notes else ["- (none)"]
    )
    quality_lines = _render_quality_summary(task)
    resume_hint = command_hint(provider, task, handoff_file)
    lines = [
        f"# Task Handoff: {task.id}",
        "",
        "## Snapshot",
        f"- Title: {task.title}",
        f"- Status: {task.status}",
        f"- Phase: {task.phase}",
        f"- Created: {task.created_at}",
        f"- Updated: {task.updated_at}",
        "",
        "## Plan",
        *plan_lines,
        "",
        "## Notes",
        *note_lines,
        "",
        "## Quality Gates (latest)",
        *quality_lines.splitlines(),
        "",
        "## Resume Hint",
        "```bash",
        resume_hint,
        "```",
    ]
    if extra_notes:
        lines.extend(["", "## Extra Notes", extra_notes.strip()])
    return "\n".join(lines).rstrip() + "\n"


def _render_quality_summary(task: Task) -> str:
    if not task.quality_results:
        return "- No quality gate runs yet."
    last_by_name: dict[str, QualityResult] = {}
    for result in task.quality_results:
        last_by_name[result.name] = result
    lines = []
    for name in sorted(last_by_name):
        result = last_by_name[name]
        status = "PASS" if result.success else "FAIL"
        lines.append(
            f"- {name}: {status} (code={result.exit_code}, duration={result.duration_seconds}s, at={result.ran_at})"
        )
    return "\n".join(lines)


def normalize_phase(phase: str) -> str:
    normalized = (phase or "").strip().lower()
    if normalized not in SPEC_PHASES:
        options = ", ".join(SPEC_PHASES)
        raise ValueError(f"Invalid phase '{phase}'. Valid phases: {options}.")
    return normalized


def next_phase_name(phase: str) -> str | None:
    normalized = normalize_phase(phase)
    index = _phase_index(normalized)
    if index >= len(SPEC_PHASES) - 1:
        return None
    return SPEC_PHASES[index + 1]


def _phase_index(phase: str) -> int:
    return SPEC_PHASES.index(normalize_phase(phase))


def _validate_phase_gate(task: Task, target: str, config: Config) -> None:
    if target == "implement":
        if not task.plan_steps:
            raise ValueError("Cannot enter 'implement' without at least one plan step.")
        idea_ok, idea_detail = task_idea_compliance(task.id)
        if not idea_ok:
            raise ValueError(
                "Cannot enter 'implement' before idea pipeline passes. "
                + idea_detail
                + " Run `pilot suggest`, `pilot challenge`, and `pilot reply` first."
            )
    if target == "complete":
        tdd_ready_flag, tdd_detail = tdd_readiness(task)
        if not tdd_ready_flag:
            raise ValueError(f"Cannot enter 'complete'. {tdd_detail}")
        if task.status == "blocked":
            raise ValueError("Cannot enter 'complete' while task status is 'blocked'.")
        ready, reasons = completion_readiness(task, config)
        if not ready:
            joined = " ".join(reasons)
            raise ValueError(f"Cannot enter 'complete'. {joined}")
    if target == "verify":
        ready, detail = tdd_readiness(task)
        if not ready:
            raise ValueError(f"Cannot enter 'verify'. {detail}")
