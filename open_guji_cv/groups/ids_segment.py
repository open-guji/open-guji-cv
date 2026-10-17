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
