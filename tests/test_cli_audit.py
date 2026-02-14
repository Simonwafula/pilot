from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from pilot.cli import main


class CliAuditTests(unittest.TestCase):
    def _run_capture(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _run(self, argv: list[str]) -> int:
        rc, _, _ = self._run_capture(argv)
        return rc

    def _extract_idea_id(self, stdout: str) -> str:
        for line in stdout.splitlines():
            if line.startswith("idea_id: "):
                return line.split(": ", 1)[1].strip()
        self.fail("idea_id not found in command output")
        return ""

    def test_audit_fails_for_incomplete_task_and_passes_when_complete(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                config_path = Path(".pilot/config.json")
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config["quality_gates"] = [
                    {"name": "test", "command": "test ! -f .pilot/force_fail"}
                ]
                config_path.write_text(
                    json.dumps(config, indent=2) + "\n", encoding="utf-8"
                )
                self.assertEqual(
                    self._run(["new", "Audit test task", "--id", "audit-task"]), 0
                )

                # Incomplete task should fail audit.
                self.assertEqual(
                    self._run(["audit", "audit-task", "--no-run-gates"]), 1
                )

                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "audit-task"]), 0
                )
                self.assertEqual(self._run(["plan", "audit-task", "Define scope"]), 0)
                rc, out, _ = self._run_capture(
                    [
                        "suggest",
                        "Audit readiness gate",
                        "Route all features through suggestion and challenge modes.",
                        "--task-id",
                        "audit-task",
                    ]
                )
                self.assertEqual(rc, 0)
                idea_id = self._extract_idea_id(out)
                self.assertEqual(
                    self._run(["challenge", idea_id, "--persona", "Dr. Scrutiny"]), 0
                )
                self.assertEqual(
                    self._run(
                        [
                            "reply",
                            idea_id,
                            "--persona",
                            "Dr. Scrutiny",
                            "--response",
                            "Assumptions will be tracked and verified before release.",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "audit-task"]), 0
                )
                Path(".pilot/force_fail").write_text("1\n", encoding="utf-8")
                self.assertEqual(self._run(["tdd", "red", "audit-task"]), 0)
                Path(".pilot/force_fail").unlink()
                self.assertEqual(self._run(["tdd", "green", "audit-task"]), 0)
                self.assertEqual(self._run(["tdd", "refactor", "audit-task"]), 0)
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "audit-task"]), 0
                )
                self.assertEqual(self._run(["verify", "audit-task"]), 0)
                self.assertEqual(self._run(["audit", "audit-task"]), 0)
        finally:
            os.chdir(original_cwd)

    def test_workspace_audit_strict_fails_without_gate_execution(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["audit", "--workspace", "--strict", "--no-run-gates"]), 1
                )
                self.assertEqual(self._run(["audit", "--workspace"]), 0)
        finally:
            os.chdir(original_cwd)

    def test_spec_advance_to_implement_requires_idea_pipeline(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["new", "Spec gate task", "--id", "spec-task"]), 0
                )
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "spec-task"]), 0
                )
                self.assertEqual(self._run(["plan", "spec-task", "Define scope"]), 0)
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "spec-task"]), 1
                )
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
