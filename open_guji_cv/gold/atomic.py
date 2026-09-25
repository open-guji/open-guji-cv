# -*- coding: utf-8 -*-
"""金标 expected 合并时**必须整组替换**的键组。

`gold_add`（事件 → 裁决表）与 `import_to_dataset` / `export_to_workspace`（裁决表 ↔ 测试集）都按
「旧 expected 打底、新值覆盖同名键」合并（2026-09-04 教训：v1 字段不能被抹掉）。但有些键是
**一次判定的整体**：切线金标的 y / col_h / 折线 / 候选 / 干扰标签同属一个坐标系、一次裁决，
重裁时若新判定不带折线，旧坐标系的折线就会原样留下——评测优先读折线，等于金标没修
（2026-09-14 两次实锤：gold_add 留下 24 条；import 又把 dataset 里的旧折线留了回来）。
"""
from __future__ import annotations

# 切线事件写进 touching-cuts 的全部键
CUTLINE_KEYS: tuple[str, ...] = ("y", "y_old", "verdict", "bi", "slot_above", "slot_below", "col_h",
                                 "char_above", "char_below", "shape_above", "shape_below",
                                 "tags", "note", "polyline", "cand",
                                 # 页面坐标与列窗几何签名（2026-09-25，eval/colgeom.py）：与 y/polyline
                                 # 同属一次判定，必须整组替换，否则新 y 配旧 page_y 会被评测当真
                                 "geom_sig", "page_x", "page_y", "page_polyline")

ATOMIC_KEY_GROUPS: dict[str, tuple[str, ...]] = {
    "char-segmentation/touching-cuts": CUTLINE_KEYS,
}


def merge_expected(shard: str, old: dict, new: dict, atomic: bool = True) -> dict:
    """旧值打底、新值覆盖；`atomic` 时该分片的整组键先从旧值里整组剔除（新值给几个就是几个）。"""
    base = dict(old or {})
    group = ATOMIC_KEY_GROUPS.get(shard) if atomic else None
    if group and any(k in (new or {}) for k in group):
        base = {k: v for k, v in base.items() if k not in group}
    return {**base, **(new or {})}
