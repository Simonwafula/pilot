from __future__ import annotations

import unittest
from unittest.mock import patch

from pilot.audit import AuditCheck, audit_task, audit_workspace, evaluate_done
from pilot.models import Config, QualityResult, Task


class AuditTests(unittest.TestCase):
    def test_evaluate_done_respects_strict_warnings(self) -> None:
        checks = [
            AuditCheck("a", "pass", "ok"),
            AuditCheck("b", "warn", "warning"),
        ]
        self.assertTrue(evaluate_done(checks, strict=False))
        self.assertFalse(evaluate_done(checks, strict=True))

    def test_task_audit_passes_when_complete(self) -> None:
        config = Config(
            provider="codex",
            quality_gates=[{"name": "test", "command": "pytest -q"}],
        )
        task = Task(
            id="task-1",
            title="done",
            status="completed",
            phase="complete",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step"],
            handoff_file=".pilot/handoffs/task-1.md",
            quality_results=[
                QualityResult(
                    name="test",
                    command="pytest -q",
                    exit_code=0,
                    success=True,
                    duration_seconds=0.1,
                    ran_at="2026-02-14T00:00:10+00:00",
                )
            ],
        )
        with (
            patch(
                "pilot.audit.task_idea_compliance",
                return_value=(True, "idea pipeline passed"),
            ),
            patch(
                "pilot.audit.tdd_readiness",
                return_value=(True, "tdd cycle complete"),
            ),
        ):
            report = audit_task(task, config, gate_results=None, strict=False)
        self.assertTrue(report.done)
        self.assertEqual(report.summary["fail"], 0)

    def test_task_audit_fails_when_idea_pipeline_missing(self) -> None:
        config = Config(
            provider="codex",
            quality_gates=[],
        )
        task = Task(
            id="task-2",
            title="incomplete ideation",
            status="completed",
            phase="complete",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
        )
        with (
            patch(
                "pilot.audit.task_idea_compliance",
                return_value=(False, "No idea record found for this task."),
            ),
            patch(
                "pilot.audit.tdd_readiness", return_value=(True, "tdd cycle complete")
            ),
        ):
            report = audit_task(task, config, gate_results=None, strict=False)
        self.assertFalse(report.done)
        idea_check = next(
            item for item in report.checks if item.name == "idea_pipeline"
        )
        self.assertEqual(idea_check.status, "fail")

    def test_workspace_audit_warns_when_gates_not_run(self) -> None:
        config = Config(
            provider="codex",
            quality_gates=[{"name": "lint", "command": "ruff check ."}],
        )
        report = audit_workspace(config, gate_results=None, strict=False, dry_run=False)
        names = [check.name for check in report.checks]
        self.assertIn("quality_gate_execution", names)


if __name__ == "__main__":
    unittest.main()
