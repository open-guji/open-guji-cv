"""IDS 路的切分（M7 块 C3，GUJI-563）：把 ⿳ 上中下结构的字块切成三段。

- **分界是折线，不是直线**（用户 10-17）：`polylines_to_mask` 把两条折线（上/中、中/下，坐标 0–1 比例、
  左上原点）转成三类像素掩码：0＝上段、1＝中段、2＝下段。
- `straight_baseline` 是直线基线（水平投影谷底），只用来和折线对照，不是成品。
- `pixel_accuracy` 在**墨迹像素**上比较两张掩码的归段准确率（背景像素不计）。
- `split_parts` 按掩码把字块拆成三张部件图（非本段像素置白），供后面的每段二选一判别器用。
- 只依赖 numpy；不被任何 Step 引用。分层 L2。
"""
from __future__ import annotations

import numpy as np


def _interp(pts, width: int) -> np.ndarray:
    """折线 `[[x,y],..]`（比例）→ 每列的 y（比例），两端水平延伸到图边缘。"""
    pts = sorted((float(x), float(y)) for x, y in pts)
    if not pts:
        raise ValueError("折线没有点")
    xs = (np.arange(width) + 0.5) / width
    px = [p[0] for p in pts]; py = [p[1] for p in pts]
    return np.interp(xs, px, py)          # np.interp 两端自动取端点值＝水平延伸


def polylines_to_mask(shape: tuple[int, int], upper_mid, mid_lower) -> np.ndarray:
    """`shape=(h,w)`；两条折线 → 三类掩码（0 上／1 中／2 下）。第二条线若在某列高于第一条，压到第一条上（不交叉）。"""
    h, w = shape
    y1 = _interp(upper_mid, w) * h
    y2 = np.maximum(_interp(mid_lower, w) * h, y1)
    rows = (np.arange(h) + 0.5)[:, None]
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[rows >= y1[None, :]] = 1
    mask[rows >= y2[None, :]] = 2
    return mask


def ink_of(gray: np.ndarray, thr: int = 128) -> np.ndarray:
    """灰度字块（深色墨、浅色底）→ 布尔墨迹图。"""
    return np.asarray(gray) < thr


def straight_baseline(ink: np.ndarray, smooth: int = 3) -> tuple[float, float]:
    """直线基线：在水平墨迹投影上，上/中界取 [0.15,0.5] 内、中/下界取 [0.5,0.85] 内投影最小的行（平滑后）。
    返回两个比例 `(y1, y2)`。"""
    h = ink.shape[0]
    prof = ink.sum(axis=1).astype(float)
    if smooth > 1:
        prof = np.convolve(prof, np.ones(smooth) / smooth, mode="same")

    def pick(lo: float, hi: float) -> float:
        a, b = int(lo * h), max(int(hi * h), int(lo * h) + 1)
        return (a + int(np.argmin(prof[a:b])) + 0.5) / h

    return pick(0.15, 0.5), pick(0.5, 0.85)


def pixel_accuracy(pred: np.ndarray, gold: np.ndarray, ink: np.ndarray) -> float:
    """墨迹像素上的归段准确率。没有墨迹返回 nan。"""
    if pred.shape != gold.shape or pred.shape != ink.shape:
        raise ValueError("形状不一致")
    n = int(ink.sum())
    return float((pred[ink] == gold[ink]).sum() / n) if n else float("nan")


def split_parts(gray: np.ndarray, mask: np.ndarray, fill: int = 255) -> list[np.ndarray]:
    """按掩码拆成三张同尺寸部件图（非本段像素置 `fill`＝白）。"""
    out = []
    for k in range(3):
        part = np.full_like(gray, fill)
        part[mask == k] = gray[mask == k]
        out.append(part)
    return out


def seam_polyline(ink: np.ndarray, y0: float, band: float = 0.12, lam: float = 0.6, pull: float = 4.0, step: int = 4):
    """折线切分（自动版）：在 `y0±band`（占图高比例）内，找一条从左到右穿过墨迹最少的缝。
    DP 逐列走，每步可上下 ±1 行；代价＝本格墨迹 + `lam`×|行变化| + `pull`×偏离 y0 的比例。
    返回归一化折线 `[[x,y],…]`，每 `step` 列取一点（两端各取一点）。"""
    h, w = ink.shape
    lo, hi = max(int((y0 - band) * h), 0), min(int((y0 + band) * h) + 1, h)
    cost = ink[lo:hi].astype(float)
    ys = np.arange(lo, hi)
    cost = cost + pull * np.abs(ys - y0 * h)[:, None] / h
    n = hi - lo
    acc = np.full((n, w), np.inf); back = np.zeros((n, w), dtype=np.int16)
    acc[:, 0] = cost[:, 0]
    for x in range(1, w):
        prev = acc[:, x - 1]
        cand = np.stack([np.r_[np.inf, prev[:-1]] + lam, prev, np.r_[prev[1:], np.inf] + lam])
        k = cand.argmin(axis=0)
        acc[:, x] = cand[k, np.arange(n)] + cost[:, x]
        back[:, x] = k - 1
    i = int(acc[:, -1].argmin()); path = [0] * w
    for x in range(w - 1, -1, -1):
        path[x] = i
        i = min(max(i + int(back[i, x]), 0), n - 1) if x else i
    # 回溯时 back 记的是"来自 i+back"，故上面按 i+back 回退
    xs = list(range(0, w, step)) + [w - 1]
    return [[(x + 0.5) / w, (lo + path[x] + 0.5) / h] for x in xs]


def vertical_seam(ink: np.ndarray, mid_mask: np.ndarray, band: float = 0.18, lam: float = 0.5, pull: float = 6.0, step: int = 4):
    """中段左右竖切（米｜右部）：在中段（`mid_mask`==1）里，从上到下找一条穿过墨迹最少的缝。
    先取中段墨迹外框，竖缝先验在框的 50% 处±`band`×框宽；DP 逐行走，每步左右 ±1 列；
    代价＝墨迹 + `lam`×|列变化| + `pull`×偏离先验（占图宽比例）。返回归一化折线 `[[x,y],…]`（自上而下），
    起止行取中段在缝所在列的上下边。中段没墨迹返回 None。"""
    h, w = ink.shape
    m = (mid_mask == 1) & ink
    if not m.any():
        return None
    ys, xs = np.where(m)
    bx0, bx1 = xs.min(), xs.max() + 1
    x0 = bx0 + 0.5 * (bx1 - bx0)
    lo, hi = max(int(x0 - band * (bx1 - bx0)), 0), min(int(x0 + band * (bx1 - bx0)) + 1, w)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    cost = np.where(mid_mask[y0:y1, lo:hi] == 1, ink[y0:y1, lo:hi].astype(float), 0.0)
    cost = cost + pull * np.abs(np.arange(lo, hi) - x0)[None, :] / w
    n, wd = cost.shape
    acc = np.full((n, wd), np.inf); back = np.zeros((n, wd), dtype=np.int16)
    acc[0] = cost[0]
    for r in range(1, n):
        prev = acc[r - 1]
        cand = np.stack([np.r_[np.inf, prev[:-1]] + lam, prev, np.r_[prev[1:], np.inf] + lam])
        k = cand.argmin(axis=0)
        acc[r] = cand[k, np.arange(wd)] + cost[r]
        back[r] = k - 1
    i = int(acc[-1].argmin()); path = [0] * n
    for r in range(n - 1, -1, -1):
        path[r] = i
        if r:
            i = min(max(i + int(back[r, i]), 0), wd - 1)
    rows = list(range(0, n, step)) + [n - 1]
    return [[(lo + path[r] + 0.5) / w, (y0 + r + 0.5) / h] for r in rows]
