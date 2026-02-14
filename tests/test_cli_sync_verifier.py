from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from pilot.cli import main


class CliSyncVerifierTests(unittest.TestCase):
    def _run_capture(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _run(self, argv: list[str]) -> int:
        rc, _, _ = self._run_capture(argv)
        return rc

    def test_sync_command_generates_index(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                Path("main.py").write_text("print('sync')\n", encoding="utf-8")
                self.assertEqual(self._run(["sync"]), 0)
                self.assertTrue(Path(".pilot/index/manifest.json").exists())
                self.assertTrue(Path(".pilot/index/context.md").exists())
        finally:
            os.chdir(original_cwd)

    def test_verifier_requires_git_repo(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["new", "Verifier task", "--id", "v-task"]), 0
                )
                self.assertEqual(self._run(["verifier", "v-task", "--dry-run"]), 1)
        finally:
            os.chdir(original_cwd)

    def test_verifier_runs_in_isolated_worktree(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                subprocess.run(
                    ["git", "init"], check=True, capture_output=True, text=True
                )
                subprocess.run(
                    ["git", "config", "user.email", "you@example.com"], check=True
                )
                subprocess.run(["git", "config", "user.name", "Your Name"], check=True)
                Path("README.md").write_text("# repo\n", encoding="utf-8")
                subprocess.run(["git", "add", "README.md"], check=True)
                subprocess.run(
                    ["git", "commit", "-m", "init"],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(self._run(["init", "--provider", "codex"]), 0)
                self.assertEqual(
                    self._run(["new", "Verifier task", "--id", "v-task"]), 0
                )
                self.assertEqual(
                    self._run(
                        [
                            "verifier",
                            "v-task",
                            "--skip-gates",
                            "--skip-provider",
                        ]
                    ),
                    0,
                )
                rc, out, _ = self._run_capture(["show", "v-task"])
                self.assertEqual(rc, 0)
                self.assertIn("verifier_runs:", out)
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
