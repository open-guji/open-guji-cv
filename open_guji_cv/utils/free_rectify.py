"""自由版式：按版框把页面拉正（Sheldon 10-28：「整卷有拉伸，先匹配边框，进行修复」）。

yxat 的扫描图有倾斜、透视（射影）变形，框线也不全直：列是斜的，竖直切线就穿字。
做法：沿框线四边逐段量**墨带内沿**的位置，各拟一条二次曲线（弯框也跟得上），四条边围成的区域用
Coons 曲面片映成正矩形；矩形放在原框的平均位置，所以拉正后坐标与原图只差几到几十 px，
人标的 splits／box（原图像素）照样能吸附。框外的部分跟着最近的框边平移（不外推曲线）。

没找到的边（多是书脊一侧，那边是纸边、没框线）取对边的形状平移到兜底位置。
`warp` 记在 `layout_blocks` 里，Step2／3 用 `rectify_gray` 得到同一张拉正后的图。
"""

from __future__ import annotations

import cv2
import numpy as np

SIDES = ("top", "bottom", "left", "right")


def _inner_edge(prof: np.ndarray, at: int, inward: int, thr: float, reach: int) -> float | None:
    """一维墨投影 prof 上，at 附近（±reach）最近的墨带的内沿（inward=+1 往下标增大方向是框里）。"""
    n = len(prof)
    best = None
    for d in range(reach + 1):
        for k in (at - d, at + d):
            if 0 <= k < n and prof[k] >= thr:
                best = k
                break
        if best is not None:
            break
    if best is None:
        return None
    k = best
    while 0 <= k + inward < n and prof[k + inward] >= thr:
        k += inward
    return float(k + inward)


def trace_side(ink: np.ndarray, side: str, pos: float, lo: float, hi: float, *, step: int = 24,
               win: int = 24, thr: float = 0.5, reach: int = 30, deg: int = 2) -> np.ndarray | None:
    """沿一条框边（大约在 pos，沿边方向覆盖 [lo, hi)）逐段量墨带内沿，鲁棒拟 deg 次多项式。

    横边返回 y(x) 的系数，竖边返回 x(y) 的系数（np.polyval 用）。点太少或拟不齐返回 None。"""
    H, W = ink.shape
    horiz = side in ("top", "bottom")
    inward = 1 if side in ("top", "left") else -1
    ts, ps = [], []
    p0 = int(round(pos))
    for t in range(int(lo), int(hi) - win, step):
        if horiz:
            strip = ink[:, t:t + win].mean(1)
        else:
            strip = ink[t:t + win].mean(0)
        e = _inner_edge(strip, p0, inward, thr, reach)
        if e is not None:
            ts.append(t + win / 2)
            ps.append(e)
    if len(ts) < 8:
        return None
    ts_a, ps_a = np.array(ts), np.array(ps)
    keep = np.ones(len(ts_a), bool)
    for _ in range(4):             # 贴框的字把某几段墨带拉长：拟合、丢离得远的、再拟
        c = np.polyfit(ts_a[keep], ps_a[keep], deg)
        r = np.abs(np.polyval(c, ts_a) - ps_a)
        tol = max(3.0, 3 * float(np.median(r[keep])))
        nk = r <= tol
        if nk.sum() < 8 or (nk == keep).all():
            break
        keep = nk
    if keep.sum() < 0.5 * len(ts_a):
        return None
    return np.polyfit(ts_a[keep], ps_a[keep], deg)


def fit_frame_curves(ink: np.ndarray, frame, found: dict[str, bool], **kw) -> dict[str, np.ndarray] | None:
    """四边的曲线（top/bottom 是 y(x)，left/right 是 x(y)）。没找到或拟不出的边取对边形状平移到兜底位置；
    对边也没有就是直线。返回 None = 两对边都拟不出，不拉。"""
    t, b, l, r = frame.top, frame.bottom, frame.left, frame.right
    ext = {"top": (t, l, r), "bottom": (b, l, r), "left": (l, t, b), "right": (r, t, b)}
    cur: dict[str, np.ndarray | None] = {}
    for s in SIDES:
        pos, lo, hi = ext[s]
        m = 0.05 * (hi - lo)
        cur[s] = trace_side(ink, s, pos, lo + m, hi - m, **kw) if found.get(s) else None
    opp = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
    out = {}
    for s in SIDES:
        c = cur[s]
        if c is None:
            pos, lo, hi = ext[s]
            o = cur[opp[s]]
            if o is None:
                c = np.array([0.0] * 2 + [pos])
            else:             # 对边形状平移：边中点落在兜底位置
                c = o.copy()
                c[-1] += pos - np.polyval(o, (lo + hi) / 2)
        out[s] = np.asarray(c, float)
    if all(cur[s] is None for s in SIDES):
        return None
    return out


def _corner(top_or_bottom: np.ndarray, left_or_right: np.ndarray, x0: float, y0: float) -> tuple[float, float]:
    x, y = x0, y0
    for _ in range(20):            # 交点：x = side(y)，y = hcurve(x)，不动点迭代（边近乎垂直，收敛很快）
        y = float(np.polyval(top_or_bottom, x))
        x = float(np.polyval(left_or_right, y))
    return x, y


def make_warp(curves: dict[str, np.ndarray], frame, size: tuple[int, int]) -> dict:
    """拉正参数：四条曲线、四个角、目标矩形（原框四边的平均位置）、图大小。可 JSON 存。"""
    tl = _corner(curves["top"], curves["left"], frame.left, frame.top)
    tr = _corner(curves["top"], curves["right"], frame.right, frame.top)
    bl = _corner(curves["bottom"], curves["left"], frame.left, frame.bottom)
    br = _corner(curves["bottom"], curves["right"], frame.right, frame.bottom)
    rect = ((tl[0] + bl[0]) / 2, (tl[1] + tr[1]) / 2, (tr[0] + br[0]) / 2, (bl[1] + br[1]) / 2)
    return {"size": [int(size[0]), int(size[1])], "rect": [round(v, 2) for v in rect],
            "corners": [[round(v, 2) for v in c] for c in (tl, tr, bl, br)],
            "curves": {s: [float(v) for v in curves[s]] for s in SIDES}}


def warp_maps(warp: dict) -> tuple[np.ndarray, np.ndarray]:
    """拉正后每个像素在原图上的位置（cv2.remap 用的 map_x、map_y，float32）。"""
    W, H = warp["size"]
    X0, Y0, X1, Y1 = warp["rect"]
    cv = {s: np.array(c) for s, c in warp["curves"].items()}
    (tlx, tly), (trx, try_), (blx, bly), (brx, bry) = warp["corners"]
    X = np.arange(W, dtype=np.float64)[None, :]
    Y = np.arange(H, dtype=np.float64)[:, None]
    u = np.clip((X - X0) / (X1 - X0), 0, 1)
    v = np.clip((Y - Y0) / (Y1 - Y0), 0, 1)
    # 四条边的参数取端点间线性：上边 x 从 tl 到 tr，左边 y 从 tl 到 bl
    txs, bxs = tlx + u * (trx - tlx), blx + u * (brx - blx)
    lys, rys = tly + v * (bly - tly), try_ + v * (bry - try_)
    Ty, By = np.polyval(cv["top"], txs), np.polyval(cv["bottom"], bxs)
    Lx, Rx = np.polyval(cv["left"], lys), np.polyval(cv["right"], rys)
    # Coons 曲面片：两向线性插值相加，减去四角的双线性
    Sx = ((1 - v) * txs + v * bxs + (1 - u) * Lx + u * Rx
          - ((1 - u) * (1 - v) * tlx + u * (1 - v) * trx + (1 - u) * v * blx + u * v * brx))
    Sy = ((1 - v) * Ty + v * By + (1 - u) * lys + u * rys
          - ((1 - u) * (1 - v) * tly + u * (1 - v) * try_ + (1 - u) * v * bly + u * v * bry))
    # 框外：跟最近的框边平移
    Sx = Sx + (X - (X0 + u * (X1 - X0)))
    Sy = Sy + (Y - (Y0 + v * (Y1 - Y0)))
    return Sx.astype(np.float32), Sy.astype(np.float32)


def rectify_gray(gray: np.ndarray, warp: dict | None) -> np.ndarray:
    """按 warp 拉正一张图（灰度或彩色）；warp 为 None 原样返回。"""
    if warp is None:
        return gray
    mx, my = warp_maps(warp)
    return cv2.remap(gray, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
