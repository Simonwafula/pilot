from __future__ import annotations

import unittest
from unittest.mock import patch

from pilot.models import Config, QualityResult, Task
from pilot.workflow import advance_phase, apply_quality_results, phase_report, render_handoff, set_phase


class WorkflowTests(unittest.TestCase):
    def test_apply_quality_results_sets_blocked_on_failure(self) -> None:
        task = Task(
            id="task-1",
            title="test task",
            status="in_progress",
            phase="implement",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
        )
        results = [
            QualityResult(
                name="lint",
                command="echo lint",
                exit_code=1,
                success=False,
                duration_seconds=0.1,
                ran_at="2026-02-14T00:01:00+00:00",
            )
        ]
        apply_quality_results(task, results)
        self.assertEqual(task.status, "blocked")
        self.assertEqual(len(task.quality_results), 1)

    def test_render_handoff_includes_expected_sections(self) -> None:
        task = Task(
            id="task-2",
            title="handoff task",
            status="verifying",
            phase="verify",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step 1"],
            notes=["note 1"],
        )
        markdown = render_handoff(task, "codex", ".pilot/handoffs/task-2.md")
        self.assertIn("# Task Handoff: task-2", markdown)
        self.assertIn("## Snapshot", markdown)
        self.assertIn("## Plan", markdown)
        self.assertIn("## Notes", markdown)
        self.assertIn("## Quality Gates (latest)", markdown)
        self.assertIn("## Resume Hint", markdown)
        self.assertIn("codex", markdown)
        self.assertIn("- Phase: verify", markdown)

    def test_set_phase_blocks_skip_without_force(self) -> None:
        task = Task(
            id="task-3",
            title="phase task",
            status="planned",
            phase="discover",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
        )
        config = Config(provider="codex", quality_gates=[])
        with self.assertRaises(ValueError):
            set_phase(task, "implement", config=config)

    def test_set_phase_requires_plan_steps_for_implement(self) -> None:
        task = Task(
            id="task-4",
            title="phase task",
            status="planned",
            phase="plan",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
        )
        config = Config(provider="codex", quality_gates=[])
        with self.assertRaises(ValueError):
            set_phase(task, "implement", config=config)

    def test_complete_phase_requires_passing_quality(self) -> None:
        task = Task(
            id="task-5",
            title="phase task",
            status="verifying",
            phase="verify",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step 1"],
            quality_results=[
                QualityResult(
                    name="test",
                    command="pytest -q",
                    exit_code=1,
                    success=False,
                    duration_seconds=0.5,
                    ran_at="2026-02-14T00:01:00+00:00",
                )
            ],
        )
        config = Config(
            provider="codex",
            quality_gates=[{"name": "test", "command": "pytest -q"}],
        )
        with self.assertRaises(ValueError):
            set_phase(task, "complete", config=config)

    def test_advance_phase_sets_status(self) -> None:
        task = Task(
            id="task-6",
            title="phase task",
            status="planned",
            phase="plan",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step 1"],
        )
        config = Config(provider="codex", quality_gates=[])
        with patch("pilot.workflow.task_idea_compliance", return_value=(True, "idea pipeline passed")):
            transition = advance_phase(task, config=config)
        self.assertEqual(transition, "plan -> implement")
        self.assertEqual(task.phase, "implement")
        self.assertEqual(task.status, "in_progress")

    def test_set_phase_requires_idea_pipeline_for_implement(self) -> None:
        task = Task(
            id="task-8",
            title="idea gate task",
            status="planned",
            phase="plan",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step 1"],
        )
        config = Config(provider="codex", quality_gates=[])
        with patch(
            "pilot.workflow.task_idea_compliance",
            return_value=(False, "No idea record found for this task."),
        ):
            with self.assertRaises(ValueError):
                set_phase(task, "implement", config=config)

    def test_complete_phase_blocked_when_task_status_blocked(self) -> None:
        task = Task(
            id="task-7",
            title="blocked task",
            status="blocked",
            phase="verify",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            quality_results=[
                QualityResult(
                    name="test",
                    command="pytest -q",
                    exit_code=0,
                    success=True,
                    duration_seconds=0.1,
                    ran_at="2026-02-14T00:01:00+00:00",
                )
            ],
        )
        config = Config(
            provider="codex",
            quality_gates=[{"name": "test", "command": "pytest -q"}],
        )
        with self.assertRaises(ValueError):
            set_phase(task, "complete", config=config)
        report = phase_report(task, config=config)
        self.assertIn("Task status is blocked.", report["blocking_reasons"])

    def test_verify_phase_requires_completed_tdd_cycle(self) -> None:
        task = Task(
            id="task-9",
            title="tdd gate task",
            status="in_progress",
            phase="implement",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
            plan_steps=["step 1"],
        )
        config = Config(provider="codex", quality_gates=[])
        with self.assertRaises(ValueError):
            set_phase(task, "verify", config=config)


if __name__ == "__main__":
    unittest.main()
