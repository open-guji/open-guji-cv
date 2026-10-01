# -*- coding: utf-8 -*-
"""人裁「小注当正文」→ Step3 强制按雙行小注从中间拆（2026-09-30）。

提要末尾 2~3 行的短版本小注，判据（`jiazhu_split.gap_center`）常落空：缝只有 2px、缝偏出窗口、
搭档量不出缝凑不成段。人指认的格不看判据直接拆。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.utils import jiazhu_split as jz
from open_guji_cv.utils import row_boundaries as fit_mod

COL_W, SLOT_H, N_SLOTS, GRID_Y0, RULE_W = 185, 110, 21, 10, 4


def _column(thin_seam_slots=(), seam_x=98, seam_w=2, tail_slots=()):
    """正文列；`thin_seam_slots` 里的格画成两个小字、中缝只有 `seam_w`px（< GAP_MIN，判据认不出）。"""
    h = GRID_Y0 + N_SLOTS * SLOT_H + 20
    img = np.full((h, COL_W), 255, dtype=np.uint8)
    img[:, :RULE_W] = 0
    img[:, -RULE_W:] = 0
    img[0:4, :] = 0
    img[h - 4:, :] = 0
    for k in range(N_SLOTS):
        y0 = GRID_Y0 + k * SLOT_H + 10
        y1 = y0 + 90
        if (k + 1) in tail_slots:                      # 奇数字末行：只有右半一个小字
            img[y0:y1, 110:COL_W - 15] = 0
        elif (k + 1) in thin_seam_slots:
            img[y0:y1, 15:seam_x] = 0
            img[y0:y1, seam_x + seam_w:COL_W - 15] = 0
        else:
            img[y0:y1, 37:148] = 0
    return img


def _cells(r):
    out = {}
    for c in r.cells:
        out.setdefault(c.slot, {})[c.sub or ""] = c
    return out


def test_gap_center_misses_a_two_pixel_seam():
    patch = _column(thin_seam_slots=(8,))[GRID_Y0 + 7 * SLOT_H:GRID_Y0 + 8 * SLOT_H, 4:-4]
    assert jz.gap_center(patch, COL_W) is None          # 前提：判据真的认不出


def test_forced_split_center_picks_the_valley_near_the_middle():
    patch = _column(thin_seam_slots=(8,))[GRID_Y0 + 7 * SLOT_H:GRID_Y0 + 8 * SLOT_H, 4:-4]
    cx = jz.forced_split_center(patch)
    assert cx is not None and abs(cx - (98 + 1 - 4)) <= 1.5     # 缝在整图 x=98..100 → patch 局部 95
    assert jz.forced_split_center(np.full((50, 50), 255, np.uint8)) is None    # 没墨量不出


def test_forced_jiazhu_splits_the_cell_otherwise_it_stays_a_char():
    img = _column(thin_seam_slots=(8,))
    base = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W)
    assert base is not None and set(_cells(base)[8]) == {""} and _cells(base)[8][""].kind == "char"

    r = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W,
                               forced_jiazhu={8})
    assert r is not None
    halves = _cells(r)[8]
    assert sorted(halves) == ["a", "b"]
    a, b = halves["a"], halves["b"]
    assert a.kind == "jiazhu_a" and b.kind == "jiazhu_b"
    assert a.x0 > b.x0 and a.x0 == b.x1                  # a = 右子列、b = 左子列，中缝相接
    assert abs(a.gap_center - (98 + 1)) <= 1.5
    # 别的格一字不动
    for slot, cs in _cells(base).items():
        if slot != 8:
            assert {k: (c.kind, c.y0, c.y1) for k, c in cs.items()} == \
                {k: (c.kind, c.y0, c.y1) for k, c in _cells(r)[slot].items()}


def test_forced_cell_lets_the_following_right_half_char_be_adopted_as_tail():
    img = _column(thin_seam_slots=(8,), tail_slots=(9,))
    base = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W)
    assert _cells(base)[9][""].kind == "jiazhu_solo"            # 没人指认：自成單行小注
    r = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W,
                               forced_jiazhu={8})
    assert {sub: c.kind for sub, c in _cells(r)[9].items()} == {"a": "jiazhu_a"}   # 段尾收编，只发 a 半


def test_forced_on_blank_or_unforced_columns_changes_nothing():
    img = _column()
    base = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W)
    same = fit_mod.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W,
                                  forced_jiazhu=set())
    assert [(c.slot, c.sub, c.kind) for c in base.cells] == [(c.slot, c.sub, c.kind) for c in same.cells]


# ── 数据源：事件日志里最新一条定字裁决是 seg_defect+reason=jiazhu_as_main ──

def _ev(batch, seq, key, payload, ts):
    from open_guji_cv.feedback.events import EventTarget, make_event
    _, pg, col, slot = key.split(":")
    e = make_event(batch, seq, "confirm",
                   EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                               page=int(pg), col=int(col), slot=0), payload, source_format="server")
    e.ts = ts
    return e


def test_resolved_forced_jiazhu_latest_wins(tmp_path):
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import resolved_forced_jiazhu
    jzp = {"v": "seg_defect", "quality": "truncated", "reason": "jiazhu_as_main"}
    log = EventLog(tmp_path)
    log.append([
        _ev("b", 1, "vol01:12:7:9", jzp, "2026-10-01T00:00:01Z"),
        _ev("b", 2, "vol01:20:7:3", jzp, "2026-10-01T00:00:02Z"),
        _ev("b", 3, "vol01:20:7:3", {"v": "confirm", "shape": "引"}, "2026-10-01T00:00:03Z"),   # 后来改判了
        _ev("b", 4, "vol01:97:9:19", {"v": "seg_defect", "quality": "truncated"}, "2026-10-01T00:00:04Z"),  # 普通截断
        _ev("b", 5, "vol01:97:9:20", jzp, "2026-10-01T00:00:05Z"),
        _ev("b", 6, "vol01:97:9:21", jzp, "2026-10-01T00:00:06Z"),
    ])
    got = resolved_forced_jiazhu("vol01", log)
    assert got == {(12, 7): {9}, (97, 9): {20, 21}}
    assert resolved_forced_jiazhu("vol02", log) == {}


def test_route_invalidates_row_segment_for_jiazhu_marks():
    from open_guji_cv.feedback.routes import RouteTable
    table = RouteTable.load(None)
    jzp = {"v": "seg_defect", "quality": "truncated", "reason": "jiazhu_as_main"}
    steps = lambda p: sorted((d.extra or {}).get("step") or d.consumer
                             for d in table.destinations(_ev("b", 1, "vol01:12:7:9", p, "2026-10-01T00:00:01Z")))
    assert "row_segment" in steps(jzp)
    assert "row_segment" not in steps({"v": "seg_defect", "quality": "truncated"})
