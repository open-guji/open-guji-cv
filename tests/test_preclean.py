"""Step0 预清理：默认不动图；登记过的页才把反色带反回来。

产物落 precleaned/<book>/<page>.png，raw_page 优先读它；原图永不改写。
"""
import numpy as np
import pytest

from open_guji_cv.utils.preclean import apply_preclean, invert_band


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
