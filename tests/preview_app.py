"""Render the real PyQt UI against a workbook without touching user settings."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from product_manager.dialogs import DetailDialog
from product_manager.gui import MainWindow
from product_manager.fonts import configure_fonts
from product_manager.parser import import_files
from product_manager.storage import Store


def main():
    source, destination = sys.argv[1:3]
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication([])
    configure_fonts(app)
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as directory:
        window = MainWindow(Store(Path(directory) / "state.sqlite3"))
        window.apply_dataset(import_files([source]))
        window.show()
        app.processEvents()
        window.grab().save(str(output / "preview.png"))
        detail = DetailDialog(window.dataset.styles[0], window.product_edited, parent=window)
        detail.show()
        app.processEvents()
        detail.grab().save(str(output / "details.png"))
        detail.close()
        window.hover.display(window.dataset.styles[0], "浩酷", window.mapToGlobal(window.rect().center()))
        app.processEvents()
        window.hover.grab().save(str(output / "hover.png"))
        window.close()
    print("GUI previews saved")


if __name__ == "__main__":
    main()
