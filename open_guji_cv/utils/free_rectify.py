"""自由版式：按版框把页面拉正（Sheldon 10-28：「整卷有拉伸，先匹配边框，进行修复」）。

yxat 的扫描图有倾斜、透视（射影）变形，框线也不全直：列是斜的，竖直切线就穿字。
做法：沿框线四边逐段量**框线内沿**的位置（双线框取细内框），连成折线（弯框、折框都跟得上），四条边围成的区域用
Coons 曲面片映成正矩形；矩形放在原框的平均位置，所以拉正后坐标与原图只差几到几十 px，
人标的 splits／box（原图像素）照样能吸附。框外的部分跟着最近的框边平移（不外推曲线）。

没找到的边（多是书脊一侧，那边是纸边、没框线）取对边的形状平移到兜底位置。
`warp` 记在 `layout_blocks` 里，Step2／3 用 `rectify_gray` 得到同一张拉正后的图。
"""

from __future__ import annotations

import cv2
import numpy as np

SIDES = ("top", "bottom", "left", "right")


def _bands(prof: np.ndarray, at: int, inward: int, thr: float, reach: int, inner: int,
           thin: int) -> tuple[float | None, float | None]:
    """一维墨投影上，at 附近（±reach）最近的墨带的内沿；再往里 inner 以内若还有一条细墨带（≤ thin 宽，
    双线框的细内线），也给它的内沿。inward=+1 是下标增大方向朝框里。"""
    n = len(prof)
    hit = None
    for d in range(reach + 1):
        for k in (at - d, at + d):
            if 0 <= k < n and prof[k] >= thr:
                hit = k
                break
        if hit is not None:
            break
    if hit is None:
        return None, None
    k = hit
    while 0 <= k + inward < n and prof[k + inward] >= thr:
        k += inward
    e1 = k + inward
    e2 = None
    # 量到的这条墨带本身细（就是细框线）就不再往里找——往里是字（Sheldon 10-28 p32 左框）；
    # 墨带越粗（粗外框、扫描的黑边）细内框可以离得越远
    o = hit
    while 0 <= o - inward < n and prof[o - inward] >= thr:
        o -= inward
    band_w = abs(k - o) + 1
    if band_w <= thin:
        return float(e1), None
    reach_in = min(2 * inner, max(inner, 2 * band_w))
    j = e1
    while abs(j - e1) <= reach_in and 0 <= j < n:
        if prof[j] >= thr:                 # 下一条墨带：量宽度，够细才算内线
            m = j
            while 0 <= m + inward < n and prof[m + inward] >= thr and abs(m - j) <= thin:
                m += inward
            if abs(m - j) < thin:
                e2 = m + inward
            break
        j += inward
    return float(e1), (None if e2 is None else float(e2))


def _clean(ts: np.ndarray, ps: np.ndarray, *, win: int = 7, tol: float = 4.0) -> tuple[np.ndarray, np.ndarray]:
    """逐段量的点去掉离群（离滑动中位 > tol），再滑动中位一遍：折点保得住，零星的字拉长的段丢掉。"""
    if len(ts) < win:
        return ts, ps
    med = np.array([np.median(ps[max(0, i - win // 2):i + win // 2 + 1]) for i in range(len(ps))])
    keep = np.abs(ps - med) <= tol
    ts, ps = ts[keep], ps[keep]
    w2 = max(1, win // 2)
    sm = np.array([np.median(ps[max(0, i - w2 // 2 - 1):i + w2 // 2 + 2]) for i in range(len(ps))])
    return ts, sm


def trace_side(ink: np.ndarray, side: str, pos: float, lo: float, hi: float, *, step: int = 24,
               win: int = 24, thr: float = 0.5, reach: int = 30, inner: int = 45, thin: int = 12,
               min_frac: float = 0.5) -> dict | None:
    """沿一条框边（大约在 pos，沿边方向覆盖 [lo, hi)）逐段量框线内沿，连成折线 {"t": [...], "p": [...]}
    （横边 t 是 x、p 是 y；竖边 t 是 y、p 是 x）。

    双线框（粗外框＋细内框，Sheldon 10-28）：量到的墨带里面 inner 以内还有一条细线，且这样的段占一半以上，
    就取细内框的内沿——外框常和内框不平行，以内框为准。折线不拟多项式：弯的、折的框都跟得上。
    量到的点太少（< min_frac）返回 None。"""
    horiz = side in ("top", "bottom")
    inward = 1 if side in ("top", "left") else -1
    ts, p1, p2 = [], [], []
    p0 = int(round(pos))
    for t in range(int(lo), int(hi) - win, step):
        strip = ink[:, t:t + win].mean(1) if horiz else ink[t:t + win].mean(0)
        e1, e2 = _bands(strip, p0, inward, thr, reach, inner, thin)
        if e1 is not None:
            ts.append(t + win / 2)
            p1.append(e1)
            p2.append(np.nan if e2 is None else e2)
    n_all = max(1, len(range(int(lo), int(hi) - win, step)))
    if len(ts) < max(8, min_frac * n_all):
        return None
    ts_a, p1_a, p2_a = np.array(ts), np.array(p1), np.array(p2)
    has2 = ~np.isnan(p2_a)
    if has2.sum() >= 0.5 * len(ts_a):
        t2, q2 = _clean(ts_a[has2], p2_a[has2])
        if len(t2) >= 0.5 * len(ts_a):
            return {"t": [round(float(v), 1) for v in t2], "p": [round(float(v), 1) for v in q2]}
    t1, q1 = _clean(ts_a, p1_a)
    if len(t1) < max(8, min_frac * n_all):
        return None
    return {"t": [round(float(v), 1) for v in t1], "p": [round(float(v), 1) for v in q1]}


def trace_hline(lines: np.ndarray, y: float, lo: float, hi: float, *, step: int = 24, win: int = 24,
                thr: float = 0.3, reach: int = 30, thick: int = 14, min_frac: float = 0.4) -> dict | None:
    """框里一条横贯的分栏线（人标 splits 处，大约在 y）沿 x 逐段量中线，连成折线。`lines` 是横线图（0/1，
    虚线、淡线已接上）。分栏线常和框不平行、断断续续（Sheldon 10-28 p12：二三栏间的破横线是斜的）。
    量到的段不到 min_frac，或量出的高低差超过 reach（量到了两条不同的东西）返回 None。"""
    ts, ps = [], []
    y0 = max(0, int(y) - reach)
    for t in range(int(lo), int(hi) - win, step):
        prof = lines[y0:int(y) + reach + 1, t:t + win].mean(1)
        on = np.flatnonzero(prof >= thr)
        if not len(on):
            continue
        runs = np.split(on, np.flatnonzero(np.diff(on) > 1) + 1)
        runs = [r for r in runs if len(r) <= thick]          # 粗墨团（字）不算
        if runs:
            r = min(runs, key=lambda r: abs(y0 + r.mean() - y))
            ts.append(t + win / 2)
            ps.append(y0 + float(r.mean()))
    n_all = max(1, len(range(int(lo), int(hi) - win, step)))
    if len(ts) < max(8, min_frac * n_all):
        return None
    t1, q1 = _clean(np.array(ts), np.array(ps))
    if len(t1) < max(8, min_frac * n_all) or q1.max() - q1.min() > reach:
        return None
    return {"t": [round(float(v), 1) for v in t1], "p": [round(float(v), 1) for v in q1]}


def curve_at(c: dict, t):
    """折线在 t 处的值；两端外面按端头一段的斜率外推。"""
    ts, ps = np.asarray(c["t"], float), np.asarray(c["p"], float)
    t = np.asarray(t, float)
    v = np.interp(t, ts, ps)
    if len(ts) >= 2:
        k = min(5, len(ts) - 1)
        s0 = (ps[k] - ps[0]) / max(1e-6, ts[k] - ts[0])
        s1 = (ps[-1] - ps[-1 - k]) / max(1e-6, ts[-1] - ts[-1 - k])
        v = np.where(t < ts[0], ps[0] + s0 * (t - ts[0]), v)
        v = np.where(t > ts[-1], ps[-1] + s1 * (t - ts[-1]), v)
    return v


def fit_frame_curves(ink: np.ndarray, frame, found: dict[str, bool], **kw) -> dict[str, dict] | None:
    """四边的折线（top/bottom 是 y(x)，left/right 是 x(y)）。没找到或量不出的边取对边形状平移到兜底位置；
    对边也没有就是直线。返回 None = 四边都量不出，不拉。"""
    t, b, l, r = frame.top, frame.bottom, frame.left, frame.right
    ext = {"top": (t, l, r), "bottom": (b, l, r), "left": (l, t, b), "right": (r, t, b)}
    cur: dict[str, dict | None] = {}
    for s in SIDES:
        pos, lo, hi = ext[s]
        m = 0.03 * (hi - lo)
        cur[s] = trace_side(ink, s, pos, lo + m, hi - m, **kw) if found.get(s) else None
    if all(cur[s] is None for s in SIDES):
        return None
    opp = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
    out = {}
    for s in SIDES:
        c = cur[s]
        if c is None:
            pos, lo, hi = ext[s]
            o = cur[opp[s]]
            if o is None:
                c = {"t": [lo, hi], "p": [pos, pos]}
            else:             # 对边形状平移：边中点落在兜底位置
                d = pos - float(curve_at(o, (lo + hi) / 2))
                c = {"t": list(o["t"]), "p": [v + d for v in o["p"]]}
        out[s] = c
    return out


def _corner(hcurve: dict, vcurve: dict, x0: float, y0: float) -> tuple[float, float]:
    x, y = x0, y0
    for _ in range(20):            # 交点：x = side(y)，y = hcurve(x)，不动点迭代（边近乎垂直，收敛很快）
        y = float(curve_at(hcurve, x))
        x = float(curve_at(vcurve, y))
    return x, y


def make_warp(curves: dict[str, dict], frame, size: tuple[int, int], mids: list[dict] | None = None) -> dict:
    """拉正参数：四条折线、四个角、目标矩形（原框四边的平均位置）、图大小。可 JSON 存。
    `mids`：框里横贯的分栏线（y(x) 折线，自上而下），拉正后各自拉成水平线（放在它的平均高度），
    框分成几段，每段各做一片 Coons。"""
    tl = _corner(curves["top"], curves["left"], frame.left, frame.top)
    tr = _corner(curves["top"], curves["right"], frame.right, frame.top)
    bl = _corner(curves["bottom"], curves["left"], frame.left, frame.bottom)
    br = _corner(curves["bottom"], curves["right"], frame.right, frame.bottom)
    rect = ((tl[0] + bl[0]) / 2, (tl[1] + tr[1]) / 2, (tr[0] + br[0]) / 2, (bl[1] + br[1]) / 2)
    w = {"size": [int(size[0]), int(size[1])], "rect": [round(v, 2) for v in rect],
         "corners": [[round(v, 2) for v in c] for c in (tl, tr, bl, br)],
         "curves": {s: curves[s] for s in SIDES}}
    if mids:
        rows = []
        for c in sorted(mids, key=lambda c: float(np.mean(c["p"]))):
            a = _corner(c, curves["left"], frame.left, float(np.mean(c["p"])))
            b = _corner(c, curves["right"], frame.right, float(np.mean(c["p"])))
            yy = float(np.mean(curve_at(c, np.linspace(a[0], b[0], 50))))
            if rect[1] + 20 < yy < rect[3] - 20:
                rows.append({"curve": c, "y": round(yy, 2), "corners": [[round(v, 2) for v in a], [round(v, 2) for v in b]]})
        if rows:
            w["mids"] = rows
    return w


def _coons(top: dict, bottom: dict, left: dict, right: dict, tl, tr, bl, br, u, v):
    """一片 Coons 曲面片：(u, v) ∈ [0,1]² → 原图 (x, y)。四条边的参数取端点间线性。"""
    (tlx, tly), (trx, try_), (blx, bly), (brx, bry) = tl, tr, bl, br
    txs, bxs = tlx + u * (trx - tlx), blx + u * (brx - blx)
    lys, rys = tly + v * (bly - tly), try_ + v * (bry - try_)
    Ty, By = curve_at(top, txs), curve_at(bottom, bxs)
    Lx, Rx = curve_at(left, lys), curve_at(right, rys)
    Sx = ((1 - v) * txs + v * bxs + (1 - u) * Lx + u * Rx
          - ((1 - u) * (1 - v) * tlx + u * (1 - v) * trx + (1 - u) * v * blx + u * v * brx))
    Sy = ((1 - v) * Ty + v * By + (1 - u) * lys + u * rys
          - ((1 - u) * (1 - v) * tly + u * (1 - v) * try_ + (1 - u) * v * bly + u * v * bry))
    return Sx, Sy


def warp_maps(warp: dict) -> tuple[np.ndarray, np.ndarray]:
    """拉正后每个像素在原图上的位置（cv2.remap 用的 map_x、map_y，float32）。"""
    W, H = warp["size"]
    X0, Y0, X1, Y1 = warp["rect"]
    cv = warp["curves"]
    tl, tr, bl, br = warp["corners"]
    X = np.arange(W, dtype=np.float64)[None, :]
    Y = np.arange(H, dtype=np.float64)[:, None]
    u = np.clip((X - X0) / (X1 - X0), 0, 1)
    # 横向分段：框上沿、各分栏线、框下沿；每段一片 Coons
    hs = [(cv["top"], Y0, tl, tr)] + [(m["curve"], m["y"], *m["corners"]) for m in warp.get("mids", [])] \
        + [(cv["bottom"], Y1, bl, br)]
    Sx = np.zeros((H, W))
    Sy = np.zeros((H, W))
    for i in range(len(hs) - 1):
        (ct, ya, a1, a2), (cb, yb, b1, b2) = hs[i], hs[i + 1]
        lo = 0 if i == 0 else int(np.ceil(ya))
        hi = H if i == len(hs) - 2 else int(np.ceil(yb))
        if hi <= lo:
            continue
        v = np.clip((Y[lo:hi] - ya) / (yb - ya), 0, 1)
        Sx[lo:hi], Sy[lo:hi] = _coons(ct, cb, cv["left"], cv["right"], a1, a2, b1, b2, u, v)
    # 框外：跟最近的框边平移
    Sx = Sx + (X - (X0 + u * (X1 - X0)))
    Sy = Sy + (Y - np.clip(Y, Y0, Y1))
    return Sx.astype(np.float32), Sy.astype(np.float32)


def rectify_gray(gray: np.ndarray, warp: dict | None) -> np.ndarray:
    """按 warp 拉正一张图（灰度或彩色）；warp 为 None 原样返回。"""
    if warp is None:
        return gray
    mx, my = warp_maps(warp)
    return cv2.remap(gray, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
