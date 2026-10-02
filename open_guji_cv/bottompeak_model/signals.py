# -*- coding: utf-8 -*-
"""下版框候选枚举与信号（线上线下共用的单一口径）。

候选 = 沿「救援之后现役线」的倾角，在搜索带 [lo, hi] 里投影曲线的全部局部极大点，外加现役线本身
（救援可能换过倾角，它不一定是这条曲线上的极大点）。每个候选的 `final` 是它走完
`finalize_bottom`（落到墨条下沿 + 固定余量）之后的最终线位——跟金标、现役输出同口径，可直接比。

坐标：旧坐标（左上角原点），`position` 是线在 x=w/2 处的 y，倾角 slope = dy/dx。
"""
from __future__ import annotations

import numpy as np

from ..utils.peak_line_search import (
    DEFAULT_ALPHA, DEFAULT_HYST, RESCUE_MARGIN, LineMatch, _descend_to_ink_bottom,
    finalize_bottom, half_height_score_at, local_maxima, sample_line_curve)

SIGNAL_VERSION = "1"

FEATURES: tuple[str, ...] = (
    "rel_rule",        # 候选峰位 − 现役线位（>0 在现役线下方）
    "rel_prior",       # (页高−候选终点) − 册基准间距；无先验记 0
    "has_prior",
    "h_norm",          # 峰高 / 带内最高峰
    "h_abs",           # 峰高 / 页宽
    "score_log",       # log1p(半高宽匹配分)
    "width",           # 半高宽
    "rank_score",      # 带内按分数排名（0=最高）
    "rank_height",
    "up_ink",          # 峰上方 8~30px 的投影均值 / 峰高（上翼脏度：紧挨末行字）
    "paper_beyond",    # 终点下方 10~40px 的投影中位 / 峰高（条外是不是纸；双边框页有外条，不为 0）
    "bar_len",         # 峰 → 墨条下沿的距离（粗条在不在 / 多厚）
    "central_h_norm",  # 去掉两端拐角后的峰高 / 带内最高
    "central_ratio",   # 去拐角峰高 / 全宽峰高（拐角墨团灌分的程度）
    "edge_dist",       # 距搜索带下边界
    "is_rule",
    "n_cand",
    "frame_h_rel",     # (终点 − 上框位) / 页高；无上框记 0
    "has_top",
)


def _central_curve(mask: np.ndarray, slope: float, lo: int, hi: int, verticals) -> np.ndarray | None:
    """去掉两端各 RESCUE_MARGIN（最外竖线以内）后的同倾角投影，按全宽坐标对齐到 lo..hi。"""
    h, w = mask.shape
    if not verticals:
        return None
    xs = sorted(v.position for v in verticals)
    x0 = max(0, int(xs[0]) + RESCUE_MARGIN)
    x1 = min(w, int(xs[-1]) - RESCUE_MARGIN)
    if x1 - x0 < 200:
        return None
    sub = mask[:, x0:x1]
    cx = (x1 - x0) / 2.0
    shift = slope * ((w / 2.0 - x0) - cx)          # 子图 y → 全宽 y
    lo_s = lo - int(round(shift))
    hi_s = hi - int(round(shift))
    _, c = sample_line_curve(sub, "h", lo_s, hi_s, slope)
    return c


def enumerate_candidates(mask: np.ndarray, cur: LineMatch, verticals, book_gap: float | None,
                         lo: int, hi: int, top_pos: float | None = None,
                         max_cand: int = 16) -> list[dict]:
    """返回候选列表，每项 {"line": LineMatch（峰位，未收尾）, "final": float, "feats": {...}}。"""
    h, w = mask.shape
    pos, curve = sample_line_curve(mask, "h", lo, hi, cur.slope)
    if len(curve) == 0:
        return []
    cmax = float(curve.max()) or 1.0
    cc = _central_curve(mask, cur.slope, lo, hi, verticals)

    peaks = []
    for i in local_maxima(curve, radius=5):
        wd, sc = half_height_score_at(curve, i, DEFAULT_ALPHA, DEFAULT_HYST)
        peaks.append((i, wd, sc))
    # 现役线本身（救援可能换了倾角，不一定是极大点）
    i_cur = int(round(cur.position)) - lo
    if 0 <= i_cur < len(curve) and all(abs(i - i_cur) > 2 for i, _, _ in peaks):
        wd, sc = half_height_score_at(curve, i_cur, DEFAULT_ALPHA, DEFAULT_HYST)
        peaks.append((i_cur, wd, sc))
    peaks.sort(key=lambda t: -t[2])
    keep = peaks[:max_cand]
    if all(abs(i - i_cur) > 2 for i, _, _ in keep):
        keep += [p for p in peaks if abs(p[0] - i_cur) <= 2][:1]
    n = len(keep)
    by_height = sorted(range(n), key=lambda k: -curve[keep[k][0]])
    rank_h = {k: r for r, k in enumerate(by_height)}

    out = []
    for r, (i, wd, sc) in enumerate(keep):
        pk = float(curve[i])
        lm = LineMatch(position=float(pos[i]), slope=cur.slope, score=sc, width=wd, proj=pk)
        fin = finalize_bottom(mask, lm)
        i_end = int(np.clip(round(fin.position - lo), 0, len(curve) - 1))
        # 条厚：峰 → 墨条下沿（同 finalize_bottom 里的下沿路线，不含固定余量）
        bar = _descend_to_ink_bottom(curve, i) - i
        up = curve[max(0, i - 30):max(0, i - 8)]
        # 终点下方 10~40px：带内曲线不够长时读不到，按 0 墨（纸）算会给出假「干净」，故补采
        _, low = sample_line_curve(mask, "h", int(fin.position) + 10, min(h - 1, int(fin.position) + 40), cur.slope)
        paper = float(np.median(low)) / max(pk, 1e-9) if len(low) else 0.0
        cen = float(cc[i]) if cc is not None and i < len(cc) else pk
        feats = {
            "rel_rule": float(pos[i] - cur.position),
            "rel_prior": float((h - fin.position) - book_gap) if book_gap is not None else 0.0,
            "has_prior": float(book_gap is not None),
            "h_norm": pk / cmax,
            "h_abs": pk / w,
            "score_log": float(np.log1p(sc)),
            "width": float(wd),
            "rank_score": float(r),
            "rank_height": float(rank_h[r]),
            "up_ink": float(up.mean()) / max(pk, 1e-9) if len(up) else 0.0,
            "paper_beyond": paper,
            "bar_len": float(bar),
            "central_h_norm": cen / cmax,
            "central_ratio": cen / max(pk, 1e-9),
            "edge_dist": float(hi - pos[i]),
            "is_rule": float(abs(i - i_cur) <= 2),
            "n_cand": float(n),
            "frame_h_rel": float((fin.position - top_pos) / h) if top_pos is not None else 0.0,
            "has_top": float(top_pos is not None),
        }
        out.append({"line": lm, "final": float(fin.position), "feats": feats})
    return out
