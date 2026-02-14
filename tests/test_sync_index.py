from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pilot.sync_index import context_path, manifest_path, sync_workspace_index


class SyncIndexTests(unittest.TestCase):
    def test_sync_workspace_index_writes_manifest_and_context(self) -> None:
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                Path("app.py").write_text("print('ok')\n", encoding="utf-8")
                Path("README.md").write_text("# Title\n", encoding="utf-8")
                result = sync_workspace_index(max_files=20, max_file_bytes=100000)
                self.assertTrue(manifest_path().exists())
                self.assertTrue(context_path().exists())
                manifest = result.get("manifest", {})
                self.assertIsInstance(manifest, dict)
                summary = manifest.get("summary", {})
                self.assertIsInstance(summary, dict)
                self.assertGreaterEqual(int(summary.get("indexed_files", 0)), 2)
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
