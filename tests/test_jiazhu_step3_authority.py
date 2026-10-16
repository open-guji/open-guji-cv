# -*- coding: utf-8 -*-
"""夹注段尾：Step3 与 Step4 格位口径统一（overview#436）。

1. Step4 extractor 拿到 `jiazhu_authority=step3` 时，**拆哪几格、每格发哪几半**一律照 Step3：
   Step3 没拆的格不拆（#434：v1 段端收编在清理后图块上又把整格拆成 a/b），Step3 只发 a 半的格不发 b。
2. 反向人裁「正文当小注」（`forced_main`）：人指认的格从夹注段里摘掉、按整格出（#415 vol02 p100c4「此」），
   数据源 `lookup.resolved_forced_main`（收 `…a`/`…b` 子格 key），路由让该页 Step3 失效。

合成列图，几何按四库：列宽 180、字距 115。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import CharExtractor
from open_guji_cv.utils import row_boundaries as fit_mod

W, P = 180, 115.0
SEAM = 90


def _small_pair(img, y, seam=SEAM, left=True, right=True):
    """一行雙行小注：缝左右各一个小字（横 + 竖 + 横），缝宽 12px。"""
    for on, (x0, x1) in ((left, (8, seam - 6)), (right, (seam + 6, W - 8))):
        if not on:
            continue
        img[y + 20:y + 27, x0:x1] = 0
        img[y + 15:y + 98, (x0 + x1) // 2 - 3:(x0 + x1) // 2 + 3] = 0
        img[y + 60:y + 67, x0 + 4:x1 - 4] = 0


def _ext_column():
    """5 格：0 正文；1–3 雙行小注（缝对齐）；4 是段尾一行两个小字（v1 段端收编会拆成 a/b）。"""
    img = np.full((6 * int(P) + 40, W), 255, np.uint8)
    y = 20
    img[y + 20:y + 28, 36:144] = 0
    img[y + 10:y + 100, 86:94] = 0
    for k in (1, 2, 3, 4):
        _small_pair(img, 20 + k * int(P))
    return img


def _grid(step3: dict[int, list[str]], authority: bool):
    cells = []
    for k in range(6):
        c = {"type": "char" if k < 5 else "empty", "index": k, "y_top": 20 + k * P,
             "y_bottom": 20 + (k + 1) * P, "is_punct": False, "seam_top": None, "seam_bottom": None}
        if k in step3:
            c.update(jiazhu_cx=float(SEAM), jiazhu_tail_a="b" not in step3[k], jiazhu_subs=step3[k])
        cells.append(c)
    g = {"shear": 0.0, "period": float(W), "cell_h": P, "head_raise_rows": 0,
         "frame_top": None, "frame_bottom": None, "frame_bar_strategy": "side_gap"}
    if authority:
        g["jiazhu_authority"] = "step3"
    return {"image_size": [W, 6 * int(P) + 40], "chars_per_line": 6, "grid": g,
            "columns": [{"index": 1, "left_x": 0.0, "right_x": float(W),
                         "cell_left_x": 0.0, "cell_right_x": float(W), "cells": cells}]}


def _subs(res):
    out: dict[int, set] = {}
    for inst, _p in res:
        out.setdefault(int(inst.idx), set()).add(inst.sub)
    return out


S3_RUN = {1: ["a", "b"], 2: ["a", "b"], 3: ["a", "b"]}


def test_v1_alone_splits_the_tail_row_step3_kept_whole():
    """前提：不给 authority 时（旧行为）v1 段端收编把第 4 格拆了——两步各一套格位。"""
    subs = _subs(CharExtractor().extract_page(_ext_column(), _grid(S3_RUN, False), "t", "1"))
    assert subs[1] == subs[2] == subs[3] == {"a", "b"}
    assert subs[4] == {"a", "b"}


def test_step3_authority_keeps_a_cell_step3_left_whole():
    res = CharExtractor().extract_page(_ext_column(), _grid(S3_RUN, True), "t", "1")
    subs = _subs(res)
    assert subs[1] == subs[2] == subs[3] == {"a", "b"}
    assert subs[4] == {None}                      # Step3 记整格 → 这里也整格
    assert subs[0] == {None}
    tail = next(i for i, _ in res if int(i.idx) == 4)
    assert "jiazhu" not in tail.flags             # v1 打的夹注旗一并摘掉


def test_step3_authority_emits_only_the_halves_step3_emitted():
    """Step3 把第 4 格收成段尾单字（只发 a），v1 量的是整行——照 Step3 只发 a 半。"""
    s3 = {**S3_RUN, 4: ["a"]}
    subs = _subs(CharExtractor().extract_page(_ext_column(), _grid(s3, True), "t", "1"))
    assert subs[4] == {"a"}
    # 同一份 Step3 提示、不给 authority：v1 自己那套照旧拆成一整行
    assert _subs(CharExtractor().extract_page(_ext_column(), _grid(s3, False), "t", "1"))[4] == {"a", "b"}


def test_step3_authority_without_any_jiazhu_splits_nothing():
    subs = _subs(CharExtractor().extract_page(_ext_column(), _grid({}, True), "t", "1"))
    assert all(s == {None} for s in subs.values())


# ── Step3：反向人裁「正文当小注」────────────────────────────────

N, Y0 = 12, 10


def _seg_column():
    """12 格：1–2 正文；3–7 雙行小注；8 是被小注段吞进去的「整宽正文」——两笔分在缝两侧、
    几何上与小注行分不开（#415「此」：左右结构字恰好在缝位有空隙）；9–12 正文。"""
    h = Y0 + N * int(P) + 20
    img = np.full((h, W), 255, np.uint8)
    img[:, :4] = 0
    img[:, -4:] = 0
    for k in range(N):
        y = Y0 + k * int(P)
        if 3 <= k + 1 <= 8:
            _small_pair(img, y)
        else:
            img[y + 20:y + 28, 36:144] = 0
            img[y + 10:y + 100, 86:94] = 0
    return img


def _cells(r):
    out: dict[int, dict] = {}
    for c in r.cells:
        out.setdefault(c.slot, {})[c.sub or ""] = c
    return out


def _seg(**kw):
    return fit_mod.segment_column(_seg_column(), period=P, n_body_slots=N, ref_w=W, seam_band=0, **kw)


def test_forced_main_keeps_the_swallowed_cell_whole():
    base = _seg()
    assert base is not None and sorted(_cells(base)[8]) == ["a", "b"]      # 前提：被并进小注段
    r = _seg(forced_main={8})
    cs = _cells(r)
    assert set(cs[8]) == {""} and cs[8][""].kind == "char"
    assert cs[8][""].x0 < SEAM < cs[8][""].x1                             # 整格：跨过缝
    # 别的格一字不动
    for slot, c in _cells(base).items():
        if slot != 8:
            assert {k: (v.kind, v.y0, v.y1) for k, v in c.items()} == \
                {k: (v.kind, v.y0, v.y1) for k, v in cs[slot].items()}


def test_forced_main_on_unsplit_cells_changes_nothing():
    base = _seg()
    same = _seg(forced_main={1, 10})
    assert [(c.slot, c.sub, c.kind) for c in base.cells] == [(c.slot, c.sub, c.kind) for c in same.cells]


def test_forced_main_wins_over_forced_jiazhu():
    cs = _cells(_seg(forced_main={8}, forced_jiazhu={8}))
    assert set(cs[8]) == {""}


# ── 数据源 / 路由 / Step8 勾选 ──────────────────────────────────

def _ev(seq, key, payload, ts):
    from open_guji_cv.feedback.events import EventTarget, make_event
    _, pg, col, _slot = key.split(":")
    e = make_event("b", seq, "confirm",
                   EventTarget(step="seed_admit", unit="cell", key=key, book="vol02",
                               page=int(pg), col=int(col), slot=0), payload, source_format="server")
    e.ts = ts
    return e


MAIN = {"v": "seg_defect", "quality": "truncated", "reason": "main_as_jiazhu"}


def test_resolved_forced_main_takes_sub_keys_and_latest_wins(tmp_path):
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import resolved_forced_jiazhu, resolved_forced_main
    log = EventLog(tmp_path)
    log.append([
        _ev(1, "vol02:100:4:17a", MAIN, "2026-10-06T00:00:01Z"),
        _ev(2, "vol02:57:4:20b", MAIN, "2026-10-06T00:00:02Z"),
        _ev(3, "vol02:57:4:20b", {"v": "confirm", "shape": "子"}, "2026-10-06T00:00:03Z"),   # 后来改判了
        _ev(4, "vol02:97:9:21", MAIN, "2026-10-06T00:00:04Z"),                               # 整格 key 也收
        _ev(5, "vol02:12:7:9", {"v": "seg_defect", "quality": "truncated",
                                "reason": "jiazhu_as_main"}, "2026-10-06T00:00:05Z"),
    ])
    assert resolved_forced_main("vol02", log) == {(100, 4): {17}, (97, 9): {21}}
    assert resolved_forced_jiazhu("vol02", log) == {(12, 7): {9}}         # 两条通道互不串
    assert resolved_forced_main("vol01", log) == {}


def test_route_invalidates_row_segment_for_main_marks():
    from open_guji_cv.feedback.routes import RouteTable
    table = RouteTable.load(None)
    steps = sorted((d.extra or {}).get("step") or d.consumer
                   for d in table.destinations(_ev(1, "vol02:100:4:17a", MAIN, "2026-10-06T00:00:01Z")))
    assert "row_segment" in steps


def test_returns_classify_main_as_jiazhu_split():
    from open_guji_cv.feedback.returns import classify_return
    assert classify_return(_ev(1, "vol02:100:4:17a", MAIN, "2026-10-06T00:00:01Z")) == \
        ("row_segment", "jiazhu_split")


def test_step8_main_flag_payload_and_readback():
    from open_guji_cv.feedback.collate_state import seg_flags, seg_payload
    p = seg_payload(["main"])
    assert p["reason"] == "main_as_jiazhu" and p["quality"] == "truncated" and p["defect"] == "main"
    both = seg_payload(["jiazhu", "main"])
    assert both["reason"] == "main_as_jiazhu"                              # 两个都勾以「正文当小注」为准
    e = _ev(1, "vol02:100:4:17a", p, "2026-10-06T00:00:01Z")
    assert seg_flags([e], "vol02") == {"vol02:100:4:17a": ["main"]}       # quality=truncated 不读成「字形不完整」
