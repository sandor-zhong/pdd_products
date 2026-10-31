from __future__ import annotations

import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .domain import DEFAULT_BRAND_COLOR, REMARKS, Style
from .models import ChoiceDelegate, ProductFilter, ProductModel


class BrandsDialog(QDialog):
    def __init__(self, rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("品牌识别规则与显示顺序")
        self.resize(880, 620)
        self.result_rules = rules
        root = QVBoxLayout(self)
        hint = QLabel("从“颜色及规格”末尾识别品牌，优先匹配较长别名。别名用逗号分隔；无品牌归为原品牌。\n颜色仅用于视觉区分。规则保存后会重新解析当前数据，并保留手工修正。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["品牌名称", "识别别名", "单元格颜色"])
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 470)
        self.table.setColumnWidth(2, 150)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for rule in rules:
            self.add_row(rule)
        self.table.cellDoubleClicked.connect(self.choose_color)
        root.addWidget(self.table)
        controls = QHBoxLayout()
        for label, callback in [("添加品牌", lambda: self.add_row()), ("删除所选", self.remove_row),
                                ("上移", lambda: self.move_row(-1)), ("下移", lambda: self.move_row(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addStretch()
        root.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存规则")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def add_row(self, rule=None):
        rule = rule if isinstance(rule, dict) else {"name": "新品牌", "aliases": [], "color": DEFAULT_BRAND_COLOR}
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate([rule["name"], ", ".join(rule.get("aliases", [])), rule["color"]]):
            self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.item(row, 2).setBackground(QColor(rule["color"]))

    def remove_row(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def move_row(self, offset):
        row = self.table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        for column in range(3):
            a, b = self.table.takeItem(row, column), self.table.takeItem(target, column)
            self.table.setItem(row, column, b)
            self.table.setItem(target, column, a)
        self.table.selectRow(target)

    def choose_color(self, row, column):
        if column != 2:
            return
        item = self.table.item(row, column)
        color = QColorDialog.getColor(QColor(item.text()), self, "选择品牌单元格颜色")
        if color.isValid():
            item.setText(color.name())
            item.setBackground(color)

    def validate(self):
        rules, aliases, names = [], {}, set()
        for row in range(self.table.rowCount()):
            name, alias_text, color = [self.table.item(row, c).text().strip() if self.table.item(row, c) else "" for c in range(3)]
            if not name or name in names or name == "待确认" or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                QMessageBox.warning(self, "规则无效", f"第 {row + 1} 行：名称须唯一且非空，不能使用“待确认”；颜色格式为 #RRGGBB。")
                return
            names.add(name)
            values = list(dict.fromkeys([v.strip() for v in re.split(r"[,，;；]", alias_text) if v.strip()] + [name]))
            for alias in values:
                if alias.casefold() in aliases and aliases[alias.casefold()] != name:
                    QMessageBox.warning(self, "别名重复", f"别名“{alias}”属于多个品牌，请修正后保存。")
                    return
                aliases[alias.casefold()] = name
            rules.append({"name": name, "aliases": values, "color": color})
        if "原品牌" not in names:
            rules.append({"name": "原品牌", "aliases": ["原品牌"], "color": DEFAULT_BRAND_COLOR})
        self.result_rules = rules
        self.accept()


class DetailDialog(QDialog):
    def __init__(self, style: Style, on_edit, brand="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"商品明细 · {style.code}")
        self.resize(1320, 780)
        root = QVBoxLayout(self)
        heading = QLabel(f"{style.name}　/　共 {len(style.products)} 个商品编码")
        heading.setObjectName("dialogHeading")
        root.addWidget(heading)
        root.addWidget(QLabel("双击名称、品牌、颜色、规格或商品备注可以修改。"))
        search_bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索商品编码、规格或备注")
        self.brands = QComboBox()
        self.brands.addItem("全部品牌", "")
        for name in sorted(style.brands):
            self.brands.addItem(name, name)
        if brand:
            self.brands.setCurrentIndex(max(0, self.brands.findData(brand)))
        search_bar.addWidget(self.search, 1)
        search_bar.addWidget(self.brands)
        root.addLayout(search_bar)
        self.model = ProductModel(style.products, self)
        self.model.edited.connect(on_edit)
        self.proxy = ProductFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setColumnWidth(0, 285)
        self.table.setColumnWidth(1, 225)
        self.table.setColumnWidth(5, 145)
        self.table.setColumnWidth(13, 180)
        self.table.setColumnWidth(14, 350)
        for column in range(6, 11):
            self.table.setColumnHidden(column, True)
        self.table.setItemDelegateForColumn(2, ChoiceDelegate(sorted(style.brands | {"原品牌"}), self.table, editable=True))
        self.table.setItemDelegateForColumn(5, ChoiceDelegate([""] + list(REMARKS), self.table, editable=True))
        root.addWidget(self.table, 1)
        self.search.textChanged.connect(self.filter)
        self.brands.currentIndexChanged.connect(self.filter)
        self.filter()
        controls = QHBoxLayout()
        controls.addStretch()
        close = QPushButton("完成")
        close.clicked.connect(self.accept)
        controls.addWidget(close)
        root.addLayout(controls)

    def filter(self):
        self.proxy.query = self.search.text().strip()
        self.proxy.brand = self.brands.currentData() or ""
        self.proxy.invalidateFilter()

