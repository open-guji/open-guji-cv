"""零墨折线候选 `row_boundaries._free_seam`（cut_free_seam，史記 r77，A22 2026-11-17）：数据自造。"""
from types import SimpleNamespace

import cv2
import numpy as np

from open_guji_cv.impl.keben import row_boundaries as rb

P = 100.0   # 格高


def _cc(ink):
    return cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)[1:3]


def _hook():
    """宽 100：上字（戈）身 y 20–90、x 15–40，横 y 60–70 接到右边的钩，钩 x 78–98 往下伸到 y 140；下字 y 110–190、x 5–25，
    与钩不相碰。直线格线 y 100 劈开上字（钩下段约占两成墨），零墨折线从两字之间斜着绕到钩下面。"""
    ink = np.zeros((220, 100), bool)
    ink[20:90, 15:40] = True
    ink[60:70, 40:78] = True
    ink[60:140, 78:98] = True
    ink[110:190, 5:25] = True
    return ink


def _cells():
    return SimpleNamespace(y0=0.0), SimpleNamespace(y1=220.0)


def _c(y=None):
    return rb.SeamCandidate(kind="straight" if y is None else "seam_narrow", y=y, seam_ink=0, dev_max=0)


def test_split_glyphs_sees_hook_cut():
    ink = _hook()
    lab, st = _cc(ink)
    assert rb._split_glyphs(lab, st, np.full(100, 100), P)          # 直线劈开钩
    assert not rb._split_glyphs(lab, st, np.full(100, 100), 300.0)  # 格高放大三倍：块太小、伸出不够，不算单字劈开


def test_free_seam_goes_around_hook():
    ink = _hook()
    up, dn = _cells()
    cands, ch, by = rb._free_seam([_c()], 0, "rule", ink, _cc(ink), 100.0, P, 0.5, up, dn, None, None, 0, 100, 128)
    assert by == "free" and ch == 1 and cands[1].kind == "free_seam" and cands[1].seam_ink == 0
    ys = np.asarray(cands[1].y)
    assert ys[85] >= 140 and 90 <= ys[10] < 110      # 钩下面绕过去、左边仍在两字之间


def test_free_seam_off_human_and_clean():
    ink = _hook()
    up, dn = _cells()
    c0 = [_c()]
    assert rb._free_seam(c0, 0, "rule", ink, _cc(ink), 100.0, P, 0.0, up, dn, None, None, 0, 100, 128)[2] == "rule"
    assert rb._free_seam(c0, 0, "human", ink, _cc(ink), 100.0, P, 0.5, up, dn, None, None, 0, 100, 128)[2] == "human"
    clean = ink.copy()
    clean[60:140, 78:98] = False              # 没有钩：直线不劈字，不动
    assert rb._free_seam(c0, 0, "rule", clean, _cc(clean), 100.0, P, 0.5, up, dn, None, None, 0, 100, 128)[2] == "rule"


def test_free_seam_judge_only_records():
    ink = _hook()
    up, dn = _cells()

    class J:
        def assess(self, *a, **k):
            return [0.7], [50]                # U-Net 不同意也换（写本戈钩它判给下字），只记一致率
    cands, ch, by = rb._free_seam([_c()], 0, "rule", ink, _cc(ink), 100.0, P, 0.5, up, dn, J(), np.zeros((220, 100)),
                                  0, 100, 128)
    assert by == "free" and cands[ch].agree == 0.7 and cands[ch].dis_unet == 50


def test_free_seam_only_upper_majority():
    """下字的头伸进上格（被劈块墨大半在下格）不换：这类零墨路常走进上字字内白缝，对错各半。"""
    ink = np.flipud(_hook()).copy()       # 上下翻过来：钩从下字往上伸
    up, dn = _cells()
    assert rb._free_seam([_c()], 0, "rule", ink, _cc(ink), 120.0, P, 0.5, up, dn, None, None, 0, 100, 128)[2] == "rule"
