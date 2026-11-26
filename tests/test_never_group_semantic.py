# -*- coding: utf-8 -*-
"""永不并组名单管语义层（`clustering/variants.py`，2026-09-28 overview#201）。

名单里的对从**自动表**剔掉、手工表照旧覆盖。沙/砂、僕/仆、冶/治、咸/鹹、嘗/嚐 五对是整理本
简繁转换留下的假异体（D #178），登记后 `vmap.semantic` 不再把它们归到一起。
"""
from __future__ import annotations

import json

from open_guji_cv.clustering import variants as V
from open_guji_cv.clustering.variants import VariantMap, _drop_never, never_group_pairs


def test_drop_never_direct_and_via_third_char():
    m = {"砂": "沙", "𣲓": "沙", "甲": "丙", "乙": "丙", "丁": "戊"}
    _drop_never(m, frozenset({frozenset("沙砂"), frozenset("甲乙")}))
    # 直接映射删；经第三字归一的两条都删；无关条目不动（𣲓→沙 这类真异体保留）
    assert m == {"𣲓": "沙", "丁": "戊"}


def test_never_group_file_read(tmp_path):
    p = tmp_path / "never_group.json"
    assert never_group_pairs(p) == frozenset()
    p.write_text(json.dumps({"pairs": [["沙", "砂"], ["甲", "甲"], ["一"]]}), encoding="utf-8")
    assert never_group_pairs(p) == frozenset({frozenset("沙砂")})


def test_hand_table_still_overrides(tmp_path, monkeypatch):
    auto, hand, never = tmp_path / "a.tsv", tmp_path / "h.tsv", tmp_path / "n.json"
    auto.write_text("砂\t沙\tgraph\n迴\t回\tgraph\n", encoding="utf-8")
    hand.write_text("迴\t回\n", encoding="utf-8")
    never.write_text(json.dumps({"pairs": [["沙", "砂"], ["回", "迴"]]}), encoding="utf-8")
    monkeypatch.setattr(V, "DEFAULT_AUTO_PATH", auto)
    monkeypatch.setattr(V, "DEFAULT_VARIANTS_PATH", hand)
    monkeypatch.setattr(V, "NEVER_GROUP_PATH", never)
    monkeypatch.setattr(V.never_group_pairs, "__defaults__", (never,))
    vm = VariantMap.load()
    assert vm.semantic("砂") == "砂"
    assert vm.semantic("迴") == "回"          # 人定的手工表压过名单
    # 显式给路径时只读那一份，名单不介入
    assert VariantMap.load(auto).semantic("砂") == "沙"


def test_production_config_splits_the_five_pairs():
    vm = VariantMap.load()
    for a, b in ("沙砂", "僕仆", "冶治", "咸鹹", "嘗嚐"):
        assert vm.semantic(a) != vm.semantic(b), (a, b)
    # 同一正字下的真异体不受牵连
    assert vm.semantic("𣲓") == "沙" and vm.semantic("㒒") == "僕"
