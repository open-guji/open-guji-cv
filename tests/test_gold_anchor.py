# -*- coding: utf-8 -*-
"""金标坐标系有效性判据 `eval.touching.gold_anchor_ok`。

背景（2026-09-16，实验十六/十七）：vol01 按新 Step1 重跑后 706 条切线金标 `col_h` 对不上，
老判据全按「漂移」跳过，评测样本从 ~900 掉到 239、漂移重标卡出 706 张。实测 `y_new − y_old`
中位 0.0——列只是底部变长了，格线一根没动。判据改成「原格线 `y_old` 与当前同一格线位移 ≤ 3px
即有效」后：评测 n 488、漂移卡 41。这里把三种情形钉死，免得回退成按 col_h 判。
"""
from types import SimpleNamespace

from open_guji_cv.eval.touching import ANCHOR_TOL, gold_anchor_ok, gold_anchor_shift


def _col(boundaries, slots):
    """造一个最小的列对象：boundaries 比 cells 多一条。"""
    cells = [SimpleNamespace(slot=s, sub=None) for s in slots]
    assert len(boundaries) == len(cells) + 1
    return SimpleNamespace(boundaries=list(boundaries), cells=cells, ok=True)


def test_col_h_changed_but_boundary_unchanged_is_ok():
    # 列底部变长 10px（col_h 2458→2468），格线坐标原样：金标仍有效
    cc = _col([0, 115, 230, 345, 2468], [1, 2, 3, 4])
    ex = {"y_old": 230, "y": 230, "slot_above": 2, "slot_below": 3, "bi": 2, "col_h": 2458}
    assert gold_anchor_shift(cc, ex) == 0.0
    assert gold_anchor_ok(cc, ex)


def test_slot_renumbered_same_geometry_is_ok_via_nearest_fallback():
    # 上方插了一格，slot 全部 +1：按 slot 对不回，但 y_old=230 处仍有格线
    cc = _col([0, 60, 115, 230, 345, 2468], [0, 1, 2, 3, 4])
    ex = {"y_old": 230, "y": 230, "slot_above": 2, "slot_below": 3, "bi": 2, "col_h": 2458}
    # slot 对 (2,3) 现在夹的是 115..230 之间那条=115？不：cells[2].slot=2, cells[3].slot=3 → boundaries[3]=230。恰好对上。
    # 换一个真对不上的：slot 全部 +5
    cc2 = _col([0, 60, 115, 230, 345, 2468], [5, 6, 7, 8, 9])
    assert gold_anchor_shift(cc2, ex) == 0.0          # 退到最近格线
    assert gold_anchor_ok(cc2, ex)


def test_true_shift_beyond_tol_is_not_ok():
    # 整列上移 20px（顶部裁切变了）：格线都挪了，金标坐标失效
    cc = _col([0, 95, 210, 325, 2448], [1, 2, 3, 4])
    ex = {"y_old": 230, "y": 230, "slot_above": 2, "slot_below": 3, "bi": 2, "col_h": 2458}
    d = gold_anchor_shift(cc, ex)
    assert d is not None and abs(d) == 20.0
    assert not gold_anchor_ok(cc, ex)
    assert abs(d) > ANCHOR_TOL


def test_missing_geometry_is_not_ok():
    assert gold_anchor_shift(None, {"y_old": 1}) is None
    assert not gold_anchor_ok(_col([0, 100], [1]), {})     # 没 y_old 也没 y
