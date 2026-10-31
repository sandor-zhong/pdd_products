from __future__ import annotations

import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .domain import DEFAULT_BRAND_COLOR, DEFAULT_BRANDS, Dataset, REMARK_COLORS, REMARKS, Style, detail_text
from .parser import infer_mapping

EDITABLE_SOURCE_FIELDS = {"商品名称": "name", "品牌": "brand", "颜色": "color", "规格": "specification"}
STOCK_COLUMNS = [("实际库存", "actual_stock"), ("可用库存", "available_stock"),
                 ("订单占用", "occupied_stock"), ("采购在途", "transit_stock"),
                 ("30天销量", "sales_30d")]
THIN_BORDER = Border(*(Side(style="thin", color="777777") for _ in range(4)))


def brand_columns(dataset: Dataset, brands: list[dict] | None = None, show_empty: bool = False) -> list[str]:
    rules = brands if brands is not None else DEFAULT_BRANDS
    present = {p.brand for p in dataset.products}
    names = [rule["name"] for rule in rules if show_empty or rule["name"] in present]
    names.extend(sorted(present - set(names)))
    return names


def image_for_export(picture, width=86, height=54) -> Image:
    with PILImage.open(BytesIO(picture.data)) as source:
        converted = source.convert("RGBA")
        converted.thumbnail((width, height))
        blob = BytesIO()
        converted.save(blob, format="PNG")
    blob.seek(0)
    return Image(blob)


def _cell(sheet, row: int, column: int, value, identifier=False):
    cell = sheet.cell(row, column)
    cell.value = value
    if isinstance(value, str):
        # Source strings and manual notes are literal data, including strings beginning with '='.
        cell.data_type = "s"
    cell.font = Font(name="Microsoft YaHei", size=10, color="20242B")
    cell.border = THIN_BORDER
    cell.alignment = Alignment(vertical="center", horizontal="left" if isinstance(value, str) else "right", wrap_text=False)
    if identifier:
        cell.number_format = "@"
    elif isinstance(value, datetime):
        cell.number_format = 'yyyy"年"m"月"d"日"'
        cell.alignment = Alignment(horizontal="center", vertical="center")
    elif isinstance(value, (int, float)):
        cell.number_format = "#,##0" if value == int(value) else "#,##0.00####"
    return cell


def _header(sheet, headers: list[str], widths: list[float], freeze: str):
    sheet.freeze_panes = freeze
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 90
    sheet.row_dimensions[1].height = 32
    for column, header in enumerate(headers, 1):
        cell = _cell(sheet, 1, column, header)
        cell.fill = PatternFill("solid", fgColor="EBECEF")
        cell.font = Font(name="Microsoft YaHei", size=10, bold=True, color="111827")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = widths[column - 1]
    sheet.print_title_rows = "1:1"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0


def _dropdown(sheet, column: int, last_row: int, options, strict=True):
    if last_row < 2:
        return
    validation = DataValidation(type="list", formula1='"' + ",".join(options) + '"',
                                allow_blank=True, showDropDown=False)
    validation.showErrorMessage = strict
    validation.errorStyle = "stop"
    validation.errorTitle = "请选择列表中的状态"
    validation.error = "请选择下拉选项，或清空该单元格。"
    sheet.add_data_validation(validation)
    letter = get_column_letter(column)
    validation.add(f"{letter}2:{letter}{last_row}")
    if options == REMARKS:
        for label, (background, foreground) in REMARK_COLORS.items():
            sheet.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'${letter}2="{label}"'],
                            fill=PatternFill("solid", fgColor=background.lstrip("#")),
                            font=Font(color=foreground.lstrip("#")), stopIfTrue=True),
            )


def export_workbook(dataset: Dataset, destination: str | Path, brands: list[dict] | None = None,
                    styles: list[Style] | None = None, include_inventory=False, show_empty_brands=False,
                    progress=None) -> Path:
    path = Path(destination).resolve()
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    if any(path == Path(source).resolve() for source in dataset.source_files):
        raise ValueError("请选择新的导出文件名，不能覆盖导入的源文件。")
    selected = list(styles) if styles is not None else list(dataset.styles)
    if not selected:
        raise ValueError("没有可导出的款式，请调整筛选条件。")
    rules = brands if brands is not None else DEFAULT_BRANDS
    selected_products = [p for style in selected for p in style.products]
    detail_headers = list(dict.fromkeys(key for product in selected_products for key in product.raw))
    if not detail_headers:
        raise ValueError("没有可导出的源字段，请先导入商品 Excel。")
    subset = Dataset(products=selected_products)
    columns = brand_columns(subset, rules, show_empty_brands)
    colors = {rule["name"]: rule.get("color", DEFAULT_BRAND_COLOR).lstrip("#") for rule in rules}
    workbook = Workbook()
    workbook.properties.title = "商品资料台 · 款式品牌汇总"
    workbook.properties.description = (
        "√ 表示款式存在对应品牌的商品。品牌格颜色仅用于视觉区分。"
        "商品明细仅包含源数据已有的字段，保留源字段名称与顺序。"
        "悬浮备注为本次导出的快照，后续修改明细后请重新导入并导出以刷新。"
    )
    summary = workbook.active
    summary.title = "款式汇总"
    summary.sheet_properties.tabColor = "3C65DA"
    headers = ["备注", "款式编码", "商品名称", "图片", "创建时间"] + columns
    widths = [14, 24, 34, 15, 19] + [12] * len(columns)
    if include_inventory:
        headers.extend(label for label, _ in STOCK_COLUMNS)
        headers.extend(["商品数", "待核对商品数"])
        widths.extend([15] * (len(STOCK_COLUMNS) + 2))
    _header(summary, headers, widths, "F2")
    summary["E1"].comment = Comment("款式创建时间取所属商品最早创建时间。", "商品资料台")
    for index, brand in enumerate(columns, 6):
        summary.cell(1, index).comment = Comment("√ 表示该款式存在此品牌商品，颜色没有业务含义。\n鼠标悬浮查看本次导出时的全部商品备注。", "商品资料台")
    for row, style in enumerate(selected, 2):
        values = [style.remark, style.code, style.name, "", style.created_at]
        values.extend("√" if brand in style.brands else "" for brand in columns)
        if include_inventory:
            values.extend(style.stock(attribute) for _, attribute in STOCK_COLUMNS)
            values.extend([len(style.products), sum(bool(p.problems) for p in style.products)])
        summary.row_dimensions[row].height = 48 if style.pictures else 24
        for column, value in enumerate(values, 1):
            cell = _cell(summary, row, column, value, identifier=column == 2)
            if 6 <= column < 6 + len(columns):
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if value:
                    brand = columns[column - 6]
                    cell.fill = PatternFill("solid", fgColor=colors.get(brand, DEFAULT_BRAND_COLOR.lstrip("#")))
                    cell.font = Font(name="Calibri", size=15, color="222222")
                    text = detail_text(style, brand)
                    if len(text) > 32000:
                        text = text[:31500] + "\n内容较长；全部商品编码及备注请查看商品明细。"
                    cell.comment = Comment(text, "商品资料台")
                    cell.comment.width = 640
                    cell.comment.height = 460
            if include_inventory and 6 + len(columns) <= column < 6 + len(columns) + len(STOCK_COLUMNS) and value is None:
                cell.comment = Comment("所属商品中存在未知数值，汇总留空；请查看商品明细。", "商品资料台")
        if style.pictures:
            summary.add_image(image_for_export(style.pictures[0]), f"D{row}")
            summary.cell(row, 4).comment = Comment(f"此款式保留 {len(style.pictures)} 张不同图片，其它图片见商品明细。", "商品资料台")
        if progress:
            progress(int(35 * (row - 1) / len(selected)), "正在生成款式汇总")
    _dropdown(summary, 1, len(selected) + 1, REMARKS)
    summary.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(selected) + 1}"

    detail = workbook.create_sheet("商品明细")
    detail_widths = [52 if "规格" in header else 15 if header in ("图片", "商品图片", "主图") else 22
                     for header in detail_headers]
    _header(detail, detail_headers, detail_widths, "D2")
    for row, product in enumerate(selected_products, 2):
        detail.row_dimensions[row].height = 46 if product.pictures else 24
        mapping = product.source_mapping or infer_mapping(list(product.raw))
        for column, header in enumerate(detail_headers, 1):
            value = product.raw.get(header)
            if header in product.raw:
                attribute = EDITABLE_SOURCE_FIELDS.get(header)
                if header == mapping.get("备注"):
                    attribute = "remark"
                    if product.remark != str(value or "").strip():
                        value = product.remark
                if attribute in product.overrides:
                    value = getattr(product, attribute)
                for field, attribute in (("商品编码", "code"), ("款式编码", "style_code")):
                    if header == mapping.get(field) and value is not None and str(value).strip():
                        value = getattr(product, attribute)
            cell = _cell(detail, row, column, value, identifier=header in (mapping.get("商品编码"), mapping.get("款式编码")))
            if header == mapping.get("创建时间") and isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
        image_header = mapping.get("图片")
        if product.pictures and image_header in detail_headers:
            image_column = get_column_letter(detail_headers.index(image_header) + 1)
            detail.add_image(image_for_export(product.pictures[0]), f"{image_column}{row}")
        if progress and (row % 100 == 0 or row == len(selected_products) + 1):
            progress(35 + int(55 * (row - 1) / len(selected_products)), "正在生成商品明细及图片")
    mapping = infer_mapping(detail_headers)
    header = mapping.get("备注")
    if header:
        _dropdown(detail, detail_headers.index(header) + 1, len(selected_products) + 1, REMARKS, strict=False)
    detail.auto_filter.ref = f"A1:{get_column_letter(len(detail_headers))}{len(selected_products) + 1}"

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".product-export-", suffix=".xlsx", dir=path.parent)
    os.close(handle)
    try:
        workbook.save(temporary)
        os.replace(temporary, path)
    finally:
        workbook.close()
        if Path(temporary).exists():
            Path(temporary).unlink()
    if progress:
        progress(100, "导出完成")
    return path
