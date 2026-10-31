from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PyQt5") is not None
if HAS_QT:
    from PyQt5.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
    from PyQt5.QtGui import QDragEnterEvent, QDropEvent
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton
    from product_manager.dialogs import DetailDialog
    from product_manager.gui import MainWindow, Worker
    from product_manager.fonts import configure_fonts
    from product_manager.models import ProductModel
    from product_manager.parser import import_files
    from product_manager.storage import Store

from product_manager.domain import Dataset, Product, detail_html
from test_products import create_source


@unittest.skipUnless(HAS_QT, "PyQt5 未安装")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_fonts(cls.app)
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "state.sqlite3")
        self.store.set_setting("inventory", True)
        self.window = MainWindow(self.store)
        self.products = [
            Product("X1", "S1", "数据线", "浩酷", color="蓝色", specification="1米", source_spec="数据线 蓝色 1米 浩酷",
                    actual_stock=10, available_stock=9, created_at=datetime(2026, 3, 7)),
            Product("X2", "S1", "数据线", "原品牌", color="紫色", specification="1米", source_spec="数据线 紫色 1米",
                    actual_stock=None, available_stock=0, created_at=datetime(2026, 3, 8)),
            Product("Y1", "S2", "编织线", "宏碁", source_spec="编织线 宏碁",
                    actual_stock=0, available_stock=0, created_at=datetime(2026, 4, 1)),
        ]
        data = Dataset(products=self.products)
        data.rebuild()
        self.window.apply_dataset(data)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.busy:
            self.window.worker.wait(10000)
            self.app.processEvents()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_preview_filters_without_inventory_or_review_controls(self):
        self.assertEqual(self.window.model.rowCount(), 2)
        self.assertEqual(self.window.model.headers, ["备注", "款式编码", "商品名称", "图片", "创建时间"] + self.window.model.brands)
        texts = [widget.text() for kind in (QLabel, QCheckBox, QPushButton) for widget in self.window.findChildren(kind)]
        options = [combo.itemText(i) for combo in self.window.findChildren(QComboBox) for i in range(combo.count())]
        for removed in ("款式总数", "商品编码总数", "可用库存", "待核对商品", "显示库存列",
                        "只看待核对款式", "查看数据问题", "字段映射导入", "全部库存", "未知", "低库存",
                        "全部上架记录", "最近导入"):
            self.assertNotIn(removed, texts + options)
        self.assertNotIn("库存", self.window.side_info.text() + self.window.side_brands.text())
        self.assertNotIn("上架记录", self.window.side_note.text())
        self.window.search.setText("X2")
        self.assertEqual(self.window.model.rowCount(), 1)
        self.assertEqual(self.window.model.styles[0].code, "S1")
        self.window.search.clear()
        self.window.brand_filter.setCurrentText("浩酷")
        self.assertEqual(len(self.window.model.styles[0].products), 2)
        self.window.brand_filter.setCurrentIndex(0)
        self.window.refresh()
        self.assertEqual(self.window.model.rowCount(), 2)

    def test_edit_is_persisted_and_reflected(self):
        row = next(i for i, style in enumerate(self.window.model.styles) if style.code == "S1")
        self.assertTrue(self.window.model.setData(self.window.model.index(row, 0), "清仓"))
        self.window.remark_filter.setCurrentText("清仓")
        self.assertEqual(self.window.model.rowCount(), 1)
        fresh = Dataset(products=[Product("X1", "S1", "数据线", "浩酷")])
        fresh.rebuild()
        self.store.apply(fresh)
        self.assertEqual(fresh.styles[0].remark, "清仓")

    def test_product_edit_refreshes_brand_matrix(self):
        style = next(s for s in self.window.dataset.styles if s.code == "S1")
        dialog = DetailDialog(style, self.window.product_edited, parent=self.window)
        self.assertTrue(all(dialog.table.isColumnHidden(column) for column in range(6, 11)))
        self.assertNotIn("上架记录", [dialog.model.headerData(column, Qt.Horizontal) for column in range(dialog.model.columnCount())])
        self.assertFalse(dialog.model.setData(dialog.model.index(0, 6), "已上架"))
        self.assertEqual(self.products[0].actual_stock, 10)
        self.assertNotIn("设置上架记录", [button.text() for button in dialog.findChildren(QPushButton)])
        self.assertNotIn("设置备注", [button.text() for button in dialog.findChildren(QPushButton)])
        self.assertTrue(dialog.model.setData(dialog.model.index(0, 2), "新品牌"))
        self.assertIn("新品牌", self.window.model.brands)
        self.assertEqual(self.products[0].brand, "新品牌")
        dialog.close()
        dialog.deleteLater()

    def test_remark_edit_targets_correct_sku_after_sort(self):
        style = next(s for s in self.window.dataset.styles if s.code == "S1")
        dialog = DetailDialog(style, self.window.product_edited, parent=self.window)
        dialog.show()
        self.app.processEvents()
        dialog.table.sortByColumn(0, Qt.DescendingOrder)
        self.assertEqual(dialog.proxy.index(0, 0).data(), "X2")
        self.assertTrue(dialog.proxy.setData(dialog.proxy.index(0, 5), "批发专用"))
        self.assertEqual([p.remark for p in style.products], ["", "批发专用"])
        dialog.close()
        dialog.deleteLater()

    def test_hover_card_contains_every_sku(self):
        row = next(i for i, style in enumerate(self.window.model.styles) if style.code == "S1")
        column = 5 + self.window.model.brands.index("浩酷")
        index = self.window.model.index(row, column)
        self.window.table.scrollTo(index)
        point = self.window.table.visualRect(index).center()
        QTest.mouseMove(self.window.table.viewport(), point)
        QTest.qWait(480)
        self.assertTrue(self.window.hover.isVisible())
        text = self.window.hover.browser.toPlainText()
        self.assertIn("X1", text)
        self.assertIn("X2", text)

    def test_import_detects_header_row_without_mapping(self):
        path = self.root / "自动识别.xlsx"
        create_source(path, header_row=4)
        self.window.import_paths([path])
        self.wait_for_worker()
        self.assertEqual(self.window.dataset.products[0].code, "0001")
        self.assertEqual(len(self.window.dataset.products), 3)

    def wait_for_worker(self):
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(self.window.busy)

    def test_gui_export_hides_summary_stock_and_preserves_source_fields(self):
        from openpyxl import load_workbook
        from test_products import HEADERS
        source, destination = self.root / "商品.xlsx", self.root / "导出.xlsx"
        create_source(source)
        self.window.apply_dataset(import_files([source]))
        with patch("product_manager.gui.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
             patch("product_manager.gui.QMessageBox.information"), \
             patch("product_manager.gui.QMessageBox.warning") as warning:
            self.window.choose_export()
            self.wait_for_worker()
            warning.assert_not_called()
        workbook = load_workbook(destination)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], HEADERS)
        self.assertNotIn("可用库存", [cell.value for cell in workbook["款式汇总"][1]])
        workbook.close()

    def test_drag_drop_runs_real_import_worker(self):
        path = self.root / "拖拽.xlsx"
        create_source(path)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter = QDragEnterEvent(QPoint(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.window.dropEvent(drop)
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertFalse(self.window.busy)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(len(self.window.dataset.products), 3)
        self.assertEqual(self.window.dataset.products[0].code, "0001")


if __name__ == "__main__":
    unittest.main()
