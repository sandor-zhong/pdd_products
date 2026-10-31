from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image

from product_manager.domain import Dataset, Picture, Product, detail_html, detail_text
from product_manager.exporter import brand_columns, export_workbook
from product_manager.parser import Layout, SpecParser, date_value, import_files, inspect_layouts, number
from product_manager.storage import Store

SAMPLE = Path(os.environ.get("PRODUCT_SAMPLE_XLSX", "D:/UserData/My Documents/WXWork/1688855311824769/Cache/File/2026-10/商品资料_20261012095158_199813145_1.xlsx"))
HEADERS = ["商品编码", "款式编码", "颜色及规格", "实际库存数", "可用数", "订单占有数", "采购在途数", "30天销量", "商品状态", "店铺链接数", "创建时间", "备注", "图片"]


def create_source(path, rows=None, header_row=1, headers=None, image=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "商品"
    if header_row > 1:
        sheet.cell(1, 1, "这是标题")
    for col, header in enumerate(headers or HEADERS, 1):
        sheet.cell(header_row, col, header)
    rows = rows if rows is not None else [
        ["0001", "S1", "240WC对C硅胶扁线 蓝色 1.5米 浩酷", 10, 9, 1, 2, 30, "启用", 3, "2026/3/7 9:43:07", "", None],
        ["0002", "S1", "240WC对C硅胶扁线 紫色 2米", None, 0, None, 0, 0, "启用", 1, "2026/4/2 9:00:00", "", None],
        ["0003", "S2", "编织线 白色 1米 宏碁", 5, 5, 0, 0, 2, "停用", 0, "2026/9/2 9:00:00", "外采", None],
    ]
    for row in rows:
        sheet.append(row)
    if image:
        blob = BytesIO()
        PILImage.new("RGB", (120, 90), "#3B82F6").save(blob, format="PNG")
        blob.seek(0)
        sheet.add_image(Image(blob), f"M{header_row + 1}")
    workbook.save(path)
    workbook.close()


class ParsingTests(unittest.TestCase):
    def test_spec_brand_name_and_original(self):
        parser = SpecParser()
        result = parser.parse("240WC对C硅胶扁线 蓝色 1.5米 浩酷")
        self.assertEqual((result.name, result.brand, result.color, result.specification),
                         ("240WC对C硅胶扁线", "浩酷", "蓝色", "1.5米"))
        self.assertEqual(parser.parse("240WC对C硅胶扁线 蓝色 1.5米").brand, "原品牌")

    def test_alias_whitespace_and_brackets(self):
        parser = SpecParser()
        self.assertEqual(parser.parse("编织线　蓝色   2m hOcO").brand, "浩酷")
        self.assertEqual(parser.parse("编织线 蓝色 2米（UNITEK）").brand, "优越者")

    def test_unknown_suffix_is_reviewed(self):
        result = SpecParser().parse("编织线 白色 1米 新牌子")
        self.assertEqual(result.brand, "待确认")
        self.assertEqual(SpecParser().parse("普通编织线").brand, "原品牌")
        self.assertEqual(SpecParser().parse("").name, "待确认")

    def test_custom_rules(self):
        parser = SpecParser([{"name": "新牌子", "aliases": ["新牌子", "NEW"], "color": "#FF0000"}])
        self.assertEqual(parser.parse("编织线 白色 1米 NEW").brand, "新牌子")

    def test_typed_missing_values(self):
        self.assertIsNone(number(None))
        self.assertIsNone(number("nan"))
        self.assertEqual(number("0"), 0)
        self.assertEqual(number("1,200"), 1200)
        self.assertEqual(date_value("2026年3月7日"), datetime(2026, 3, 7))
        self.assertIsNone(date_value("无"))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "商品.xlsx"
        create_source(self.source, image=True)
        self.dataset = import_files([self.source])

    def tearDown(self):
        self.directory.cleanup()

    def test_grouping_missing_stock_and_images(self):
        self.assertEqual(len(self.dataset.styles), 2)
        style = self.dataset.styles[0]
        self.assertEqual(style.name, "240WC对C硅胶扁线")
        self.assertEqual(style.stock("available_stock"), 9)
        self.assertIsNone(style.stock("actual_stock"))
        self.assertEqual(len(style.pictures), 1)
        self.assertEqual(style.created_at, datetime(2026, 3, 7, 9, 43, 7))
        self.assertTrue(all(not hasattr(p, "listing") for p in self.dataset.products))
        self.assertEqual(self.dataset.products[0].code, "0001")

    def test_duplicate_rows_do_not_double_stock(self):
        duplicate = self.root / "同一数据.xlsx"
        duplicate.write_bytes(self.source.read_bytes())
        result = import_files([self.source, duplicate])
        self.assertEqual(len(result.products), 3)
        self.assertEqual(len(result.issues), 3)

    def test_conflicting_duplicate_is_rejected(self):
        conflict = self.root / "冲突.xlsx"
        create_source(conflict)
        workbook = load_workbook(conflict)
        workbook.active["E2"] = 100
        workbook.save(conflict)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "出现不同数据"):
            import_files([self.source, conflict])

    def test_header_detection_and_field_mapping(self):
        path = self.root / "自定义.xlsx"
        custom = ["货号", "大款号", "完整名称"] + HEADERS[3:]
        create_source(path, header_row=4, headers=custom)
        layouts = inspect_layouts(path)
        self.assertEqual(layouts[0].header_row, 4)
        # Automatic detection cannot know arbitrary header aliases; explicit mapping supplies them.
        chosen = Layout("商品", 4, custom, {"商品编码": "货号", "款式编码": "大款号", "颜色及规格": "完整名称", "可用数": "可用数"})
        result = import_files([path], layouts={str(path.resolve()): chosen})
        self.assertEqual(len(result.products), 3)
        self.assertEqual(result.products[0].available_stock, 9)
        self.assertTrue(layouts)

    def test_numeric_identifier_zero_format(self):
        workbook = load_workbook(self.source)
        workbook.active["A2"] = 1
        workbook.active["A2"].number_format = "0000"
        workbook.save(self.source)
        workbook.close()
        dataset = import_files([self.source])
        self.assertEqual(dataset.products[0].code, "0001")
        exported = export_workbook(dataset, self.root / "编码导出.xlsx")
        self.assertEqual(import_files([exported]).products[0].code, "0001")

    def test_missing_style_codes_kept_separate(self):
        workbook = load_workbook(self.source)
        workbook.active["B2"] = None
        workbook.active["B3"] = None
        workbook.save(self.source)
        workbook.close()
        result = import_files([self.source])
        self.assertEqual(len(result.styles), 3)
        self.assertTrue(result.products[0].problems)

    def test_stock_refresh_preserves_only_manual_edits(self):
        with_store = Store(self.root / "state.sqlite3")
        with_store.edit_product("0001", "remark", "清仓")
        with_store.edit_style("S1", "remark", "批发专用")
        with_store.connection.execute("UPDATE product_state SET value=? WHERE code=?",
                                      ('{"remark":"清仓","listing":"已上架"}', "0001"))
        with_store.connection.commit()
        with_store.apply(self.dataset)
        self.assertEqual(self.dataset.products[0].remark, "清仓")
        self.assertFalse(hasattr(self.dataset.products[0], "listing"))
        self.assertNotIn("listing", self.dataset.products[0].overrides)
        workbook = load_workbook(self.source)
        workbook.active["E2"] = 500
        workbook.save(self.source)
        workbook.close()
        fresh = import_files([self.source])
        with_store.apply(fresh)
        self.assertEqual(fresh.products[0].available_stock, 500)
        self.assertEqual(fresh.products[0].remark, "清仓")
        self.assertEqual(fresh.styles[0].remark, "批发专用")
        with_store.close()

    def test_export_native_features_and_literal_text(self):
        destination = self.root / "结果.xlsx"
        self.dataset.styles[0].remark = "清仓"
        self.dataset.products[0].remark = '=HYPERLINK("https://example.org","备注")'
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        export_workbook(self.dataset, destination)
        workbook = load_workbook(destination)
        summary, detail = workbook["款式汇总"], workbook["商品明细"]
        self.assertEqual(summary["A2"].value, "清仓")
        self.assertEqual(summary.freeze_panes, "F2")
        self.assertEqual(summary.auto_filter.ref.split(":")[0], "A1")
        self.assertEqual(len(summary.data_validations.dataValidation), 1)
        self.assertFalse(summary.data_validations.dataValidation[0].showDropDown)
        self.assertEqual(len(summary.conditional_formatting), 1)
        self.assertEqual(len(summary._images), 1)
        self.assertEqual(len(detail._images), 1)
        self.assertEqual([cell.value for cell in detail[1]], HEADERS)
        self.assertEqual(detail["L2"].data_type, "s")
        self.assertTrue(detail["L2"].value.startswith("="))
        self.assertEqual(detail._images[0].anchor._from.col, HEADERS.index("图片"))
        self.assertNotIn("可用库存", [cell.value for cell in summary[1]])
        self.assertNotIn("待核对商品数", [cell.value for cell in summary[1]])
        self.assertTrue(any("0001" in cell.comment.text and "0002" in cell.comment.text
                            for row in summary for cell in row if cell.value == "√" and cell.comment))
        self.assertEqual(detail["A2"].value, "0001")
        workbook.close()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_export_reimport_only_writes_existing_source_columns(self):
        self.dataset.products[0].brand = "自定义牌"
        self.dataset.products[0].remark = "清仓"
        self.dataset.styles[0].name_override = "统一商品名"
        self.dataset.styles[0].remark = "批发专用"
        destination = export_workbook(self.dataset, self.root / "结果.xlsx")
        result = import_files([destination])
        workbook = load_workbook(destination)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], HEADERS)
        self.assertEqual(workbook["款式汇总"]["C2"].value, "统一商品名")
        self.assertEqual(workbook["款式汇总"]["A2"].value, "批发专用")
        workbook.close()
        self.assertEqual(result.products[0].brand, "浩酷")
        self.assertEqual(result.products[0].remark, "清仓")
        self.assertFalse(hasattr(result.products[0], "listing"))
        self.assertEqual(result.products[0].occupied_stock, 1)
        self.assertEqual(result.products[0].source_status, "启用")
        self.assertEqual(result.styles[0].name, "240WC对C硅胶扁线")
        self.assertEqual(set(result.products[0].raw), set(self.dataset.products[0].raw))

    def test_export_preserves_custom_fields_and_does_not_add_optional_fields(self):
        source = self.root / "精简源表.xlsx"
        headers = ["SKU", "款号", "颜色规格", "供应商备注", "自定义价格"]
        rows = [["0009", "S9", "编织线 蓝色 1米 浩酷", "原始备注", 12.5]]
        create_source(source, headers=headers, rows=rows)
        dataset = import_files([source])
        dataset.products[0].remark = "清仓"
        dataset.products[0].brand = "新品牌"
        first = export_workbook(dataset, self.root / "精简导出.xlsx")
        workbook = load_workbook(first)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], headers)
        self.assertEqual([cell.value for cell in workbook["商品明细"][2]], rows[0])
        self.assertEqual(len(workbook["商品明细"].data_validations.dataValidation), 0)
        workbook.close()
        second = export_workbook(import_files([first]), self.root / "再次导出.xlsx")
        workbook = load_workbook(second)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], headers)
        workbook.close()

    def test_export_merges_only_fields_present_in_selected_sources(self):
        source = self.root / "另一源表.xlsx"
        headers = ["商品编码", "款式编码", "颜色及规格", "供应商"]
        create_source(source, headers=headers, rows=[["0004", "S3", "编织线 红色 1米 宏碁", "供应商A"]])
        dataset = import_files([self.source, source])
        full = export_workbook(dataset, self.root / "合并.xlsx")
        filtered = export_workbook(dataset, self.root / "只导另一表.xlsx", styles=[dataset.styles[-1]])
        workbook = load_workbook(full)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], HEADERS + ["供应商"])
        workbook.close()
        workbook = load_workbook(filtered)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], headers)
        workbook.close()

    def test_export_edits_existing_optional_fields_without_adding_columns(self):
        source = self.root / "已有字段.xlsx"
        headers = ["商品编码", "款式编码", "颜色及规格", "品牌", "商品名称", "上架状态", "商品备注"]
        create_source(source, headers=headers, rows=[["0004", "S3", "编织线 红色 1米 宏碁", "源品牌", "源名称", "在售", "  原备注  "]])
        dataset = import_files([source])
        original = export_workbook(dataset, self.root / "原值.xlsx")
        workbook = load_workbook(original)
        self.assertEqual([cell.value for cell in workbook["商品明细"][2]][3:], ["源品牌", "源名称", "在售", "  原备注  "])
        workbook.close()
        product = dataset.products[0]
        product.brand, product.name, product.remark = "新品牌", "新名称", "清仓"
        product.overrides.update(brand=product.brand, name=product.name, remark=product.remark)
        changed = export_workbook(dataset, self.root / "修改.xlsx")
        workbook = load_workbook(changed)
        self.assertEqual([cell.value for cell in workbook["商品明细"][1]], headers)
        self.assertEqual([cell.value for cell in workbook["商品明细"][2]][3:], ["新品牌", "新名称", "在售", "清仓"])
        self.assertEqual(len(workbook["商品明细"].data_validations.dataValidation), 1)
        workbook.close()

    def test_filtered_export_does_not_drop_other_brands(self):
        path = export_workbook(self.dataset, self.root / "筛选.xlsx", styles=[self.dataset.styles[0]])
        result = import_files([path])
        self.assertEqual(len(result.products), 2)
        self.assertEqual(result.styles[0].brands, {"浩酷", "原品牌"})

    def test_prevent_source_overwrite_and_empty_export(self):
        with self.assertRaisesRegex(ValueError, "源文件"):
            export_workbook(self.dataset, self.source)
        with self.assertRaisesRegex(ValueError, "没有可导出"):
            export_workbook(self.dataset, self.root / "空.xlsx", styles=[])

    def test_hover_has_all_skus_and_escapes_user_text(self):
        style = self.dataset.styles[0]
        self.dataset.products[0].remark = "<script>备注</script>"
        html = detail_html(style, "浩酷")
        self.assertIn("0001", html)
        self.assertIn("0002", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("0002", detail_text(style, "浩酷"))
        self.assertNotIn("上架记录", detail_text(style, "浩酷"))


@unittest.skipUnless(SAMPLE.is_file(), "用户提供的样表不在本机")
class UserSampleTests(unittest.TestCase):
    def test_actual_sample(self):
        digest = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
        dataset = import_files([SAMPLE])
        workbook = load_workbook(SAMPLE, read_only=True, data_only=True)
        layout = inspect_layouts(SAMPLE)[0]
        code_column = layout.headers.index(layout.mapping["商品编码"])
        expected_codes = {str(row[code_column]).strip() for row in workbook[layout.sheet].iter_rows(min_row=layout.header_row + 1, values_only=True)
                          if row[code_column] is not None}
        workbook.close()
        self.assertEqual({product.code for product in dataset.products}, expected_codes)
        style = next(style for style in dataset.styles if style.code == "240WCDCGJBX")
        self.assertEqual(len(style.products), 42)
        self.assertEqual(style.code, "240WCDCGJBX")
        self.assertEqual(style.name, "240WC对C硅胶扁线")
        self.assertEqual(len(style.brands), 7)
        for brand in style.brands:
            self.assertEqual(sum(p.brand == brand for p in style.products), 6)
        self.assertEqual(style.stock("available_stock"), 6836)
        self.assertIsNone(style.stock("actual_stock"))
        self.assertEqual(len(style.pictures), 2)
        self.assertEqual(sum(len(p.pictures) for p in style.products), 42)
        self.assertEqual(style.created_at, datetime(2026, 3, 7, 9, 43, 7))
        with tempfile.TemporaryDirectory() as directory:
            destination = export_workbook(dataset, Path(directory) / "样表导出.xlsx")
            workbook = load_workbook(destination)
            self.assertEqual([cell.value for cell in workbook["商品明细"][1]], layout.headers)
            self.assertEqual(workbook["商品明细"].max_row - 1, len(expected_codes))
            self.assertEqual(len(workbook["商品明细"]._images), sum(bool(p.pictures) for p in dataset.products))
            workbook.close()
        self.assertEqual(hashlib.sha256(SAMPLE.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
