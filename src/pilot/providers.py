from __future__ import annotations

import shutil
import subprocess
import time
from textwrap import dedent

from .models import Config, Task, utc_now_iso

SUPPORTED_PROVIDERS = {"codex", "opencode"}


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"Unsupported provider '{provider}'. Supported: {supported}.")
    return normalized


def default_agent_rules(provider: str) -> str:
    provider = normalize_provider(provider)
    common = dedent(
        """\
        # pilot rules
        - Follow task status in `.pilot/tasks/<task_id>.json`.
        - Work in phases: discover, plan, implement, verify.
        - Run configured quality gates before marking complete.
        - Keep handoff notes concise and actionable.
        """
    )
    if provider == "codex":
        provider_specific = dedent(
            """\
            # codex adapter
            - Use this repo's `AGENTS.md` as the default instruction contract.
            - Prefer deterministic shell commands and include file references in updates.
            """
        )
    else:
        provider_specific = dedent(
            """\
            # opencode adapter
            - Respect project `AGENTS.md` and local `.opencode` settings if present.
            - Use approval/permission checks before risky commands.
            """
        )
    return common + "\n" + provider_specific


def command_hint(provider: str, task: Task, handoff_file: str) -> str:
    provider = normalize_provider(provider)
    if provider == "codex":
        return (
            "codex \"Resume task "
            + task.id
            + " using handoff file "
            + handoff_file
            + " and follow AGENTS.md\""
        )
    return (
        "opencode run \"Resume task "
        + task.id
        + " using handoff file "
        + handoff_file
        + " and follow AGENTS.md\""
    )


def resume_prompt(provider: str, task: Task, handoff_file: str) -> str:
    provider = normalize_provider(provider)
    return dedent(
        f"""\
        Resume task `{task.id}` ({task.title}) on provider `{provider}`.

        Required context:
        1. Read `.pilot/tasks/{task.id}.json`.
        2. Read `{handoff_file}`.
        3. Continue from current status: `{task.status}`.
        4. Execute remaining plan steps.
        5. Run quality gates before completion.

        First output:
        - Brief restatement of current goal.
        - Next concrete action.
        """
    )


def build_run_prompt(provider: str, task: Task, handoff_file: str, extra_instructions: str = "") -> str:
    provider = normalize_provider(provider)
    base = resume_prompt(provider, task, handoff_file).strip()
    extra = extra_instructions.strip()
    extra_block = ""
    if extra:
        extra_block = f"\n\nOperator instructions:\n{extra}"
    return (
        base
        + "\n\nExecution contract:\n"
        + "- Follow `.pilot/templates/agent-rules.md` and `AGENTS.md`.\n"
        + "- Keep responses concise and action-oriented.\n"
        + "- Update code and run quality gates before proposing completion."
        + extra_block
    )


def provider_command(
    provider: str,
    prompt: str,
    *,
    settings: dict[str, str] | None = None,
) -> list[str]:
    provider = normalize_provider(provider)
    settings = settings or {}
    if provider == "codex":
        command = ["codex"]
        model = settings.get("model", "").strip()
        if model:
            command.extend(["-m", model])
        profile = settings.get("profile", "").strip()
        if profile:
            command.extend(["-p", profile])
        reasoning_effort = normalize_reasoning_effort(settings.get("reasoning_effort", ""))
        if reasoning_effort:
            escaped = reasoning_effort.replace('"', '\\"')
            command.extend(["-c", f'reasoning_effort="{escaped}"'])
        command.append(prompt)
        return command
    command = ["opencode", "run"]
    model = settings.get("model", "").strip()
    if model:
        command.extend(["-m", model])
    variant = settings.get("variant", "").strip()
    if variant:
        command.extend(["--variant", variant])
    if _as_bool(settings.get("thinking", "")):
        command.append("--thinking")
    agent = settings.get("agent", "").strip()
    if agent:
        command.extend(["--agent", agent])
    command.append(prompt)
    return command


def run_provider_command(
    provider: str,
    prompt: str,
    timeout_seconds: int = 0,
    *,
    settings: dict[str, str] | None = None,
    cwd: str | None = None,
) -> dict[str, object]:
    command = provider_command(provider, prompt, settings=settings)
    executable = command[0]
    if shutil.which(executable) is None:
        raise FileNotFoundError(
            f"Provider executable '{executable}' not found in PATH."
        )

    started_at = utc_now_iso()
    started = time.perf_counter()
    timeout = None if timeout_seconds <= 0 else timeout_seconds
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        exit_code = completed.returncode
        stdout = _clean_output(completed.stdout)
        stderr = _clean_output(completed.stderr)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = _clean_output((exc.stdout or "") if isinstance(exc.stdout, str) else "")
        stderr = f"Command timed out after {timeout_seconds}s."
        timed_out = True

    duration_seconds = round(time.perf_counter() - started, 3)
    return {
        "provider": provider,
        "settings": settings or {},
        "command": command,
        "prompt": prompt,
        "started_at": started_at,
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


def _clean_output(text: str, max_chars: int = 20000) -> str:
    cleaned = (text or "").replace("\x00", "\\0").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "\n...[truncated]..."


def resolve_provider_settings(config: Config, context: str) -> dict[str, str]:
    context_key = (context or "").strip().lower()
    profile_map = config.provider_profiles.get(context_key, {})
    provider_settings = profile_map.get(config.provider, {})
    if provider_settings:
        return dict(provider_settings)
    return default_provider_settings(config.provider, context_key)


def default_provider_settings(provider: str, context: str) -> dict[str, str]:
    provider = normalize_provider(provider)
    context_key = (context or "").strip().lower()
    if context_key == "plan":
        if provider == "codex":
            return {"model": "gpt-5.3-codex", "reasoning_effort": "high"}
        return {"model": "glm-5", "variant": "max", "thinking": "true"}
    if context_key in {"audit", "verifier"}:
        if provider == "codex":
            return {"model": "gpt-5.3-codex", "reasoning_effort": "xhigh"}
        return {"model": "glm-5", "variant": "max", "thinking": "true"}
    if context_key == "implement":
        if provider == "codex":
            return {"model": "gpt-5.3-codex", "reasoning_effort": "medium"}
        if provider == "opencode":
            return {"model": "glm-4.7", "variant": "medium"}
        return {}
    return {}


def normalize_reasoning_effort(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    mapping = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "extra_high": "xhigh",
        "extrahigh": "xhigh",
        "xhigh": "xhigh",
    }
    return mapping.get(normalized, normalized)


def _as_bool(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}
