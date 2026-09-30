"""`context` 通道（及 `ref_ctx`）的放行护栏（overview#274 D 道，2026-09-30）。

vol03 最终包上穷举出 94 格「已放行但错」，其中 78 格走 `context`。两类共性：

1. **整页错位**：切分/切线整段错位的页（vol03 的 49、107、110），列里的图块
   跟字位号对不上，上下文 n-gram 和整理本对齐都是在**错的图**上得出的一致——
   这类页一格 context 都不该放行。名单没有现成信号可读（仓里没有「整页错位」
   的产物），做成书级配置 `context_guard_pages`（yaml 顶层，缺省空 = 行为不变）。
2. **列首第 1–2 格是非字**：列首常压着界行残段、抬头框、印章边、纸缘，上下文
   给的字是凭空补的，图上根本没有字。要求列首两格有「像字」的证据才放行：
   库匹配 verdict 是 same/unsure，**或**图块的墨形合理（见 `patch_looks_like_char`）。

判据只依赖图块像素，不看任何书的活数据；阈值在 `tests/test_context_guard.py`
的合成数据上定（正例：笔画交织的字形；反例：空白 / 细长界行 / 满黑块 / 散点噪声）。
"""
from __future__ import annotations

import cv2
import numpy as np

#: 列首要查的格数（按读序前 N 格）
HEAD_CELLS = 2
#: 墨占比合理区间：低于下限是空白/只剩碎点，高于上限是黑块/印章。
INK_MIN, INK_MAX = 0.04, 0.60
#: 墨的连通块（面积 ≥ MIN_COMP_AREA_FRAC 才算）数上限：字最多十几块；散点噪声几十上百块。
MAX_COMPONENTS = 14
MIN_COMP_AREA_FRAC = 0.0005
#: 墨外接框短边 / 图块短边 至少这么大——界行残段、横竖线是又细又长的一条。
MIN_EXTENT_FRAC = 0.30


def page_guarded(page: int, guard_pages) -> bool:
    return bool(guard_pages) and int(page) in {int(p) for p in guard_pages}


def patch_looks_like_char(img: np.ndarray | None) -> bool:
    """灰度图块（深墨浅底）的墨形像不像一个字。拿不到图 → False（没证据就不放行）。"""
    if img is None or img.ndim != 2 or img.size == 0:
        return False
    h, w = img.shape
    if min(h, w) < 4:
        return False
    _t, ink = cv2.threshold(img, 0, 1, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # 全平的图（纯白/纯黑）Otsu 不可信：直接用极差判
    if int(img.max()) - int(img.min()) < 32:
        return False
    ratio = float(ink.mean())
    if not (INK_MIN <= ratio <= INK_MAX):
        return False
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    min_area = max(2, int(MIN_COMP_AREA_FRAC * h * w))
    comps = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= min_area]
    if not (1 <= len(comps) <= MAX_COMPONENTS):
        return False
    x0 = min(s[cv2.CC_STAT_LEFT] for s in comps)
    y0 = min(s[cv2.CC_STAT_TOP] for s in comps)
    x1 = max(s[cv2.CC_STAT_LEFT] + s[cv2.CC_STAT_WIDTH] for s in comps)
    y1 = max(s[cv2.CC_STAT_TOP] + s[cv2.CC_STAT_HEIGHT] for s in comps)
    return min(x1 - x0, y1 - y0) >= MIN_EXTENT_FRAC * min(h, w)


def head_cell_ok(verdict: str | None, img: np.ndarray | None) -> bool:
    """列首格能不能让 context 放行：库匹配有信号（same/unsure）或墨形像字。"""
    return verdict in ("same", "unsure") or patch_looks_like_char(img)
