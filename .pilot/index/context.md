# Workspace Index

- Generated: 2026-02-14T11:02:51+00:00
- Root: /Users/hp/Library/CloudStorage/OneDrive-Personal/Codes/pilot
- Indexed files: 26
- Added since last sync: 0
- Changed since last sync: 4
- Removed since last sync: 0

## Added
- (none)

## Changed
- `README.md`
- `src/pilot/providers.py`
- `src/pilot/state.py`
- `tests/test_providers.py`

## Removed
- (none)

## File Preview Index
- `.gitignore` (8 lines): .venv/ | __pycache__/ | .pytest_cache/
- `AGENTS.md` (8 lines): <!-- pilot-core:begin --> | ## pilot-core | - Load and follow `.pilot/templates/agent-rules.md`.
- `README.md` (274 lines): # pilot-core | Clean-room reimplementation of the core idea behind agent workflow products:
- `pilot` (13 lines): #!/usr/bin/env python3 | from pathlib import Path | import sys
- `pyproject.toml` (17 lines): [build-system] | requires = ["setuptools", "wheel"] | build-backend = "setuptools.build_meta"
- `src/pilot/__init__.py` (4 lines): """pilot-core package.""" | __all__ = ["__version__"]
- `src/pilot/audit.py` (290 lines): from __future__ import annotations | from dataclasses import dataclass
- `src/pilot/cli.py` (1569 lines): from __future__ import annotations | import argparse
- `src/pilot/doctor.py` (447 lines): from __future__ import annotations | import shlex
- `src/pilot/ideas.py` (377 lines): from __future__ import annotations | import json
- `src/pilot/models.py` (242 lines): from __future__ import annotations | from dataclasses import dataclass, field
- `src/pilot/providers.py` (249 lines): from __future__ import annotations | import shutil
- `src/pilot/state.py` (166 lines): from __future__ import annotations | import json
- `src/pilot/sync_index.py` (199 lines): from __future__ import annotations | import hashlib
- `src/pilot/verifier.py` (115 lines): from __future__ import annotations | import secrets
- `src/pilot/workflow.py` (302 lines): from __future__ import annotations | import subprocess
- `tests/test_audit.py` (85 lines): from __future__ import annotations | import unittest
- `tests/test_cli_ai_modes.py` (47 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_audit.py` (113 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_auto.py` (75 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_ideas.py` (72 lines): from __future__ import annotations | import contextlib
- `tests/test_cli_sync_verifier.py` (83 lines): from __future__ import annotations | import contextlib
- `tests/test_doctor.py` (93 lines): from __future__ import annotations | import os
- `tests/test_providers.py` (91 lines): from __future__ import annotations | import unittest
- `tests/test_sync_index.py` (32 lines): from __future__ import annotations | import os
- `tests/test_workflow.py` (187 lines): from __future__ import annotations | import unittest

## Agent Note
- Read `.pilot/index/context.md` and `.pilot/index/manifest.json` before major edits.
