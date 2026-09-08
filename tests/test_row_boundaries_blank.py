"""弹性 DP 的两条新规则（2026-09-05，切线金标 250 条驱动）：

1. 空白格不吃间距下界：列里少一个字时，缺的那一格不该摊到邻字上（局部滑格）；
2. 列尾格按墨算高：尾部留白/残渣不该把倒数第二条格线挤进末字。

合成投影：字 = 一段墨（0.8·period 高，墨量 0.5·dst_w），缝 = 0 墨。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.row_boundaries import fit_row_boundaries

PERIOD, DST_W = 110, 180


def _column(chars: list[bool], tail_blank: int = 0, head: int = 10) -> tuple[np.ndarray, list[int]]:
    """chars[i] = 该格有没有字。返回投影与"真缝"位置（每个字格的上边界）。"""
    h = head + PERIOD * len(chars) + tail_blank + 10
    proj = np.zeros(h, dtype=np.float64)
    gaps = []
    y = head
    for present in chars:
        gaps.append(y)
        if present:
            proj[y + 12:y + 12 + int(PERIOD * 0.8)] = 0.5 * DST_W
        y += PERIOD
    gaps.append(y)
    return proj, gaps


def _err(bounds, gaps):
    return [min(abs(b - g) for b in bounds) for g in gaps]


def test_regular_column_unchanged():
    proj, gaps = _column([True] * 21)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    assert max(_err(r.boundaries, gaps[1:-1])) <= 3


def test_missing_char_mid_column_does_not_shift_neighbors():
    """第 10 格空：旧 DP 把这一格摊给邻字（每条格线偏几十像素），新规则给它一个空白格。"""
    chars = [True] * 21
    chars[9] = False
    proj, gaps = _column(chars)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    # 除空格两侧外，其余真缝都要有格线落在 ±3px；空格只要求不把邻字切坏
    keep = [g for i, g in enumerate(gaps[1:-1], start=1) if i not in (9, 10)]
    assert max(_err(r.boundaries, keep)) <= 3, _err(r.boundaries, keep)


def test_trailing_blank_does_not_push_last_cut_into_last_char():
    """末字之后有 0.5·period 留白：倒数第二条格线仍该落在末字上方的真缝。"""
    proj, gaps = _column([True] * 21, tail_blank=int(PERIOD * 0.5))
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    last_gap = gaps[-2]          # 末字上边界
    assert min(abs(b - last_gap) for b in r.boundaries[1:-1]) <= 3


def test_two_missing_chars_at_tail():
    """列尾少两个字：真缝全部命中，末两格是空白格。"""
    chars = [True] * 19 + [False, False]
    proj, gaps = _column(chars)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    assert max(_err(r.boundaries, gaps[1:19])) <= 3
    # 末字的下边界落在空白区里，那里只有每 20px 一个的合成候选，精度天然是半步（≤10px）
    assert _err(r.boundaries, gaps[19:20])[0] <= 10


def test_effective_body_slots_drops_one_when_frame_is_a_row_short():
    """版框高只有 20.0 个 period（vol01/5）：按 20 格切，别硬凑 21 格造假空白。"""
    from open_guji_cv.utils.row_boundaries import effective_body_slots
    assert effective_body_slots(21, 0.0, 20.02 * 116, 116) == 20
    assert effective_body_slots(21, 0.0, 20.40 * 112, 112) == 20      # vol02/26
    assert effective_body_slots(21, 0.0, 20.56 * 115, 115) == 21      # vol01/3：够 21 格
    assert effective_body_slots(21, 0.0, 21.0 * 116, 116) == 21
    assert effective_body_slots(21, 103.8, 103.8 + 21.0 * 117, 117) == 21   # 抬头列按主版框以下算


def test_effective_body_slots_never_drops_more_than_one():
    """版框矮得离谱是探测失败：不动，让 DP 照旧无解报错。"""
    from open_guji_cv.utils.row_boundaries import effective_body_slots
    assert effective_body_slots(21, 0.0, 15 * 116, 116) == 21
    assert effective_body_slots(21, 0.0, None, 116) == 21
    assert effective_body_slots(21, 0.0, 2400.0, None) == 21


def test_anchor_does_not_drop_the_first_char():
    """锚点之外的墨要计价（2026-09-08，vol01/48 c5「五朝聖訓」）。

    抬头列：首字「五」贴着列图顶端（y 0~85，字内一道零墨空隙 y 50~58），后接
    朝/聖/訓、十七个空白格、末字。整格空白只收 0.01 之后，没有丢墨代价的 DP 会把
    首锚点放到「五」之后（y=89）——整个「五」扔在格外，再多认一个便宜的空白格凑数。"""
    P, W, n = 117, 180, 22
    h = 2560
    proj = np.zeros(h, dtype=np.float64)
    proj[2:50] = 0.2 * W
    proj[58:85] = 0.2 * W                       # 五
    for a, b in ((95, 185), (215, 320), (335, 450)):
        proj[a:b] = 0.45 * W                    # 朝 聖 訓
    proj[2440:2530] = 0.45 * W                  # 末字
    kw = dict(border_top=100.0, border_bottom=2553.0, period=P, n_slots=n, top_slack=100.0)
    res = fit_row_boundaries(proj, W, **kw)
    assert res is not None and res.boundaries[0] <= 2, f"首锚点落在字内/字后：{res.boundaries[:3]}"
    assert 85 <= res.boundaries[1] <= 95
    res0 = fit_row_boundaries(proj, W, drop_lam=0.0, **kw)
    assert res0 is not None and res0.boundaries[0] > 40, "对照失效：无丢墨代价本应把「五」扔掉"


def test_full_blank_is_cheaper_than_splitting_a_char():
    """整格空白便宜、碎空白贵（vol01/17 c7「示」，真实几何）：首格空白后是「示」，
    顶横（y 138~147）与字身（150~231）之间零墨。老口径认空白格要 0.05，而切在字内
    空隙的两格 127/85 只要 0.025，于是「示」被劈成两格、空格位被吃掉。"""
    P, W = 117, 180
    h = 20 + P * 21
    proj = np.zeros(h, dtype=np.float64)
    proj[138:147] = 0.55 * W                    # 示 顶横
    proj[150:231] = 0.35 * W                    # 示 字身
    for k in range(1, 20):
        y = 234 + P * (k - 1)
        proj[y:y + 90] = 0.45 * W               # 其余 19 字
    kw = dict(border_top=20.0, border_bottom=float(h - 5), period=P, n_slots=21)
    res = fit_row_boundaries(proj, W, **kw)
    assert res is not None
    b = res.boundaries
    assert 100 <= b[1] <= 127, f"首格应是整格空白，格线落在 {b[:3]}"
    assert 228 <= b[2] <= 236, f"示/下字之间的格线不对：{b[:4]}"
