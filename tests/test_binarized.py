"""整页二值副本（`utils/binarized.py`）：进字形库与人裁看的都该是二值图。

要点：输出必须严格 {0,255} 且与原图同尺寸；读的是 `effective_raw_path`
（登记过 Step0 预清理的页要二值化**修好的那张**）；没生成时调用方能退回灰度。
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from open_guji_cv.utils.binarized import (binarize_page, binarized_or_none,
                                          binarized_path, build_binarized)


def _page(w=240, h=200) -> np.ndarray:
    """灰底纸 + 笔画粗细的深墨 + 一条**浅灰细线**（模拟界行：固定阈 128 砍不下来）。

    ⚠️ 「字」要用**笔画**画，不能画一整块实心方块：Sauvola 是局部阈值，
    大块实心区的内部局部方差为 0、均值又被自己拉黑，内部会被判成纸，只留一圈边
    （实测 50×40 实心块中心判白）。真页面上不存在这种形状——本书 2801×2343 实测
    `<100` 的深墨像素有 505,005 个，二值副本里 **504,718 个（99.94%）仍是黑**。
    合成页画得不像，测出来的就是合成页的毛病，不是代码的。
    """
    g = np.full((h, w), 205, np.uint8)          # 纸
    for x in range(40, 92, 16):                 # 竖笔（宽 6px，笔画量级）
        g[40:80, x:x + 6] = 30
    g[44:50, 40:90] = 30                        # 一道横笔
    g[20:h - 20, 150:153] = 150                 # 浅灰界行
    return g


class _Book:
    id = "tb"
    preclean: dict = {}

    def __init__(self, root, pages):
        self._root = root
        self._pages = pages

    def all_pages(self):
        return list(self._pages)

    def raw_path(self, page: int):
        return self._root / f"{page}.png"


def _mkbook(tmp_path, pages=(1, 2)):
    raw = tmp_path / "raw"
    raw.mkdir()
    for p in pages:
        cv2.imwrite(str(raw / f"{p}.png"), _page())
    return _Book(raw, pages)


def test_binarize_page_is_strictly_two_level_and_same_size():
    g = _page()
    out = binarize_page(g)
    assert out.shape == g.shape
    assert sorted(np.unique(out).tolist()) == [0, 255], "必须是严格二值，不能留灰"
    assert out.dtype == np.uint8


def test_binarize_keeps_the_faint_rule_that_fixed_threshold_would_lose():
    """界行是浅灰细线（150）。固定阈 128 砍不下来，Sauvola 局部阈值留得住——
    这正是本书 Step1 当初被迫上网格模式的那条线。"""
    g = _page()
    col = slice(150, 153)
    assert not (g[:, col] < 128).any(), "前提：这条线在固定阈下是留不下的"
    out = binarize_page(g)
    assert (out[:, col] == 0).any(), "Sauvola 应当把浅灰界行判成墨"


def test_binarize_marks_ink_black_and_paper_white():
    g = _page()
    out = binarize_page(g)
    ink = g < 100
    kept = (out[ink] == 0).mean()
    assert kept > 0.9, f"深墨笔画该判成黑，实得 {kept:.1%}"
    assert out[5, 5] == 255, "纸该是白"
    assert (out[g > 190] == 255).mean() > 0.95, "纸该判成白"


def test_build_writes_one_png_per_page_and_skips_existing(tmp_path):
    book = _mkbook(tmp_path)
    got = build_binarized(book, repo_root=tmp_path, log=lambda *_: None)
    assert len(got) == 2
    for p in book.all_pages():
        dst = binarized_path(book.id, p, repo_root=tmp_path)
        assert dst.exists()
        img = cv2.imread(str(dst), cv2.IMREAD_GRAYSCALE)
        assert sorted(np.unique(img).tolist()) == [0, 255]
    # 第二次不重做
    assert build_binarized(book, repo_root=tmp_path, log=lambda *_: None) == []
    # --force 重做
    assert len(build_binarized(book, force=True, repo_root=tmp_path, log=lambda *_: None)) == 2


def test_build_never_touches_the_raw_page(tmp_path):
    book = _mkbook(tmp_path, pages=(1,))
    src = book.raw_path(1)
    before = src.read_bytes()
    build_binarized(book, repo_root=tmp_path, log=lambda *_: None)
    assert src.read_bytes() == before, "原图是唯一真相，不许改写"


def test_binarized_or_none_returns_none_before_build(tmp_path):
    book = _mkbook(tmp_path, pages=(1,))
    assert binarized_or_none(book.id, 1, repo_root=tmp_path) is None
    build_binarized(book, repo_root=tmp_path, log=lambda *_: None)
    assert binarized_or_none(book.id, 1, repo_root=tmp_path) is not None
