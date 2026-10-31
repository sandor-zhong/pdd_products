from __future__ import annotations

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPixmap
from PyQt5.QtWidgets import QComboBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .domain import DEFAULT_BRAND_COLOR, REMARK_COLORS, REMARKS, Dataset, Product, Style, quantity
from .exporter import STOCK_COLUMNS, brand_columns


class ChoiceDelegate(QStyledItemDelegate):
    def __init__(self, choices, parent=None, editable=False):
        super().__init__(parent)
        self.choices = choices
        self.editable = editable

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(self.editable)
        editor.addItems(list(self.choices))
        editor.activated.connect(lambda: self._commit(editor))
        return editor

    def _commit(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

    def setEditorData(self, editor, index):
        value = str(index.data(Qt.EditRole) or "")
        location = editor.findText(value)
        if location >= 0:
            editor.setCurrentIndex(location)
        elif editor.isEditable():
            editor.setEditText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


class BrandCellDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        copied = QStyleOptionViewItem(option)
        if index.data(Qt.DisplayRole) == "√" and index.data(Qt.BackgroundRole) is not None:
            copied.state &= ~QStyle.State_Selected
        super().paint(painter, copied, index)


class StyleModel(QAbstractTableModel):
    edited = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.styles: list[Style] = []
        self.brands: list[str] = []
        self.colors = {}
        self.inventory = False
        self.headers = []
        self.pixmaps = {}

    def configure(self, dataset: Dataset, rules, styles=None, inventory=False, show_empty=False):
        self.beginResetModel()
        self.styles = list(dataset.styles if styles is None else styles)
        self.brands = brand_columns(dataset, rules, show_empty)
        self.colors = {rule["name"]: rule.get("color", DEFAULT_BRAND_COLOR) for rule in rules}
        self.inventory = inventory
        self.headers = ["备注", "款式编码", "商品名称", "图片", "创建时间"] + self.brands
        if inventory:
            self.headers.extend(label for label, _ in STOCK_COLUMNS)
            self.headers.extend(["商品数", "待核对"])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.styles)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.headers[section] if orientation == Qt.Horizontal else section + 1
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        return None

    def value(self, style, column):
        if column < 5:
            return [style.remark, style.code, style.name, "", style.created_at][column]
        if column < 5 + len(self.brands):
            return "√" if self.brands[column - 5] in style.brands else ""
        stock_index = column - 5 - len(self.brands)
        if stock_index < len(STOCK_COLUMNS):
            return style.stock(STOCK_COLUMNS[stock_index][1])
        return len(style.products) if stock_index == len(STOCK_COLUMNS) else sum(bool(p.problems) for p in style.products)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.styles):
            return None
        style = self.styles[index.row()]
        column = index.column()
        value = self.value(style, column)
        if role == Qt.UserRole:
            return style
        if role == Qt.EditRole:
            return value
        if role == Qt.DisplayRole:
            if column == 4:
                return value.strftime("%Y年%m月%d日") if value else "未知"
            if column >= 5 + len(self.brands):
                return quantity(value)
            return value or ("选择备注" if column == 0 else "")
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignVCenter | (Qt.AlignLeft if column in (1, 2) else Qt.AlignHCenter))
        if role == Qt.BackgroundRole:
            if column == 0 and style.remark in REMARK_COLORS:
                return QColor(REMARK_COLORS[style.remark][0])
            if 5 <= column < 5 + len(self.brands) and value:
                return QColor(self.colors.get(self.brands[column - 5], DEFAULT_BRAND_COLOR))
        if role == Qt.ForegroundRole:
            if column == 0:
                return QColor(REMARK_COLORS.get(style.remark, ("", "#7E8898"))[1])
            if column >= 5 + len(self.brands) and value is None:
                return QColor("#B54708")
        if role == Qt.FontRole and 5 <= column < 5 + len(self.brands) and value:
            return QFont("Segoe UI", 15)
        if role == Qt.DecorationRole and column == 3 and style.pictures:
            picture = style.pictures[0]
            if picture.key not in self.pixmaps:
                pixmap = QPixmap()
                pixmap.loadFromData(picture.data)
                self.pixmaps[picture.key] = pixmap.scaled(82, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return self.pixmaps[picture.key]
        if role == Qt.ToolTipRole:
            if column == 0:
                return "款式备注为单选；每个商品的独立备注在明细中维护。"
            if column == 2:
                return style.name
            if column == 3:
                return f"共 {len(style.pictures)} 张不同图片，右侧可查看全部图片。"
        return None

    def flags(self, index):
        result = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and index.column() in (0, 2):
            result |= Qt.ItemIsEditable
        return result

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid() or index.column() not in (0, 2):
            return False
        text = str(value or "").strip()
        if index.column() == 0 and text and text not in REMARKS:
            return False
        style = self.styles[index.row()]
        field = "remark" if index.column() == 0 else "name"
        setattr(style, "remark" if field == "remark" else "name_override", text)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole, Qt.ForegroundRole])
        self.edited.emit(style.code, field, text)
        return True

    def sort(self, column, order=Qt.AscendingOrder):
        if not self.styles or column >= len(self.headers):
            return
        self.layoutAboutToBeChanged.emit()
        old_indices = self.persistentIndexList()
        identities = [(self.styles[index.row()], index.column()) for index in old_indices]
        self.styles.sort(key=lambda style: (self.value(style, column) is None,
                                           self.value(style, column) if self.value(style, column) is not None else ""),
                         reverse=order == Qt.DescendingOrder)
        positions = {id(style): row for row, style in enumerate(self.styles)}
        self.changePersistentIndexList(old_indices, [self.index(positions[id(style)], col) for style, col in identities])
        self.layoutChanged.emit()


PRODUCT_COLUMNS = [
    ("商品编码", "code"), ("商品名称", "name"), ("品牌", "brand"), ("颜色", "color"),
    ("规格", "specification"), ("商品备注", "remark"),
    ("实际库存", "actual_stock"), ("可用库存", "available_stock"), ("订单占用", "occupied_stock"),
    ("采购在途", "transit_stock"), ("30天销量", "sales_30d"), ("源商品状态", "source_status"),
    ("店铺链接数", "link_count"), ("创建时间", "created_at"), ("原颜色及规格", "source_spec"),
]
PRODUCT_NUMERIC_FIELDS = {attribute for _, attribute in STOCK_COLUMNS} | {"link_count"}


class ProductModel(QAbstractTableModel):
    edited = pyqtSignal(str, str, str)

    def __init__(self, products: list[Product], parent=None):
        super().__init__(parent)
        self.products = products

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.products)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(PRODUCT_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return PRODUCT_COLUMNS[section][0] if orientation == Qt.Horizontal else section + 1
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        product = self.products[index.row()]
        attribute = PRODUCT_COLUMNS[index.column()][1]
        value = getattr(product, attribute)
        if role in (Qt.EditRole, Qt.UserRole):
            return value
        if role == Qt.DisplayRole:
            if attribute == "created_at":
                return value.strftime("%Y-%m-%d %H:%M:%S") if value else "未知"
            if attribute in PRODUCT_NUMERIC_FIELDS:
                return quantity(value)
            return value
        if role == Qt.BackgroundRole and attribute == "remark" and value in REMARK_COLORS:
            return QColor(REMARK_COLORS[value][0])
        if role == Qt.ForegroundRole:
            if value is None or value == "待确认":
                return QColor("#B54708")
            if attribute == "remark" and value in REMARK_COLORS:
                return QColor(REMARK_COLORS[value][1])
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignVCenter | (Qt.AlignRight if attribute in PRODUCT_NUMERIC_FIELDS else Qt.AlignLeft))
        if role == Qt.ToolTipRole:
            return product.source_spec
        return None

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and index.column() in range(1, 6):
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid() or index.column() not in range(1, 6):
            return False
        text = str(value or "").strip()
        attribute = PRODUCT_COLUMNS[index.column()][1]
        if attribute in ("name", "brand") and not text:
            return False
        product = self.products[index.row()]
        setattr(product, attribute, text)
        product.overrides[attribute] = text
        self.dataChanged.emit(index, index)
        self.edited.emit(product.code, attribute, text)
        return True


class ProductFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.brand = ""
        self.setSortRole(Qt.UserRole)

    def filterAcceptsRow(self, row, parent):
        product = self.sourceModel().products[row]
        searchable = " ".join(str(getattr(product, attribute) or "") for _, attribute in PRODUCT_COLUMNS).casefold()
        return (not self.brand or product.brand == self.brand) and (not self.query or self.query.casefold() in searchable)

    def lessThan(self, left, right):
        a, b = left.data(Qt.UserRole), right.data(Qt.UserRole)
        if a is None or b is None:
            return a is not None and b is None
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)
