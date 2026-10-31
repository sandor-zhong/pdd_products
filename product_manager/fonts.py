from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtGui import QFont, QFontDatabase


def configure_fonts(app) -> None:
    # The Windows offscreen Qt plugin has no system font database. Explicitly loading
    # existing Windows fonts keeps screenshots and automated UI checks readable.
    database = QFontDatabase()
    if not database.families():
        directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "arial.ttf", "segoeui.ttf"):
            font_path = directory / filename
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei", 10))
