from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from html import escape
from typing import Any

REMARKS = ("已下架", "清仓", "无品牌", "批发专用")
REMARK_COLORS = {
    "已下架": ("#FDE2E2", "#B42318"),
    "清仓": ("#EBD5FF", "#66269B"),
    "无品牌": ("#FFDDEE", "#A61E69"),
    "批发专用": ("#E1E4EA", "#475467"),
}

DEFAULT_BRAND_COLOR = "#ff8b24"
DEFAULT_BRANDS = [
    {"name": "浩酷", "aliases": ["浩酷", "Hoco", "HOCO"], "color": DEFAULT_BRAND_COLOR},
    {"name": "优派", "aliases": ["优派", "ViewSonic"], "color": DEFAULT_BRAND_COLOR},
    {"name": "提耀", "aliases": ["提耀"], "color": DEFAULT_BRAND_COLOR},
    {"name": "宏碁", "aliases": ["宏碁", "宏基", "Acer"], "color": DEFAULT_BRAND_COLOR},
    {"name": "优越者", "aliases": ["优越者", "UNITEK"], "color": DEFAULT_BRAND_COLOR},
    {"name": "双鹿", "aliases": ["双鹿"], "color": DEFAULT_BRAND_COLOR},
    {"name": "优加", "aliases": ["优加"], "color": DEFAULT_BRAND_COLOR},
    {"name": "古尚古", "aliases": ["古尚古"], "color": DEFAULT_BRAND_COLOR},
    {"name": "联想（胶带）", "aliases": ["联想（胶带）", "联想(胶带)", "联想", "Lenovo"], "color": DEFAULT_BRAND_COLOR},
    {"name": "神舟", "aliases": ["神舟", "Hasee"], "color": DEFAULT_BRAND_COLOR},
    {"name": "原品牌", "aliases": ["原品牌"], "color": DEFAULT_BRAND_COLOR},
]


@dataclass(frozen=True)
class Picture:
    data: bytes
    filename: str

    @property
    def key(self) -> str:
        return sha256(self.data).hexdigest()


@dataclass
class Product:
    code: str
    style_code: str
    name: str
    brand: str
    color: str = ""
    specification: str = ""
    source_spec: str = ""
    remark: str = ""
    created_at: datetime | None = None
    actual_stock: float | None = None
    available_stock: float | None = None
    occupied_stock: float | None = None
    transit_stock: float | None = None
    sales_30d: float | None = None
    source_status: str = ""
    link_count: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    source_mapping: dict[str, str] = field(default_factory=dict)
    pictures: list[Picture] = field(default_factory=list)
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    overrides: dict[str, str] = field(default_factory=dict)
    imported_style_state: dict[str, str] = field(default_factory=dict)

    @property
    def problems(self) -> list[str]:
        result = []
        if self.code.startswith("缺少商品编码："):
            result.append("缺少商品编码（保留原行，请修正源文件后重新导入）")
        if not self.style_code:
            result.append("缺少款式编码（单独保留，不与其它缺码商品合并）")
        if not self.source_spec:
            result.append("缺少颜色及规格")
        if not self.name or self.name == "待确认":
            result.append("商品名称待确认")
        if self.brand == "待确认":
            result.append("品牌待确认，请在商品明细中修正或补充品牌规则")
        if self.actual_stock is None:
            result.append("实际库存未知")
        if self.available_stock is None:
            result.append("可用库存未知")
        if self.actual_stock is not None and self.actual_stock < 0:
            result.append("实际库存为负，请核对")
        if self.available_stock is not None and self.available_stock < 0:
            result.append("可用库存为负，请核对")
        if self.created_at is None:
            result.append("创建时间缺失或无法识别")
        return result


@dataclass
class Style:
    code: str
    products: list[Product]
    remark: str = ""
    name_override: str = ""

    @property
    def name(self) -> str:
        return self.name_override or " / ".join(dict.fromkeys(p.name for p in self.products))

    @property
    def brands(self) -> set[str]:
        return {p.brand for p in self.products}

    @property
    def created_at(self) -> datetime | None:
        values = [p.created_at for p in self.products if p.created_at is not None]
        return min(values) if values else None

    @property
    def pictures(self) -> list[Picture]:
        result: dict[str, Picture] = {}
        for product in self.products:
            for picture in product.pictures:
                result.setdefault(picture.key, picture)
        return list(result.values())

    def stock(self, attribute: str) -> float | None:
        values = [getattr(p, attribute) for p in self.products]
        return sum(values) if values and all(v is not None for v in values) else None

    @property
    def problems(self) -> list[str]:
        result = [f"{p.code}：{message}" for p in self.products for message in p.problems]
        if not self.name_override and len({p.name for p in self.products}) > 1:
            result.insert(0, "同款式商品名称不一致，可在主表统一名称或明细中逐条修正")
        return result


@dataclass
class Dataset:
    products: list[Product] = field(default_factory=list)
    styles: list[Style] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    imported_at: datetime = field(default_factory=datetime.now)

    def rebuild(self, style_states: dict[str, dict[str, str]] | None = None) -> None:
        previous = {s.code: {"remark": s.remark, "name": s.name_override} for s in self.styles}
        if style_states:
            previous.update(style_states)
        groups: dict[str, list[Product]] = {}
        for product in self.products:
            key = product.style_code or f"缺少款式编码：{product.code}"
            groups.setdefault(key, []).append(product)
        self.styles = [Style(code, products, previous.get(code, {}).get("remark", ""),
                             previous.get(code, {}).get("name", "")) for code, products in groups.items()]

    @property
    def problem_count(self) -> int:
        return len(self.issues) + sum(bool(s.problems) for s in self.styles)


def quantity(value: float | None) -> str:
    if value is None:
        return "未知"
    return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"


def detail_text(style: Style, current_brand: str = "") -> str:
    lines = [f"款式：{style.code}  商品：{style.name}",
             f"款式备注：{style.remark or '未备注'}  商品数：{len(style.products)}",
             "品牌勾选表示商品存在。"]
    for product in sorted(style.products, key=lambda p: (p.brand != current_brand, p.brand, p.code)):
        lines.append(f"【{product.brand}】{product.code}\n"
                     f"颜色/规格：{product.color or '—'} / {product.specification or '—'}\n"
                     f"商品备注：{product.remark or '未备注'}")
    return "\n\n".join(lines)


def detail_html(style: Style, current_brand: str = "") -> str:
    rows = []
    for product in sorted(style.products, key=lambda p: (p.brand != current_brand, p.brand, p.code)):
        bg = "#FFF1E4" if product.brand == current_brand else "#FFFFFF"
        rows.append(f'<tr bgcolor="{bg}"><td>{escape(product.brand)}</td>'
                    f'<td><b>{escape(product.code)}</b><br>{escape(product.color)} '
                    f'{escape(product.specification)}</td>'
                    f'<td>{escape(product.remark or "未备注")}</td></tr>')
    return ('<html><body style="font-family:Microsoft YaHei;font-size:10pt;color:#263044">'
            f'<p><b>{escape(style.code)}</b>　{escape(style.name)}<br>'
            f'款式备注：{escape(style.remark or "未备注")}　全部 {len(style.products)} 个商品编码</p>'
            '<table width="100%" cellpadding="7" cellspacing="0" border="0">'
            '<tr bgcolor="#EEF1F5"><th>品牌</th><th>商品编码 / 规格</th><th>商品备注</th></tr>'
            + "".join(rows) + '</table></body></html>')
