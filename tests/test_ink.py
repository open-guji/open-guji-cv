"""册级墨层＋二值化（`utils/ink.py`）与二值体检（`utils/binqc.py`），用户 2026-11-17 定。

要点：没写 `ink` 的册行为与指纹逐位不变；写了的册彩图压掉有色记号、缺省 Otsu＋去小斑、同尺寸同坐标；
认印步读原样亮度；体检能标出有色记号与纸纹。
"""
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from helpers import make_book, make_ctx
from open_guji_cv.utils.ink import (InkSpec, ink_page, is_color, parse_ink, speck_area_for,
                                    to_ink_gray)
from open_guji_cv.utils.binqc import canon_box_suspect, check_page


def _color_page(w=400, h=300) -> np.ndarray:
    """米黄纸＋黑墨竖笔＋一方朱印（BGR）。"""
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (170, 215, 230)                       # 米黄纸
    for x in range(60, 140, 20):
        img[60:220, x:x + 6] = (30, 30, 30)        # 黑墨
    img[80:160, 250:330] = (40, 40, 200)           # 朱印（红）
    return img


# ── 配置 ───────────────────────────────────────────────────────────────

def test_parse_absent_is_none_and_defaults():
    assert parse_ink(None) is None
    s = parse_ink({})
    assert (s.color, s.binarize, s.speck_area) == ("auto", "otsu", "auto")
    assert parse_ink({"binarize": "none"}).binary is False
    assert parse_ink({"binarize": "sauvola", "window": "auto"}).window == "auto"


@pytest.mark.parametrize("bad", [{"color": "blue"}, {"binarize": "niblack"}, {"window": 30},
                                 {"speck_area": -1}, {"oops": 1}, "otsu"])
def test_parse_rejects_bad(bad):
    with pytest.raises(ValueError):
        parse_ink(bad)


def test_token_only_has_relevant_keys():
    assert "window" not in parse_ink({}).token()
    assert parse_ink({"binarize": "sauvola"}).token()["window"] == 31
    assert "speck_area" not in parse_ink({"binarize": "none"}).token()


# ── 墨层 ───────────────────────────────────────────────────────────────

def test_color_detection():
    assert is_color(_color_page())
    g = cv2.cvtColor(_color_page(), cv2.COLOR_BGR2GRAY)
    assert not is_color(g)
    assert not is_color(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))   # 灰度存成 RGB：三通道相同


def test_auto_ink_drops_red_seal_keeps_black():
    img = _color_page()
    out = ink_page(img, parse_ink({}))
    assert out.shape == img.shape[:2]                           # 同尺寸＝同坐标
    assert sorted(np.unique(out).tolist()) == [0, 255]
    assert (out[60:220, 60:66] == 0).mean() > 0.95              # 黑墨在
    assert (out[90:150, 260:320] == 255).mean() > 0.95          # 朱印被压掉
    # 只按亮度转（luma）时朱印是墨——这正是要压的东西
    luma = ink_page(img, parse_ink({"color": "luma"}))
    assert (luma[90:150, 260:320] == 0).mean() > 0.95


def test_gray_page_auto_is_luma_and_none_keeps_gray():
    g = cv2.cvtColor(_color_page(), cv2.COLOR_BGR2GRAY)
    assert np.array_equal(to_ink_gray(g, "auto"), g)
    assert np.array_equal(ink_page(g, parse_ink({"binarize": "none"})), g)


def test_otsu_removes_specks_scaled_by_height():
    g = np.full((3000, 400), 210, np.uint8)
    g[500:900, 100:110] = 20                                     # 一笔
    for y in range(1200, 2800, 50):
        g[y:y + 2, 200:202] = 60                                 # 4 px 的纸纹斑
    out = ink_page(g, parse_ink({}))
    assert (out[500:900, 100:110] == 0).mean() > 0.95
    assert (out[1200:2800, 200:202] == 255).all()
    assert speck_area_for(parse_ink({}), 6300) > speck_area_for(parse_ink({}), 3000)
    keep = ink_page(g, parse_ink({"speck_area": 0}))
    assert (keep[1200:1202, 200:202] == 0).all()


# ── 管线读图与指纹 ─────────────────────────────────────────────────────

def _book_with_page(tmp_path, img, **kw):
    raw = tmp_path / "raw"
    raw.mkdir()
    cv2.imwrite(str(raw / "1.png"), img)
    return make_book(raw_dir=raw, raw_pattern="{page}.png", **kw)


def test_raw_page_uses_ink_and_luma_for_seal_step(tmp_path):
    img = _color_page()
    ctx = make_ctx(tmp_path, _book_with_page(tmp_path, img, ink=parse_ink({})))
    out = ctx.raw_page(1)
    assert sorted(np.unique(out).tolist()) == [0, 255]
    assert (out[90:150, 260:320] == 255).mean() > 0.95
    ctx.step_id = "seal_detect"
    seal = ctx.raw_page(1)
    assert np.array_equal(seal, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    ctx.step_id = "border_detect"
    assert np.array_equal(ctx.raw_page(1), out)


def test_raw_page_without_ink_unchanged(tmp_path):
    img = _color_page()
    ctx = make_ctx(tmp_path, _book_with_page(tmp_path, img))
    from open_guji_cv.utils.image_io import imread
    assert np.array_equal(ctx.raw_page(1), imread(str(tmp_path / "raw" / "1.png"), 0))


def test_fingerprint_key_only_when_set():
    from open_guji_cv.core import engine as E
    from open_guji_cv.steps.border_detect import BorderDetectStep
    step = BorderDetectStep()
    p = step.spec.params()
    ph = E.params_hash(p, step.spec.soft_params, step.spec.path_params)
    base = E._self_payload(step, make_book(), ph)
    assert "ink" not in base and "bin_input" not in base
    with_ink = E._self_payload(step, make_book(ink=parse_ink({})), ph)
    assert with_ink["ink"] == parse_ink({}).token()
    assert {k: v for k, v in with_ink.items() if k != "ink"} == base
    both = E._self_payload(step, make_book(ink=parse_ink({}), binarized_input=True), ph)
    assert "bin_input" not in both                              # 写了 ink，老开关不起作用
    assert E._self_payload(step, make_book(binarized_input=True), ph)["bin_input"] is True


# ── 二值副本与体检 ─────────────────────────────────────────────────────

def test_build_binarized_with_ink_writes_qc(tmp_path):
    from open_guji_cv.utils.binarized import build_binarized, binarized_path
    from open_guji_cv.utils.binqc import qc_path, read_qc
    img = _color_page()
    book = _book_with_page(tmp_path, img, ink=parse_ink({}))
    book.preclean = {}
    build_binarized(book, [1], repo_root=tmp_path, log=lambda s: None)
    png = binarized_path(book.id, 1, tmp_path)
    out = cv2.imread(str(png), 0)
    assert np.array_equal(out, ink_page(img, book.ink))
    qc = read_qc(png)
    assert qc_path(png).exists() and qc["page"] == 1 and qc["color_mode"] == "max"
    marks = [r for r in qc["regions"] if r["reason"] == "color_mark"]
    assert marks, "朱印处该标 color_mark"
    x0, y0, x1, y1 = marks[0]["bbox"]
    assert x0 <= 260 and x1 >= 320 and y0 <= 90 and y1 >= 150
    json.dumps(qc)


def test_canon_box_suspect_flips_x():
    qc = check_page(_color_page(), parse_ink({}))
    W = qc["size"][0]
    seal = [(W - 1) - 320, 90, (W - 1) - 260, 150]               # 朱印处，右上原点
    ink = [(W - 1) - 66, 100, (W - 1) - 60, 180]                  # 黑墨处
    assert canon_box_suspect(qc, seal) == ["color_mark"]
    assert canon_box_suspect(qc, ink) == []
    assert canon_box_suspect(None, seal) == []


def test_qc_marks_speckle_on_textured_paper():
    rng = np.random.default_rng(0)
    g = np.full((3000, 600), 210, np.uint8)
    ys, xs = rng.integers(100, 2900, 4000), rng.integers(100, 500, 4000)
    for y, x in zip(ys, xs):
        g[y:y + 2, x:x + 2] = 80
    qc = check_page(g, InkSpec())
    assert any(r["reason"] == "speckle" for r in qc["regions"])
