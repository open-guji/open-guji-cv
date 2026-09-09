"""四把尺子的回归。

这个模块的 bug **不会报错，只会给出好看的错数**——开发时 R4 先后虚高成
20.74% 和 13.42%（真值 0.51%），两次都跑得好好的。所以这里把踩过的坑
钉成用例：窗口越界的症状是「被切」厚度接近一个整字（~110px），而真被切
的笔画只有几十像素。
"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.eval.rulers import CLIP_MIN_PX, _clipped_ink, _runs_over, _seam_masked_row_ink


class _Cell:
    def __init__(self, y0: float, y1: float) -> None:
        self.y0, self.y1 = y0, y1


def _prof(h: int, inks: list[tuple[int, int]]) -> np.ndarray:
    p = np.zeros(h)
    for a, b in inks:
        p[a:b] = 0.5
    return p


def test_runs_over_edges():
    m = np.array([1, 1, 0, 0, 1, 0, 1, 1], dtype=bool)
    assert _runs_over(m) == [(0, 2), (4, 5), (6, 8)]
    assert _runs_over(np.zeros(5, dtype=bool)) == []
    assert _runs_over(np.ones(3, dtype=bool)) == [(0, 3)]


def test_no_clip_when_box_fills_cell():
    """紧框贴着格线：框外无空间，必然 0。"""
    prof = _prof(300, [(100, 200)])
    assert _clipped_ink(prof, (0, 100, 0, 200), _Cell(100, 200), 300) == 0


def test_detects_stroke_clipped_above():
    """紧框上方紧贴着一段笔画墨 → 算被切。"""
    prof = _prof(300, [(75, 100), (100, 200)])   # 上方 25px 笔画
    n = _clipped_ink(prof, (0, 100, 0, 200), _Cell(70, 210), 300)
    assert n >= CLIP_MIN_PX and n < 40


def test_ignores_ink_not_touching_box():
    """墨在格内但离紧框有距离 → 是框线残渣/噪声，不算被切。"""
    prof = _prof(300, [(72, 92), (100, 200)])    # 与紧框间隔 8px
    assert _clipped_ink(prof, (0, 100, 0, 200), _Cell(70, 210), 300) == 0


def test_window_never_reaches_neighbour_char():
    """窗口只到本格格线——这是 R4 两次虚高的根因。

    构造：本格 [100,200]，紧框 [105,195]，**格外**（邻字）有 110px 的整字墨。
    窗口若开到版框就会把那 110px 当成「被切」。
    """
    prof = _prof(400, [(105, 195), (210, 320)])  # 后者是邻字
    n = _clipped_ink(prof, (0, 105, 0, 195), _Cell(100, 200), 400)
    assert n < 30, f"窗口越界扫到邻字了：{n}px（整字高度量级）"


def test_seam_top_window_excludes_neighbour_ink():
    """有缝格位：邻字墨落在缝外（缝之上），按直线口径会被 R4 误数。

    本格格线 [100,200]，紧框顶 y0=140（上缘窗口 [100,140) 共 40px）。
    列宽 60px：左 30 列在 [100,140) 整段都有墨——这是邻字紧贴粘连留下的、
    在直线窗口里连续贴到紧框边的墨；右 30 列全空。

    直线口径（不看缝）：40px 连续贴边 → 误判被切，且 ≥ CLIP_MIN_PX。
    缝在这批列上正好落在窗口顶（seam_top=140，整段划给邻格）——按缝开窗后
    这段墨被掐掉，右 30 列本就没有墨，结果应为 0。
    """
    h, w = 300, 60
    cell = _Cell(100, 200)
    cell.seam_top = [140] * 30 + [100] * 30   # 折线：左半段划给邻格，右半段贴直线
    cell.seam_bottom = None
    ink_img = np.zeros((h, w), dtype=bool)
    ink_img[100:140, :30] = True              # 邻字墨：只在左半段，整段贴到紧框边

    bbox = (0, 140, w, 200)
    prof = ink_img.mean(axis=1)
    naive = _clipped_ink(prof, bbox, cell, h)
    assert naive >= CLIP_MIN_PX, f"样例没搭对：直线口径下应先复现出误判，实际 {naive}px"

    fixed = _clipped_ink(prof, bbox, cell, h, ink_img=ink_img, cx0=0)
    assert fixed == 0, f"按缝开窗后邻字墨应被掐掉，实际仍数到 {fixed}px"


def test_seam_masked_row_ink_keeps_own_side():
    """缝之外（本字自己那侧）的墨不该被掐掉——只掐邻格那侧。"""
    ink = np.zeros((10, 4), dtype=bool)
    ink[6:, :] = True   # 本字自己的墨，紧贴窗口下沿
    row = _seam_masked_row_ink(ink, seam=[5, 5, 5, 5], cx0=0, a=0, b=10, keep_from_seam=True)
    assert (row[6:] > 0).all()
    assert (row[:5] == 0).all()


@pytest.mark.parametrize("goal_key", ["R1", "R2", "R3", "R4"])
def test_measure_shape_on_real_data(goal_key):
    """真数据上跑通，且分母非空、比值合理。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure
    try:
        bk = load_book("vol01")
        pgs = bk.resolve_pages("dev_set")[:2]
    except Exception:
        pytest.skip("没有 vol01 数据")
    rs = {r["key"]: r for r in measure("vol01", pgs)["rulers"]}
    r = rs[goal_key]
    assert r["den"] > 0, f"{goal_key} 分母为 0，说明产物没读到"
    assert 0 <= r["num"] <= r["den"]
    # R4 若窗口越界会飙到十几个百分点；正常应远低于此
    if goal_key == "R4":
        assert r["value"] < 5.0, f"R4={r['value']}% 太高，多半是窗口又越界了"
