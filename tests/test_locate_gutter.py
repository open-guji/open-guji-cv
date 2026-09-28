# -*- coding: utf-8 -*-
"""`guji locate-gutter` 版心定位（overview #174）：合成整叶，不读真书。

整叶 = 右半叶 N 列 + 版心 + 左半叶 N 列。版心宽故意做得跟列距差不多（Z18 的坑：
把普通界行当成版心边框），里面只有两小段书口字；正文列满字。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from open_guji_cv.utils.locate_gutter import locate_gutter


def spread(*, w=2400, h=1600, n=8, pitch=110, gutter=120, frame=60, shift=0,
           blob=False, noise_line=None) -> tuple[np.ndarray, float]:
    """造一张整叶，返回 (灰度图, 版心中线 x)。`shift` 把整版往右挪（版心不在图中央）；
    `blob` 在版框外右下角贴一块扫描黑斑；`noise_line` 在正文里多加一条假竖线。"""
    g = np.full((h, w), 255, np.uint8)
    total = 2 * n * pitch + gutter
    x0 = (w - total) // 2 + shift
    xs = [x0 + i * pitch for i in range(n + 1)]
    gl, gr = xs[-1], xs[-1] + gutter
    xs += [gr + i * pitch for i in range(n + 1)]
    top, bot = frame, h - frame
    g[top:top + 6, xs[0]:xs[-1]] = 0
    g[bot - 6:bot, xs[0]:xs[-1]] = 0
    for x in xs:
        g[top:bot, x - 3:x + 3] = 0
    for a, b in zip(xs[:-1], xs[1:]):
        if a == gl:                                          # 版心：两小段书口字
            g[top + 80:top + 260, a + 35:b - 35] = 0
            g[bot - 200:bot - 120, a + 40:b - 40] = 0
            continue
        for y in range(top + 20, bot - 80, 90):             # 正文：满列
            g[y:y + 70, a + 15:b - 15] = 0
    if blob:
        g[h - 300:h, w - 90:w - 10] = 0
    if noise_line is not None:
        g[top:bot, noise_line - 2:noise_line + 2] = 0
    return g, (gl + gr) / 2.0


@pytest.mark.parametrize("kw", [{}, {"shift": 180}, {"blob": True}, {"gutter": 105}])
def test_finds_gutter_not_neighbour_rule(kw):
    g, truth = spread(**kw)
    r = locate_gutter(g)
    assert r.x == pytest.approx(truth, abs=8), r.to_dict()
    assert r.confidence > 0.5
    assert r.extent_source == "外框竖线"


def test_band_picks_each_block_separately():
    """一张图上下装两叶、版心 x 不同（Z18 vol09 p258 就差 8~16px；这里差一列多）。"""
    a, ta = spread(h=1200)
    b, tb = spread(h=1200, shift=150)
    img = np.vstack([a, np.full((200, a.shape[1]), 255, np.uint8), b])
    assert locate_gutter(img, band=(0, 1200)).x == pytest.approx(ta, abs=8)
    assert locate_gutter(img, band=(1400, 2600)).x == pytest.approx(tb, abs=8)


def test_no_lines_reports_none():
    r = locate_gutter(np.full((800, 1200), 255, np.uint8))
    assert r.x is None and r.confidence == 0.0 and r.note


def test_half_leaf_is_flagged_low():
    """已剪开的半叶（没有版心）：离中点最近的那对也是正文列——空项低、要么报不像整叶。"""
    g, _ = spread(n=8)
    half = g[:, : g.shape[1] // 2 - 70]
    r = locate_gutter(half)
    assert r.x is None or r.candidates[0].blank < 0.5


def test_cli_json(tmp_path, capsys):
    import cv2
    from open_guji_cv import cli_v2
    g, truth = spread()
    f = tmp_path / "leaf.png"
    cv2.imwrite(str(f), g)
    args = type("A", (), {"image": str(f), "band": None, "ink_threshold": 128, "json": True})()
    cli_v2.cmd_locate_gutter(args)
    out = json.loads(capsys.readouterr().out)
    assert out["x"] == pytest.approx(truth, abs=8)
    assert out["x_left"] < out["x"] < out["x_right"]
    assert 0 <= out["confidence"] <= 1 and out["candidates"]
