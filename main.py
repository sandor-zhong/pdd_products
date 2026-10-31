from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from product_manager.runtime import APP_NAME, APP_VERSION, data_directory, resource_path


def main():
    parser = argparse.ArgumentParser(description="商品资料台 · PyQt5 商品品牌与备注管理")
    parser.add_argument("files", nargs="*", help="启动时导入的 .xlsx / .xlsm 文件")
    parser.add_argument("--export", metavar="OUTPUT.xlsx", help="直接解析并导出，不打开界面")
    parser.add_argument("--no-settings", action="store_true", help="命令行导出时不应用本地手工备注和品牌设置")
    parser.add_argument("--self-test", metavar="REPORT.json", help=argparse.SUPPRESS)
    args = parser.parse_args()
    data = data_directory()
    if args.export:
        if not args.files:
            parser.error("--export 需要至少一个输入文件")
        from product_manager.exporter import export_workbook
        from product_manager.parser import import_files
        from product_manager.storage import Store
        store = None if args.no_settings else Store(data / "state.sqlite3")
        try:
            dataset = import_files(args.files, store.brands if store else None)
            if store:
                store.apply(dataset)
            path = export_workbook(dataset, args.export, store.brands if store else None)
            print(f"已导出：{path}\n款式 {len(dataset.styles)}，商品 {len(dataset.products)}")
        finally:
            if store:
                store.close()
        return 0
    if args.self_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from product_manager.gui import MainWindow
    from product_manager.fonts import configure_fonts
    from product_manager.storage import Store
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.ico"))))
    configure_fonts(app)
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / "app.log", encoding="utf-8", level=logging.ERROR)
    window = MainWindow(Store(data / "state.sqlite3"))

    def report_exception(kind, value, traceback):
        logging.error("Unhandled application exception", exc_info=(kind, value, traceback))
        QMessageBox.critical(window, "操作未完成", f"{value}\n详细信息已保存到 {data / 'app.log'}。")
    sys.excepthook = report_exception
    if args.self_test:
        report = {
            "application": APP_NAME, "version": APP_VERSION,
            "frozen": bool(getattr(sys, "frozen", False)),
            "icon_loaded": not app.windowIcon().isNull(),
            "database": str(window.store.path),
            "qt_platform": app.platformName(),
            "window_created": window.model.columnCount() >= 5,
        }
        Path(args.self_test).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        return 0 if report["icon_loaded"] and report["window_created"] else 1
    window.show()
    if args.files:
        QTimer.singleShot(0, lambda: window.import_paths(args.files))
    return app.exec_()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportError as exc:
        print(f"缺少运行依赖：{exc}\n请先运行安装依赖.ps1，或执行 python -m pip install -r requirements.txt。", file=sys.stderr)
        raise SystemExit(1)
