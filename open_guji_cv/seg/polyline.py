"""界行折线拟合（2026-10-30 切分模块化第 3 步，从 `utils/border_geometry` 原样拆出）。

竖线按弯度判断走直线还是三段折线：沿线逐行量墨（`_rule_rows`、`gutter_projection`），按页级弯度
（w80）决定要不要折，坐标下降找折点（`_fit_knots`），再用相邻线间距护栏和「折线沿线墨不许比直线多」
验收（`fit_vlines_polyline`）。与书无关，只吃二值图和右上原点的 HLine／VLine。
"""

from __future__ import annotations

import numpy as np

from .frame_types import HLine, VLine


# ---------------------------------------------------------------- 界行折线拟合

BEND_SEARCH = 40          # 弯度投影窗口半宽（px）。要盖得住弯幅（实测最大 ~30），
                          # 又别宽到吃进邻列的字（列距 ~185）
BEND_INK_W_MAX = 9        # 一行在窗口里的墨宽超过这个就当被笔画占了，不算——
                          # 界行本身 3~6px 宽，不剔量的是字不是线
BEND_Y_STEP = 2
BEND_MIN_ROWS = 150       # 有效行少于这个不给结论（按直线处理）
BEND_W80_MED = 7.0        # 页级 w80 中位 >= 这个 => 整页三段。
                          # 门槛定在"折线开始有收益"的那一档，不是拍脑袋：200 页
                          # 实测（加局部一致性闸后）直线主峰在 4~6（137 页），
                          # 7~9 档 37 页强制跑折线，**18/18 页全部降到 4~5、每页
                          # 9~10 条线都动了**——说明这一档已经是真的轻微弯，不是
                          # 噪声。定 7 会切 ~31% 的页，代价只是 Step2 多做两次
                          # 射影；每条线另有"折线得分不比直线高就退回"的保险。
BEND_W80_MAX = 24.0       # 或任一条线 w80 >= 这个（单条线跑飞的那一型：vol01/11
                          # 页级中位只有 9.5 但单条到 64，只看中位会漏）
KNOT_SEARCH = 40          # 每个折点在直线估计的 ±这么多 px 里找。
                          # 24 不够：vol01/119 L3 段3 真墨离直线中位 23px（到 33）、
                          # L4 段1 中位 18.5px（到 55），折点够不着。扫 24/40/60：
                          # 40 把这两段从 w80 19/22 修到 15/13，60 再无收益（已收敛），
                          # 对照页 vol01/151、11、24、vol02/95 一个数都没变。
                          # 邻列界行相距 ~183px，40 不会跳到隔壁。
KNOT_PASSES = 3           # 坐标下降轮数（实测 2 轮已收敛，第 3 轮保险）
KNOT_GUARD_HITS: list = []   # 诊断：护栏每退回一条线记 (线序号, 该对列宽变化率)，跑批时可清空
PAIR_WIDTH_TOL = 0.25     # 护栏：相邻两条折线之间的间距（列宽）沿高度的变化率上限。
                          # 同一页的线是一起弯的，所以**弯页上列宽也不随高度变**——人裁认可的
                          # 折线金标（vol01/11、119、151，83/90 段）上相邻对的变化率全部 ≤ 8%，
                          # 两册 146 张折线页 1302 对里中位 2.3%、95 分位 12.7%。列宽沿高度
                          # 突变只有一种解释：某条线的折点跑进字里了。2026-09-08 vol02/119
                          # 实锤：c5|c6 共用那条界行下半段印得淡，c6 的 其/在/君/故 竖笔粗且
                          # 连续，「墨落在线上的行数」这个目标下竖笔得分反而高，折点被吸进
                          # c6 46px，c6 宽 175→107（变化率 62%），侧墨 0.165 过不了 L2。
                          # ⚠️ 别拿「折线列宽 vs 直线列宽」当判据（第一版就是）：真弯页上直线
                          # 本身就偏 30px，量到的是弯度不是错误，把金标页 119/151 的 4 条好线
                          # 拉偏了 17~29px。


KNOT_TEXT_HALF = 12       # 验收折线：沿线 ±这么多 px 量墨密度（同 snap 的 SNAP_TEXT_DENSE 窗口）
KNOT_TEXT_MARGIN = 0.08   # 折线沿线墨密度比直线高出这么多 ⇒ 折点被字的竖笔勾走了，退回直线。
                          # 2026-10-27 新图源（qiefen）界行淡且断，整页 w80 中位 40+ 全进折线，
                          # 「墨落在线上的行数」被一列列字的竖笔骗走：vol70 p77 九条线中段齐刷刷
                          # 平移 45–70px 压进字里（护栏量列宽变化，整页一起偏它看不见），直线沿线
                          # 0.02–0.05、折线 0.16–0.27。只单边判（折线比直线**更**压字才退）：真弯页
                          # 上是直线压字、折线在缝里，不受影响。


def _line_ink(binm: np.ndarray, xfn, y0: int, y1: int, w: int) -> float:
    """沿线（新坐标 x=xfn(y)）±KNOT_TEXT_HALF 窗口的平均墨密度。"""
    ys = np.arange(max(0, y0), min(binm.shape[0], y1), 4)
    if len(ys) == 0:
        return 0.0
    xr = np.rint((w - 1) - np.array([xfn(float(y)) for y in ys])).astype(int)
    tot = 0.0
    for y, x in zip(ys, xr):
        a, b = max(0, x - KNOT_TEXT_HALF), min(w, x + KNOT_TEXT_HALF + 1)
        if b > a:
            tot += float(binm[y, a:b].mean())
    return tot / len(ys)


BEND_COHERE_WIN = 9       # 局部一致性：跟相邻这么多个有效行的 x 中位比
BEND_COHERE_TOL = 3.0     # 偏离超过这么多 px 的行剔掉——碎片是跳的，线是连的


def _rule_rows(binm: np.ndarray, xfn, y0: int, y1: int, w: int
               ) -> tuple[np.ndarray, np.ndarray]:
    """挑出"这一行的墨确实像界行"的行。两道闸：

    1. 窗口里有墨且墨宽 <= BEND_INK_W_MAX（界行 3~6px 宽；宽了是撞上字）。
    2. **局部一致性**：这一行墨的 x 跟相邻 BEND_COHERE_WIN 个有效行的中位差
       不超过 BEND_COHERE_TOL。真线（哪怕弯）在 y 方向是连续的，笔画碎片是
       跳的。没这道闸 vol02/3 会被判成"最弯的页之一"（w80 36），其实界行是
       直的，只是断掉的行里混进了一小截笔画——第 1 道闸拦不住 <=9px 的碎片。

    返回 (有效行 ys, 全部采样 ys)。`xfn(y)` 是当前线的 x，要能吃 ndarray。

    **实现是整批 gather**（2026-09-03 向量化，结果逐位相同）：原来逐行切片
    每页 10 条线 × 2 次 × 600 行的 Python 循环占 `fit_vlines_polyline` 的 38%
    （直线页 86%）。现在 `_row_windows` 一次取出 (n, 81) 的窗口矩阵，墨宽/质心
    用矩阵算；局部一致性闸中段用 sliding_window_view 去掉中心列取中位，两端
    不足 9 个邻居的 4 行仍按原来的截断窗口逐行算，跟旧实现一样。"""
    ys = np.arange(int(y0), int(y1), BEND_Y_STEP)
    rows, lo, win = _row_windows(binm, xfn, ys, w)
    k = win.sum(axis=1)
    good = (k > 0) & (k <= BEND_INK_W_MAX)
    cand_y = rows[good]
    if len(cand_y) < BEND_COHERE_WIN:
        return cand_y.astype(int), ys
    j = np.arange(2 * BEND_SEARCH + 1, dtype=np.float64)
    cx = lo[good] + (win[good] * j).sum(axis=1) / k[good]      # 墨的 x 质心
    half = BEND_COHERE_WIN // 2
    n = len(cx)
    keep = np.zeros(n, dtype=bool)
    for i in list(range(min(half, n))) + list(range(max(half, n - half), n)):
        a, b = max(0, i - half), min(n, i + half + 1)
        nb = np.concatenate([cx[a:i], cx[i + 1:b]])
        keep[i] = len(nb) == 0 or abs(cx[i] - np.median(nb)) <= BEND_COHERE_TOL
    if n > 2 * half:
        sw = np.lib.stride_tricks.sliding_window_view(cx, BEND_COHERE_WIN)   # (n-8, 9)
        nb = np.delete(sw, half, axis=1)                                     # 去掉自己
        mid = np.abs(cx[half:n - half] - np.median(nb, axis=1)) <= BEND_COHERE_TOL
        keep[half:n - half] = mid
    return cand_y[keep].astype(int), ys


def _row_windows(binm: np.ndarray, xfn, ys: np.ndarray, w: int
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """每一行以这条线为中心取 ±BEND_SEARCH 的窗口（新坐标方向，右到左翻回来），
    一次 gather 成 (n, 81)。窗口出界的行整行丢掉（跟旧实现的 `continue` 一样）。
    行 y 出图（上下版框贴着图边、外推的线端落到图外，裁得紧的图源如 siku-qiefen-v2 会碰到）也丢掉。
    返回 (保留的行 y, 各行窗口起点 lo（新坐标）, 窗口矩阵)。"""
    c = np.rint(xfn(ys.astype(np.float64))).astype(int)
    lo = c - BEND_SEARCH
    ok = (lo >= 0) & (c + BEND_SEARCH + 1 <= w) & (ys >= 0) & (ys < binm.shape[0])
    ys, lo = ys[ok], lo[ok]
    # 新坐标 x = lo + j  <=>  旧列 (w-1) - (lo + j)
    cols = (w - 1) - (lo[:, None] + np.arange(2 * BEND_SEARCH + 1)[None, :])
    win = binm[ys[:, None], cols]
    return ys, lo, win


def gutter_projection(binm: np.ndarray, xfn, y0: int, y1: int, w: int
                      ) -> tuple[float, int, int, int] | None:
    """把一条界行整条投到 x 轴（用户给的直度判据）：线越直，墨全落在同一个 x
    上，峰越高越窄。返回 (peak, w50, w80, n_rows)，n 不够返回 None。

    peak = 投影峰值 ÷ 采样行数（1.0 = 完美）；w50 = 半高宽；w80 = 装下 80% 墨的
    最窄 x 跨度。**判弯用 w80**——线弯成两段时 w50 会出现双峰、被误判成窄。
    """
    rows, _ = _rule_rows(binm, xfn, y0, y1, w)
    if len(rows) < BEND_MIN_ROWS:
        return None
    _, _, win = _row_windows(binm, xfn, rows, w)
    proj = win.sum(axis=0, dtype=np.float64)      # 0/1 计数，整数和，跟逐行累加逐位相同
    p = proj / len(rows)
    pk = float(p.max())
    if pk <= 0:
        return None
    w50 = int((p >= pk / 2.0).sum())
    total, need = p.sum(), p.sum() * 0.80
    best, run, a = len(p), 0.0, 0
    for b in range(len(p)):
        run += p[b]
        while run - p[a] >= need:
            run -= p[a]
            a += 1
        if run >= need:
            best = min(best, b - a + 1)
    return pk, w50, int(best), int(len(rows))


_ALIGN_KERNEL = ((0, 3), (-1, 2), (1, 2), (-2, 1), (2, 1))


def _aligned(binm: np.ndarray, rows: np.ndarray, xs: np.ndarray, w: int) -> int:
    """rows 里的墨落在 xs（新坐标）附近的加权计数——三角核 {0:3, ±1:2, ±2:1}。
    就是"投影峰在 0 处的高度"，但**峰是尖的**：界行 3~6px 宽，用 ±1 硬窗口
    会在线上出现一段平台、折点定不到线心（合成页实测偏 2.9px）；三角核让
    线心处唯一最高。"""
    xo = (w - 1) - np.rint(xs).astype(int)          # 转回旧坐标列号
    total = 0
    for d, wt in _ALIGN_KERNEL:
        xx = xo + d
        ok = (xx >= 0) & (xx < w)
        total += wt * int((binm[rows[ok], xx[ok]] > 0).sum())
    return total


def _aligned_batch(binm: np.ndarray, rows: np.ndarray, xs: np.ndarray, w: int) -> np.ndarray:
    """`_aligned` 的批量版：xs 是 (n_rows, n_cand)，一次算 n_cand 个候选线的得分。
    折点搜索里每个折点要试 81 档偏移，原来是 81 × 5 次小 gather（每页 1.4 万次
    `_aligned` 调用占弯页 `fit_vlines_polyline` 的 49%），现在 5 次 (n_rows, 81)
    的 gather。逐元素算式跟 `_aligned` 相同（同样的 rint / 出界置零），
    结果逐位相同。"""
    xo = (w - 1) - np.rint(xs).astype(int)
    total = np.zeros(xs.shape[1], dtype=np.int64)
    ridx = rows[:, None]
    for d, wt in _ALIGN_KERNEL:
        xx = xo + d
        ok = (xx >= 0) & (xx < w)
        hit = (binm[ridx, np.clip(xx, 0, w - 1)] > 0) & ok
        total += wt * hit.sum(axis=0)
    return total


def _from_knots(kx: list[float], ky: list[float]) -> VLine:
    """四个折点 x + 四个折点 y -> (x, k1, k2, k3)，精确等价。"""
    k1 = (kx[1] - kx[0]) / (ky[1] - ky[0])
    k2 = (kx[2] - kx[1]) / (ky[2] - ky[1])
    k3 = (kx[3] - kx[2]) / (ky[3] - ky[2])
    return VLine(x_at_top=float(kx[0] - k1 * ky[0]), slope=float(k1),
                 k2=float(k2), k3=float(k3), y1=float(ky[1]), y2=float(ky[2]))


def _bridge_row(row: np.ndarray, maxgap: int) -> np.ndarray:
    """把一行里 ≤maxgap 的断口填上（横向闭运算），返回 bool 行。"""
    r = row.astype(bool).copy()
    if not r.any():
        return r
    d = np.diff(np.concatenate(([0], r.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)   # 墨段 [start, end)
    for e, s in zip(ends[:-1], starts[1:]):
        if s - e <= maxgap:
            r[e:s] = True
    return r


def _longest_true_run(r: np.ndarray) -> int:
    if not r.any():
        return 0
    d = np.diff(np.concatenate(([0], r.astype(np.int8), [0])))
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())
SNAP_REG = 0.01             # 折点往现役线拉的弱正则（没证据的段保持原状；0.05 会把 p177 底端折点拉回 9px）


def _fit_knots(ys: np.ndarray, xs: np.ndarray, ws: np.ndarray, ky: list[float],
               kx0: list[float]) -> list[float]:
    """带权最小二乘拟合连续三段折线的 4 个折点 x（帽函数基），弱正则拉向 kx0。"""
    A = np.zeros((len(ys), 4))
    for n, y in enumerate(ys):
        i = 0 if y <= ky[1] else (1 if y <= ky[2] else 2)
        t = (y - ky[i]) / (ky[i + 1] - ky[i])
        A[n, i] = 1 - t; A[n, i + 1] = t
    sw = np.sqrt(ws)
    Aw = A * sw[:, None]; bw = xs * sw
    reg = np.sqrt(SNAP_REG)
    Aw = np.vstack([Aw, reg * np.eye(4)]); bw = np.concatenate([bw, reg * np.array(kx0)])
    sol, *_ = np.linalg.lstsq(Aw, bw, rcond=None)
    return [float(x) for x in sol]


def fit_vlines_polyline(mask: np.ndarray, top: HLine, bottom: HLine,
                        verticals: list[VLine], w: int, h: int, fit: bool = True
                        ) -> tuple[list[VLine], int, float | None, float | None]:
    """按弯度决定整页用直线还是三段折线，弯就逐线拟合折线。
    返回 (verticals, segments, w80_med, w80_max)。

    `fit=False`：只量 w80（给闸1 的 L2 旗标用），**不拟合**，整页保持直线。
    给界行淡而断的书用（`BookSpec.vline_polyline: false`）：那种书上 w80 量的是
    "线有多断"不是"线有多弯"——北行日錄刻本平直扫描页 w80 中位 41、远超
    BEND_W80_MED=7，整页被判成弯页；折点得分在淡线上是噪声，某条线找到一个
    假最优、失败的邻居再照抄它的位移，全页 20 条线齐刷刷平移 33~39px 落到空白
    纸上（p40/p41 实测），闸2 因此只剩 1/19 列过闸。

    **先量再改**：先在直线拟合下算每条线的 w80，页级中位 >= BEND_W80_MED 或任
    一条 >= BEND_W80_MAX 才进入三段；否则原样返回、segments=1。**整页统一**——
    用户要求"要变整个页面都变"，Step2 分带逻辑也只看页级标志。

    三段的拟合不按 k1→k2→k3 顺序贪心搜（前一段的误差会往下传），而是直接搜
    四个折点的 x（x0/xa/xb/x3，在这条线跟上版框、1/3、2/3、下版框交点处），
    连续性天然满足；目标 = 相邻段"墨落在线上 ±1px"的行数（= 投影峰在 0 处的
    高度，就是用户说的"投影最能出现高峰"）。坐标下降 KNOT_PASSES 轮。最后换算
    成 (x, k1, k2, k3)，精确等价。某条线折线得分不高于直线时退回直线斜率
    （k2=k3=k1），格式仍是三段，整页保持一致。
    """
    binm = (mask > 0).astype(np.uint8)
    metrics = []
    for v in verticals:
        xc = v.x_at(h / 2.0)
        y0 = int(top.y_at(xc)) + 30
        y1 = int(bottom.y_at(xc)) - 30
        m = gutter_projection(binm, v.x_at, y0, y1, w) if y1 - y0 > 400 else None
        metrics.append(m)
    w80s = [m[2] for m in metrics if m]
    if not w80s:
        return verticals, 1, None, None
    w80_med, w80_max = float(np.median(w80s)), float(max(w80s))
    if not fit:
        return verticals, 1, w80_med, w80_max
    if w80_med < BEND_W80_MED and w80_max < BEND_W80_MAX:
        return verticals, 1, w80_med, w80_max

    out, shifts, failed = [], [], []
    for vi, v in enumerate(verticals):
        xc = v.x_at(h / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        if yb - yt < 400:
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope,
                             yt + (yb - yt) / 3, yt + 2 * (yb - yt) / 3))
            continue
        ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
        kx = [v.x_at(y) for y in ky]                      # 直线初值
        rows_all, _ = _rule_rows(binm, v.x_at, int(yt), int(yb), w)
        if len(rows_all) < BEND_MIN_ROWS:
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope, ky[1], ky[2]))
            failed.append(vi)
            continue

        # 三段的行集合和归一化位置 t 在整个坐标下降里不变，先算好
        segs = []
        for i in range(3):
            r = rows_all[(rows_all >= ky[i]) & (rows_all < ky[i + 1])]
            segs.append((r, (r - ky[i]) / (ky[i + 1] - ky[i]) if len(r) else None))

        def seg_score(i, xa, xb):
            r, t = segs[i]
            if len(r) == 0:
                return 0
            return _aligned(binm, r, xa + t * (xb - xa), w)

        offs = np.arange(-KNOT_SEARCH, KNOT_SEARCH + 1, dtype=np.float64)
        base_score = sum(seg_score(i, kx[i], kx[i + 1]) for i in range(3))
        for _ in range(KNOT_PASSES):
            moved = False
            for j in range(4):
                xs_all = kx[j] + offs                          # 81 个候选折点 x
                sc = np.zeros(len(offs), dtype=np.int64)
                if j > 0:                                      # 左段：xa 固定，xb 变
                    r, t = segs[j - 1]
                    if len(r):
                        xa = kx[j - 1]
                        sc += _aligned_batch(binm, r, xa + t[:, None] * (xs_all[None, :] - xa), w)
                if j < 3:                                      # 右段：xa 变，xb 固定
                    r, t = segs[j]
                    if len(r):
                        xb = kx[j + 1]
                        sc += _aligned_batch(binm, r, xs_all[None, :] + t[:, None] * (xb - xs_all[None, :]), w)
                # 跟旧的逐档循环同一条挑选规则：分数严格更高才换；平分取 |d| 更小的
                best, best_x = None, kx[j]
                for di, d in enumerate(range(-KNOT_SEARCH, KNOT_SEARCH + 1)):
                    x = kx[j] + d
                    s_ = int(sc[di])
                    if best is None or s_ > best or (s_ == best and abs(d) < abs(best_x - kx[j])):
                        best, best_x = s_, x
                if best_x != kx[j]:
                    kx[j] = best_x
                    moved = True
            if not moved:
                break
        new_score = sum(seg_score(i, kx[i], kx[i + 1]) for i in range(3))
        cand = _from_knots(kx, ky)
        if (new_score <= base_score
                or _line_ink(binm, cand.x_at, int(yt), int(yb), w)
                > _line_ink(binm, v.x_at, int(yt), int(yb), w) + KNOT_TEXT_MARGIN):
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope, ky[1], ky[2]))
            continue
        shifts.append([kx[j] - v.x_at(ky[j]) for j in range(4)])
        out.append(cand)

    # 拟合失败的线（有效行不够）借同页已拟合线的折点位移——**同一页的线是一起
    # 弯的**（纸张/雕版形变是整页的），这个先验比"退回直线"强得多。
    # 治的是最外侧那两条框线：窗口里同时压着内框细线和外框粗条，合起来墨宽
    # 中位 17~21px，被 BEND_INK_W_MAX 全剔掉，有效行只剩 83/1185（vol01/11 L1）
    # 和 46/1197（vol01/119 L1）。
    if shifts and failed:
        med = np.median(np.array(shifts), axis=0)
        for i in failed:
            v = verticals[i]
            xc = v.x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
            out[i] = _from_knots([v.x_at(ky[j]) + med[j] for j in range(4)], ky)

    # ── 护栏：折点被邻列字的竖笔勾走（见 PAIR_WIDTH_TOL 注释）────────────
    # 折线得分只看「墨落在线上的行数」，分不清淡界行和粗竖笔；「得分不比直线高就退回」
    # 在这种情况下不触发（勾到字上得分更高）。几何兜底：相邻两条折线的间距沿高度
    # 变化超过 PAIR_WIDTH_TOL 就是断裂对。断裂对里退谁——看另一侧：一条线若两侧的对
    # 都断（或它是外框线、另一侧无对），退它；否则退另一侧也断的那条；两条都只此一侧
    # 断时退折点位移更大的那条。退回的形状用**相邻线的局部位移插值**（同页的线一起弯，
    # 邻线怎么弯它就怎么弯），不用页级中位——中位会被少数跑飞的线带偏。最多扫两轮。
    n_out = len(out)
    if n_out >= 2:
        def _ys(i):
            xc = verticals[i].x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            return [yt + 30.0, yt + (yb - yt) / 3.0, yt + (yb - yt) / 2.0, yt + 2.0 * (yb - yt) / 3.0, yb - 30.0]
        def _pair_var(i):
            ws = [abs(out[i + 1].x_at(y) - out[i].x_at(y)) for y in _ys(i)]
            lo = min(ws)
            return (max(ws) / lo - 1.0) if lo > 1e-6 else float('inf')
        def _shift(i, y):
            return out[i].x_at(y) - verticals[i].x_at(y)
        def _revert(k):
            v = verticals[k]
            xc = v.x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
            nb = [j for j in (k - 1, k + 1) if 0 <= j < n_out]
            kx = [v.x_at(y) + (sum(_shift(j, y) for j in nb) / len(nb) if nb else 0.0) for y in ky]
            out[k] = _from_knots(kx, ky)
        for _pass in range(2):
            bad = [i for i in range(n_out - 1) if _pair_var(i) > PAIR_WIDTH_TOL]
            if not bad:
                break
            done: set[int] = set()
            for i in bad:
                a, b = i, i + 1
                if a in done or b in done:
                    continue
                a_other = (a == 0) or (_pair_var(a - 1) > PAIR_WIDTH_TOL)
                b_other = (b == n_out - 1) or (_pair_var(b) > PAIR_WIDTH_TOL)
                if a_other and not b_other:
                    k = a
                elif b_other and not a_other:
                    k = b
                else:
                    da = max(abs(_shift(a, y)) for y in _ys(a))
                    db = max(abs(_shift(b, y)) for y in _ys(a))
                    k = a if da >= db else b
                KNOT_GUARD_HITS.append((k, round(float(_pair_var(i)), 3)))
                _revert(k)
                done.add(k)
    return out, 3, w80_med, w80_max
