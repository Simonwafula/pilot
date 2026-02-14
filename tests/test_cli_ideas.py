from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest

from pilot.cli import main


class CliIdeasTests(unittest.TestCase):
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

    def test_suggest_challenge_reply_and_listing(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["new", "Idea workflow task", "--id", "idea-task"]), 0
                )

                rc, out, _ = self._run_capture(
                    [
                        "suggest",
                        "Improve onboarding",
                        "Propose feature paths and verify them adversarially.",
                        "--task-id",
                        "idea-task",
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
                            "We will test assumptions with user interviews and a pilot.",
                        ]
                    ),
                    0,
                )
                self.assertEqual(self._run(["ideas", "--task-id", "idea-task"]), 0)
                self.assertEqual(self._run(["idea-show", idea_id]), 0)
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
