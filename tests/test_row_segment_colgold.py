"""Step3 逐列字数先验（doc/design/19 块 C）：按目标字数重切一次的决策与金标表读取。

只测纯逻辑：DP 用假函数代替（返回指定 kind 序列的「结果」），数据全部现造。
"""
import json
from types import SimpleNamespace

from open_guji_cv.steps.row_segment import RowSegmentParams, apply_count_target, load_colgold


def _res(kinds):
    return SimpleNamespace(cells=[SimpleNamespace(kind=k) for k in kinds])


def _seg_table(table):
    calls = []

    def seg(n):
        calls.append(n)
        return table.get(n)
    return seg, calls


def test_over_split_recut_accepted():
    # 切出 20 字，目标 19：格数 21→20 重切，重切出 19 字 → 采用
    r = _res(["blank"] + ["char"] * 20)
    seg, calls = _seg_table({20: _res(["blank"] + ["char"] * 19)})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert calls == [20] and n == 20 and r2 is not r
    assert flags and flags[0].startswith("colgold_prior")


def test_recut_still_wrong_keeps_original_and_flags():
    r = _res(["char"] * 20)
    seg, _ = _seg_table({20: _res(["char"] * 20)})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert r2 is r and n == 21 and flags[0].startswith("colgold_conflict")


def test_count_already_right_is_untouched():
    r = _res(["blank", "blank"] + ["char"] * 19)
    seg, calls = _seg_table({})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert r2 is r and n == 21 and flags == [] and calls == []


def test_large_diff_not_applied():
    r = _res(["char"] * 21)
    seg, calls = _seg_table({})
    _, n, flags = apply_count_target(r, seg, 21, 15, "colgold")
    assert calls == [] and n == 21 and "超过" in flags[0]


def test_jiazhu_column_untouched():
    r = _res(["char"] * 10 + ["jiazhu_a", "jiazhu_b"] * 5)
    seg, calls = _seg_table({})
    r2, n, flags = apply_count_target(r, seg, 21, 12, "colgold")
    assert r2 is r and calls == [] and flags == []


def test_under_split_adds_slot():
    r = _res(["char"] * 18)
    seg, calls = _seg_table({22: _res(["char"] * 19)})
    _, n, flags = apply_count_target(r, seg, 21, 19, "yolo")
    assert calls == [22] and n == 22 and flags[0].startswith("yolo_prior")


def test_load_colgold_filters(tmp_path):
    rows = [
        {"vol": "volX", "page": 3, "col": 1, "agree": True, "dzg": {"n": 19, "note": None}},
        {"vol": "volX", "page": 3, "col": 2, "agree": False, "dzg": {"n": 19, "note": None}},
        {"vol": "volX", "page": 3, "col": 3, "agree": True, "dzg": {"n": 25, "note": {"start": 5, "r": 3, "l": 3}}},
        {"vol": "volY", "page": 3, "col": 1, "agree": True, "dzg": {"n": 19, "note": None}},
    ]
    p = tmp_path / "colgold.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = load_colgold(str(p), "volX")
    assert set(got) == {(3, 1)}


def test_params_off_by_default_no_fingerprint():
    p = RowSegmentParams(cut_judge="rule")
    assert p.colgold_prior == "" and p.colgold_fingerprint == ""


# ── 块 D：原生 YOLO 并格闸的成对判定 ──────────────────────────────

from open_guji_cv.steps.row_segment import yolo_merge_pairs  # noqa: E402


def _yolo_normal(n=20, h=100):
    # 一列正常字框（列外另放，作中位高的底）
    return [(500, i * 110, 600, i * 110 + h) for i in range(n)]


def test_split_char_inside_one_yolo_box_counts_pair():
    ink = [(10, 10, 90, 40), (10, 60, 90, 95), (10, 120, 90, 210)]   # 前两格是被切开的「三」
    yolo = _yolo_normal() + [(5, 5, 95, 100), (5, 115, 95, 215)]
    assert yolo_merge_pairs(ink, yolo) == 1


def test_double_height_yolo_box_ignored():
    ink = [(10, 10, 90, 95), (10, 105, 90, 195)]                     # 两个真字
    yolo = _yolo_normal() + [(5, 5, 95, 200)]                        # YOLO 把两字并成一个 2 倍高框
    assert yolo_merge_pairs(ink, yolo) == 0


def test_cell_used_once():
    ink = [(10, 10, 90, 30), (10, 40, 90, 60), (10, 70, 90, 95)]
    yolo = _yolo_normal() + [(5, 5, 95, 100)]                        # 三格都在一个框里 → 只记一对
    assert yolo_merge_pairs(ink, yolo) == 1


def test_blank_cells_and_no_yolo():
    assert yolo_merge_pairs([None, (0, 0, 1, 1)], _yolo_normal()) == 0
    assert yolo_merge_pairs([(0, 0, 1, 1), (0, 2, 1, 3)], []) == 0


def test_colgold_count_ignores_low_ink_cells_outside_gold_slots():
    from open_guji_cv.steps.row_segment import colgold_count
    g = {"start": 2, "n": 3}                      # 金标：字在 3、4、5 格
    cells = [SimpleNamespace(kind="char", slot=1, ink_ratio=0.02),    # 抬头位残墨 → 不算
             SimpleNamespace(kind="char", slot=3, ink_ratio=0.03),    # 金标字位上的瘦字「一」→ 算
             SimpleNamespace(kind="char", slot=4, ink_ratio=0.2),
             SimpleNamespace(kind="char", slot=5, ink_ratio=0.2),
             SimpleNamespace(kind="char", slot=6, ink_ratio=0.15)]    # 金标外但墨足 → 算（真多切）
    assert colgold_count(g)(cells) == 4
