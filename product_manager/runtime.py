from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "商品资料台"
APP_VERSION = "1.0.2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)).joinpath(*parts)


def data_directory() -> Path:
    override = os.environ.get("PRODUCT_DESK_DATA_DIR")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        local = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))
        return local / "ProductDesk" / "data"
    return PROJECT_ROOT / "data"


def default_export_directory() -> Path:
    if getattr(sys, "frozen", False):
        from PyQt5.QtCore import QStandardPaths
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return Path(documents or str(Path.home() / "Documents")) / APP_NAME
    return PROJECT_ROOT / "outputs"
