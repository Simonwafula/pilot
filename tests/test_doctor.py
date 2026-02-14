from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pilot.doctor import (
    _command_executable,
    _is_shell_builtin,
    apply_fixes,
    sanitize_hook_commands,
    sanitize_provider_profiles,
    sanitize_quality_gates,
    summarize,
)


class DoctorTests(unittest.TestCase):
    def test_command_executable_parses_shell_command(self) -> None:
        self.assertEqual(_command_executable("pytest -q"), "pytest")
        self.assertEqual(_command_executable("python -m unittest"), "python")
        self.assertEqual(_command_executable(""), None)

    def test_shell_builtin_detection(self) -> None:
        self.assertTrue(_is_shell_builtin("echo"))
        self.assertFalse(_is_shell_builtin("pytest"))

    def test_summarize_counts_statuses(self) -> None:
        class _R:
            def __init__(self, status: str) -> None:
                self.status = status

        results = [_R("pass"), _R("warn"), _R("fail"), _R("pass")]
        counts = summarize(results)  # type: ignore[arg-type]
        self.assertEqual(counts["pass"], 2)
        self.assertEqual(counts["warn"], 1)
        self.assertEqual(counts["fail"], 1)

    def test_sanitize_quality_gates_filters_invalid_entries(self) -> None:
        raw = [
            {"name": "test", "command": "pytest -q"},
            {"name": "", "command": "ruff check ."},
            {"name": "lint", "command": ""},
            {"name": "fmt", "command": "ruff format ."},
        ]
        cleaned = sanitize_quality_gates(raw)
        self.assertEqual(
            cleaned,
            [
                {"name": "test", "command": "pytest -q"},
                {"name": "fmt", "command": "ruff format ."},
            ],
        )

    def test_sanitize_hook_commands_filters_invalid_entries(self) -> None:
        raw = ["pytest -q", "", "   ", "ruff check ."]
        cleaned = sanitize_hook_commands(raw)
        self.assertEqual(cleaned, ["pytest -q", "ruff check ."])

    def test_sanitize_provider_profiles_filters_invalid_entries(self) -> None:
        raw = {
            "plan": {
                "codex": {"model": "o3", "reasoning_effort": True},
                "opencode": {"variant": ""},
            },
            "": {"codex": {"model": "o4"}},
        }
        cleaned = sanitize_provider_profiles(raw)  # type: ignore[arg-type]
        self.assertEqual(
            cleaned,
            {
                "plan": {
                    "codex": {"model": "o3", "reasoning_effort": "true"},
                }
            },
        )

    def test_apply_fixes_creates_config_when_missing(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                config, actions = apply_fixes(preferred_provider="opencode")
                self.assertTrue(Path(".pilot/config.json").exists())
                self.assertEqual(config.provider, "opencode")
                self.assertTrue(any(action.name == "config" for action in actions))
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
