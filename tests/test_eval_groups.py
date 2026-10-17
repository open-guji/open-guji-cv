# -*- coding: utf-8 -*-
"""字组统一评测（`open_guji_cv/eval/groups.py`，S1）。全部自造 `items.jsonl`，不读 dataset。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.eval import groups as eg
from open_guji_cv.groups import GROUPS, GroupVerdict, PatchUnavailable


def item(i, *, group="jys", gold="已", tier="A_human", book="vol02", split="dev", core=True, ref="已",
         admit=True, char="已", left="而", right="地", **kw):
    d = {"id": f"{book}:1:1:{i}", "book": book, "group": group, "core": core, "split": split, "gold": gold,
         "gold_tier": tier, "ref": ref, "admit": admit, "char": char, "left": left, "right": right, "crop": None}
    d.update(kw)
    return d


def write_items(root, group, items):
    d = root / group
    d.mkdir(parents=True)
    (d / "items.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n", encoding="utf-8")
    return d


# ------------------------------------------------------------------ Wilson
def test_wilson_known_values():
    assert eg.wilson(0, 0) == (0.0, 1.0)
    lo, hi = eg.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)       # 「0/10 错」的 95% 上界约 28%
    lo, hi = eg.wilson(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-3) and hi == 1.0
    lo, hi = eg.wilson(50, 100)
    assert lo < 0.5 < hi


# ------------------------------------------------------------------ 载入与筛选
def test_load_items_filters_core_and_splits(tmp_path):
    d = write_items(tmp_path, "jys", [item(1), item(2, core=False), item(3, split="val"), item(4, split="pool")])
    assert len(eg.load_items(d)) == 3                               # 外围格默认不取
    assert len(eg.load_items(d, core_only=False)) == 4
    assert [x["split"] for x in eg.load_items(d, splits={"val"})] == ["val"]
    assert len(eg.load_items(d / "items.jsonl")) == 3               # 也可直接传文件


def test_eligible_counts_what_it_drops():
    spec = GROUPS["jys"]
    items = [item(1), item(2, tier="C_weak"), item(3, tier=None), item(4, gold=""), item(5, gold="天"), item(6, tier="B_vision")]
    keep, skipped = eg.eligible(items, spec)
    assert [x["id"][-1] for x in keep] == ["1", "6"]
    assert skipped == {"weak_or_no_tier": 2, "no_gold": 1, "gold_outside_group": 1}


# ------------------------------------------------------------------ 汇总数字
class Fixed:
    """桩后端：按格号返回固定答案（None＝弃权），可抛缺图。"""
    name = "fixed"
    fingerprint = ""

    def __init__(self, answers):
        self.answers = answers

    def judge(self, spec, cell):
        a = self.answers[cell.id]
        if a == "MISSING":
            raise PatchUnavailable(cell.id)
        return GroupVerdict(a, conf=0.9 if a else None, why="agree" if a else "abstain:stub", via="stub")


def test_summarize_numbers_by_book_and_tier():
    spec = GROUPS["jys"]
    items = [item(1), item(2), item(3), item(4, tier="B_vision"), item(5, book="vol03")]
    ans = {items[0]["id"]: "已", items[1]["id"]: "己", items[2]["id"]: None, items[3]["id"]: "已", items[4]["id"]: "MISSING"}
    rows = {r.key: r for r in eg.summarize(eg.run_backend(items, spec, Fixed(ans)), by=("book", "tier"))}
    r = rows[("vol02", "A_human")]
    assert (r.n, r.gave, r.correct, r.wrong, r.abstain) == (3, 2, 1, 1, 1)
    assert r.wrong_ids == [items[1]["id"]]
    assert (rows[("vol02", "B_vision")].gave, rows[("vol02", "B_vision")].correct) == (1, 1)
    m = rows[("vol03", "A_human")]
    assert (m.gave, m.abstain, m.patch_missing) == (0, 1, 1)             # 缺图单列，不混进普通弃权的原因
    total = rows[("全部", "全部")]
    assert (total.n, total.gave, total.correct, total.abstain) == (5, 3, 2, 2)
    d = r.to_dict()
    assert d["give_rate"] == pytest.approx(2 / 3) and d["accuracy"] == pytest.approx(0.5)


def test_baseline_arms_ref_and_admit():
    spec = GROUPS["ry"]
    items = [item(1, group="ry", gold="日", ref="日", char="日", admit=True),
             item(2, group="ry", gold="曰", ref="日", char="曰", admit=True),          # ref 错、admit 对
             item(3, group="ry", gold="日", ref="·", char="日", admit=False),          # ref 无字、未放行 → 两臂都弃权
             item(4, group="ry", gold="日", ref="天", char="天", admit=True)]          # 字在组外 → 弃权
    ref = {r.id: r.pick for r in eg.arm_ref(items, spec)}
    adm = {r.id: r.pick for r in eg.arm_admit(items, spec)}
    assert [ref[x["id"]] for x in items] == ["日", "日", None, None]
    assert [adm[x["id"]] for x in items] == ["日", "曰", None, None]


# ------------------------------------------------------------------ 端到端（命令行）
def test_main_end_to_end_with_rule_backend(tmp_path, capsys):
    items = [item(1, gold="巳", ref="己", char="己", admit=True, left="甲", right=""),        # 规则 → 巳 ✓；ref/admit 都错
             item(2, gold="己", ref="己", char="己", admit=True, left="", right="丑"),        # 规则 → 己 ✓
             item(3, gold="已", ref="已", char="已", admit=True, left="天", right="地"),       # 规则无字 → 弃权
             item(4, gold="已", tier="C_weak", left="而", right="")]                        # 弱真值 → 不数
    write_items(tmp_path, "jys", items)
    out = tmp_path / "r.json"
    assert eg.main(["jys", "--dataset", str(tmp_path), "--backend", "rule", "--by", "book", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "弱真值或无档 1" in text and "### 臂 `rule`" in text
    data = json.loads(out.read_text(encoding="utf-8"))
    rule = {tuple(r["key"]): r for r in data["arms"]["rule"]}[("vol02",)]
    assert (rule["n"], rule["gave"], rule["correct"], rule["abstain"]) == (3, 2, 2, 1)
    ref = {tuple(r["key"]): r for r in data["arms"]["ref（整理本对位字）"]}[("vol02",)]
    assert (ref["gave"], ref["correct"]) == (3, 2)                    # 整理本给了 3 个字，对 2 个（item1 错）
    assert data["n"] == 3 and data["skipped"]["weak_or_no_tier"] == 1


def test_image_backend_reports_patch_missing_not_silent(tmp_path, capsys):
    write_items(tmp_path, "rr", [item(1, group="rr", gold="入", ref="入", char="入")])        # crop 为空 → 缺图
    out = tmp_path / "r.json"
    eg.main(["rr", "--dataset", str(tmp_path), "--backend", "image", "--no-baseline", "--by", "book", "--json", str(out)])
    row = {tuple(r["key"]): r for r in json.loads(out.read_text(encoding="utf-8"))["arms"]["image"]}[("vol02",)]
    assert (row["gave"], row["abstain"], row["patch_missing"]) == (0, 1, 1)
    assert "缺图 1" in capsys.readouterr().out


def test_make_backend_detects_table_format(tmp_path):
    from open_guji_cv.groups.backends import GroupClfTableBackend, RyV2TableBackend
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"schema": "group_clf/1", "group": "ry", "cells": {}}), encoding="utf-8")
    b.write_text(json.dumps({"cells": {}}), encoding="utf-8")
    assert isinstance(eg.make_backend(f"table:{a}", "ry"), GroupClfTableBackend)
    assert isinstance(eg.make_backend(f"table:{b}", "ry"), RyV2TableBackend)
    with pytest.raises(SystemExit):
        eg.make_backend("nope", "ry")
