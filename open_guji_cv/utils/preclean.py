"""Step0 预清理：把扫描件上的污渍从原图里修掉，喂给 Step1 之前。

**这一步默认不开**，只对手工登记过的页生效——在 books/<book>.yaml 里写 `preclean:`。
不改磁盘上的原图（原图是唯一真相，永远保持原样），只在 `RunContext.raw_page`
返回前对内存里的那份做处理。

目前只有一种污渍：`inverted_band`
--------------------------------
vol02 p151 正文上部横着一条粗带，带内**黑白是反的**——纸成了黑、字成了白。
这不是墨污，是扫描/二值化在这一带翻了极性，所以修法就是把带内的点整体反回来，
字迹能一笔不少地还原（不像抹黑条那样会连笔画一起抹掉）。

怎么找这条带
-----------
带的边界是一个**多段梯形**：上沿从左到右一级级抬高（648 → 645 → 641 → 615 → 608 → 600），
下沿基本平（693，最左一段 723），中间还断开一处（x 663-724 无带）。
所以不能用一对固定的 y，得逐列量出上下沿。

量的办法是找**列间纸列**：上下文都无墨、本该全白的那些列。带内它们是黑的，
且黑得干净（没有笔画混进来），一量一个准。量到的点做中值滤波去掉个别异常，
再线性内插到整段宽度，就得到多边形。

判据（在原图 2307×3049 上量的）
  - 反色前带内墨占比 0.806（纸被翻成黑）；
  - 反色后 0.194，正文正常水平是 0.152 —— 对上了；
  - 反色后逐字核对整理本「真卿所見者四卷全本…傳寫者諱其殘缺因於書名增入卦爻二字」，
    所見 / 者 / 缺因 都对得上，笔画完整。
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter


def _trace_band(b: np.ndarray, y_lo: int, y_hi: int, y_probe: int,
                ctx: int, smooth: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用列间纸列量出带的上下沿。返回 (量到的 x, 上沿, 下沿)。

    列间纸列 = 带上方 ctx 行与带下方 ctx 行都无墨的列。带内这些列是纯黑的一段，
    取包含 y_probe 的那段连续黑，就是带在该列的上下沿。
    """
    above = b[y_lo - ctx:y_lo].any(axis=0)
    below = b[y_hi:y_hi + ctx].any(axis=0)
    paper = ~above & ~below

    w = b.shape[1]
    top = np.full(w, -1, int)
    bot = np.full(w, -1, int)
    for x in np.flatnonzero(paper):
        col = b[y_lo:y_hi, x].astype(np.uint8)
        idx = np.flatnonzero(np.diff(np.r_[0, col, 0]))
        for a, c in zip(idx[::2], idx[1::2]):
            if y_lo + a <= y_probe <= y_lo + c - 1:
                top[x] = y_lo + a
                bot[x] = y_lo + c - 1
                break
    xs = np.flatnonzero(top >= 0)
    if xs.size == 0:
        raise ValueError("没量到带：检查 y_lo/y_hi/y_probe 是否框住了污渍带")
    t = median_filter(top[xs].astype(float), size=smooth, mode="nearest")
    bo = median_filter(bot[xs].astype(float), size=smooth, mode="nearest")
    return xs, t, bo


def invert_band(gray: np.ndarray, *, segments: list[list[int]],
                y_lo: int, y_hi: int, y_probe: int,
                ink_threshold: int = 128, ctx: int = 170,
                smooth: int = 31) -> np.ndarray:
    """把多段梯形围出的区域整体黑白反转，返回新图；入参不改。

    segments  横向分段 [[x0, x1], ...]，闭区间；带中间断开的地方要分开写。
    y_lo/y_hi 搜索窗（带一定落在窗内），y_probe 窗内一定在带里的一行。
    ctx       量列间纸列时，往带上下各看多少行。
    """
    b = gray < ink_threshold
    xs, t, bo = _trace_band(b, y_lo, y_hi, y_probe, ctx, smooth)

    mask = np.zeros(gray.shape, bool)
    for x0, x1 in segments:
        gx = np.arange(x0, x1 + 1)
        tt = np.round(np.interp(gx, xs, t)).astype(int)
        bb = np.round(np.interp(gx, xs, bo)).astype(int)
        for x, a, c in zip(gx, tt, bb):
            mask[a:c + 1, x] = True

    out = gray.copy()
    out[mask] = 255 - gray[mask]
    return out


_OPS = {"inverted_band": invert_band}


def apply_preclean(gray: np.ndarray, rules: list[dict]) -> tuple[np.ndarray, list[str]]:
    """按 book.yaml 里登记的规则依次处理一页。返回 (新图, 每条规则的说明)。"""
    notes: list[str] = []
    out = gray
    for r in rules:
        kind = r.get("kind", "inverted_band")
        fn = _OPS.get(kind)
        if fn is None:
            raise ValueError(f"未知的 preclean 类型: {kind}（可用: {sorted(_OPS)}）")
        kw = {k: v for k, v in r.items() if k not in ("kind", "page", "note")}
        th = kw.get("ink_threshold", 128)
        before = float((out < th).mean())
        out = fn(out, **kw)
        after = float((out < th).mean())
        notes.append(f"{kind}: 全页墨占比 {before:.3f} -> {after:.3f}")
    return out, notes
