from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest

from pilot.cli import main


class CliAiModesTests(unittest.TestCase):
    def _run_capture(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _run(self, argv: list[str]) -> int:
        rc, _, _ = self._run_capture(argv)
        return rc

    def test_plan_ai_and_audit_ai_dry_run(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["new", "AI planning task", "--id", "ai-task"]), 0
                )
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "ai-task"]), 0
                )
                self.assertEqual(self._run(["plan", "ai-task", "Scope feature"]), 0)
                self.assertEqual(
                    self._run(["spec", "advance", "--task-id", "ai-task", "--force"]), 0
                )

                rc, out, _ = self._run_capture(["plan-ai", "ai-task", "--dry-run"])
                self.assertEqual(rc, 0)
                self.assertIn("profile_context: plan", out)

                rc, out, _ = self._run_capture(["audit-ai", "ai-task", "--dry-run"])
                self.assertEqual(rc, 0)
                self.assertIn("profile_context: audit", out)
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
