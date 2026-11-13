# -*- coding: utf-8 -*-
"""open_guji_cv.strokes：笔画模板配准与两种判据。数据全在这里现造（粗线画的字），不读字形库、不读 Make Me a Hanzi。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from open_guji_cv.strokes import (ClassStats, RegParams, TemplateBank, average, fit_to_unit, from_polylines, geometry,
                                  plan_pair, register, verify_extra)
from open_guji_cv.strokes._ink import thin
from open_guji_cv.strokes.skeleton import extract

# 字框 0–100 的笔画中线 (y, x)
DA = [("横", [(35, 15), (35, 85)]), ("撇", [(10, 50), (40, 48), (90, 15)]), ("捺", [(45, 52), (90, 88)])]
TAI = DA + [("点", [(68, 44), (78, 52)])]
WANG = [("横", [(12, 20), (12, 80)]), ("横", [(50, 25), (50, 75)]), ("竖", [(12, 50), (88, 50)]),
        ("提", [(88, 15), (88, 85)])]
YU = WANG + [("点", [(66, 62), (76, 70)])]
TU = [("横", [(40, 20), (40, 80)]), ("竖", [(10, 50), (85, 50)]), ("横", [(85, 8), (85, 92)])]
SHI = [("横", [(40, 8), (40, 92)]), ("竖", [(10, 50), (85, 50)]), ("横", [(85, 25), (85, 75)])]


def draw(strokes, size=128, width=9, jitter=0.0, seed=0, extra=()):
    """白底黑字。jitter：每笔端点随机抖动（字框百分比），模拟刻本笔位不一。"""
    rng = np.random.default_rng(seed)
    im = np.full((size, size), 255, np.uint8)
    s = size / 100.0
    for _, pts in list(strokes) + list(extra):
        p = np.array(pts, float) + rng.normal(0, jitter, (len(pts), 2))
        cv2.polylines(im, [np.round(p[:, ::-1] * s).astype(np.int32)], False, 0, width, cv2.LINE_AA)
    return im


def tpl(ch, strokes):
    return from_polylines(ch, [(n, np.array(p, float)) for n, p in strokes])


def test_thin_one_pixel_wide():
    m = np.zeros((40, 80), np.uint8)
    m[15:25, 10:70] = 1
    sk = thin(m)
    assert sk.sum() > 40
    assert (sk.sum(0)[15:65] == 1).all()          # 每列只剩一个像素
    assert set(np.unique(np.nonzero(sk)[0])) <= {19, 20}


def test_register_strokes_land_on_ink():
    fit = register(draw(TAI), tpl("太", TAI))
    assert [s.name for s in fit.strokes] == ["横", "撇", "捺", "点"]
    assert all(s.on_ink > 0.9 for s in fit.strokes)
    assert fit.cover > 0.9
    h = fit.strokes[0]                              # 横：起点在左、止点在右，外推到墨边
    assert h.start[1] < 25 and h.end[1] > 104


@pytest.mark.parametrize("img_strokes,expect", [(TAI, "more"), (DA, "less")])
def test_verify_extra_da_tai(img_strokes, expect):
    t = tpl("太", TAI)
    plan = plan_pair(tpl("大", DA), t)
    assert (plan.kind, plan.more, plan.less, plan.stroke) == ("verify", "太", "大", 3)
    fit = register(draw(img_strokes, jitter=1.0, seed=3), t, RegParams(pin=(plan.stroke,)))
    assert verify_extra(fit, plan.stroke)[0] == expect


@pytest.mark.parametrize("img_strokes,expect", [(YU, "more"), (WANG, "less")])
def test_verify_extra_wang_yu(img_strokes, expect):
    t = tpl("玉", YU)
    plan = plan_pair(tpl("王", WANG), t)
    assert plan.stroke == 4
    fit = register(draw(img_strokes), t, RegParams(pin=(plan.stroke,)))
    assert verify_extra(fit, plan.stroke)[0] == expect


def test_pinned_stroke_does_not_grab_frame_line():
    """切图带进来的框线（贴底的细长横）不是点：钉住的点不许挪过去吃它（殿本 v2~r2~vol02~177~9~21 那种）。
    框线会把整体外框往下撑，点落得偏低，允许弃权，但不许判成「多一笔」。"""
    im = draw(DA)
    cv2.line(im, (3, 122), (124, 122), 0, 2)
    fit = register(im, tpl("太", TAI), RegParams(pin=(3,)))
    assert verify_extra(fit, 3)[0] != "more"
    assert fit.strokes[3].excl < 0.5


def test_pinned_stroke_finds_shifted_dot():
    """点比模板偏了一点（刻本常见）：钉住的笔在小范围内找残墨，仍判得出。"""
    shifted = DA + [("点", [(72, 50), (82, 58)])]
    fit = register(draw(shifted), tpl("太", TAI), RegParams(pin=(3,)))
    assert verify_extra(fit, 3)[0] == "more"
    fit0 = register(draw(shifted), tpl("太", TAI), RegParams(pin=(3,), pin_search=0))
    assert fit0.strokes[3].excl <= fit.strokes[3].excl


def test_geometry_tu_shi():
    t = tpl("土", TU)
    plan = plan_pair(t, tpl("士", SHI))
    assert (plan.kind, plan.tpl_char) == ("geometry", "土")
    X = {c: [geometry(register(draw(s, jitter=1.0, seed=k), t)) for k in range(6)] for c, s in (("土", TU), ("士", SHI))}
    st = ClassStats.from_samples(X)
    for c, s in (("土", TU), ("士", SHI)):
        got, d = st.decide(geometry(register(draw(s, jitter=1.0, seed=99), t)), margin=0.1)
        assert got == c, d
    assert ClassStats.from_json(st.to_json()).decide(X["土"][0])[0] == "土"


def test_plan_pair_not_applicable():
    assert plan_pair(tpl("土", TU), tpl("玉", YU)).kind == "none"


def test_book_template_and_bank_roundtrip(tmp_path):
    base = tpl("太", TAI)
    runs = [fit_to_unit(register(draw(TAI, jitter=1.5, seed=k), base)) for k in range(4)]
    book = average(base, runs, source="book:test")
    assert book.n == 4 and book.names == base.names
    assert all(len(a.pts) == len(b.pts) for a, b in zip(book.strokes, base.strokes))
    bank = TemplateBank(templates={"太": book}, meta={"book": "test"})
    bank.save(tmp_path / "bank.json")
    back = TemplateBank.load(tmp_path / "bank.json")
    assert back.fingerprint == bank.fingerprint
    assert back.get("太").fingerprint == book.fingerprint


def test_register_blank_image():
    fit = register(np.full((64, 64), 255, np.uint8), tpl("大", DA))
    assert len(fit.strokes) == 3 and fit.cover == 0.0


def test_skeleton_extract_san():
    san = [("横", [(20, 25), (20, 75)]), ("横", [(50, 30), (50, 70)]), ("横", [(82, 12), (82, 88)])]
    sts, _ = extract(draw(san, size=200, width=12))
    assert [s.name for s in sts] == ["横", "横", "横"]


def test_verify_extra_abstains_on_bad_fit():
    """整体贴坏了（别的笔不落墨、骨架没被解释）就弃权，不管验的那一笔独占率多高。"""
    from open_guji_cv.strokes import Fit, FitStroke
    ok = [FitStroke("横", np.zeros((2, 2)), on_ink=1.0, excl=0.9) for _ in range(3)]
    dot = FitStroke("点", np.zeros((2, 2)), on_ink=1.0, excl=0.9)
    assert verify_extra(Fit(strokes=ok + [dot], cover=0.95), 3)[0] == "more"
    off = ok[:2] + [FitStroke("捺", np.zeros((2, 2)), on_ink=0.4, excl=0.0)]
    assert verify_extra(Fit(strokes=off + [dot], cover=0.95), 3)[0] is None
    assert verify_extra(Fit(strokes=ok + [dot], cover=0.6), 3)[0] is None


def test_clean_cell_drops_edge_fragments():
    from open_guji_cv.strokes._ink import binarize, clean_cell
    im = draw(DA)
    im[118:128, 40:60] = 0                       # 邻字伸进来的笔头，贴底边
    im[:, 0:2] = 0                               # 界栏线，贴左边
    ink = clean_cell(binarize(im))
    assert ink[120:128, 40:60].sum() == 0 and ink[:, 0:2].sum() == 0
    assert ink.sum() > 0.8 * binarize(draw(DA)).sum()


def test_verify_extra_abstains_on_solid_blob():
    """切坏成一整块黑的格（全唐文 005:1:2:2）弃权。"""
    im = np.full((128, 128), 255, np.uint8)
    im[10:118, 30:90] = 0
    fit = register(im, tpl("太", TAI), RegParams(pin=(3,)))
    assert fit.ink_frac > 0.9
    assert verify_extra(fit, 3)[0] is None


def test_hollow_dot_counts_as_whole_stroke():
    """空心点（刻本只剩一圈墨边，全唐文 008:73:5:20 太）：先填小孔再量，不量成半笔。"""
    im = draw(DA)
    cv2.ellipse(im, (int(0.48 * 128), int(0.75 * 128)), (7, 9), 30, 0, 360, 0, 3)
    fit = register(im, tpl("太", TAI), RegParams(pin=(3,)))
    assert verify_extra(fit, 3)[0] == "more"
    fit0 = register(im, tpl("太", TAI), RegParams(pin=(3,), pin_fill_holes=0))
    assert fit0.strokes[3].excl < fit.strokes[3].excl


def test_far_search_only_when_nothing_near():
    """点离模板远（玉 的点连在第二横末，全唐文 014:153:1:6）：开 pin_search_far 才找得到；近处有残墨就不放宽。"""
    far = WANG + [("点", [(66, 78), (76, 86)])]
    t = tpl("玉", YU)
    assert verify_extra(register(draw(far), t, RegParams(pin=(4,))), 4)[0] != "more"
    assert verify_extra(register(draw(far), t, RegParams(pin=(4,), pin_search_far=0.25)), 4)[0] == "more"


MU = [("横", [(35, 12), (35, 88)]), ("竖", [(8, 50), (92, 50)]), ("撇", [(38, 47), (80, 15)]), ("点", [(38, 53), (80, 85)])]
BEN = MU + [("横", [(72, 32), (72, 68)])]


def test_verify_learned_crossing_stroke():
    """本 的底横穿过竖，独占率天然偏低，固定门槛弃权；按本书刻例学门槛判得出（木本）。"""
    from open_guji_cv.strokes import extra_feats, verify_learned
    t = tpl("本", BEN)
    plan = plan_pair(tpl("木", MU), t)
    assert (plan.kind, plan.more, plan.stroke) == ("verify", "本", 4)
    P = RegParams(pin=(plan.stroke,))
    X = {c: [extra_feats(register(draw(s, jitter=1.0, seed=k), t, P), plan.stroke) for k in range(5)]
         for c, s in (("木", MU), ("本", BEN))}
    st = ClassStats.from_samples(X)
    for c, s in (("木", MU), ("本", BEN)):
        got, _ = verify_learned(register(draw(s, jitter=1.0, seed=42), t, P), plan.stroke, st)
        assert got == c
