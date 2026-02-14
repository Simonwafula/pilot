# Workspace Index

- Generated: 2026-02-14T11:59:39+00:00
- Root: /Users/hp/Library/CloudStorage/OneDrive-Personal/Codes/pilot
- Indexed files: 28
- Added since last sync: 0
- Changed since last sync: 0
- Removed since last sync: 0

## Added
- (none)

## Changed
- (none)

## Removed
- (none)

## File Preview Index
- `.gitignore` (8 lines): .venv/ | __pycache__/ | .pytest_cache/
- `.ruff_cache/.gitignore` (2 lines): # Automatically created by ruff. | *
- `.ruff_cache/CACHEDIR.TAG` (1 lines): Signature: 8a477f597d28d172789f06886806bc55
- `AGENTS.md` (8 lines): <!-- pilot-core:begin --> | ## pilot-core | - Load and follow `.pilot/templates/agent-rules.md`.
- `README.md` (303 lines): # pilot-core | Clean-room reimplementation of the core idea behind agent workflow products:
- `pilot` (13 lines): #!/usr/bin/env python3 | from pathlib import Path | import sys
- `pyproject.toml` (17 lines): [build-system] | requires = ["setuptools", "wheel"] | build-backend = "setuptools.build_meta"
- `src/pilot/__init__.py` (4 lines): """pilot-core package.""" | __all__ = ["__version__"]
- `src/pilot/audit.py` (306 lines): from __future__ import annotations | from dataclasses import dataclass
- `src/pilot/cli.py` (1789 lines): from __future__ import annotations | import argparse
- `src/pilot/doctor.py` (465 lines): from __future__ import annotations | import shlex
- `src/pilot/ideas.py` (402 lines): from __future__ import annotations | import json
- `src/pilot/models.py` (246 lines): from __future__ import annotations | from dataclasses import dataclass, field
- `src/pilot/providers.py` (255 lines): from __future__ import annotations | import shutil
- `src/pilot/state.py` (179 lines): from __future__ import annotations | import json
- `src/pilot/sync_index.py` (207 lines): from __future__ import annotations | import hashlib
- `src/pilot/verifier.py` (121 lines): from __future__ import annotations | import secrets
- `src/pilot/workflow.py` (318 lines): from __future__ import annotations | import subprocess
- `tests/test_audit.py` (98 lines): from __future__ import annotations | import unittest
- `tests/test_cli_ai_modes.py` (53 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_audit.py` (137 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_auto.py` (81 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_ideas.py` (76 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_sync_verifier.py` (96 lines): from __future__ import annotations | import contextlib
- `tests/test_doctor.py` (93 lines): from __future__ import annotations | import os
- `tests/test_providers.py` (91 lines): from __future__ import annotations | import unittest
- `tests/test_sync_index.py` (32 lines): from __future__ import annotations | import os
- `tests/test_workflow.py` (196 lines): from __future__ import annotations | import unittest

## Agent Note
- Read `.pilot/index/context.md` and `.pilot/index/manifest.json` before major edits.
