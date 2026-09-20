"""Step2 列窗上界按版框修正（2026-09-20）：`refine_top_by_frame`。

bxgb p48/p54：Step1 的上版框直线落在首行字的顶边而不是框上（低 12~22px）。首字比上界高的
顶部整块不在列图里；首字顶边恰在上界的，被 `column_border_trim` 当贴边薄线削掉 6~16 行
（二 变一、三 变二、六 丢点、冢 丢宀）。合成一页：满宽框条 + 框下的字墨，top_y 故意给低，
期望上界提到框下沿；框贴着上界（正常）的不动；二/三 的宽横不是框。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.border_geometry import VLine
from open_guji_cv.utils.column_projection import ColumnWindow, refine_top_by_frame

W, H = 300, 400
RAW_L, RAW_R = 50, 150            # 列在原图里的 x 范围


def _win(top_y: float, raised: bool = False) -> ColumnWindow:
    # 新坐标 x = (W-1) - raw_x；left 是页面左侧那条线（raw x 小 → 新坐标 x 大）
    left = VLine(x_at_top=float((W - 1) - RAW_L), slope=0.0)
    right = VLine(x_at_top=float((W - 1) - RAW_R), slope=0.0)
    return ColumnWindow(col=1, left=left, right=right, top_y=top_y, bottom_y=380.0,
                        border_top_y=top_y, border_bottom_y=370.0, raised=raised)


def _page(frame_rows=(100, 112), text_rows=(118, 150)) -> np.ndarray:
    g = np.full((H, W), 255, np.uint8)
    g[frame_rows[0]:frame_rows[1], :] = 0                       # 满宽版框
    g[text_rows[0]:text_rows[1], RAW_L + 25:RAW_R - 25] = 0     # 框下的字（宽 0.5，不满宽）
    g[200:380, RAW_L + 20:RAW_R - 20] = 0                        # 下面的正文
    return g


def test_top_moves_up_to_frame_bottom():
    win = _win(130.0)                       # 落在字墨中间
    d = refine_top_by_frame(_page(), win)
    assert d > 0
    assert abs(win.top_y - 112) <= 2, win.top_y
    assert win.border_top_in_column == 0.0


def test_frame_adjacent_to_top_is_left_alone():
    win = _win(113.0)                       # 框下沿就在上界上方 1 行：正常贴框
    assert refine_top_by_frame(_page(), win) == 0.0
    assert win.top_y == 113.0


def test_moves_even_when_only_white_lies_between():
    """首字顶边恰在上界的情形（二 变一）：框与上界之间只有白，也要提——列图该从框内缘起。"""
    win = _win(118.0)                       # 框下沿 112，中间 6 行白，字从 118 起
    d = refine_top_by_frame(_page(), win)
    assert d > 0 and abs(win.top_y - 112) <= 2


def test_wide_stroke_is_not_a_frame():
    """二/三 的顶横：宽但不满宽（0.7）——不能被当成框把上界提上去。"""
    g = np.full((H, W), 255, np.uint8)
    g[100:106, RAW_L + 15:RAW_R - 15] = 0   # 0.7 宽的横
    g[118:150, RAW_L + 25:RAW_R - 25] = 0
    win = _win(130.0)
    assert refine_top_by_frame(g, win) == 0.0


def test_raised_or_framed_columns_untouched():
    g = _page()
    w1 = _win(130.0, raised=True)
    assert refine_top_by_frame(g, w1) == 0.0
    w2 = _win(130.0)
    w2.border_top_y = 140.0                 # border_top_in_column > 0：框在列图里，另一套逻辑
    assert refine_top_by_frame(g, w2) == 0.0


def test_does_not_move_when_frame_already_at_top():
    """`top_y` 正正切在真框上时不许动——2026-09-19 vol02 实测的回归。

    页面上有两条满宽墨：上面一条是**外框/上欄線**，下面一条是**真版框**，Step1 已经
    把 top_y 切在真框上。旧实现的探针窗口在 top_y 处截止，真框被腰斩、凑不满 MIN_RUN，
    于是抓住上面那条外框、把 top_y 提到它下沿——真框反被圈进列图（vol02 被上移的列里
    47% 是这种）。修法是探针越过 top_y 往下多看几行。
    """
    g = np.full((H, W), 255, np.uint8)
    g[100:112, :] = 0                       # 外框/上欄線
    g[196:202, :] = 0                       # 真版框（top_y 正压在它上面）
    g[210:340, RAW_L + 20:RAW_R - 20] = 0   # 正文
    win = _win(197.0)                       # Step1 切在真框上
    d = refine_top_by_frame(g, win)
    assert d == 0.0, f"不该动，却上移了 {d}px（又去抓上面那条外框了）"
    assert win.top_y == 197.0


def test_still_moves_when_only_the_upper_frame_exists():
    """反证：top_y 处没有框、上面有框时照样要提（别把上一条测试修成「永不动」）。"""
    win = _win(130.0)
    d = refine_top_by_frame(_page(), win)
    assert d > 0
    assert abs(win.top_y - 112) <= 2, win.top_y


def test_outer_run_thickness_counts_rows_not_endpoint_gap():
    """外框墨条厚度按**行数**算，不是端点之差——2026-09-19 vol02 实测的 off-by-one。

    vol02 的上下外框只有 3~5px 厚（竖直外框 19~24px，`OUTER_RUN_MIN=4` 是按它标的）。
    原来 `thick = offs[b]-offs[a]` 少算 1px，占 4 行的条算成 3、被 RUN_MIN 挡掉，
    整册漏报几十页。
    """
    from open_guji_cv.utils.border_geometry import _outer_run, OUTER_INK_MIN
    prof = np.zeros(40)
    prof[20:24] = OUTER_INK_MIN + 0.2        # 占 20,21,22,23 共 4 行 => 厚 4px
    offs = -np.arange(0, 40, 1.0)
    r = _outer_run(prof, offs)
    assert r is not None, "4 行厚的墨条应该认出来（端点之差只有 3，按行数是 4）"
    prof3 = np.zeros(40)
    prof3[20:23] = OUTER_INK_MIN + 0.2       # 3 行 => 厚 3px，仍应被挡
    assert _outer_run(prof3, offs) is None


def test_outer_borders_single_bar_and_weak_vertical_prior():
    """單邊框判 single、不报外框；竖直外框弱峰不当先验（2026-09-20 vol02 p160 / p10）。

    合成一页：上版框是从内框线起 12 行的粗条（單邊框）；下版框是 3 行内框 + 30px 外
    一条 5 行的外框（雙邊框）；竖直只有 3px 细内框、没有外框。期望：top 判 single 且
    不报 outer；bottom 判 double 且报 outer；竖直先验为 None（不能凭噪点造先验）。
    """
    from open_guji_cv.utils.border_geometry import (HLine, SINGLE_BAR_MIN,
                                                   detect_outer_borders)
    Wd, Hd = 600, 800
    mask = np.zeros((Hd, Wd), np.uint8)
    mask[89:101, :] = 255                        # 上：單邊框粗条 12 行（从内框线往外=往上）
    mask[700:703, :] = 255                       # 下：内框 3 行
    mask[733:738, :] = 255                       # 下：外框 5 行，离内框 30px
    mask[:, 60:63] = 255                         # 竖直内框（右侧）
    mask[:, 537:540] = 255                       # 竖直内框（左侧）
    verts = [VLine(x_at_top=float((Wd - 1) - 60), slope=0.0),
             VLine(x_at_top=float((Wd - 1) - 538), slope=0.0)]
    top = HLine(y_at_right=100.0, slope=0.0, kind="top")
    bot = HLine(y_at_right=700.0, slope=0.0, kind="bottom")
    out = detect_outer_borders(mask, top, bot, verts, Wd, Hd)
    assert out["top_frame_kind"] == "single", out
    assert out["top_outer_offset"] is None and out["top_bar_extent"] >= SINGLE_BAR_MIN
    assert out["v_outer_offset"] is None, out          # 没有竖直外框 → 没有先验
    assert out["bottom_frame_kind"] == "double" and out["bottom_outer_offset"] is not None, out


def _hl(y, kind):
    from open_guji_cv.utils.border_geometry import HLine
    return HLine(y_at_right=float(y), slope=0.0, kind=kind)


def _vl(x_raw, w):
    return VLine(x_at_top=float((w - 1) - x_raw), slope=0.0)


def test_push_bottom_to_bar_moves_line_from_text_baseline_to_bar():
    """线塌在最后一行字底边、真框条在 22px 之下 → 推到条上沿 −4（2026-09-20 vol02 p35/p106）。"""
    from open_guji_cv.utils.border_geometry import push_bottom_to_bar, BPUSH_MARGIN
    Wd, Hd = 900, 800
    binm = np.zeros((Hd, Wd), np.uint8)
    for cx in range(120, 800, 90):                    # 一行字：底边 698
        binm[640:698, cx - 25:cx + 25] = 1
    binm[722:731, 40:860] = 1                         # 真框条
    verts = [_vl(40, Wd), _vl(860, Wd)]
    bot = _hl(700, "bottom")
    new, shift = push_bottom_to_bar(binm, bot, verts, Wd, Hd)
    assert shift == 22 - BPUSH_MARGIN, shift
    assert abs(new.y_at(0) - (722 - BPUSH_MARGIN)) < 1e-6


def test_push_bottom_to_bar_leaves_double_frame_and_barless_pages_alone():
    """雙邊框：内框细线在 +5（够格的条）→ 目标 <8 不动；没有条 → 不动；条在线上方 → 不动。"""
    from open_guji_cv.utils.border_geometry import push_bottom_to_bar
    Wd, Hd = 900, 800
    verts = [_vl(40, Wd), _vl(860, Wd)]
    binm = np.zeros((Hd, Wd), np.uint8)
    binm[705:708, 40:860] = 1                         # 内框 +5
    binm[725:730, 40:860] = 1                         # 外框 +25
    _, shift = push_bottom_to_bar(binm, _hl(700, "bottom"), verts, Wd, Hd)
    assert shift == 0.0
    binm = np.zeros((Hd, Wd), np.uint8)
    for cx in range(120, 800, 90):
        binm[640:698, cx - 25:cx + 25] = 1            # 只有字，没有条
    _, shift = push_bottom_to_bar(binm, _hl(700, "bottom"), verts, Wd, Hd)
    assert shift == 0.0
    binm = np.zeros((Hd, Wd), np.uint8)
    binm[680:695, 40:860] = 1                         # 粗条在线之上（下沿路线）
    _, shift = push_bottom_to_bar(binm, _hl(700, "bottom"), verts, Wd, Hd)
    assert shift == 0.0


def _leaning_page(lean_px: float, rule_frac: float):
    """四列文字页：界行只印在顶部 rule_frac 的高度；下面文字列逐渐向右偏 lean_px。"""
    Wd, Hd = 900, 1500
    binm = np.zeros((Hd, Wd), np.uint8)
    yt, yb = 100, 1400
    rules = [60, 240, 420, 600, 780]                    # 5 条线（含两侧框线），列距 180
    for x in rules:
        binm[yt:yt + int((yb - yt) * rule_frac), x - 1:x + 2] = 1
    binm[yt - 3:yt, 40:820] = 1; binm[yb:yb + 3, 40:820] = 1
    for y in range(yt + 20, yb - 20, 60):
        off = lean_px * (y - yt) / (yb - yt)
        for a, b in zip(rules[:-1], rules[1:]):
            cx = (a + b) / 2 + off
            binm[y:y + 40, int(cx - 45):int(cx + 45)] = 1
    verts = [_vl(x, Wd) for x in rules]
    return binm, _hl(yt, "top"), _hl(yb, "bottom"), verts, Wd, Hd


def test_snap_verticals_follows_text_gaps_where_rules_are_missing():
    """界行只印了顶部 15%、文字列往下渐偏 60px（线压进字里）：按文字缝重定位（2026-09-20 p177）。"""
    from open_guji_cv.utils.border_geometry import snap_verticals_to_evidence
    binm, top, bot, verts, Wd, Hd = _leaning_page(60.0, 0.15)     # 页底线要压进字里 ~15px 才算「有病」
    out, n = snap_verticals_to_evidence(binm, top, bot, verts, Wd, Hd, straight=verts)
    assert n == 3, n                                   # 三条内部线都动了，框线不动
    for vi in (1, 2, 3):
        rule = [60, 240, 420, 600, 780][vi]
        raw_top = (Wd - 1) - out[vi].x_at(150.0)
        assert abs(raw_top - rule) <= 4, (vi, raw_top)
        # 底带（中心 y≈1318）：线要离开字、进到缝里（缝 = 两侧文字块之间，离字边 ≥8px）。
        # 不要求落到缝中心——无界行横带只保证「不压字」，中段锚在直线拟合上。
        y = 1318.0
        off = 60 * (y - 100) / 1300
        gap_lo, gap_hi = (rule - 90 + 45) + off + 8, (rule + 90 - 45) + off - 8
        raw_bot = (Wd - 1) - out[vi].x_at(y)
        assert gap_lo <= raw_bot <= gap_hi, (vi, raw_bot, gap_lo, gap_hi)
    assert out[0] is verts[0] and out[4] is verts[4]


def test_snap_verticals_keeps_fully_ruled_page():
    """整页都有界行且线在界行上 → 一条不动。"""
    from open_guji_cv.utils.border_geometry import snap_verticals_to_evidence
    binm, top, bot, verts, Wd, Hd = _leaning_page(0.0, 1.0)
    out, n = snap_verticals_to_evidence(binm, top, bot, verts, Wd, Hd)
    assert n == 0 and all(a is b for a, b in zip(out, verts))


def test_snap_keeps_lines_that_sit_inside_the_gap_even_off_center():
    """整页没印界行、文字不偏、线整体偏离缝中心 15px（仍在缝里、离字 ≥8px）→ 一条不动。
    缝中心不是界行位置（两侧文字不对称时差 ±18px），线在缝里就是对的。"""
    from open_guji_cv.utils.border_geometry import snap_verticals_to_evidence
    binm, top, bot, verts, Wd, Hd = _leaning_page(0.0, 0.0)      # 整页一条界行都没印
    shifted = [verts[0]] + [VLine(x_at_top=v.x_at_top - 15.0, slope=0.0) for v in verts[1:-1]] + [verts[-1]]
    out, n = snap_verticals_to_evidence(binm, top, bot, shifted, Wd, Hd)
    assert n == 0, n


def test_single_bar_tolerates_a_few_white_rows_before_the_bar():
    """下版框被推到条上沿 −4 之后，粗条从 +4 起：仍判 single，不报「外框没探到」。"""
    from open_guji_cv.utils.border_geometry import detect_outer_borders, HLine
    Wd, Hd = 600, 800
    mask = np.zeros((Hd, Wd), np.uint8)
    mask[704:716, :] = 255                       # 下：粗条 12 行，线在 700（条从 +4 起）
    mask[:, 60:63] = 255; mask[:, 537:540] = 255
    verts = [VLine(x_at_top=float((Wd - 1) - 60), slope=0.0),
             VLine(x_at_top=float((Wd - 1) - 538), slope=0.0)]
    out = detect_outer_borders(mask, HLine(y_at_right=100.0, slope=0.0, kind="top"),
                               HLine(y_at_right=700.0, slope=0.0, kind="bottom"), verts, Wd, Hd)
    assert out["bottom_frame_kind"] == "single", out
    assert out["bottom_bar_extent"] == 16.0


def test_snap_reverts_unruled_polyline_bends_to_the_straight_fit():
    """界行只印顶部、文字不偏：折线在下段被（模拟）勾到字上偏 30px，直线拟合是对的 →
    无界行横带锚回直线（2026-09-20 vol02 p160 c4~c7）。"""
    from open_guji_cv.utils.border_geometry import snap_verticals_to_evidence, _from_knots
    binm, top, bot, verts, Wd, Hd = _leaning_page(0.0, 0.15)
    yt, yb = 100.0, 1400.0
    ky = [yt, yt + (yb - yt) / 3, yt + 2 * (yb - yt) / 3, yb]
    bent = [verts[0]]
    for v in verts[1:-1]:
        x = v.x_at_top
        bent.append(_from_knots([x, x, x - 30.0, x - 30.0], ky))   # 下两个折点偏 30px（仍在缝里）
    bent.append(verts[-1])
    out, n = snap_verticals_to_evidence(binm, top, bot, bent, Wd, Hd, straight=verts)
    assert n == 3, n
    for vi in (1, 2, 3):
        for y in (300.0, 900.0, 1350.0):
            assert abs(out[vi].x_at(y) - verts[vi].x_at(y)) <= 4, (vi, y, out[vi].x_at(y), verts[vi].x_at(y))
