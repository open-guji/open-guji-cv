"""Step0 预清理：默认不动图；登记过的页才把反色带反回来。

产物落 precleaned/<book>/<page>.png，raw_page 优先读它；原图永不改写。
"""
import numpy as np
import pytest

from open_guji_cv.utils.preclean import PrecleanGateError, apply_preclean, invert_band


def _page_with_inverted_band(y0=120, y1=170, x0=40, x1=360):
    """造一页：白底 + 竖笔 + 一条带内黑白翻转的横带。

    带内：纸是黑的，笔画是白的 —— 就是 vol02 p151 的情形。
    """
    g = np.full((300, 400), 255, np.uint8)
    strokes = [(60, 66), (140, 146), (220, 226), (300, 306)]
    for a, c in strokes:
        g[40:260, a:c] = 0
    g[y0:y1, x0:x1] = 255 - g[y0:y1, x0:x1]      # 整带反色
    return g, strokes


def test_band_inverted_back():
    g, strokes = _page_with_inverted_band()
    out = invert_band(g, segments=[[40, 359]], y_lo=90, y_hi=200, y_probe=145,
                      ctx=40, smooth=3)

    band = out[120:170, 40:360]
    assert (band < 128).mean() < 0.20, "带内应回到正常墨量（大片纸+少量笔画）"
    for a, c in strokes:                          # 笔画在带内应恢复为黑
        assert (out[125:165, a:c] < 128).all(), f"x={a} 的竖笔没还原"
    # 带外分毫不动
    assert (out[:90] == g[:90]).all() and (out[210:] == g[210:]).all()
    assert set(np.unique(out)) <= {0, 255}, "仍是二值图"


def test_input_not_mutated():
    g, _ = _page_with_inverted_band()
    before = g.copy()
    invert_band(g, segments=[[40, 359]], y_lo=90, y_hi=200, y_probe=145,
                ctx=40, smooth=3)
    assert (g == before).all(), "入参不能被改"


def test_multi_segment_skips_the_gap():
    """带中间断开时，缺口那几列不该被反。"""
    g, _ = _page_with_inverted_band()
    g[120:170, 180:210] = 255 - g[120:170, 180:210]   # 把这段再翻回去 = 缺口
    out = invert_band(g, segments=[[40, 179], [210, 359]], y_lo=90, y_hi=200,
                      y_probe=145, ctx=40, smooth=3)
    assert (out[120:170, 180:210] == g[120:170, 180:210]).all(), "缺口被误反"


def test_raises_when_window_misses_band():
    g, _ = _page_with_inverted_band()
    with pytest.raises(ValueError, match="没量到带"):
        invert_band(g, segments=[[40, 359]], y_lo=10, y_hi=60, y_probe=30,
                    ctx=5, smooth=3)


def test_apply_preclean_reports_and_rejects_unknown():
    g, _ = _page_with_inverted_band()
    out, notes = apply_preclean(g, [{"kind": "inverted_band", "segments": [[40, 359]],
                                     "y_lo": 90, "y_hi": 200, "y_probe": 145,
                                     "ctx": 40, "smooth": 3}])
    assert len(notes) == 1 and "inverted_band" in notes[0]
    assert (out < 128).sum() < (g < 128).sum()

    with pytest.raises(ValueError, match="未知的 preclean 类型"):
        apply_preclean(g, [{"kind": "没这种"}])


def test_no_rules_is_a_noop():
    g, _ = _page_with_inverted_band()
    out, notes = apply_preclean(g, [])
    assert notes == [] and out is g


# ── 出口闸0：带内墨占比要回落到本底量级 ────────────────────────────
def test_gate_passes_a_well_repaired_band():
    """合成的「带内翻转」图，修好之后带内墨占比该落在闸内，报告里带着数字。"""
    g, _ = _page_with_inverted_band()
    out, notes = apply_preclean(g, [{"kind": "inverted_band", "segments": [[40, 359]],
                                     "y_lo": 90, "y_hi": 200, "y_probe": 145,
                                     "ctx": 40, "smooth": 3}])
    assert "带内墨占比" in notes[0] and "过闸" in notes[0]
    assert out is not None


def test_gate_blocks_a_badly_repaired_band():
    """带内除了反色，还压了一块反转也洗不掉的痂（修复后仍是浓墨）——闸必须拦下。"""
    g, _ = _page_with_inverted_band()
    g[130:160, 60:340] = 255      # 压在已反色的带内；反转回来后变成一块浓墨，代表修不好
    with pytest.raises(PrecleanGateError, match="闸0未过"):
        apply_preclean(g, [{"kind": "inverted_band", "segments": [[40, 359]],
                            "y_lo": 90, "y_hi": 200, "y_probe": 145,
                            "ctx": 40, "smooth": 3}])


# ── 产物落盘 + raw_page 改道 ────────────────────────────────────────
def _fake_book(tmp_path, preclean):
    """造一册只有两页的书：p1 登记了预清理，p2 没有。"""
    from dataclasses import dataclass, field
    from pathlib import Path
    from cv2 import imwrite

    raw = tmp_path / "raw"; raw.mkdir()
    g, _ = _page_with_inverted_band()
    imwrite(str(raw / "1.png"), g)
    imwrite(str(raw / "2.png"), np.full((300, 400), 255, np.uint8))

    @dataclass
    class B:
        id: str = "faketest"
        raw_dir: Path = raw
        preclean: dict = field(default_factory=lambda: preclean)
        def raw_path(self, page): return self.raw_dir / f"{page}.png"
    return B()


def test_build_writes_products_and_leaves_raw_alone(tmp_path):
    from cv2 import imread
    from open_guji_cv.utils.preclean import build_precleaned, precleaned_path

    rules = {1: [{"kind": "inverted_band", "segments": [[40, 359]], "y_lo": 90,
                  "y_hi": 200, "y_probe": 145, "ctx": 40, "smooth": 3}]}
    book = _fake_book(tmp_path, rules)
    before = imread(str(book.raw_path(1)), 0).copy()

    written = build_precleaned(book, log=lambda s: None, repo_root=tmp_path)
    assert len(written) == 1
    dst = precleaned_path(book.id, 1, tmp_path)
    assert dst.exists(), "登记页应写出产物"
    assert not precleaned_path(book.id, 2, tmp_path).exists(), "未登记页不该产出"
    assert (imread(str(book.raw_path(1)), 0) == before).all(), "原图被改写了"

    # 已有产物默认跳过，force 才重做
    assert build_precleaned(book, log=lambda s: None, repo_root=tmp_path) == []
    assert len(build_precleaned(book, force=True, log=lambda s: None,
                                repo_root=tmp_path)) == 1


# ── 闸0 单页放宽 gate_override ──────────────────────────────────────
def test_gate_override_needs_reason():
    """写了 gate_override 却不说理由 —— 不放行。例外要留得下痕迹。"""
    from open_guji_cv.utils.preclean import _check_gate, PrecleanGateError

    with pytest.raises(PrecleanGateError, match="gate_reason"):
        _check_gate("inverted_band", 0.74, 0.261, 0.27, None)


def test_gate_override_cannot_tighten():
    """gate_override 只能放宽。要收紧请改全局常量，别在单页偷偷卡严。"""
    from open_guji_cv.utils.preclean import (_check_gate, BODY_INK_GATE,
                                             PrecleanGateError)

    with pytest.raises(PrecleanGateError, match="还严"):
        _check_gate("inverted_band", 0.74, 0.20, BODY_INK_GATE - 0.05, "理由")


def test_gate_override_passes_and_records_reason():
    """放宽生效，且理由写进说明里 —— 日志上看得见这页是例外。"""
    from open_guji_cv.utils.preclean import _check_gate

    note = _check_gate("inverted_band", 0.74, 0.261, 0.27, "字本来就密")
    assert "过闸" in note and "单页放宽至 0.270" in note and "字本来就密" in note


def test_gate_still_blocks_without_override():
    """没写 override 的页，超阈照拦 —— 放宽是单页的，不外溢。"""
    from open_guji_cv.utils.preclean import _check_gate, PrecleanGateError

    with pytest.raises(PrecleanGateError, match="闸0未过"):
        _check_gate("inverted_band", 0.74, 0.261, None, None)


def test_gate_override_beyond_its_own_threshold_still_blocked():
    """放宽了也不是不设防：超过放宽后的阈值照样拦。"""
    from open_guji_cv.utils.preclean import _check_gate, PrecleanGateError

    with pytest.raises(PrecleanGateError, match="闸0未过"):
        _check_gate("inverted_band", 0.80, 0.35, 0.27, "理由")


# ── inverted_rect：坏区本来就是齐整矩形 ──────────────────────────────
def _rect_page(h=300, w=400, rect=(80, 320, 90, 210)):
    """造一页：白纸黑字（墨占比约 0.15，与正文本底同量级），rect 这块整体反色。"""
    g = np.full((h, w), 255, np.uint8)
    for x in range(40, w - 40, 60):          # 几道竖着的"字"
        g[60:260, x:x + 10] = 0
    x0, x1, y0, y1 = rect
    g[y0:y1 + 1, x0:x1 + 1] = 255 - g[y0:y1 + 1, x0:x1 + 1]
    return g


def test_invert_rect_restores_and_leaves_outside_alone():
    """矩形内反回来、矩形外一个像素都不动。"""
    from open_guji_cv.utils.preclean import invert_rect

    rect = (80, 320, 90, 210)
    orig = _rect_page(rect=(0, -1, 0, -1))   # 不反色的"干净版"
    bad = _rect_page(rect=rect)
    x0, x1, y0, y1 = rect

    out = invert_rect(bad, x0=x0, x1=x1, y0=y0, y1=y1)
    assert (out[y0:y1 + 1, x0:x1 + 1] == orig[y0:y1 + 1, x0:x1 + 1]).all(), "矩形内没还原"
    outside = np.ones(bad.shape, bool)
    outside[y0:y1 + 1, x0:x1 + 1] = False
    assert (out[outside] == bad[outside]).all(), "矩形外被动了"
    assert (bad == _rect_page(rect=rect)).all(), "入参被就地改了"


def test_apply_preclean_routes_inverted_rect_through_gate():
    """inverted_rect 也走闸0（不是只有 inverted_band 才核算）。"""
    rect = (80, 320, 90, 210)
    x0, x1, y0, y1 = rect
    rules = [{"kind": "inverted_rect", "x0": x0, "x1": x1, "y0": y0, "y1": y1}]

    out, notes = apply_preclean(_rect_page(rect=rect), rules)
    assert "inverted_rect" in notes[0] and "过闸" in notes[0]
    assert "带内墨占比" in notes[0], "报的应是区内墨占比，不是全页"


def test_inverted_rect_over_gate_is_blocked():
    """矩形反完仍然墨太多 —— 闸照拦，没有因为换了算子就放水。

    构造：区内本来就是大片白纸，反完成了大片黑，墨占比远超闸。
    """
    g = np.full((200, 200), 255, np.uint8)
    rules = [{"kind": "inverted_rect", "x0": 50, "x1": 149, "y0": 50, "y1": 149}]
    with pytest.raises(PrecleanGateError, match="闸0未过"):
        apply_preclean(g, rules)
