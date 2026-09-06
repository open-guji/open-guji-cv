"""Step0 预清理：把扫描件上的污渍从原图里抹掉，喂给 Step1 之前。

**这一步默认不开**，只对手工登记过的页生效——在 books/<book>.yaml 里写 `preclean:`。
不改磁盘上的原图（原图是唯一真相，永远保持原样），只在 `RunContext.raw_page`
返回前对内存里的那份做处理。

目前只有一种污渍：`horizontal_bar`
--------------------------------
vol02 p151 正文上部压着一条横贯大半页的粗黑污渍条（原图 y≈648-693）。
肉眼像"黑白反色"（字成了白色），但实测不是反色，是**一条实心黑条压在纸上**，
被它盖住的笔画在二值图里已经没了，白色只是没被墨盖满的缝隙。

判据（在原分辨率上量的）：
  - 在纯纸列（上下文都无墨的列）上，条内墨占比 0.58-0.69，条外 0.24；
  - 若真是整块反色，把它反过来后墨占比应回到正文水平（约 0.25），实测是 0.4+，
    且条上下沿的笔画接不上 —— 排除反色。

抹法：条内逐行扫水平黑游程，
  - 短游程（< min_run）判为真笔画，原样留下；
  - 长游程判为污渍，再逐列看有没有竖笔穿过条（条上下各 ctx 行都有墨）：
    有就留（真笔画穿过污渍），没有就抹白；
  - 「穿条」的连通块若宽过 max_stroke_w，仍判污渍 —— 真竖笔不会那么宽。

**能救回什么、救不回什么**：污渍薄处笔画能整个留下；最浓处笔画已被完全吞掉，
二值图里没有信息可还原，抹完那里是一片白，字要靠上下文/整理本定。
这一步的目的是**让切分和识别不被那条黑杠带偏**，不是把字变回来。
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def _bar_extent(b: np.ndarray, y0: int, y1: int, min_thick: int) -> tuple[np.ndarray, np.ndarray]:
    """在 y0..y1 搜索窗内，逐列定位污渍条的上下沿。

    条不是水平的（vol02 p151 从左到右抬了约 40px），所以不能用一对固定的 y。
    逐列取窗内最长的连续黑段当条；太薄（< min_thick）的当没有条。
    再用中值滤波把被笔画带偏的列拉回来 —— 条是连续的，相邻列不会突然跳。
    """
    w = b.shape[1]
    top = np.full(w, -1, int)
    bot = np.full(w, -1, int)
    for x in range(w):
        col = b[y0:y1 + 1, x].astype(np.uint8)
        idx = np.flatnonzero(np.diff(np.r_[0, col, 0]))
        s, e = idx[::2], idx[1::2]
        if len(s) == 0:
            continue
        k = int(np.argmax(e - s))
        if e[k] - s[k] >= min_thick:
            top[x] = y0 + s[k]
            bot[x] = y0 + e[k] - 1
    seen = top >= 0
    if seen.any():                       # 有条的列上做中值平滑，抹掉笔画造成的跳变
        xs = np.flatnonzero(seen)
        top[xs] = ndimage.median_filter(top[xs], size=51, mode="nearest")
        bot[xs] = ndimage.median_filter(bot[xs], size=51, mode="nearest")
    return top, bot


def remove_horizontal_bar(gray: np.ndarray, y0: int, y1: int, *,
                          ink_threshold: int = 128, min_run: int = 42,
                          max_stroke_w: int = 36, ctx: int = 8,
                          min_thick: int = 20) -> np.ndarray:
    """抹掉 y0..y1 搜索窗里的横条污渍，返回新图；入参不改。

    y0/y1 给的是**搜索窗**不是条本身 —— 条在窗内逐列自动定位（它是斜的）。
    其余参数都在该图自己的像素尺度上说，换分辨率要跟着缩放
    （min_run / max_stroke_w / min_thick 大致按宽度比例走）。
    """
    b = gray < ink_threshold
    fixed = b.copy()
    h = b.shape[0]
    top, bot = _bar_extent(b, y0, y1, min_thick)

    for y in range(max(0, y0), min(h, y1 + 1)):
        row = b[y].astype(np.uint8)
        idx = np.flatnonzero(np.diff(np.r_[0, row, 0]))
        for a, c in zip(idx[::2], idx[1::2]):
            if c - a < min_run:
                continue                      # 短游程 = 真笔画
            # 只处理确实落在条内的那部分列
            in_bar = (top[a:c] >= 0) & (y >= top[a:c]) & (y <= bot[a:c])
            if not in_bar.any():
                continue
            # 竖笔判据：以各列自己的条上下沿为界往外看
            up = np.zeros(c - a, bool)
            dn = np.zeros(c - a, bool)
            for j, x in enumerate(range(a, c)):
                if top[x] < 0:
                    continue
                u0, u1 = max(0, top[x] - ctx - 1), max(0, top[x] - 1)
                d0, d1 = min(h, bot[x] + 2), min(h, bot[x] + ctx + 2)
                up[j] = b[u0:u1, x].any()
                dn[j] = b[d0:d1, x].any()
            through = up & dn
            lab, n = ndimage.label(through)
            for k in range(1, n + 1):
                xs = np.flatnonzero(lab == k)
                if len(xs) > max_stroke_w:
                    through[xs] = False       # 太宽，不是竖笔
            keep = through | ~in_bar          # 条外的墨一律不动
            fixed[y, a:c] = keep

    out = gray.copy()
    out[b & ~fixed] = 255                     # 判为污渍的墨 → 纸
    return out


_OPS = {"horizontal_bar": remove_horizontal_bar}


def apply_preclean(gray: np.ndarray, rules: list[dict]) -> tuple[np.ndarray, list[str]]:
    """按 book.yaml 里登记的规则依次处理一页。返回 (新图, 每条规则的说明)。"""
    notes: list[str] = []
    out = gray
    for r in rules:
        kind = r.get("kind", "horizontal_bar")
        fn = _OPS.get(kind)
        if fn is None:
            raise ValueError(f"未知的 preclean 类型: {kind}（可用: {sorted(_OPS)}）")
        kw = {k: v for k, v in r.items() if k not in ("kind", "page", "note")}
        before = (out < kw.get("ink_threshold", 128)).sum()
        out = fn(out, **kw)
        after = (out < kw.get("ink_threshold", 128)).sum()
        notes.append(f"{kind} y{kw.get('y0')}-{kw.get('y1')}: 抹墨 {before - after} px")
    return out, notes
