"""等距格网：刻本一列 n 格等高，格线 = 格高 P + 一个相位。

殿本（四库总目）正文几乎每列都是严格 21 格、格高相近，空白也占格、照样等距排（用户 2026-10-21）。
实测 vol05/vol09 已切对的列：字心离「本列等距格网」的偏差中位 3%、九成在 9% 格高以内；同一页各列
格高一致（差 1% 上下），但各列列图的上下起点不齐（Step2 逐列矫正，起点差到半格），所以相位要逐列定。

做法（不靠 DP、不靠字缝）：
- 本列行墨投影去均值后，在频率 1/P 上取傅里叶分量。字心排成 c + kP，这个分量的相位就是 c（模 P），
  全列 21 个字一起投票，单个字的墨重偏上偏下、个别格被印章或墨污盖住都只是噪声。
- P 取整页各列分量模长之和最大的那个（在页级 period 附近搜），同一页共用。
- 整数格的歧义（c 只定到模 P）按版框定：正文中间那格（21 格的第 11 格）的字心落在版框上下沿的中点附近。
  中点到字心的偏移各页基本一样（上留白比下留白小，约 -0.1 格），取整页各列的一致值，再让每列在它
  ±半格以内取自己的相位。

这里只定格号（第几格在哪一段）。格线的确切位置由 `row_boundaries.snap_to_gaps` 在 ±0.2 格内就近挪进
字缝——刻本字常伸出名义格，直线格网会擦掉字头字脚（殿本 vol05/vol09 实测：不挪时多出几百条穿字格线，
挪了反比 DP 少）。

调用方：`steps/row_segment.py`（逐列格位先验的候选格网之一，见那里的打分）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: 页级格高 P 的搜索范围（× 页级 period）与步长（px）
PITCH_LO, PITCH_HI, PITCH_STEP = 0.97, 1.04, 0.1
#: 投影只取内容窗口中间这一段的列宽（避开界行残墨）
CORE_W = 0.7


@dataclass
class ColumnGrid:
    center: float         # 正文中间那格（n_body 格的正中）字心的列图 y
    pitch: float
    dev: float            # 本列相位偏离整页一致值多少格（|dev| 接近 0.5 = 整数格有歧义）

    def bounds(self, n_body: int, n_raised: int) -> list[float]:
        """抬头 n_raised 格 + 正文 n_body 格的 n_raised+n_body+1 条格线（自上而下）。"""
        top = self.center - (n_body / 2.0 + n_raised) * self.pitch
        return [top + i * self.pitch for i in range(n_body + n_raised + 1)]


def _profile(col_gray: np.ndarray, x_lo: int, x_hi: int, lo: int, hi: int, ink_threshold: int) -> np.ndarray:
    w = x_hi - x_lo
    a, b = x_lo + int(w * (1 - CORE_W) / 2), x_hi - int(w * (1 - CORE_W) / 2)
    p = (col_gray[:, a:b] < ink_threshold).mean(axis=1).astype(np.float64)
    q = np.zeros_like(p)
    lo, hi = max(0, lo), min(len(p), hi)
    if hi > lo:
        q[lo:hi] = p[lo:hi] - p[lo:hi].mean()
    return q


def _component(q: np.ndarray, pitch: float, ref: float) -> complex:
    y = np.arange(len(q), dtype=np.float64)
    return complex((q * np.exp(-2j * np.pi * (y - ref) / pitch)).sum())


def fit_page_grids(columns: list[dict], period: float, ink_threshold: int = 128) -> dict[int, ColumnGrid]:
    """一页各列的等距格网。

    `columns` 每项：`col`、`img`（列图灰度）、`content_x`、`border_top`、`border_bottom`、
    `n_raised`（投影要不要往版框上方多取几格）。返回 `{col: ColumnGrid}`；列太少（<1）返回空表。"""
    if not columns:
        return {}
    qs, mids = {}, {}
    for c in columns:
        x_lo, x_hi = int(round(c["content_x"][0])), int(round(c["content_x"][1]))
        lo = int(c["border_top"] - c["n_raised"] * period)
        qs[c["col"]] = _profile(c["img"], x_lo, x_hi, lo, int(c["border_bottom"]), ink_threshold)
        mids[c["col"]] = (c["border_top"] + c["border_bottom"]) / 2.0
    pitches = np.arange(period * PITCH_LO, period * PITCH_HI, PITCH_STEP)
    pitch = float(pitches[int(np.argmax([sum(abs(_component(qs[k], P, mids[k])) for k in qs)
                                         for P in pitches]))])
    comp = {k: _component(qs[k], pitch, mids[k]) for k in qs}
    # 字心格点相对版框中点的偏移（模 P，落在 ±P/2）；整页按分量模长加权取圆周平均
    off = {k: float((-np.angle(z) / (2 * np.pi) * pitch + pitch / 2) % pitch - pitch / 2) for k, z in comp.items()}
    page = sum(abs(comp[k]) * np.exp(2j * np.pi * off[k] / pitch) for k in comp)
    page_off = float(np.angle(page) / (2 * np.pi) * pitch)
    out: dict[int, ColumnGrid] = {}
    for c in columns:
        k = c["col"]
        dev = float((off[k] - page_off + pitch / 2) % pitch - pitch / 2)
        out[k] = ColumnGrid(center=mids[k] + page_off + dev, pitch=pitch, dev=dev / pitch)
    return out
