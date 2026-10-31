from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from product_manager.runtime import PROJECT_ROOT, data_directory, resource_path
from product_manager.storage import Store


class RuntimeTests(unittest.TestCase):
    def test_source_mode_keeps_existing_project_data(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "frozen", False, create=True):
            self.assertEqual(data_directory(), PROJECT_ROOT / "data")

    def test_frozen_data_survives_install_location_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=True), \
                 patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(root / "installation-v1"), create=True):
                data = data_directory()
                store = Store(data / "state.sqlite3")
                store.set_setting("user_note", "保留备注")
                store.close()
                self.assertNotIn("installation-v1", str(data))
                self.assertEqual(resource_path("assets", "app-icon.ico"), root / "installation-v1" / "assets" / "app-icon.ico")
                with patch.object(sys, "_MEIPASS", str(root / "installation-v2")):
                    reopened = Store(data_directory() / "state.sqlite3")
                    self.assertEqual(reopened.setting("user_note"), "保留备注")
                    reopened.close()


if __name__ == "__main__":
    unittest.main()
