from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

from .domain import DEFAULT_BRAND_COLOR, DEFAULT_BRANDS, Dataset


class Store:
    """Only explicit manual edits are persisted; refreshed source data stays fresh."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS product_state (code TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS style_state (code TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.commit()
        self._upgrade_brand_color_defaults()

    def _upgrade_brand_color_defaults(self) -> None:
        if self.setting("brand_color_defaults_version", 0) >= 1:
            return
        rules = self.setting("brands")
        if rules is not None:
            changed = False
            for rule in rules:
                if rule["name"] in ("优越者", "优加", "联想（胶带）", "原品牌") and rule.get("color", "").lower() == "#aca181":
                    rule["color"] = DEFAULT_BRAND_COLOR
                    changed = True
            if changed:
                self.set_setting("brands", rules)
        self.set_setting("brand_color_defaults_version", 1)

    def setting(self, key: str, default=None):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else copy.deepcopy(default)

    def set_setting(self, key: str, value) -> None:
        self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)",
                                (key, json.dumps(value, ensure_ascii=False)))
        self.connection.commit()

    @property
    def brands(self) -> list[dict]:
        return self.setting("brands", DEFAULT_BRANDS)

    def _states(self, table: str) -> dict[str, dict[str, str]]:
        if table not in ("product_state", "style_state"):
            raise ValueError("Invalid state table")
        return {code: json.loads(value) for code, value in self.connection.execute(f"SELECT code, value FROM {table}")}

    def _update(self, table: str, code: str, field: str, value: str) -> None:
        if table not in ("product_state", "style_state"):
            raise ValueError("Invalid state table")
        row = self.connection.execute(f"SELECT value FROM {table} WHERE code=?", (code,)).fetchone()
        state = json.loads(row[0]) if row else {}
        state[field] = value
        self.connection.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?)",
                                (code, json.dumps(state, ensure_ascii=False)))
        self.connection.commit()

    def edit_product(self, code: str, field: str, value: str) -> None:
        if field not in ("name", "brand", "color", "specification", "remark"):
            raise ValueError("Unsupported product override")
        self._update("product_state", code, field, value)

    def edit_style(self, code: str, field: str, value: str) -> None:
        if field not in ("name", "remark"):
            raise ValueError("Unsupported style override")
        self._update("style_state", code, field, value)

    def apply(self, dataset: Dataset) -> None:
        products = self._states("product_state")
        for product in dataset.products:
            supported = ("name", "brand", "color", "specification", "remark")
            imported = {key: value for key, value in product.overrides.items() if key in supported}
            product.overrides = {key: value for key, value in products.get(product.code, {}).items() if key in supported}
            product.overrides.update(imported)
            for key, value in product.overrides.items():
                if key in supported:
                    setattr(product, key, value)
            if imported:
                self.connection.execute("INSERT OR REPLACE INTO product_state VALUES (?, ?)",
                                        (product.code, json.dumps(product.overrides, ensure_ascii=False)))
        style_states = self._states("style_state")
        for style in dataset.styles:
            if any(p.imported_style_state for p in style.products):
                state = {"remark": style.remark, "name": style.name_override}
                style_states[style.code] = state
                self.connection.execute("INSERT OR REPLACE INTO style_state VALUES (?, ?)",
                                        (style.code, json.dumps(state, ensure_ascii=False)))
        self.connection.commit()
        dataset.rebuild(style_states)

    def reset_overrides(self, product_codes: list[str], style_codes: list[str]) -> None:
        self.connection.executemany("DELETE FROM product_state WHERE code=?", [(c,) for c in product_codes])
        self.connection.executemany("DELETE FROM style_state WHERE code=?", [(c,) for c in style_codes])
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
