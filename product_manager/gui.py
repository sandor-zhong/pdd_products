from __future__ import annotations

import copy
from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                             QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
                             QTableView, QTextBrowser, QVBoxLayout, QWidget)

from .dialogs import BrandsDialog, DetailDialog
from .domain import REMARKS, Dataset, Style, detail_html
from .exporter import export_workbook
from .models import BrandCellDelegate, ChoiceDelegate, StyleModel
from .parser import REQUIRED_FIELDS, SpecParser, import_files, inspect_layouts
from .runtime import default_export_directory
from .storage import Store

STYLESHEET = """
QWidget { font-family: 'Microsoft YaHei', 'Segoe UI'; font-size: 12px; color: #263044; }
QMainWindow, QWidget#canvas { background: #F5F7FB; }
QLabel#title { font-size: 25px; font-weight: 700; color: #1F2B40; }
QLabel#subtitle, QLabel#muted { color: #7B879A; }
QLabel#sectionTitle, QLabel#dialogHeading { font-size: 16px; font-weight: 600; }
QFrame#card, QFrame#sideCard { background: white; border: 1px solid #E0E5EE; border-radius: 9px; }
QPushButton { background: white; border: 1px solid #D8DFEA; border-radius: 6px; padding: 8px 14px; }
QPushButton:hover { background: #EFF4FF; border-color: #A2B8ED; }
QPushButton:pressed { background: #E4EDFF; }
QPushButton:disabled { color: #A0A8B6; background: #F0F2F6; border-color: #E2E6EE; }
QPushButton#primary { background: #3D65D9; color: white; border: 1px solid #3D65D9; font-weight: 600; }
QPushButton#primary:hover { background: #3056C6; }
QPushButton#primary:disabled { background: #AEBDE7; border-color: #AEBDE7; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #D8DFEA; border-radius: 5px; min-height: 25px; padding: 3px 7px; }
QLineEdit:focus, QComboBox:focus { border-color: #7294EC; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #D9E8FF; selection-color: #263044; }
QTableView { background: white; alternate-background-color: #FAFBFD; border: 1px solid #D7DDE7; gridline-color: #ABB3C0; selection-background-color: #AFE2F5; selection-color: #1F2B40; }
QTableView::item { padding: 4px; }
QHeaderView::section { background: #EBECEF; color: #1F2937; font-weight: 600; padding: 8px 5px; border: 0; border-right: 1px solid #BCC2CD; border-bottom: 1px solid #A8B0BF; }
QScrollBar:vertical { background: #F2F4F8; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #C5CDDB; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #F2F4F8; height: 11px; margin: 0; }
QScrollBar::handle:horizontal { background: #C5CDDB; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QProgressBar { border: 1px solid #D8DFEA; border-radius: 4px; background: #EDF1F8; text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #6B8BE5; }
QStatusBar { background: #EDF1F7; color: #6A768B; }
QCheckBox { spacing: 6px; }
QSplitter::handle { background: #EDF1F7; width: 7px; }
QFrame#dropArea { background: white; border: 2px dashed #C8D3E9; border-radius: 14px; }
QLabel#dropTitle { font-size: 23px; font-weight: 600; color: #2D456F; }
QTextBrowser { background: white; border: 0; }
"""


class Worker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class HoverCard(QFrame):
    open_detail = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("sideCard")
        self.resize(690, 430)
        root = QVBoxLayout(self)
        label = QLabel("全部商品编码与备注")
        label.setObjectName("sectionTitle")
        root.addWidget(label)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        root.addWidget(self.browser, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("可滚动查看全部商品；当前品牌以浅橙色标出。"), 1)
        open_button = QPushButton("打开明细")
        open_button.clicked.connect(self.open_detail.emit)
        footer.addWidget(open_button)
        root.addLayout(footer)

    def display(self, style: Style, brand: str, position: QPoint):
        self.browser.setHtml(detail_html(style, brand))
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        x = min(max(geometry.left(), position.x() + 18), geometry.right() - self.width() + 1)
        y = min(max(geometry.top(), position.y() + 18), geometry.bottom() - self.height() + 1)
        self.move(x, y)
        self.show()
        self.raise_()


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.dataset = Dataset()
        self.rules = store.brands
        self.worker = None
        self.busy = False
        self.current_style = None
        self._hover_key = None
        self._hover_position = QPoint()
        self._hover_style = None
        self._hover_brand = ""
        self.setWindowTitle("商品资料台 · 品牌与备注")
        self.resize(1530, 920)
        self.setMinimumSize(1120, 720)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self.hover = HoverCard(self)
        self.hover.open_detail.connect(self._open_hover_detail)
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(450)
        self.hover_timer.timeout.connect(self._show_hover)
        self.hover_hide = QTimer(self)
        self.hover_hide.setSingleShot(True)
        self.hover_hide.setInterval(240)
        self.hover_hide.timeout.connect(self._hide_hover_if_away)
        self.table.viewport().installEventFilter(self)
        self.table.viewport().setMouseTracking(True)
        self.table.verticalScrollBar().valueChanged.connect(self._cancel_hover)
        self.table.horizontalScrollBar().valueChanged.connect(self._cancel_hover)
        self.statusBar().showMessage("导入 Excel 后即可按款式查看品牌和商品备注。")
        self.refresh()

    def _build(self):
        canvas = QWidget()
        canvas.setObjectName("canvas")
        self.setCentralWidget(canvas)
        root = QVBoxLayout(canvas)
        root.setContentsMargins(25, 21, 25, 14)
        root.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("商品资料台")
        title.setObjectName("title")
        subtitle = QLabel("按款式汇总品牌，保留每个商品的备注")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.import_button = QPushButton("导入 Excel")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self.choose_files)
        self.rules_button = QPushButton("品牌规则")
        self.rules_button.clicked.connect(self.edit_rules)
        self.export_button = QPushButton("导出 Excel")
        export_menu = QMenu(self)
        export_menu.addAction("导出全部款式", lambda: self.choose_export(False))
        export_menu.addAction("导出当前筛选结果", lambda: self.choose_export(True))
        self.export_button.setMenu(export_menu)
        for button in (self.import_button, self.rules_button, self.export_button):
            header.addWidget(button)
        root.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索款式编码、商品编码、名称或备注")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.brand_filter = QComboBox()
        self.brand_filter.addItem("全部品牌", "")
        self.remark_filter = QComboBox()
        self.remark_filter.addItems(["全部备注", "未备注"] + list(REMARKS))
        for widget in (self.search, self.brand_filter, self.remark_filter):
            filters.addWidget(widget, 1 if widget is self.search else 0)
        root.addLayout(filters)
        self.search.textChanged.connect(self.refresh)
        for combo in (self.brand_filter, self.remark_filter):
            combo.currentIndexChanged.connect(self.refresh)

        options = QHBoxLayout()
        self.empty_brands_check = QCheckBox("显示全部品牌列")
        self.empty_brands_check.setChecked(self.store.setting("empty_brands", False))
        options.addWidget(self.empty_brands_check)
        self.empty_brands_check.toggled.connect(self.refresh)
        options.addStretch()
        root.addLayout(options)

        self.pages = QStackedWidget()
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(70, 25, 70, 25)
        drop = QFrame()
        drop.setObjectName("dropArea")
        drop_layout = QVBoxLayout(drop)
        drop_layout.setAlignment(Qt.AlignCenter)
        drop_layout.setSpacing(20)
        drop_title = QLabel("把商品 Excel 拖到这里")
        drop_title.setObjectName("dropTitle")
        drop_title.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(drop_title)
        caption = QLabel("支持 .xlsx / .xlsm，也可以同时导入多个文件\n一款式一行，自动汇总品牌与图片")
        caption.setAlignment(Qt.AlignCenter)
        caption.setObjectName("muted")
        drop_layout.addWidget(caption)
        welcome_import = QPushButton("选择 Excel 文件")
        welcome_import.setObjectName("primary")
        welcome_import.setFixedWidth(190)
        welcome_import.clicked.connect(self.choose_files)
        drop_layout.addWidget(welcome_import, alignment=Qt.AlignCenter)
        welcome_layout.addWidget(drop, 1)
        self.pages.addWidget(welcome)

        splitter = QSplitter(Qt.Horizontal)
        self.table = QTableView()
        self.model = StyleModel(self)
        self.table.setModel(self.model)
        self.table.setItemDelegate(BrandCellDelegate(self.table))
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.table.setIconSize(QSize(82, 54))
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionsMovable(False)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.setItemDelegateForColumn(0, ChoiceDelegate([""] + list(REMARKS), self.table))
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(self.table_double_clicked)
        self.model.edited.connect(self.style_edited)
        splitter.addWidget(self.table)

        side = QFrame()
        side.setObjectName("sideCard")
        side.setMinimumWidth(250)
        side.setMaximumWidth(330)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(17, 17, 17, 17)
        self.side_title = QLabel("款式详情")
        self.side_title.setObjectName("sectionTitle")
        side_layout.addWidget(self.side_title)
        self.side_info = QLabel("选择一个款式查看商品与备注")
        self.side_info.setWordWrap(True)
        side_layout.addWidget(self.side_info)
        self.picture_area = QScrollArea()
        self.picture_area.setWidgetResizable(True)
        self.picture_area.setMinimumHeight(120)
        self.picture_area.setMaximumHeight(300)
        self.picture_area.setFrameShape(QFrame.NoFrame)
        self.picture_content = QWidget()
        self.picture_layout = QVBoxLayout(self.picture_content)
        self.picture_area.setWidget(self.picture_content)
        side_layout.addWidget(self.picture_area)
        self.side_brands = QLabel("")
        self.side_brands.setWordWrap(True)
        side_layout.addWidget(self.side_brands)
        side_layout.addStretch()
        self.detail_button = QPushButton("查看 / 编辑商品明细")
        self.detail_button.setObjectName("primary")
        self.detail_button.clicked.connect(lambda: self.open_detail())
        side_layout.addWidget(self.detail_button)
        self.side_note = QLabel("√ 表示该品牌商品存在\n颜色仅作视觉区分")
        self.side_note.setObjectName("muted")
        side_layout.addWidget(self.side_note)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1180, 290])
        self.pages.addWidget(splitter)
        root.addWidget(self.pages, 1)

        self.source_caption = QLabel("尚未导入文件")
        self.source_caption.setObjectName("muted")
        self.source_caption.setWordWrap(True)
        root.addWidget(self.source_caption)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

    def _matches(self, style: Style):
        query = self.search.text().strip().casefold()
        if query:
            content = " ".join([style.code, style.name, style.remark] +
                               [" ".join([p.code, p.name, p.brand, p.source_spec, p.remark]) for p in style.products]).casefold()
            if query not in content:
                return False
        brand = self.brand_filter.currentData()
        if brand and brand not in style.brands:
            return False
        remark = self.remark_filter.currentText()
        if remark == "未备注" and style.remark:
            return False
        if remark in REMARKS and style.remark != remark:
            return False
        return True

    def refresh(self, *_):
        previous = self.current_style.code if self.current_style else ""
        filtered = [style for style in self.dataset.styles if self._matches(style)]
        self.model.configure(self.dataset, self.rules, filtered, inventory=False, show_empty=self.empty_brands_check.isChecked())
        for column, width in enumerate([96, 155, 220, 82, 135] + [70] * len(self.model.brands)):
            if column < self.model.columnCount():
                self.table.setColumnWidth(column, width)
        header = self.table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        if sort_column >= self.model.columnCount():
            sort_column = 1
        self.model.sort(sort_column, header.sortIndicatorOrder())
        self.pages.setCurrentIndex(1 if self.dataset.products else 0)
        self.export_button.setEnabled(bool(self.dataset.styles) and not self.busy)
        self.detail_button.setEnabled(bool(filtered))
        if self.dataset.products:
            names = "、".join(Path(p).name for p in self.dataset.source_files)
            self.source_caption.setText(f"来源：{names}")
        self.current_style = None
        if filtered:
            row = next((i for i, style in enumerate(self.model.styles) if style.code == previous), 0)
            self.table.selectRow(row)
            self.current_style = self.model.styles[row]
            self.update_side()
        else:
            self.update_side()
        if hasattr(self, "hover"):
            self._cancel_hover()

    def selection_changed(self, *_):
        selected = self.table.selectionModel().selectedRows()
        self.current_style = self.model.styles[selected[0].row()] if selected and selected[0].row() < len(self.model.styles) else None
        self.update_side()

    def update_side(self):
        while self.picture_layout.count():
            item = self.picture_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        style = self.current_style
        if style is None:
            self.side_title.setText("款式详情")
            self.side_info.setText("选择一个款式查看商品与备注")
            self.side_brands.setText("")
            return
        self.side_title.setText(style.code)
        self.side_info.setText(f"{style.name}\n\n{len(style.products)} 个商品编码 · {len(style.brands)} 个品牌\n"
                               f"款式备注：{style.remark or '未备注'}")
        for picture in style.pictures:
            pixmap = QPixmap()
            pixmap.loadFromData(picture.data)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(pixmap.scaled(220, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.picture_layout.addWidget(label)
        if not style.pictures:
            self.picture_layout.addWidget(QLabel("暂无商品图片"))
        self.picture_layout.addStretch()
        self.side_brands.setText("\n".join(f"{brand}：{sum(p.brand == brand for p in style.products)} 个商品"
                                         for brand in sorted(style.brands)))

    def style_edited(self, code, field, value):
        self.store.edit_style(code, field, value)
        self.refresh()
        self.statusBar().showMessage("款式修改已保存。商品独立备注在商品明细中维护。", 6000)

    def product_edited(self, code, field, value):
        self.store.edit_product(code, field, value)
        self.dataset.rebuild()
        self.refresh_brand_filter()
        self.refresh()
        self.statusBar().showMessage("商品修改已保存，重新导入会保留这些手工修改。", 5000)

    def refresh_brand_filter(self):
        previous = self.brand_filter.currentData()
        self.brand_filter.blockSignals(True)
        self.brand_filter.clear()
        self.brand_filter.addItem("全部品牌", "")
        for brand in sorted({p.brand for p in self.dataset.products}):
            self.brand_filter.addItem(brand, brand)
        self.brand_filter.setCurrentIndex(max(0, self.brand_filter.findData(previous)))
        self.brand_filter.blockSignals(False)

    def choose_files(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "导入商品 Excel", self.store.setting("last_directory", ""), "Excel 文件 (*.xlsx *.xlsm)")
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        if self.busy:
            self.statusBar().showMessage("当前任务正在处理中，请完成后再导入。", 6000)
            return
        paths = list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
        layouts = {}
        try:
            for source in paths:
                candidates = inspect_layouts(source)
                if not candidates:
                    raise ValueError(f"{Path(source).name} 没有可读取的工作表。")
                valid = [layout for layout in candidates if all(layout.mapping.get(field) for field in REQUIRED_FIELDS)]
                if not valid:
                    raise ValueError(f"{Path(source).name}：找不到商品编码、款式编码或颜色及规格，请检查源表字段名称。")
                preferred = next((layout for layout in valid if layout.sheet == "商品明细"), None)
                if preferred is not None or len(valid) == 1:
                    layouts[source] = preferred or valid[0]
                else:
                    sheet, accepted = QInputDialog.getItem(self, "选择商品工作表", Path(source).name,
                                                          [layout.sheet for layout in valid], 0, False)
                    if not accepted:
                        return
                    layouts[source] = next(layout for layout in valid if layout.sheet == sheet)
        except Exception as exc:
            QMessageBox.warning(self, "无法读取文件", str(exc))
            return
        rules = copy.deepcopy(self.rules)
        self.start_worker(lambda progress: import_files(paths, rules, layouts, progress), self.apply_dataset, "正在解析商品数据")

    def apply_dataset(self, dataset):
        self.store.apply(dataset)
        self.dataset = dataset
        if dataset.source_files:
            self.store.set_setting("last_directory", str(Path(dataset.source_files[0]).parent))
        self.model.pixmaps.clear()
        self.refresh_brand_filter()
        self.refresh()
        self.statusBar().showMessage("解析完成，备注会自动保存。", 12000)

    def start_worker(self, operation, completed, message):
        self.busy = True
        for widget in (self.import_button, self.rules_button, self.export_button):
            widget.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(message + " · %p%")
        self.progress_bar.show()
        self.worker = Worker(operation, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.succeeded.connect(completed)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()

    def on_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(message + " · %p%")

    def task_failed(self, message):
        if "Permission denied" in message or "权限" in message or "WinError 32" in message:
            message += "\n请检查文件是否被 Excel / WPS 占用，或选择其它保存位置。"
        QMessageBox.warning(self, "处理未完成", message)
        self.statusBar().showMessage("本次任务未应用。现有预览数据仍然保留。", 8000)

    def task_finished(self):
        self.busy = False
        self.progress_bar.hide()
        for widget in (self.import_button, self.rules_button):
            widget.setEnabled(True)
        self.export_button.setEnabled(bool(self.dataset.styles))

    def choose_export(self, filtered=False):
        if self.busy or not self.dataset.styles:
            return
        selected = list(self.model.styles) if filtered else list(self.dataset.styles)
        if not selected:
            QMessageBox.information(self, "没有导出内容", "当前筛选结果为空，请调整筛选条件。")
            return
        directory = self.store.setting("export_directory", str(default_export_directory()))
        destination, _ = QFileDialog.getSaveFileName(self, "导出商品资料", str(Path(directory) / "商品资料_处理结果.xlsx"), "Excel 文件 (*.xlsx)")
        if not destination:
            return
        snapshot = copy.deepcopy(self.dataset)
        selected_map = {style.code: style for style in snapshot.styles}
        selected_snapshot = [selected_map[style.code] for style in selected]
        rules = copy.deepcopy(self.rules)
        empty_brands = self.empty_brands_check.isChecked()
        self.store.set_setting("export_directory", str(Path(destination).parent))
        self.start_worker(lambda progress: export_workbook(snapshot, destination, rules, selected_snapshot,
                                                          False, empty_brands, progress), self.export_done, "正在导出 Excel")

    def export_done(self, path):
        self.statusBar().showMessage(f"导出完成：{path}", 15000)
        QMessageBox.information(self, "导出完成", f"已保存款式汇总与商品明细：\n{path}\n\n主表备注可下拉选择；将鼠标移到 √ 上可查看商品备注。")

    def edit_rules(self):
        dialog = BrandsDialog(copy.deepcopy(self.rules), self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.rules = dialog.result_rules
        self.store.set_setting("brands", self.rules)
        parser = SpecParser(self.rules)
        for product in self.dataset.products:
            parsed = parser.parse(product.source_spec)
            for field in ("name", "brand", "color", "specification"):
                if field not in product.overrides:
                    setattr(product, field, getattr(parsed, field))
        self.dataset.rebuild()
        self.refresh_brand_filter()
        self.refresh()
        self.statusBar().showMessage("品牌规则已保存，当前数据已重新解析。", 7000)

    def table_double_clicked(self, index):
        if index.column() in (0, 2):
            return
        brand = self.model.brands[index.column() - 5] if 5 <= index.column() < 5 + len(self.model.brands) else ""
        self.open_detail(brand)

    def open_detail(self, brand="", style=None):
        style = style or self.current_style
        if style is not None:
            self._cancel_hover()
            DetailDialog(style, self.product_edited, brand, self).exec_()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport():
            if event.type() == QEvent.ToolTip:
                index = self.table.indexAt(event.pos())
                if index.isValid() and 5 <= index.column() < 5 + len(self.model.brands):
                    return True
            elif event.type() == QEvent.MouseMove:
                index = self.table.indexAt(event.pos())
                if index.isValid() and 5 <= index.column() < 5 + len(self.model.brands) and index.data() == "√":
                    style = self.model.styles[index.row()]
                    brand = self.model.brands[index.column() - 5]
                    key = (style.code, brand)
                    self.hover_hide.stop()
                    if key != self._hover_key:
                        self.hover.hide()
                        self._hover_key = key
                        self._hover_style, self._hover_brand = style, brand
                        self._hover_position = self.table.viewport().mapToGlobal(event.pos())
                        self.hover_timer.start()
                else:
                    self.hover_timer.stop()
                    self._hover_key = None
                    self.hover_hide.start()
            elif event.type() == QEvent.Leave:
                self.hover_timer.stop()
                self.hover_hide.start()
        return super().eventFilter(watched, event)

    def _show_hover(self):
        if self._hover_key and self._hover_style:
            self.hover.display(self._hover_style, self._hover_brand, self._hover_position)
            # Keep checking the pointer after it moves into the scrollable card.
            self.hover_hide.start()

    def _hide_hover_if_away(self):
        position = QCursor.pos()
        if self.hover.isVisible() and self.hover.geometry().contains(position):
            self.hover_hide.start()
        else:
            local = self.table.viewport().mapFromGlobal(position)
            index = self.table.indexAt(local)
            if not index.isValid() or not (5 <= index.column() < 5 + len(self.model.brands)) or index.data() != "√":
                self.hover.hide()
                self._hover_key = None
            else:
                self.hover_hide.start()

    def _open_hover_detail(self):
        style, brand = self._hover_style, self._hover_brand
        self._cancel_hover()
        self.open_detail(brand, style)

    def _cancel_hover(self, *_):
        if hasattr(self, "hover"):
            self.hover.hide()
            self.hover_timer.stop()
            self.hover_hide.stop()
            self._hover_key = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in (".xlsx", ".xlsm") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".xlsx", ".xlsm")]
        if paths:
            event.acceptProposedAction()
            self.import_paths(paths)

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage("正在处理数据，请任务完成后再关闭窗口。", 8000)
            event.ignore()
            return
        self._cancel_hover()
        self.store.set_setting("empty_brands", self.empty_brands_check.isChecked())
        self.store.close()
        event.accept()
