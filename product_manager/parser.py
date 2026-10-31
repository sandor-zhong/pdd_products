from __future__ import annotations

import math
import posixpath
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from .domain import DEFAULT_BRANDS, Dataset, Picture, Product

FIELD_ALIASES = {
    "商品编码": ("商品编码", "SKU编码", "SKU", "sku", "货品编码"),
    "款式编码": ("款式编码", "款号", "款式编号", "SPU"),
    "颜色及规格": ("颜色及规格", "颜色规格", "颜色及规格名称", "商品规格", "原颜色及规格"),
    "创建时间": ("创建时间", "创建日期"),
    "实际库存数": ("实际库存数", "实际库存", "库存数", "库存数量"),
    "可用数": ("可用数", "可用库存", "可用库存数"),
    "订单占有数": ("订单占有数", "订单占用数", "占用库存", "订单占用"),
    "采购在途数": ("采购在途数", "采购在途", "在途库存"),
    "30天销量": ("30天销量", "近30天销量"),
    "商品状态": ("商品状态", "货品状态", "源商品状态"),
    "店铺链接数": ("店铺链接数", "链接数"),
    "备注": ("商品备注", "备注"),
    "图片": ("图片", "商品图片", "主图"),
}
REQUIRED_FIELDS = ("商品编码", "款式编码", "颜色及规格")
COLORS = ("颜色随机", "随机色", "透明色", "透明", "黑白色", "深空灰", "深灰色", "浅灰色", "玫瑰金",
          "香槟金", "星光色", "黑色", "白色", "蓝色", "紫色", "灰色", "银色", "金色", "红色", "粉色",
          "绿色", "黄色", "橙色", "棕色", "米色", "咖啡色", "黑", "白", "蓝", "紫", "灰", "银", "红", "粉")
COLOR_RE = re.compile(r"(?:^|\s)(" + "|".join(re.escape(c) for c in COLORS) + r")(?=\s|$)")
SIZE_RE = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m|英寸|寸|GB|TB|毫安|mAh|个装|条装))(?=\s|$)", re.I)


@dataclass
class Layout:
    sheet: str
    header_row: int
    headers: list[str]
    mapping: dict[str, str]


@dataclass
class ParsedSpec:
    name: str
    brand: str
    color: str
    specification: str


class SpecParser:
    def __init__(self, brands: list[dict] | None = None):
        self.brands = brands if brands is not None else DEFAULT_BRANDS
        pairs = [(alias, item["name"]) for item in self.brands
                 for alias in set(item.get("aliases", []) + [item["name"]]) if alias]
        self.aliases = sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)

    def parse(self, value: str) -> ParsedSpec:
        text = re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()
        if not text:
            return ParsedSpec("待确认", "待确认", "", "")
        brand = "原品牌"
        for alias, canonical in self.aliases:
            pattern = r"(?:\s+|[（(\[])(?:" + re.escape(alias) + r")[）)\]]?\s*$"
            match = re.search(pattern, text, re.I)
            if match:
                brand = canonical
                text = text[:match.start()].strip()
                break
        color_match = COLOR_RE.search(text)
        size_match = SIZE_RE.search(text)
        color = color_match.group(1) if color_match else ""
        if color_match:
            name = text[:color_match.start()].strip()
            specification = text[color_match.end():].strip()
        elif size_match:
            name = text[:size_match.start()].strip()
            specification = text[size_match.start():].strip()
        else:
            name, specification = text, ""
        # A suffix after a recognizable measurement may be an unregistered brand.
        # Expose the ambiguity instead of silently classifying it as the original brand.
        if brand == "原品牌" and specification:
            measurement = SIZE_RE.match(specification)
            if measurement:
                tail = specification[measurement.end():].strip()
                if tail and not re.fullmatch(r"(?:\d+(?:\.\d+)?\s*(?:米|m|cm|毫米|厘米|条|个|套)|[xX×/\-+\d .])+", tail):
                    brand = "待确认"
        return ParsedSpec(name or "待确认", brand, color, specification)


def number(value) -> float | None:
    if value is None or isinstance(value, bool) or str(value).strip() in ("", "—", "-", "未知", "null", "None"):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def date_value(value, epoch=None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time())
    if isinstance(value, (float, int)) and epoch is not None:
        try:
            result = from_excel(value, epoch)
            return result if isinstance(result, datetime) else None
        except (ValueError, OverflowError):
            return None
    text = str(value or "").strip().replace("年", "-").replace("月", "-").replace("日", "")
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def identifier(cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == int(value):
        fmt = str(cell.number_format or "")
        if re.fullmatch(r"0+", fmt):
            return str(int(value)).zfill(len(fmt))
        return str(int(value))
    return str(value).strip()


def _headers(values: list) -> list[str]:
    seen = {}
    result = []
    for index, value in enumerate(values):
        name = str(value).strip() if value is not None else f"未命名列{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}（{seen[name]}）")
    return result


def infer_mapping(headers: list[str]) -> dict[str, str]:
    return {field: next((alias for alias in aliases if alias in headers), "") for field, aliases in FIELD_ALIASES.items()}


def inspect_layouts(path: str | Path) -> list[Layout]:
    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("请导入 .xlsx 或 .xlsm 文件；旧版 .xls 请先另存为 .xlsx。")
    workbook = load_workbook(path, read_only=True, data_only=True)
    result = []
    try:
        for sheet in workbook:
            candidates = []
            for row_number, values in enumerate(sheet.iter_rows(max_row=20, values_only=True), 1):
                if any(v is not None for v in values):
                    headers = _headers(list(values))
                    mapping = infer_mapping(headers)
                    score = sum(bool(mapping[field]) for field in REQUIRED_FIELDS)
                    candidates.append((score, row_number, headers, mapping,
                                       sum(bool(v) for v in mapping.values()),
                                       sum(isinstance(v, str) and bool(v.strip()) for v in values)))
            if candidates:
                best = max(candidates, key=lambda item: (item[0], item[4], item[5]))
                result.append(Layout(sheet.title, best[1], best[2], best[3]))
        return result
    finally:
        workbook.close()


def read_layout(path: str | Path, sheet_name: str, header_row: int) -> Layout:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name]
        values = next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True), ())
        headers = _headers(list(values))
        return Layout(sheet_name, header_row, headers, infer_mapping(headers))
    finally:
        workbook.close()


def read_pictures(path: Path, sheet_name: str) -> tuple[dict[int, list[Picture]], list[str]]:
    """Read OOXML drawing anchors; blank image cell values do not mean no image."""
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    pictures: dict[int, list[Picture]] = {}
    issues = []

    def relationships(archive, part):
        rel_path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if rel_path not in archive.namelist():
            return {}
        return {item.attrib["Id"]: posixpath.normpath(posixpath.join(posixpath.dirname(part), item.attrib["Target"]))
                if not item.attrib["Target"].startswith("/") else item.attrib["Target"].lstrip("/")
                for item in ET.fromstring(archive.read(rel_path)).findall(rel_ns + "Relationship")
                if item.attrib.get("TargetMode") != "External"}

    try:
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = relationships(archive, "xl/workbook.xml")
            sheet = next(item for item in workbook.findall("main:sheets/main:sheet", ns) if item.attrib["name"] == sheet_name)
            part = rels[sheet.attrib["{" + ns["r"] + "}id"]]
            sheet_xml = ET.fromstring(archive.read(part))
            sheet_rels = relationships(archive, part)
            cache: dict[str, Picture] = {}
            for drawing in sheet_xml.findall("main:drawing", ns):
                drawing_part = sheet_rels.get(drawing.attrib["{" + ns["r"] + "}id"])
                if not drawing_part:
                    continue
                drawing_rels = relationships(archive, drawing_part)
                for anchor in ET.fromstring(archive.read(drawing_part)):
                    origin = anchor.find("xdr:from", ns)
                    if origin is None:
                        continue
                    row = int(origin.find("xdr:row", ns).text) + 1
                    for blip in anchor.findall(".//a:blip", ns):
                        image_part = drawing_rels.get(blip.attrib.get("{" + ns["r"] + "}embed", ""))
                        if image_part and image_part in archive.namelist():
                            if image_part not in cache:
                                cache[image_part] = Picture(archive.read(image_part), posixpath.basename(image_part))
                            pictures.setdefault(row, []).append(cache[image_part])
    except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile, StopIteration) as exc:
        issues.append(f"{path.name} / {sheet_name}：部分嵌入图片无法读取（{exc}）")
    return pictures, issues


def import_files(paths: list[str | Path], brands: list[dict] | None = None,
                 layouts: dict[str, Layout] | None = None,
                 progress: Callable[[int, str], None] | None = None) -> Dataset:
    dataset = Dataset(source_files=[str(Path(path).resolve()) for path in paths])
    spec_parser = SpecParser(brands)
    seen: dict[str, Product] = {}
    for file_index, source in enumerate(paths):
        path = Path(source)
        layout = (layouts or {}).get(str(path.resolve()))
        if layout is None:
            candidates = inspect_layouts(path)
            layout = next((item for item in candidates if all(item.mapping.get(f) for f in REQUIRED_FIELDS)), None)
            if layout is None:
                raise ValueError(f"{path.name}：找不到商品编码、款式编码或颜色及规格，请检查源表字段名称。")
        missing = [field for field in REQUIRED_FIELDS if not layout.mapping.get(field)]
        if missing:
            raise ValueError(f"{path.name}：缺少必要字段：{'、'.join(missing)}")
        pictures, image_issues = read_pictures(path, layout.sheet)
        dataset.issues.extend(image_issues)
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook[layout.sheet]
            indices = {field: layout.headers.index(header) for field, header in layout.mapping.items() if header}
            for row_number, cells in enumerate(sheet.iter_rows(min_row=layout.header_row + 1), layout.header_row + 1):
                values = [cell.value for cell in cells]
                if not any(v is not None for v in values):
                    continue
                def get(field):
                    index = indices.get(field)
                    return values[index] if index is not None and index < len(values) else None
                def code(field):
                    index = indices.get(field)
                    return identifier(cells[index]) if index is not None and index < len(cells) else ""
                raw = dict(zip(layout.headers, values))
                source_spec = str(get("颜色及规格") or "").strip()
                parsed = spec_parser.parse(source_spec)
                product_code = code("商品编码") or f"缺少商品编码：{path.name}|{layout.sheet}|{row_number}"
                product = Product(
                    code=product_code, style_code=code("款式编码"), name=parsed.name, brand=parsed.brand,
                    color=parsed.color, specification=parsed.specification, source_spec=source_spec,
                    remark=str(get("备注") or "").strip(),
                    created_at=date_value(get("创建时间"), workbook.epoch),
                    actual_stock=number(get("实际库存数")), available_stock=number(get("可用数")),
                    occupied_stock=number(get("订单占有数")), transit_stock=number(get("采购在途数")),
                    sales_30d=number(get("30天销量")), source_status=str(get("商品状态") or ""),
                    link_count=number(get("店铺链接数")), raw=raw, source_mapping=dict(layout.mapping), pictures=pictures.get(row_number, []),
                    source_file=str(path.resolve()), source_sheet=layout.sheet, source_row=row_number,
                )
                # Own exported detail sheets carry explicit corrections alongside the original text.
                if all(h in layout.headers for h in ("原颜色及规格", "来源行号")):
                    for header, field in (("商品名称", "name"), ("品牌", "brand"), ("颜色", "color"), ("规格", "specification"),
                                          ("备注", "remark")):
                        value = raw.get(header)
                        if value is not None:
                            text = str(value).strip()
                            setattr(product, field, text)
                            product.overrides[field] = text
                    product.imported_style_state = {"remark": str(raw.get("款式备注") or "").strip(),
                                                    "name": str(raw.get("款式统一名称") or "").strip()}
                    original = {key[2:]: value for key, value in raw.items() if key.startswith("源·")}
                    if original:
                        product.raw = original
                        product.source_mapping = infer_mapping(list(original))
                if product_code in seen:
                    previous = seen[product_code]
                    comparable = ("style_code", "name", "brand", "color", "specification", "remark",
                                  "created_at", "actual_stock", "available_stock", "occupied_stock", "transit_stock", "sales_30d")
                    if previous.raw == product.raw and all(getattr(previous, f) == getattr(product, f) for f in comparable):
                        dataset.issues.append(f"重复商品编码 {product_code}：相同记录已去重（{path.name} 第 {row_number} 行）")
                        continue
                    raise ValueError(f"商品编码 {product_code} 出现不同数据。\n"
                                     f"第一处：{Path(previous.source_file).name} / {previous.source_sheet} 第 {previous.source_row} 行\n"
                                     f"第二处：{path.name} / {layout.sheet} 第 {row_number} 行\n"
                                     "本次导入未应用，请选择一个数据版本或修正重复记录后重试，避免库存重复累计。")
                seen[product_code] = product
                dataset.products.append(product)
                if progress and (row_number % 100 == 0 or row_number == sheet.max_row):
                    fraction = (row_number - layout.header_row) / max(1, sheet.max_row - layout.header_row)
                    progress(int(100 * (file_index + fraction) / len(paths)), f"正在读取 {path.name}：{row_number - layout.header_row} 条")
        finally:
            workbook.close()
    if not dataset.products:
        raise ValueError("没有找到商品数据，请检查工作表和表头行。")
    dataset.rebuild()
    for style in dataset.styles:
        imported = [p.imported_style_state for p in style.products if p.imported_style_state]
        for header, state_key, field in (("款式备注", "remark", "remark"), ("款式统一名称", "name", "name_override")):
            values = {state.get(state_key, "") for state in imported}
            if len(values) == 1:
                value = next(iter(values))
                if field == "remark" and value not in ("", "已下架", "清仓", "无品牌", "批发专用"):
                    dataset.issues.append(f"{style.code}：款式备注不属于可选状态，请在主表修正。")
                else:
                    setattr(style, field, value)
            elif any(values):
                dataset.issues.append(f"{style.code}：明细中的{header}不一致，请在主表统一设置。")
    if progress:
        progress(100, f"完成：{len(dataset.products)} 个商品，{len(dataset.styles)} 个款式")
    return dataset
