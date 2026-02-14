from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ideas import task_idea_compliance
from .models import Config, QualityResult, Task
from .state import ROOT_DIR
from .workflow import completion_readiness, tdd_readiness


@dataclass
class AuditCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class AuditReport:
    target: str
    target_id: str | None
    checks: list[AuditCheck]
    summary: dict[str, int]
    done: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "target_id": self.target_id,
            "checks": [check.to_dict() for check in self.checks],
            "summary": self.summary,
            "done": self.done,
        }


def audit_task(
    task: Task,
    config: Config,
    *,
    gate_results: list[QualityResult] | None = None,
    strict: bool = False,
) -> AuditReport:
    checks: list[AuditCheck] = []

    checks.append(
        _check(
            "task_status",
            task.status == "completed",
            f"Task status is `{task.status}` (expected `completed`).",
        )
    )
    checks.append(
        _check(
            "task_phase",
            task.phase == "complete",
            f"Task phase is `{task.phase}` (expected `complete`).",
        )
    )
    idea_ok, idea_detail = task_idea_compliance(task.id)
    checks.append(_check("idea_pipeline", idea_ok, idea_detail))
    tdd_ok, tdd_detail = tdd_readiness(task)
    checks.append(_check("tdd_cycle", tdd_ok, tdd_detail))

    ready, reasons = completion_readiness(task, config)
    if ready:
        checks.append(
            AuditCheck(
                "quality_readiness", "pass", "All configured quality gates are passing."
            )
        )
    else:
        checks.append(AuditCheck("quality_readiness", "fail", " ".join(reasons)))

    if task.plan_steps:
        checks.append(
            AuditCheck(
                "plan_steps", "pass", f"{len(task.plan_steps)} plan step(s) recorded."
            )
        )
    else:
        checks.append(AuditCheck("plan_steps", "warn", "No plan steps recorded."))

    if task.handoff_file and Path(task.handoff_file).exists():
        checks.append(
            AuditCheck(
                "handoff_file", "pass", f"Found handoff file `{task.handoff_file}`."
            )
        )
    else:
        checks.append(AuditCheck("handoff_file", "warn", "Handoff file is missing."))

    if task.provider_runs:
        checks.append(
            AuditCheck(
                "provider_runs",
                "pass",
                f"{len(task.provider_runs)} provider run(s) recorded.",
            )
        )
    else:
        checks.append(
            AuditCheck(
                "provider_runs",
                "warn",
                "No provider runs recorded (acceptable if implementation happened manually).",
            )
        )

    if not task.verifier_runs:
        checks.append(
            AuditCheck("verifier_lane", "warn", "No verifier lane runs recorded.")
        )
    else:
        latest_verifier = task.verifier_runs[-1]
        if bool(latest_verifier.get("success", False)):
            checks.append(
                AuditCheck(
                    "verifier_lane",
                    "pass",
                    "Latest verifier lane run passed.",
                )
            )
        else:
            checks.append(
                AuditCheck(
                    "verifier_lane",
                    "fail",
                    "Latest verifier lane run failed.",
                )
            )

    expected_hooks = len(config.pre_edit_hooks) + len(config.post_edit_hooks)
    if expected_hooks == 0:
        checks.append(
            AuditCheck("edit_hooks", "warn", "No pre/post edit hooks configured.")
        )
    elif not task.hook_runs:
        if task.provider_runs:
            checks.append(
                AuditCheck(
                    "edit_hooks",
                    "fail",
                    "Edit hooks are configured but no hook runs were recorded.",
                )
            )
        else:
            checks.append(
                AuditCheck(
                    "edit_hooks",
                    "warn",
                    "Edit hooks are configured but no provider runs were recorded; hook execution was likely skipped.",
                )
            )
    else:
        has_failed_hook = any(
            not bool(item.get("success", False)) for item in task.hook_runs
        )
        if has_failed_hook:
            checks.append(
                AuditCheck(
                    "edit_hooks", "fail", "At least one recorded edit hook failed."
                )
            )
        else:
            checks.append(
                AuditCheck(
                    "edit_hooks",
                    "pass",
                    f"{len(task.hook_runs)} edit hook run(s) recorded with no failures.",
                )
            )

    checks.extend(_gate_checks(gate_results))
    summary = summarize_checks(checks)
    done = evaluate_done(checks, strict=strict)
    return AuditReport(
        target="task", target_id=task.id, checks=checks, summary=summary, done=done
    )


def audit_workspace(
    config: Config,
    *,
    gate_results: list[QualityResult] | None = None,
    strict: bool = False,
    dry_run: bool = False,
) -> AuditReport:
    checks: list[AuditCheck] = []
    checks.append(
        AuditCheck("workspace_root", "pass", f"Using workspace `{ROOT_DIR}`.")
    )

    if config.quality_gates:
        checks.append(
            AuditCheck(
                "quality_gate_config",
                "pass",
                f"{len(config.quality_gates)} quality gate(s) configured.",
            )
        )
    else:
        checks.append(
            AuditCheck("quality_gate_config", "warn", "No quality gates configured.")
        )

    rules_file = ROOT_DIR / "templates" / "agent-rules.md"
    if rules_file.exists():
        checks.append(AuditCheck("agent_rules", "pass", f"Found `{rules_file}`."))
    else:
        checks.append(AuditCheck("agent_rules", "warn", f"Missing `{rules_file}`."))

    agents_file = Path("AGENTS.md")
    if agents_file.exists():
        content = agents_file.read_text(encoding="utf-8")
        begin = "<!-- pilot-core:begin -->"
        end = "<!-- pilot-core:end -->"
        if begin in content and end in content:
            checks.append(
                AuditCheck(
                    "agents_block", "pass", "Managed pilot block found in `AGENTS.md`."
                )
            )
        else:
            checks.append(
                AuditCheck(
                    "agents_block",
                    "warn",
                    "Managed pilot block missing in `AGENTS.md`.",
                )
            )
    else:
        checks.append(AuditCheck("agents_block", "warn", "`AGENTS.md` is missing."))

    if gate_results is None:
        checks.append(
            AuditCheck(
                "quality_gate_execution",
                "warn",
                "Quality gates were not executed in this audit run (use default behavior or omit --no-run-gates).",
            )
        )
    else:
        if dry_run:
            checks.append(
                AuditCheck(
                    "quality_gate_execution",
                    "warn",
                    "Quality gates ran in dry-run mode; results are simulated.",
                )
            )
        else:
            checks.append(
                AuditCheck(
                    "quality_gate_execution",
                    "pass",
                    "Quality gates executed during audit.",
                )
            )
        checks.extend(_gate_checks(gate_results))

    summary = summarize_checks(checks)
    done = evaluate_done(checks, strict=strict)
    return AuditReport(
        target="workspace", target_id=None, checks=checks, summary=summary, done=done
    )


def summarize_checks(checks: list[AuditCheck]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for check in checks:
        if check.status in counts:
            counts[check.status] += 1
    return counts


def evaluate_done(checks: list[AuditCheck], *, strict: bool = False) -> bool:
    has_fail = any(check.status == "fail" for check in checks)
    if has_fail:
        return False
    if strict and any(check.status == "warn" for check in checks):
        return False
    return True


def _check(name: str, condition: bool, detail: str) -> AuditCheck:
    return AuditCheck(name, "pass" if condition else "fail", detail)


def _gate_checks(gate_results: list[QualityResult] | None) -> list[AuditCheck]:
    checks: list[AuditCheck] = []
    if not gate_results:
        return checks
    for result in gate_results:
        status = "pass" if result.success else "fail"
        checks.append(
            AuditCheck(
                f"gate:{result.name}",
                status,
                f"exit={result.exit_code} duration={result.duration_seconds}s command={result.command}",
            )
        )
    return checks
