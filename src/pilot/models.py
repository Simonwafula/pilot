from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class QualityResult:
    name: str
    command: str
    exit_code: int
    success: bool
    duration_seconds: float
    ran_at: str
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "exit_code": self.exit_code,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "ran_at": self.ran_at,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityResult":
        return cls(
            name=str(data.get("name", "")),
            command=str(data.get("command", "")),
            exit_code=int(data.get("exit_code", 1)),
            success=bool(data.get("success", False)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            ran_at=str(data.get("ran_at", "")),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
        )


@dataclass
class Config:
    provider: str = "codex"
    quality_gates: list[dict[str, str]] = field(default_factory=list)
    pre_edit_hooks: list[str] = field(default_factory=list)
    post_edit_hooks: list[str] = field(default_factory=list)
    provider_profiles: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "quality_gates": self.quality_gates,
            "pre_edit_hooks": self.pre_edit_hooks,
            "post_edit_hooks": self.post_edit_hooks,
            "provider_profiles": self.provider_profiles,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        provider = str(data.get("provider", "codex")).strip().lower()
        raw_gates = data.get("quality_gates", [])
        quality_gates: list[dict[str, str]] = []
        if isinstance(raw_gates, list):
            for gate in raw_gates:
                if not isinstance(gate, dict):
                    continue
                name = str(gate.get("name", "")).strip()
                command = str(gate.get("command", "")).strip()
                if name and command:
                    quality_gates.append({"name": name, "command": command})
        pre_edit_hooks = _sanitize_string_list(data.get("pre_edit_hooks", []))
        post_edit_hooks = _sanitize_string_list(data.get("post_edit_hooks", []))
        provider_profiles = _sanitize_provider_profiles(data.get("provider_profiles", {}))
        return cls(
            provider=provider,
            quality_gates=quality_gates,
            pre_edit_hooks=pre_edit_hooks,
            post_edit_hooks=post_edit_hooks,
            provider_profiles=provider_profiles,
        )


@dataclass
class Task:
    id: str
    title: str
    status: str
    phase: str
    created_at: str
    updated_at: str
    plan_steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    quality_results: list[QualityResult] = field(default_factory=list)
    hook_runs: list[dict[str, Any]] = field(default_factory=list)
    provider_runs: list[dict[str, Any]] = field(default_factory=list)
    verifier_runs: list[dict[str, Any]] = field(default_factory=list)
    tdd_cycles: list[dict[str, Any]] = field(default_factory=list)
    handoff_file: str | None = None

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "phase": self.phase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_steps": self.plan_steps,
            "notes": self.notes,
            "quality_results": [result.to_dict() for result in self.quality_results],
            "hook_runs": self.hook_runs,
            "provider_runs": self.provider_runs,
            "verifier_runs": self.verifier_runs,
            "tdd_cycles": self.tdd_cycles,
            "handoff_file": self.handoff_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        raw_results = data.get("quality_results", [])
        quality_results: list[QualityResult] = []
        if isinstance(raw_results, list):
            for result in raw_results:
                if isinstance(result, dict):
                    quality_results.append(QualityResult.from_dict(result))
        phase = str(data.get("phase", "")).strip().lower()
        if not phase:
            phase = _phase_from_status(str(data.get("status", "planned")))
        raw_provider_runs = data.get("provider_runs", [])
        provider_runs: list[dict[str, Any]] = []
        if isinstance(raw_provider_runs, list):
            for item in raw_provider_runs:
                if isinstance(item, dict):
                    provider_runs.append(item)
        raw_verifier_runs = data.get("verifier_runs", [])
        verifier_runs: list[dict[str, Any]] = []
        if isinstance(raw_verifier_runs, list):
            for item in raw_verifier_runs:
                if isinstance(item, dict):
                    verifier_runs.append(item)
        raw_hook_runs = data.get("hook_runs", [])
        hook_runs: list[dict[str, Any]] = []
        if isinstance(raw_hook_runs, list):
            for item in raw_hook_runs:
                if isinstance(item, dict):
                    hook_runs.append(item)
        raw_tdd_cycles = data.get("tdd_cycles", [])
        tdd_cycles: list[dict[str, Any]] = []
        if isinstance(raw_tdd_cycles, list):
            for item in raw_tdd_cycles:
                if isinstance(item, dict):
                    tdd_cycles.append(item)
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            status=str(data.get("status", "planned")),
            phase=phase,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            plan_steps=list(data.get("plan_steps", []) or []),
            notes=list(data.get("notes", []) or []),
            quality_results=quality_results,
            hook_runs=hook_runs,
            provider_runs=provider_runs,
            verifier_runs=verifier_runs,
            tdd_cycles=tdd_cycles,
            handoff_file=data.get("handoff_file"),
        )


def _phase_from_status(status: str) -> str:
    mapping = {
        "planned": "discover",
        "in_progress": "implement",
        "blocked": "implement",
        "verifying": "verify",
        "completed": "complete",
    }
    return mapping.get(status, "discover")


def _sanitize_string_list(values: Any) -> list[str]:
    cleaned: list[str] = []
    if not isinstance(values, list):
        return cleaned
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item:
            cleaned.append(item)
    return cleaned


def _sanitize_provider_profiles(values: Any) -> dict[str, dict[str, dict[str, str]]]:
    cleaned: dict[str, dict[str, dict[str, str]]] = {}
    if not isinstance(values, dict):
        return cleaned
    for context_name, raw_provider_map in values.items():
        if not isinstance(context_name, str):
            continue
        context_key = context_name.strip()
        if not context_key or not isinstance(raw_provider_map, dict):
            continue
        provider_map: dict[str, dict[str, str]] = {}
        for provider_name, raw_settings in raw_provider_map.items():
            if not isinstance(provider_name, str):
                continue
            provider_key = provider_name.strip().lower()
            if not provider_key or not isinstance(raw_settings, dict):
                continue
            settings: dict[str, str] = {}
            for key, value in raw_settings.items():
                if not isinstance(key, str):
                    continue
                setting_key = key.strip()
                if not setting_key:
                    continue
                if isinstance(value, bool):
                    settings[setting_key] = "true" if value else "false"
                elif isinstance(value, (int, float)):
                    settings[setting_key] = str(value)
                elif isinstance(value, str):
                    rendered = value.strip()
                    if rendered:
                        settings[setting_key] = rendered
            if settings:
                provider_map[provider_key] = settings
        if provider_map:
            cleaned[context_key] = provider_map
    return cleaned
