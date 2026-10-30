"""弹性 DP 的逐格结构先验 `slot_mask`（2026-10-19）。

先验说「第 k 格该空 / 该有字」，DP 按格加软罚分。要治的是部件分离的字被劈成两格
（三→一+二）：列里少一个字时 DP 拿一个空格位吃掉劈出来的那半，字数先验表达不了
「哪一格该空」，逐格掩码可以。冻结样本是殿本 vol04 三列真实行投影（见 fixture 的 meta）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from open_guji_cv.books.siku_zongmu.row_boundaries import (_pos_to_slot, fit_row_boundaries,
                                                slot_mask_from_occupied)

FIX = Path(__file__).parent / "fixtures" / "slot_mask" / "split_chars.json"


def _cols():
    return json.loads(FIX.read_text(encoding="utf-8"))["columns"]


def _fit(c, **kw):
    proj = np.asarray(c["row_proj"], dtype=np.float64)
    n = c["n_body_slots"] + c["n_raised"]
    r = fit_row_boundaries(proj, c["dst_w"], c["border_top"], c["border_bottom"], c["period"],
                           n_slots=n, top_slack=c["top_slack"], **kw)
    return proj, r


def _inked_slots(c, proj, r) -> list[int]:
    """有墨（任一行 ≥ 空白阈值 0.08 列宽）的格 → 对外 slot 号。"""
    b, thr = r.boundaries, 0.08 * c["dst_w"]
    out = []
    for i in range(len(b) - 1):
        a, z = int(round(b[i])), int(round(b[i + 1]))
        if z > a and proj[a:z].max() >= thr:
            out.append(_pos_to_slot(i + 1, c["n_raised"]))
    return out


def test_mask_of_wrong_length_is_ignored():
    """长度对不上就当没给：边界逐位相同（关时不改任何产物的底线）。"""
    for c in _cols():
        _, r0 = _fit(c)
        _, r1 = _fit(c, slot_mask=[True] * 3)
        assert r0.boundaries == r1.boundaries, c["id"]


def test_frozen_columns_split_a_char_without_mask():
    """对照：不给先验时这三列确实多切一字（样本还在复现原病，下一条测试才有意义）。"""
    for c in _cols():
        proj, r = _fit(c)
        assert r is not None
        assert len(_inked_slots(c, proj, r)) > len(c["occupied"]), c["id"]


def test_mask_keeps_the_split_char_whole():
    """给了逐格先验：有墨的格恰好是先验的格位，劈开的「三」「二」并回一格。"""
    for c in _cols():
        mask = slot_mask_from_occupied(set(c["occupied"]), c["n_body_slots"], c["n_raised"])
        proj, r = _fit(c, slot_mask=mask)
        assert r is not None
        assert _inked_slots(c, proj, r) == sorted(c["occupied"]), c["id"]


def test_mask_is_soft_when_it_contradicts_the_image():
    """先验说中间某格空、图上明明有字（版本异文 / 转写错）：仍有解，不因先验无解。"""
    c = _cols()[0]
    occ = set(c["occupied"]) - {10}
    mask = slot_mask_from_occupied(occ, c["n_body_slots"], c["n_raised"])
    _, r = _fit(c, slot_mask=mask)
    assert r is not None


def test_slot_mask_from_occupied_maps_raised_slots():
    """物理格 1..n_raised 是 -n_raised..-1，正文从 1 起、跳过 0；True = 该空。"""
    m = slot_mask_from_occupied({-1, 1, 3}, n_body_slots=4, n_raised=1)
    assert m == [False, False, True, False, True]
    assert slot_mask_from_occupied({2}, n_body_slots=3) == [True, False, True]
