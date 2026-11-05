"""`frame_residue`：清理后端部还剩不剩版框墨（闸2 判据）。

判据本身是在 bxgb 全书 2052 个端口上按 **trim 档位** 标定的（d/e 两档 1065 个
端口零误报）。这里钉的是它的**形态判别力**：只认「横贯整列宽 + 连续若干行」
的框线，不认字的横笔——这正是被证伪的「端部峰值」候选做不到的事
（削干净的 d/e 档峰值 p50 也有 0.43~0.47，与漏判的 c 档 0.548 重叠）。

另有一条独立验证记在这里，因为它不是构造出来的而是实跑撞上的：
判据标定只用了 trim 档位，事后拿它去查「末格（slot 21）把下版框吞进去」
的列，bxgb 全书 92 个末格拉长列里 **9 个含满宽段的全部命中（9/9）**，
另 83 个散墨（末字下伸，bottom_slack 的预期行为）一个没误报。
标定口径与这条查法完全独立，所以这 9/9 是真验证不是自证。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.steps.column_warp import (FRAME_RESIDUE_MIN_RUN, frame_residue)

BAND = (10, 110)


def _blank(h: int = 400, w: int = 120) -> np.ndarray:
    return np.full((h, w), 255, dtype=np.uint8)


def test_clean_column_has_no_residue():
    assert frame_residue(_blank(), BAND) == (0, 0)


def test_full_width_bar_at_top_is_caught():
    g = _blank()
    g[5:5 + FRAME_RESIDUE_MIN_RUN + 2, :] = 0      # 满宽横线
    top, bot = frame_residue(g, BAND)
    assert top >= FRAME_RESIDUE_MIN_RUN
    assert bot == 0


def test_full_width_bar_at_bottom_is_caught():
    g = _blank()
    g[-8:-2, :] = 0
    top, bot = frame_residue(g, BAND)
    assert top == 0
    assert bot >= FRAME_RESIDUE_MIN_RUN


def test_character_stroke_is_not_a_frame():
    """字的横笔：够黑、够连续，但**不满宽**——判据不该认它。

    这是与被证伪的「端部峰值」候选的分水岭：按峰值量，这根笔画的行墨占比
    0.6 会和真框线一样高。
    """
    g = _blank()
    g[5:15, 30:90] = 0              # 占带宽 60/100 = 0.6 < 0.85
    assert frame_residue(g, BAND) == (0, 0)


def test_thin_bar_below_min_run_is_ignored():
    """满宽但只有 1~2 行：够不着 min_run，不算框线。"""
    g = _blank()
    g[5:5 + FRAME_RESIDUE_MIN_RUN - 1, :] = 0
    top, _ = frame_residue(g, BAND)
    assert top < FRAME_RESIDUE_MIN_RUN


def test_only_measures_inside_the_band():
    """带外本来就是界行，必须不参与——否则每一列都会被判成有残框。"""
    g = _blank()
    g[5:20, :BAND[0]] = 0           # 只在左界行位置涂黑
    g[5:20, BAND[1]:] = 0
    assert frame_residue(g, BAND) == (0, 0)


def test_probe_depth_limits_how_far_in_it_looks():
    """列中部的满宽段不算残框——那是内容，不是端部没削干净。"""
    g = _blank(h=400)
    g[190:205, :] = 0
    assert frame_residue(g, BAND) == (0, 0)


def test_degenerate_band_returns_zero():
    """band 空或倒置：返回 0 而不是炸——老产物里出现过 b1 <= b0。"""
    assert frame_residue(_blank(), (50, 50)) == (0, 0)
    assert frame_residue(_blank(), (90, 10)) == (0, 0)
    assert frame_residue(np.zeros((0, 0), dtype=np.uint8), BAND) == (0, 0)


def test_strip_frame_debris_line_aware_keeps_parts_far_from_line():
    """inner_frame_only：给了内框线位，只剥贴着线的碎块；离线远的（「無」的灬）留着。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import strip_frame_debris
    patch = np.full((100, 80), 255, np.uint8)
    patch[10:60, 20:60] = 0              # 字身
    patch[82:87, 22:28] = 0              # 灬 的一点：在列端剥渣带里、离线 10 行
    patch[93:96, 50:56] = 0              # 贴着线的框渣
    old = strip_frame_debris(patch, 0, 98, 100)
    assert (old[82:87, 22:28] == 255).all() and (old[93:96, 50:56] == 255).all()
    new = strip_frame_debris(patch, 0, 98, 100, line_bot=97)
    assert (new[82:87, 22:28] == 0).all()
    assert (new[93:96, 50:56] == 255).all()


def test_strip_frame_debris_line_aware_keeps_tall_dots_near_line():
    """贴着线的也只剥薄片：灬 的点高过 DEBRIS_LINE_MAX_H 格高，贴线也留着。"""
    from open_guji_cv.clustering.extractor import strip_frame_debris
    patch = np.full((100, 80), 255, np.uint8)
    patch[10:60, 20:60] = 0              # 字身
    patch[82:96, 22:30] = 0              # 灬 的一点：高 14 行、贴着线
    patch[93:96, 50:60] = 0              # 线渣：高 3 行
    new = strip_frame_debris(patch, 0, 98, 100, line_bot=97)
    assert (new[82:96, 22:30] == 0).all()
    assert (new[93:96, 50:60] == 255).all()


def test_drop_end_ext_specks_keeps_strokes_only():
    """首格地盘伸到条带顶后，伸出去那段只认像笔画的墨块：零星墨点、细竖条、贴条带边的丢掉。"""
    from open_guji_cv.clustering.extractor import drop_end_ext_specks
    binary = np.zeros((120, 100), bool)
    binary[5:15, 20:80] = True           # 「三」的上横：在原地盘外
    binary[8:10, 90:92] = True           # 零星墨点
    binary[2:30, 40:42] = False
    binary[0:28, 96:99] = True           # 细竖条（界行断头）
    binary[16:20, 0:8] = True            # 贴条带左缘的拐角
    binary[30:90, 20:80] = True          # 字身：在原地盘内
    owner = np.where(binary, 0, -1).astype(np.int16)
    edge = np.full(100, 30.0)
    drop_end_ext_specks(owner, binary, 0, edge, True, 80.0)
    assert (owner[5:15, 20:40] == 0).all() and (owner[5:15, 42:80] == 0).all()
    assert (owner[8:10, 90:92] == -1).all()
    assert (owner[0:28, 96:99] == -1).all()
    assert (owner[16:20, 0:8] == -1).all()
    assert (owner[30:90, 20:80] == 0).all()


def test_restore_trimmed_ends_below_line_only():
    """inner_frame_only：Step2 削掉的列首行从 column_raw 补回，只补本列线以下、文字带以内；d 档不补。"""
    from types import SimpleNamespace
    from open_guji_cv.products.kinds.columns import BorderTrim
    from open_guji_cv.steps.cell_shrink import restore_trimmed_ends
    raw = np.full((200, 60), 255, np.uint8)
    raw[0:3, 5:55] = 0                    # 本列的线：满带
    raw[6:9, 15:40] = 0                   # 字顶横：被 Step2 当框条削掉
    raw[2:20, 0:2] = 0                    # 文字带外的界行
    img = raw.copy()
    img[:20] = 255
    line = SimpleNamespace(text_edge=lambda x: 0.5)
    mapper = SimpleNamespace(to_page_tl=lambda x, y: (x, y))     # 列图即原图
    wrec = SimpleNamespace(band=(4, 56), raised=False, head_raise_inner_y=None,
                           trim_top=BorderTrim(px=20, case="e"), trim_bottom=BorderTrim(px=0, case="c"))
    out = restore_trimmed_ends(img, raw, wrec, {"top": line}, mapper)
    assert (out[6:9, 15:40] == 0).all()   # 字顶横补回
    assert (out[0:3] == 255).all()        # 线不补
    assert (out[:, 0:2] == 255).all()     # 文字带外不补
    wrec.trim_top = BorderTrim(px=20, case="d")
    assert restore_trimmed_ends(img, raw, wrec, {"top": line}, mapper) is img


def test_strip_frame_debris_thin_only_keeps_dots_without_line():
    """没拟出内线的一端（thin_only）：框渣也只剥薄片，「心」的点留着。"""
    from open_guji_cv.clustering.extractor import strip_frame_debris
    patch = np.full((100, 80), 255, np.uint8)
    patch[10:60, 20:60] = 0              # 字身
    patch[80:94, 22:30] = 0              # 心 的一点：高 14 行
    patch[93:96, 50:60] = 0              # 框渣：高 3 行
    old = strip_frame_debris(patch, 0, 98, 100)
    assert (old[80:94, 22:30] == 255).all()
    new = strip_frame_debris(patch, 0, 98, 100, thin_only=True)
    assert (new[80:94, 22:30] == 0).all()
    assert (new[93:96, 50:60] == 255).all()


def test_cut_inner_frame_keep_cross_keeps_stroke_through_line():
    """inner_frame_keep_cross：从字那边连下来、穿过下框细线的竖画留着；别处照旧抹掉线和线外。"""
    from types import SimpleNamespace
    from open_guji_cv.steps.cell_shrink import cut_inner_frame
    img = np.full((100, 40), 255, np.uint8)
    img[90:94, :] = 0                     # 下框细线：90–93 行
    img[60:96, 18:22] = 0                 # 竖画压线、伸出线外两行
    line = SimpleNamespace(text_edge=lambda x: 90.0)
    mapper = SimpleNamespace(to_page_tl=lambda x, y: (x, y))
    old = cut_inner_frame(img, mapper, {"bottom": line})
    assert (old[89:, :] == 255).all()
    new = cut_inner_frame(img, mapper, {"bottom": line}, keep_cross=True)
    assert (new[60:96, 18:22] == 0).all()
    assert (new[89:, :10] == 255).all() and (new[89:, 30:] == 255).all()
