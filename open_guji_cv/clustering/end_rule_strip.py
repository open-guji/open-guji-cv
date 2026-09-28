# -*- coding: utf-8 -*-
"""列首／列尾格的「贴边细框线」剥离（书级开关 `end_rule_strip`，缺省关）。

## 为什么要有（2026-09-28，S 道，overview#66）

全唐文（嘉慶揚州刻本，四周雙邊）的列尾字格，紧框里常常带着一条**内框细线**：
线在字身下方隔几像素、厚 3–8px、横贯整个文字带（有时是断续的虚线）。
v006 全书 723 个列尾格里，有约 160 个紧框底边就压在这条线上。列首同理，
只是少得多（上框线多数已被 Step2 削掉）。

现役 `mask_frame_bars_outside` 管不到它：`side_gap` 要行墨 ≥0.55 条带宽
且文字带两侧空档被填满——细线断续时行墨不够、空档里也未必有墨；
`border_line` 要求厚 ≥6px。四庫的版框粗而糊，那两套判据是按四庫标定的，
不能为全唐文放松（任务书：不许改变四庫各册的缺省行为），所以另起一道、
只在书 yaml 写了 `end_rule_strip: true` 的册上开。

## 判据（在最外一格的**裁紧前**图块上，列尾看下沿、列首看上沿）

1. **位置**：线段落在图块外侧 35% 以内，且外侧除碎渣外再没有别的墨；
2. **薄**：段的半峰宽 ≤ 9px（内框线 5–7 行，字的横笔 12–15 行）；
3. **横贯**：横向闭合 9px（接上虚线断口）后，段的并集覆盖 ≥ 0.50 图块宽（图块含救援外扩带，线只跨两道界行之间）；
4. **横贯文字窗**：列图上这几行横向闭合后占文字窗宽 ≥ 0.80（v006 列图中部最宽的字横笔
   ≤0.73）——字的底横（二/且/皇/血）到字身边就停，横贯的只有框线。拿不到列图时退回
   「线的左右端各比字身外沿再伸出 ≥ 4% 图块宽」；
5. **与字分离，或只以细笔尖相连**：线内侧紧邻的 2 行里，有墨的 x 不超过线宽的 35%。

抹法：线外侧的行整行抹白；线本身那几行只抹「内侧紧邻行没有墨」的 x——
与线相连的笔画（入的捺尖压在线上）留一截与笔画同宽的桩，不削字。
"""
from __future__ import annotations

import numpy as np

BIN_T = 128
#: 只在图块外侧这一比例的行里找线
ZONE = 0.35
#: 线的最大厚度（半峰宽，px）。v006 实测内框线 5–7 行，字的横笔 12–15 行
RULE_MAX_T_PX = 9
#: 闭合后行覆盖 ≥ 此值的行才进「段」
RUN_T = 0.08
#: 横向闭合宽度（px），接上虚线断口
CLOSE_W = 9
#: 段内各行闭合后的并集覆盖 ≥ 此比例 × 图块宽，才算「横贯」
#: （图块含左右救援外扩带，比文字带宽；线只跨两道界行之间，约 0.6）
COV_T = 0.50
#: 列图上线所在行横向闭合后占文字窗宽的下限。v006 254 列列图中部（非端区）
#: 最宽的字横笔 ≤0.73（中位 0.52），线 ≥0.8
COL_COV_T = 0.80
#: 没有列图证据时：线两端各比字身外沿多伸出这一比例 × 图块宽
OVERHANG = 0.04
#: 外框粗条（实心）：厚 ≤ 此比例 × 格高、行墨均值 ≥ SOLID_INK。只作为「线外侧还有
#: 一道粗框」跳过用，最终要剥的仍是最里那道细线
SOLID_MAX_T = 0.45
SOLID_INK = 0.60
#: 从线往里连续墨达这么多行才算「笔画接在线上」（毛刺 1–3 行）
STROKE_RUN = 6
#: 线上沿毛刺：剥线后，紧贴线内侧、高 ≤ 此行数的小连通体一并抹掉
FUZZ_H = 6
#: 线内侧紧邻 2 行里有墨的 x 占线宽的上限（超了=与字身粘成一片，不动）
JOIN_MAX = 0.35


def _hclose(b: np.ndarray, w: int) -> np.ndarray:
    """逐行横向闭合（先膨胀再腐蚀），宽 w。纯 numpy，免得为这点事拉 cv2 形态学的边界约定。"""
    H, W = b.shape
    if W == 0:
        return b
    r = w // 2
    pad = np.pad(b, ((0, 0), (r, r)), constant_values=False)
    dil = np.zeros_like(b)
    for k in range(w):
        dil |= pad[:, k:k + W]
    pad2 = np.pad(dil, ((0, 0), (r, r)), constant_values=True)
    ero = np.ones_like(b)
    for k in range(w):
        ero &= pad2[:, k:k + W]
    return ero


def _stroke_cols(b: np.ndarray, ya: int) -> np.ndarray:
    """哪些 x 上有**笔画**从 ya 行往上接着走（连续墨 ≥ STROKE_RUN 行）。
    框线上沿的毛刺只有 1–3 行，不算笔画（v006 p13c2 实测：只看紧邻 2 行会把毛刺当
    笔画保护下来，线就剥不干净）。"""
    W = b.shape[1]
    run = np.zeros(W, dtype=int)
    alive = np.ones(W, dtype=bool)
    for k in range(1, STROKE_RUN + 1):
        y = ya - k
        if y < 0:
            alive[:] = False
            break
        alive &= b[y]
        run += alive
    return run >= STROKE_RUN


def find_end_rule(patch: np.ndarray, cell_h: float, bottom: bool = True,
                  col_cov=None, why: list | None = None):
    """找外侧细框线。返回 (a, b)（图块坐标，闭区间，a≤b）或 None。

    `col_cov(a, b)`（可选）：图块第 a..b 行在**列图**上、横向闭合后占文字窗宽的比例。
    图块到这里时线常被前几道端格剥离削掉一截（v006 p9c6 只剩右半），单看图块
    判不了「横贯」；列图上线是整条的。有它时 ≥ COL_COV_T 即可代替「两端比字宽」。
    `why`：给个 list 就把否决原因写进去（调试用）。"""
    def no(reason):
        if why is not None:
            why.append(reason)
        return None
    b = patch < BIN_T
    if not bottom:
        b = b[::-1]
    H, W = b.shape
    if H < 8 or W < 16:
        return None
    closed = _hclose(b, CLOSE_W)

    def _rows(a, e):               # 翻转坐标 → 图块原坐标（给 col_cov）
        return (a, e) if bottom else (H - 1 - e, H - 1 - a)
    cov = closed.mean(axis=1)
    raw = b.mean(axis=1)
    z0 = int(H * (1 - ZONE))
    runs = []                      # 区内有墨行的连续段，自外向内
    y = H - 1
    while y >= z0:
        if cov[y] >= RUN_T:
            e = y
            while y - 1 >= z0 and cov[y - 1] >= RUN_T:
                y -= 1
            runs.append((y, e))
        y -= 1
    if not runs:
        return no("区内无满宽段")
    # 最外一段之外只许有碎渣
    if runs[0][1] + 1 < H and raw[runs[0][1] + 1:].sum() > 0.25:
        return no("线外还有墨")
    hit = None
    prev_a = None
    for a, e in runs:
        pk = float(cov[a:e + 1].max())
        core = np.flatnonzero(cov[a:e + 1] >= pk / 2) + a
        t = int(core[-1] - core[0] + 1)
        span = closed[a:e + 1].any(axis=0).mean()
        if span < COV_T and not (col_cov is not None and col_cov(*_rows(a, e)) >= COL_COV_T):
            break                  # 不满宽：字的笔画，停（图块里的线常被前几道削短，列图上整条的也算）
        if prev_a is not None and raw[e + 1:prev_a].sum() > 0.25:
            break                  # 两段之间夹着别的墨，不是同一组框线
        if t <= RULE_MAX_T_PX:
            hit = (a, e)
            break                  # 细线是内框，最里一道
        if not (t <= SOLID_MAX_T * cell_h and raw[core[0]:core[-1] + 1].mean() >= SOLID_INK):
            break
        prev_a = a                 # 外粗条：跳过，往里找细线
    if hit is None:
        return no(f"无细线段 runs={runs[:3]}")
    ya, yb = hit
    band = closed[ya:yb + 1].any(axis=0)
    xs_band = np.flatnonzero(band)
    above = b[:max(0, ya - 2)]
    ax = np.flatnonzero(above.any(axis=0)) if above.size else np.array([], int)
    wide = None
    if col_cov is not None:
        wide = col_cov(*_rows(ya, yb)) >= COL_COV_T
    if wide is None and ax.size:
        m = OVERHANG * W
        wide = bool(xs_band[0] <= ax[0] - m and xs_band[-1] >= ax[-1] + m)
    if wide is False:
        return no("不横贯")
    join = _stroke_cols(b, ya) & b[ya:yb + 1].any(axis=0)
    if join.sum() > JOIN_MAX * max(1, int(b[ya:yb + 1].any(axis=0).sum())):
        return no("与字身粘连")
    if bottom:
        return ya, yb
    return H - 1 - yb, H - 1 - ya


def make_col_cov(col_img: np.ndarray, row_off: int, x0: float, x1: float):
    """`find_end_rule` 的 `col_cov`：图块第 a..b 行（图块顶在列图第 row_off 行）在列图
    文字窗 [x0, x1) 上横向闭合 15px 后的覆盖比例。"""
    import cv2
    wx0 = max(0, int(round(x0)))
    wx1 = min(col_img.shape[1], int(round(x1)))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))

    def cov(a: int, b: int) -> float:
        rows = col_img[row_off + a:row_off + b + 1, wx0:wx1] < BIN_T
        if rows.size == 0:
            return 0.0
        cl = cv2.morphologyEx(rows.astype(np.uint8), cv2.MORPH_CLOSE, k)
        return float(cl.any(axis=0).mean())
    return cov


def strip_end_rule(patch: np.ndarray, cell_h: float, bottom: bool = True, col_cov=None):
    """抹掉外侧细框线（见模块头）。返回 (新图块, 线段或 None)。不改入参。"""
    seg = find_end_rule(patch, cell_h, bottom, col_cov=col_cov)
    if seg is None:
        return patch, None
    a, b_ = seg
    src = patch if bottom else patch[::-1]
    H = src.shape[0]
    if not bottom:
        a, b_ = H - 1 - b_, H - 1 - a
    ink = src < BIN_T
    out = src.copy()
    out[b_ + 1:] = 255
    keep = _stroke_cols(ink, a)
    out[a:b_ + 1, ~keep] = 255
    # 毛刺：线内侧 FUZZ_H 行内、原本贴着线、且不往上接的小块
    lo = max(0, a - FUZZ_H)
    if lo < a:
        import cv2
        win = (out[lo:a] < BIN_T).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(win, connectivity=8)
        for k in range(1, n):
            x, y, w, h, _ar = st[k]
            if y + h < a - lo:          # 不贴线
                continue
            if y == 0 and a - lo == FUZZ_H and ink[lo - 1:lo, x:x + w].any():
                continue                # 往上还接着墨，是笔画
            win_k = lab == k
            out[lo:a][win_k] = 255
    if not bottom:
        out = out[::-1].copy()
        a, b_ = H - 1 - b_, H - 1 - a
    return out, (a, b_)
