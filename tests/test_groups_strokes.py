# -*- coding: utf-8 -*-
"""于千子干 拆笔画判（`groups.strokes`，A24 2026-11-01）：自造字块验四个字各判对，切坏、组外整理本字弃权。"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def _canvas():
    return np.full((80, 80), 255, np.uint8)


def _stem(g, hook: bool, top: int = 12):
    cv2.rectangle(g, (37, top), (43, 70), 0, -1)
    if hook:
        cv2.rectangle(g, (24, 64), (43, 70), 0, -1)


def _long_bar(g):
    cv2.rectangle(g, (4, 32), (76, 36), 0, -1)


def _top_bar(g, bump: bool = False):
    cv2.rectangle(g, (18, 10), (60, 13), 0, -1)
    if bump:      # 干 的首笔右端凸起
        cv2.fillPoly(g, [np.array([[52, 10], [60, 3], [64, 10], [64, 13], [52, 13]])], 0)


def glyph(ch: str) -> np.ndarray:
    g = _canvas()
    _long_bar(g)
    if ch == "于":
        _top_bar(g)
        _stem(g, hook=True, top=10)
    elif ch == "子":
        _top_bar(g)
        cv2.line(g, (58, 13), (41, 25), 0, 5)          # 乛 的折笔从右上斜下来
        _stem(g, hook=True, top=24)
    elif ch == "千":
        cv2.line(g, (16, 22), (60, 12), 0, 4)          # 首笔一撇：往右上升
        _stem(g, hook=False, top=12)
    elif ch == "干":
        _top_bar(g, bump=True)
        _stem(g, hook=False, top=10)
    return g


@pytest.mark.parametrize("ch", list("于千子干"))
def test_each_char_judged(ch):
    from open_guji_cv.groups import strokes
    got, why, f = strokes.judge(glyph(ch))
    assert got == ch, (why, f)


def test_bad_crop_and_frame_line_abstain():
    from open_guji_cv.groups import strokes
    thin = glyph("于")[:, 25:55]                     # 切坏的窄块
    assert strokes.judge(thin)[0] is None
    g = glyph("千")
    g[76:78, 0:80] = 0                               # 列尾边框线：不能当成钩
    assert strokes.judge(g)[0] in ("千", None)


def test_flow_method_abstains_when_ref_outside_group():
    from open_guji_cv.groups.methods import MethodInput, ZY_STROKES
    from open_guji_cv.groups.flow import FlowConfig
    img = glyph("子")
    mk = lambda ref: MethodInput(group="zy", members=frozenset("于千子干"), cell_id="c", cands=[("子", 0.9)], ref=ref,
                                 cfg=FlowConfig(groups=("zy",)), left=None, right=None, patch_fn=lambda cid: img)
    assert ZY_STROKES.run(mk("子")).char == "子"
    assert ZY_STROKES.run(mk("予")).char is None      # 予 也有钩有斜撇
    assert ZY_STROKES.run(mk(None)).char is None
