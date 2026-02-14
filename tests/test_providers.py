from __future__ import annotations

import unittest

from pilot.models import Config, Task
from pilot.providers import (
    _clean_output,
    build_run_prompt,
    normalize_reasoning_effort,
    provider_command,
    resolve_provider_settings,
)


class ProviderTests(unittest.TestCase):
    def test_provider_command_for_codex(self) -> None:
        command = provider_command("codex", "hello")
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[1], "hello")

    def test_provider_command_for_opencode(self) -> None:
        command = provider_command("opencode", "hello")
        self.assertEqual(command[:2], ["opencode", "run"])
        self.assertEqual(command[2], "hello")

    def test_provider_command_accepts_settings(self) -> None:
        codex = provider_command("codex", "hello", settings={"model": "o3"})
        self.assertEqual(codex[:3], ["codex", "-m", "o3"])
        self.assertEqual(codex[-1], "hello")
        opencode = provider_command(
            "opencode",
            "hello",
            settings={"variant": "max", "thinking": "true"},
        )
        self.assertIn("--variant", opencode)
        self.assertIn("--thinking", opencode)

    def test_resolve_provider_settings_uses_defaults_and_overrides(self) -> None:
        default_config = Config(provider="opencode", quality_gates=[])
        default_settings = resolve_provider_settings(default_config, "plan")
        self.assertEqual(default_settings.get("model"), "glm-5")
        self.assertEqual(default_settings.get("variant"), "max")
        self.assertEqual(default_settings.get("thinking"), "true")
        codex_default = Config(provider="codex", quality_gates=[])
        codex_implement = resolve_provider_settings(codex_default, "implement")
        self.assertEqual(codex_implement.get("model"), "gpt-5.3-codex")
        self.assertEqual(codex_implement.get("reasoning_effort"), "medium")

        override_config = Config(
            provider="codex",
            quality_gates=[],
            provider_profiles={
                "plan": {"codex": {"model": "o4-mini"}},
            },
        )
        override_settings = resolve_provider_settings(override_config, "plan")
        self.assertEqual(override_settings, {"model": "o4-mini"})

    def test_build_run_prompt_includes_contract(self) -> None:
        task = Task(
            id="task-1",
            title="provider task",
            status="in_progress",
            phase="implement",
            created_at="2026-02-14T00:00:00+00:00",
            updated_at="2026-02-14T00:00:00+00:00",
        )
        prompt = build_run_prompt(
            "codex",
            task,
            ".pilot/handoffs/task-1.md",
            extra_instructions="Focus on tests first.",
        )
        self.assertIn("Resume task `task-1`", prompt)
        self.assertIn("Execution contract:", prompt)
        self.assertIn("Focus on tests first.", prompt)

    def test_clean_output_replaces_nulls_and_truncates(self) -> None:
        raw = "a\x00b" + ("x" * 30)
        cleaned = _clean_output(raw, max_chars=20)
        self.assertIn("\\0", cleaned)
        self.assertIn("...[truncated]...", cleaned)

    def test_normalize_reasoning_effort_supports_xhigh_aliases(self) -> None:
        self.assertEqual(normalize_reasoning_effort("high"), "high")
        self.assertEqual(normalize_reasoning_effort("Extra high"), "xhigh")
        self.assertEqual(normalize_reasoning_effort("extra_high"), "xhigh")


if __name__ == "__main__":
    unittest.main()
