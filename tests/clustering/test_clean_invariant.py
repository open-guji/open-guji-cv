# -*- coding: utf-8 -*-
"""清边不变式（2026-11-17，全唐文清边丢笔画）：库图是清过边的 canonical，匹配前再清一遍不该再删墨。

出事时的样子自造一份：200px 的字块，主体是 9px 的笔画，左边一根 7px 粗、自成连通体的竖
（懷 的忄）。现行规则下不变式成立；把相对笔宽护栏关掉（旧规则）就违例并报警。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import glyph_selfcheck as G
from open_guji_cv.clustering import normalize as N
from open_guji_cv.clustering.glyph_db import GlyphDB


def _huai_png(shift: int = 0) -> bytes:
    img = np.full((200, 196), 255, np.uint8)
    for (y0, y1, x0, x1) in ((10, 190, 70, 80), (10, 20, 70, 190), (95, 104, 70, 190),
                             (180, 190, 70, 190), (10, 190, 180, 190)):
        img[y0:y1, x0:x1] = 0
    img[6 + shift:192, 22:29] = 0              # 忄 的竖：7px，落在左外带
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture()
def lib(tmp_path):
    p = tmp_path / "output" / "glyph.db"
    p.parent.mkdir()
    g = GlyphDB(p)
    for k in range(4):
        g.admit_instance(f"bk:1:1:{k + 1}", "懷", _huai_png(k), provenance="align",
                         page="1", col=1, idx=k + 1)
    g.close()
    return p


def test_clean_invariant_holds_with_stroke_guard(lib):
    r = G.clean_invariant(lib)
    assert r["n"] == 4 and r["n_bad"] == 0 and not r["alarm"]


def test_clean_invariant_alarms_when_rule_eats_strokes(lib, monkeypatch):
    """库图完好，但匹配前那一遍用旧规则会删掉忄竖：不变式要报出来。"""
    monkeypatch.setattr(N, "LINE_STROKE_RATIO", None)
    r = G.clean_invariant(lib)
    assert r["n_bad"] == 4 and r["alarm"]
    assert r["worst"][0]["char"] == "懷" and r["worst"][0]["loss"] >= G.CLEAN_INVARIANT_LOSS
