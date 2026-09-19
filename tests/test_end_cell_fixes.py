"""2026-09-19 切分精度一轮：周期锚定候选（Step3）+ 端格四处（Step4）。

来源是 bxgb 切分审阅导入测试集之后的集中排查（instances 84 / touching-cuts 234）：

- **Step3 相位漂移**：两字粘连的缝既不是波谷也不是低墨行 → 不在候选集 → DP 整段错
  相位（p15c16 从 955 起 7 格偏 20~34px）。修法：每个候选 v 在 v±period 补候选。
- **Step4 尾格截底 22.6%**：`frame_band_inner` 用 `_nearest_bar` 把末字的宽底横当框，
  条带在底横上方截断；各道剥离函数消融都不改变这个数。修法：`border_line` 策略
  改用「满宽连续段」认框（与 Step2 frame_residue 同一把尺）。
- **列端「一」被当条渣丢掉**：逃生口墨量 1000 是四库粗笔画标的，北行「一」只有 268~400。
- **strip_frame_stub 列外探测窗只剩几像素**、**carve 把字底点/钩尖当框渣**。

每条测试都钉一个「修前会错、修后要对」的形态；数值口径与实测见各函数上方注释。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering import extractor as EX
from open_guji_cv.utils import row_boundaries as RB


# ── Step3：周期锚定候选 ──────────────────────────────────────────────
DST_W = 110
GAP = 71


def _column_with_touching_seam(n: int = 9, touch_at: int = 4) -> np.ndarray:
    """n 个字、字高 GAP；第 touch_at/touch_at+1 两字之间的缝**粘连**：缝上墨 0.15·W，
    且离缝 10px 处各有一个更低的假谷（0.10·W）——真缝既非局部极小也非低墨行，
    与 bxgb p15c16 的形态一致（真缝 937 缺席，旁边 913/955 是候选）。"""
    length = n * GAP + 2 * GAP
    curve = np.full(length, 0.0)
    top = GAP           # 首格从 y=GAP 起（上方一格留白）
    for k in range(n):
        c = top + k * GAP + GAP / 2
        for dy in range(-int(GAP * 0.42), int(GAP * 0.42) + 1):
            y = int(c + dy)
            if 0 <= y < length:
                curve[y] = max(curve[y], DST_W * 0.85 * (1 - (dy / (GAP * 0.42)) ** 2))
    seam = top + (touch_at + 1) * GAP
    curve[seam - 9:seam + 10] = DST_W * 0.15         # 缝被墨填住（盖过两侧字身的尾巴）
    curve[seam] = DST_W * 0.14                        # 中心微凹：锚定点落在缝上而不是填墨段边缘
    # 两侧各一个**更低、够宽**的假谷（离真缝 18px，8 行、0.06·W）：要宽到平滑（win=5）
    # 之后仍比缝上的 0.148 低，缝才不会成为两字之间唯一的局部极小；窄了会被平滑抬高，
    # 缝反而以 0.7 的凸出度成了候选——那样这条测试就考不到「缝缺席」。
    curve[seam - 22:seam - 14] = DST_W * 0.06
    curve[seam + 14:seam + 22] = DST_W * 0.06
    return curve


def _fit(curve, n, **kw):
    top, bot = GAP, GAP + n * GAP
    return RB.fit_row_boundaries(curve, DST_W, float(top), float(bot), float(GAP), n_slots=n, **kw)


def test_period_candidate_keeps_phase_through_touching_seam(monkeypatch):
    n = 9
    curve = _column_with_touching_seam(n)
    res = _fit(curve, n)
    assert res is not None
    grid = [GAP + k * GAP for k in range(n + 1)]
    # 首末锚点落在留白窗口里，位置本来就由间距定，不钉；钉**内部**格线
    err = [abs(b - g) for b, g in zip(res.boundaries[1:-1], grid[1:-1])]
    assert max(err) <= 6, f"格线偏离周期格 {err}"
    # 反证：关掉周期锚定，同一列要么无解、要么至少一条格线偏出半格——证明测试确实在
    # 考这个候选，而不是本来就切得对
    monkeypatch.setattr(RB, "PERIOD_CAND_GUARD", 0.0)
    res0 = _fit(curve, n)
    if res0 is not None:
        err0 = [abs(b - g) for b, g in zip(res0.boundaries[1:-1], grid[1:-1])]
        assert max(err0) > 6, "关掉周期锚定也切对了，这条测试没考到东西"


def test_period_candidate_does_not_duplicate_existing_valleys():
    """已有候选 ±guard 内不再补——别把同一条缝挤进两个点（LOW_INK 那条踩过）。"""
    n = 6
    curve = _column_with_touching_seam(n, touch_at=2)
    smoothed = RB.smooth_curve(curve)
    valleys = RB.find_valleys(smoothed, DST_W)
    res = _fit(curve, n)
    assert res is not None
    # 每条格线附近最多一个候选来源不好直接看，退一步钉行为：内部格线与周期格一致
    grid = [GAP + k * GAP for k in range(n + 1)]
    assert max(abs(b - g) for b, g in zip(res.boundaries[1:-1], grid[1:-1])) <= 6
    assert len(valleys) >= n - 2


# ── Step4：版框带内缘（border_line 策略）────────────────────────────────
def _col_img(h: int = 200, w: int = 120) -> np.ndarray:
    return np.full((h, w), 255, np.uint8)


def test_border_line_band_ignores_wide_bottom_stroke():
    """末字的宽底横（0.7 带宽、8 行厚、离下框 25px）不是框——旧版 `_nearest_bar`
    会在 hint±40 行内把它认成框行，条带在它上方截断，底横整条不进图块。"""
    img = _col_img()
    hint = 180.0
    img[147:155, 18:102] = 0            # 底横：宽 84/120 = 0.7，厚 8
    top, bot = EX.frame_band_inner(img, bottom_hint=hint, strategy="border_line", band=(6, 114))
    assert bot == img.shape[0], f"底横被当成框：bot={bot}"


def test_border_line_band_catches_full_width_bar():
    img = _col_img()
    img[176:188, :] = 0                 # 满宽 12 行的真框，中心 182，离 hint 2
    top, bot = EX.frame_band_inner(img, bottom_hint=180.0, strategy="border_line", band=(6, 114))
    assert bot == 176


def test_border_line_band_top_hint_zero_means_no_top_frame():
    """border_top=0 = 列裁切已把上框排除；带里只有字，别去找。"""
    img = _col_img()
    img[2:6, :] = 0                     # 贴顶一条满宽横（巨/雲 的上横）
    top, _ = EX.frame_band_inner(img, top_hint=0.0, strategy="border_line", band=(6, 114))
    assert top == 0


def test_side_gap_strategy_path_untouched():
    """其它策略走原路：这里只钉「不抛异常、返回页界或更内」。"""
    img = _col_img()
    top, bot = EX.frame_band_inner(img, strategy="side_gap")
    assert 0 <= top <= bot <= img.shape[0]


# ── Step4：孤「一」逃生口（相对量）─────────────────────────────────────
def _one_patch(W: int = 109, cell_h: float = 71.0, y: int = 30, h: int = 9, w: int = 80) -> np.ndarray:
    p = np.full((int(cell_h) + 12, W), 255, np.uint8)
    x0 = (W - w) // 2
    p[y:y + h, x0:x0 + w] = 0
    p[y + 1:y + h:2, x0 + 2:x0 + w - 2:2] = 255      # 刻本笔画的毛边：墨量约六成
    return p


def test_thin_book_one_is_not_junk():
    """北行日錄尺寸的「一」（W 109、格高 71、墨量 ~400）：旧逃生口 1000 判它是条渣。"""
    p = _one_patch()
    area = int((p < 128).sum())
    assert area < EX.TAIL_JUNK_ONE_INK, "合成的「一」墨量得低于旧门槛，否则考不到相对路"
    assert not EX.is_end_cell_junk(p, 71.0, frame_guard=True)


def test_edge_hugging_bar_still_junk():
    """同样大小的横条**贴着图块端行**：那是框渣，相对逃生口不该放它过。"""
    p = _one_patch(y=0)
    p2 = _one_patch(y=(71 + 12) - 9)
    assert EX.is_end_cell_junk(p, 71.0, frame_guard=True)
    assert EX.is_end_cell_junk(p2, 71.0, frame_guard=True)


# ── Step4：strip_frame_stub 列外探测窗 ──────────────────────────────────
def test_frame_stub_needs_a_real_outside_window():
    """v2 的「整页」就是一张列图，两侧只有几像素：那几像素里的墨不能当「框线在继续」的证据。"""
    page = np.full((80, 116), 255, np.uint8)
    page[40:46, 3:113] = 0              # 一条横笔，两端伸进 3px 的边
    patch = page[:, 4:112].copy()
    out = EX.strip_frame_stub(patch, page, 4, 112, 0)
    assert (out < 128).sum() == (patch < 128).sum(), "列外只剩几像素时不该剥"


# ── Step4：carve 的框渣候选要「宽」────────────────────────────────────
def test_char_body_keeps_narrow_bottom_dots():
    """字底的点（黃 的八、灬）：薄、小、与字身隔 2px、贴端——旧判据三条全中，被曲刀切掉。"""
    b = np.zeros((70, 100), np.uint8)
    b[10:50, 30:70] = 1                 # 字身
    b[54:60, 34:42] = 1                 # 左点：8 宽 6 高，离字身 4px
    b[54:60, 58:66] = 1                 # 右点
    body = EX._char_body(b)
    assert body is not None
    assert body[56, 38] and body[56, 62], "窄小的点该归字身"


def test_char_body_still_carves_wide_thin_bar():
    b = np.zeros((70, 100), np.uint8)
    b[10:50, 30:70] = 1
    b[63:66, 20:80] = 1                 # 宽 60（0.6）、厚 3、面积 180：框渣
    body = EX._char_body(b)
    assert body is not None
    assert not body[64, 50], "宽薄横条仍应是可切的框渣候选"
