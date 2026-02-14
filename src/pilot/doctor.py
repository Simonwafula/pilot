from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Config
from .providers import default_agent_rules, normalize_provider, provider_command
from .state import (
    CONFIG_FILE,
    REPORTS_DIR,
    ROOT_DIR,
    default_provider_profiles,
    default_quality_gates,
    ensure_layout,
    init_workspace,
    load_config,
    save_config,
)


@dataclass
class DoctorResult:
    name: str
    status: str
    detail: str


@dataclass
class FixAction:
    name: str
    status: str
    detail: str


def run_doctor(config: Config) -> list[DoctorResult]:
    results = [
        _check_workspace_initialized(),
        _check_reports_dir_writable(),
        _check_provider_binary(config),
        _check_provider_help(config),
        *_check_quality_gate_commands(config),
        *_check_hook_commands(config.pre_edit_hooks, hook_name="pre_edit"),
        *_check_hook_commands(config.post_edit_hooks, hook_name="post_edit"),
    ]
    return results


def apply_fixes(preferred_provider: str = "codex") -> tuple[Config, list[FixAction]]:
    actions: list[FixAction] = []
    ensure_layout()
    provider_fallback = _normalize_preferred_provider(preferred_provider)
    config = _load_or_create_config(provider_fallback, actions)

    # Normalize provider value and quality gate structure.
    changed = False
    try:
        provider = normalize_provider(config.provider)
        if provider != config.provider:
            config.provider = provider
            actions.append(
                FixAction(
                    "provider",
                    "applied",
                    f"Normalized provider value to `{provider}`.",
                )
            )
            changed = True
    except ValueError:
        config.provider = provider_fallback
        actions.append(
            FixAction(
                "provider",
                "applied",
                f"Replaced invalid provider with `{provider_fallback}`.",
            )
        )
        changed = True

    cleaned_gates = sanitize_quality_gates(config.quality_gates)
    if not cleaned_gates:
        cleaned_gates = default_quality_gates()
        if config.quality_gates != cleaned_gates:
            actions.append(
                FixAction(
                    "quality_gates",
                    "applied",
                    "Replaced missing/invalid quality gates with defaults.",
                )
            )
            changed = True
    elif cleaned_gates != config.quality_gates:
        actions.append(
            FixAction(
                "quality_gates",
                "applied",
                "Removed malformed quality gate entries.",
            )
        )
        changed = True
    config.quality_gates = cleaned_gates

    cleaned_pre_hooks = sanitize_hook_commands(config.pre_edit_hooks)
    if cleaned_pre_hooks != config.pre_edit_hooks:
        actions.append(
            FixAction(
                "pre_edit_hooks",
                "applied",
                "Removed malformed pre-edit hook entries.",
            )
        )
        changed = True
    config.pre_edit_hooks = cleaned_pre_hooks

    cleaned_post_hooks = sanitize_hook_commands(config.post_edit_hooks)
    if cleaned_post_hooks != config.post_edit_hooks:
        actions.append(
            FixAction(
                "post_edit_hooks",
                "applied",
                "Removed malformed post-edit hook entries.",
            )
        )
        changed = True
    config.post_edit_hooks = cleaned_post_hooks

    cleaned_profiles = sanitize_provider_profiles(config.provider_profiles)
    if not cleaned_profiles:
        cleaned_profiles = default_provider_profiles()
        if config.provider_profiles != cleaned_profiles:
            actions.append(
                FixAction(
                    "provider_profiles",
                    "applied",
                    "Replaced missing/invalid provider profile configuration with defaults.",
                )
            )
            changed = True
    elif cleaned_profiles != config.provider_profiles:
        actions.append(
            FixAction(
                "provider_profiles",
                "applied",
                "Removed malformed provider profile entries.",
            )
        )
        changed = True
    config.provider_profiles = cleaned_profiles

    rules_file = ROOT_DIR / "templates" / "agent-rules.md"
    desired_rules = default_agent_rules(config.provider)
    existing_rules = (
        rules_file.read_text(encoding="utf-8") if rules_file.exists() else ""
    )
    if existing_rules != desired_rules:
        rules_file.parent.mkdir(parents=True, exist_ok=True)
        rules_file.write_text(desired_rules, encoding="utf-8")
        actions.append(
            FixAction(
                "agent_rules",
                "applied",
                f"Synchronized {rules_file} for provider `{config.provider}`.",
            )
        )

    if changed:
        save_config(config)

    if not actions:
        actions.append(FixAction("noop", "skipped", "No fixes were needed."))

    return config, actions


def summarize(results: list[DoctorResult]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for result in results:
        if result.status in counts:
            counts[result.status] += 1
    return counts


def _check_workspace_initialized() -> DoctorResult:
    if CONFIG_FILE.exists():
        return DoctorResult("workspace", "pass", f"Found {CONFIG_FILE}.")
    return DoctorResult(
        "workspace", "fail", f"Missing {CONFIG_FILE}. Run `pilot init`."
    )


def _check_reports_dir_writable() -> DoctorResult:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        marker = REPORTS_DIR / ".doctor-write-test"
        marker.write_text("ok\n", encoding="utf-8")
        marker.unlink()
        return DoctorResult("reports_dir", "pass", f"{REPORTS_DIR} is writable.")
    except OSError as exc:
        return DoctorResult(
            "reports_dir", "fail", f"{REPORTS_DIR} is not writable: {exc}"
        )


def _check_provider_binary(config: Config) -> DoctorResult:
    command = provider_command(config.provider, "ping")
    executable = command[0]
    path = shutil.which(executable)
    if path is None:
        return DoctorResult(
            "provider_binary", "fail", f"`{executable}` is not in PATH."
        )
    return DoctorResult(
        "provider_binary", "pass", f"`{executable}` resolved to {path}."
    )


def _check_provider_help(config: Config, timeout_seconds: int = 8) -> DoctorResult:
    command = _provider_help_command(config.provider)
    executable = command[0]
    if shutil.which(executable) is None:
        return DoctorResult(
            "provider_help", "warn", f"Skipped because `{executable}` is missing."
        )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return DoctorResult(
            "provider_help",
            "warn",
            f"`{' '.join(command)}` timed out after {timeout_seconds}s.",
        )
    if completed.returncode == 0:
        return DoctorResult(
            "provider_help", "pass", f"`{' '.join(command)}` succeeded."
        )
    stderr = (completed.stderr or "").strip()
    detail = f"`{' '.join(command)}` exited {completed.returncode}."
    if stderr:
        detail += f" stderr: {stderr[:240]}"
    return DoctorResult("provider_help", "warn", detail)


def _provider_help_command(provider: str) -> list[str]:
    if provider == "codex":
        return ["codex", "--help"]
    return ["opencode", "--help"]


def _check_quality_gate_commands(config: Config) -> list[DoctorResult]:
    results: list[DoctorResult] = []
    if not config.quality_gates:
        return [DoctorResult("quality_gates", "warn", "No quality gates configured.")]
    for gate in config.quality_gates:
        name = gate.get("name", "").strip() or "unnamed"
        command = gate.get("command", "").strip()
        if not command:
            results.append(
                DoctorResult(f"quality_gate:{name}", "fail", "Command is empty.")
            )
            continue
        executable = _command_executable(command)
        if executable is None:
            results.append(
                DoctorResult(
                    f"quality_gate:{name}",
                    "warn",
                    f"Could not parse executable from `{command}`.",
                )
            )
            continue
        if _is_shell_builtin(executable):
            results.append(
                DoctorResult(
                    f"quality_gate:{name}",
                    "pass",
                    f"Uses shell builtin `{executable}`.",
                )
            )
            continue
        path = shutil.which(executable)
        if path is None:
            results.append(
                DoctorResult(
                    f"quality_gate:{name}",
                    "warn",
                    f"Executable `{executable}` not found in PATH for `{command}`.",
                )
            )
            continue
        results.append(
            DoctorResult(
                f"quality_gate:{name}",
                "pass",
                f"`{executable}` resolved to {path}.",
            )
        )
    return results


def _check_hook_commands(commands: list[str], *, hook_name: str) -> list[DoctorResult]:
    results: list[DoctorResult] = []
    if not commands:
        return [
            DoctorResult(
                f"{hook_name}_hooks", "warn", f"No {hook_name} hooks configured."
            )
        ]
    for idx, command in enumerate(commands, start=1):
        executable = _command_executable(command)
        label = f"{hook_name}_hook:{idx}"
        if executable is None:
            results.append(
                DoctorResult(
                    label,
                    "warn",
                    f"Could not parse executable from `{command}`.",
                )
            )
            continue
        if _is_shell_builtin(executable):
            results.append(
                DoctorResult(
                    label,
                    "pass",
                    f"Uses shell builtin `{executable}`.",
                )
            )
            continue
        path = shutil.which(executable)
        if path is None:
            results.append(
                DoctorResult(
                    label,
                    "warn",
                    f"Executable `{executable}` not found in PATH for `{command}`.",
                )
            )
            continue
        results.append(
            DoctorResult(
                label,
                "pass",
                f"`{executable}` resolved to {path}.",
            )
        )
    return results


def sanitize_quality_gates(gates: list[dict[str, str]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        name = str(gate.get("name", "")).strip()
        command = str(gate.get("command", "")).strip()
        if not name or not command:
            continue
        cleaned.append({"name": name, "command": command})
    return cleaned


def sanitize_hook_commands(commands: list[str]) -> list[str]:
    cleaned: list[str] = []
    for command in commands:
        if not isinstance(command, str):
            continue
        item = command.strip()
        if item:
            cleaned.append(item)
    return cleaned


def sanitize_provider_profiles(
    profiles: dict[str, dict[str, dict[str, str]]],
) -> dict[str, dict[str, dict[str, str]]]:
    cleaned: dict[str, dict[str, dict[str, str]]] = {}
    if not isinstance(profiles, dict):
        return cleaned
    for context, provider_map in profiles.items():
        if not isinstance(context, str):
            continue
        context_key = context.strip()
        if not context_key or not isinstance(provider_map, dict):
            continue
        clean_provider_map: dict[str, dict[str, str]] = {}
        for provider, settings in provider_map.items():
            if not isinstance(provider, str):
                continue
            provider_key = provider.strip().lower()
            if not provider_key or not isinstance(settings, dict):
                continue
            clean_settings: dict[str, str] = {}
            for key, value in settings.items():
                if not isinstance(key, str):
                    continue
                setting_key = key.strip()
                if not setting_key:
                    continue
                if isinstance(value, bool):
                    clean_settings[setting_key] = "true" if value else "false"
                elif isinstance(value, (int, float)):
                    clean_settings[setting_key] = str(value)
                elif isinstance(value, str):
                    item = value.strip()
                    if item:
                        clean_settings[setting_key] = item
            if clean_settings:
                clean_provider_map[provider_key] = clean_settings
        if clean_provider_map:
            cleaned[context_key] = clean_provider_map
    return cleaned


def _command_executable(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    return Path(tokens[0]).name


def _is_shell_builtin(executable: str) -> bool:
    builtins = {"echo", "cd", "true", "false", ":", "test", "["}
    return executable in builtins


def _normalize_preferred_provider(provider: str) -> str:
    try:
        return normalize_provider(provider)
    except ValueError:
        return "codex"


def _load_or_create_config(provider: str, actions: list[FixAction]) -> Config:
    if not CONFIG_FILE.exists():
        config = init_workspace(provider=provider, force=False)
        actions.append(
            FixAction(
                "config",
                "applied",
                f"Created missing config at {CONFIG_FILE}.",
            )
        )
        return config
    try:
        return load_config()
    except Exception:
        config = init_workspace(provider=provider, force=True)
        actions.append(
            FixAction(
                "config",
                "applied",
                f"Rebuilt invalid config at {CONFIG_FILE}.",
            )
        )
        return config
