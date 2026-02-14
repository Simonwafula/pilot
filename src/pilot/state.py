from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Iterable

from .models import Config, Task, utc_now_iso

ROOT_DIR = Path(".pilot")
TASKS_DIR = ROOT_DIR / "tasks"
HANDOFFS_DIR = ROOT_DIR / "handoffs"
REPORTS_DIR = ROOT_DIR / "reports"
TEMPLATES_DIR = ROOT_DIR / "templates"
IDEAS_DIR = ROOT_DIR / "ideas"
INDEX_DIR = ROOT_DIR / "index"
VERIFIER_DIR = ROOT_DIR / "verifier"
CONFIG_FILE = ROOT_DIR / "config.json"


def ensure_layout() -> None:
    for path in (
        ROOT_DIR,
        TASKS_DIR,
        HANDOFFS_DIR,
        REPORTS_DIR,
        TEMPLATES_DIR,
        IDEAS_DIR,
        INDEX_DIR,
        VERIFIER_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def init_workspace(provider: str = "codex", force: bool = False) -> Config:
    ensure_layout()
    if CONFIG_FILE.exists() and not force:
        return load_config()
    config = Config(
        provider=provider,
        quality_gates=default_quality_gates(),
        provider_profiles=default_provider_profiles(),
    )
    save_config(config)
    return config


def default_quality_gates() -> list[dict[str, str]]:
    return [
        {
            "name": "format",
            "command": "echo 'configure formatter command in .pilot/config.json'",
        },
        {
            "name": "lint",
            "command": "echo 'configure lint command in .pilot/config.json'",
        },
        {
            "name": "test",
            "command": "echo 'configure test command in .pilot/config.json'",
        },
    ]


def default_provider_profiles() -> dict[str, dict[str, dict[str, str]]]:
    return {
        "plan": {
            "codex": {"model": "gpt-5.3-codex", "reasoning_effort": "high"},
            "opencode": {"model": "glm-5", "variant": "max", "thinking": "true"},
        },
        "audit": {
            "codex": {"model": "gpt-5.3-codex", "reasoning_effort": "xhigh"},
            "opencode": {"model": "glm-5", "variant": "max", "thinking": "true"},
        },
        "verifier": {
            "codex": {"model": "gpt-5.3-codex", "reasoning_effort": "xhigh"},
            "opencode": {"model": "glm-5", "variant": "max", "thinking": "true"},
        },
        "implement": {
            "codex": {"model": "gpt-5.3-codex", "reasoning_effort": "medium"},
            "opencode": {"model": "glm-4.7", "variant": "medium"},
        },
    }


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            ".pilot/config.json is missing. Run `pilot init --provider codex|opencode` first."
        )
    data = _read_json(CONFIG_FILE)
    return Config.from_dict(data)


def save_config(config: Config) -> None:
    _write_json(CONFIG_FILE, config.to_dict())


def task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def create_task(title: str, task_id: str | None = None) -> Task:
    ensure_layout()
    if not task_id:
        task_id = _new_task_id()
    path = task_path(task_id)
    if path.exists():
        raise FileExistsError(f"Task {task_id} already exists.")
    now = utc_now_iso()
    task = Task(
        id=task_id,
        title=title,
        status="planned",
        phase="discover",
        created_at=now,
        updated_at=now,
    )
    save_task(task)
    return task


def _new_task_id() -> str:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    return f"{stamp}-{secrets.token_hex(3)}"


def load_task(task_id: str) -> Task:
    path = task_path(task_id)
    if not path.exists():
        raise FileNotFoundError(f"Task {task_id} not found.")
    return Task.from_dict(_read_json(path))


def save_task(task: Task) -> None:
    _write_json(task_path(task.id), task.to_dict())


def list_tasks() -> list[Task]:
    ensure_layout()
    tasks: list[Task] = []
    for file in TASKS_DIR.glob("*.json"):
        try:
            tasks.append(Task.from_dict(_read_json(file)))
        except json.JSONDecodeError:
            continue
    tasks.sort(key=lambda item: item.updated_at, reverse=True)
    return tasks


def resolve_task(
    task_id: str | None = None, preferred_statuses: Iterable[str] | None = None
) -> Task:
    if task_id:
        return load_task(task_id)
    tasks = list_tasks()
    if not tasks:
        raise FileNotFoundError(
            'No tasks found. Create one with `pilot new "your task"`.'
        )
    if preferred_statuses:
        status_set = set(preferred_statuses)
        for task in tasks:
            if task.status in status_set:
                return task
    return tasks[0]


def handoff_path(task_id: str) -> Path:
    return HANDOFFS_DIR / f"{task_id}.md"
