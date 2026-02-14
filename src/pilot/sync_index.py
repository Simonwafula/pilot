from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import utc_now_iso
from .state import INDEX_DIR, ROOT_DIR, ensure_layout

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".pilot",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


def sync_workspace_index(
    *,
    root_dir: Path | None = None,
    max_files: int = 800,
    max_file_bytes: int = 250_000,
) -> dict[str, object]:
    ensure_layout()
    root = (root_dir or Path(".")).resolve()
    previous = load_manifest()
    previous_by_path = {
        item.get("path", ""): item.get("sha256", "")
        for item in previous.get("files", [])
        if isinstance(item, dict)
    }
    entries = _collect_file_entries(root, max_files=max_files, max_file_bytes=max_file_bytes)
    current_by_path = {item["path"]: item["sha256"] for item in entries}

    added = sorted(path for path in current_by_path if path not in previous_by_path)
    changed = sorted(
        path
        for path, digest in current_by_path.items()
        if path in previous_by_path and previous_by_path[path] != digest
    )
    removed = sorted(path for path in previous_by_path if path not in current_by_path)

    manifest = {
        "generated_at": utc_now_iso(),
        "root": str(root),
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
        "summary": {
            "indexed_files": len(entries),
            "added": len(added),
            "changed": len(changed),
            "removed": len(removed),
        },
        "files": entries,
    }
    manifest_path().write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    context_md = _render_context_markdown(manifest, added=added, changed=changed, removed=removed)
    context_path().write_text(context_md, encoding="utf-8")
    return {
        "manifest": manifest,
        "manifest_file": str(manifest_path()),
        "context_file": str(context_path()),
    }


def load_manifest() -> dict[str, object]:
    path = manifest_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def manifest_path() -> Path:
    return INDEX_DIR / "manifest.json"


def context_path() -> Path:
    return INDEX_DIR / "context.md"


def _collect_file_entries(root: Path, *, max_files: int, max_file_bytes: int) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if len(entries) >= max_files:
            break
        if not path.is_file():
            continue
        if _is_excluded(path, root):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > max_file_bytes:
            continue
        if not _is_probably_text(path):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        content = raw.decode("utf-8", errors="ignore")
        relative = str(path.relative_to(root))
        digest = hashlib.sha256(raw).hexdigest()
        first_lines = [line.strip() for line in content.splitlines()[:3] if line.strip()]
        entry = {
            "path": relative,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "sha256": digest,
            "preview": " | ".join(first_lines)[:280],
            "line_count": len(content.splitlines()),
        }
        entries.append(entry)
    return entries


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True
    if not relative_parts:
        return True
    return any(part in DEFAULT_EXCLUDE_DIRS for part in relative_parts[:-1])


def _is_probably_text(path: Path, probe_size: int = 2048) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(probe_size)
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    return True


def _render_context_markdown(
    manifest: dict[str, object],
    *,
    added: list[str],
    changed: list[str],
    removed: list[str],
) -> str:
    summary = manifest.get("summary", {})
    files = manifest.get("files", [])
    file_lines: list[str] = []
    if isinstance(files, list):
        for item in files[:60]:
            if not isinstance(item, dict):
                continue
            file_lines.append(
                f"- `{item.get('path')}` ({item.get('line_count')} lines): {item.get('preview') or '(no preview)'}"
            )
    if not file_lines:
        file_lines = ["- (no indexed files)"]

    def _short(items: list[str]) -> list[str]:
        if not items:
            return ["- (none)"]
        rendered = [f"- `{item}`" for item in items[:20]]
        if len(items) > 20:
            rendered.append(f"- ... and {len(items) - 20} more")
        return rendered

    lines = [
        "# Workspace Index",
        "",
        f"- Generated: {manifest.get('generated_at')}",
        f"- Root: {manifest.get('root')}",
        f"- Indexed files: {summary.get('indexed_files', 0)}",
        f"- Added since last sync: {summary.get('added', 0)}",
        f"- Changed since last sync: {summary.get('changed', 0)}",
        f"- Removed since last sync: {summary.get('removed', 0)}",
        "",
        "## Added",
        *_short(added),
        "",
        "## Changed",
        *_short(changed),
        "",
        "## Removed",
        *_short(removed),
        "",
        "## File Preview Index",
        *file_lines,
        "",
        "## Agent Note",
        f"- Read `{ROOT_DIR / 'index' / 'context.md'}` and `{ROOT_DIR / 'index' / 'manifest.json'}` before major edits.",
    ]
    return "\n".join(lines).rstrip() + "\n"
