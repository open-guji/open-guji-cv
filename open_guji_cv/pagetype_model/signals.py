# -*- coding: utf-8 -*-
"""页级信号抽取（线上线下共用的单一口径）。

两组信号：
- 灰度结构量：`clustering.page_type.page_features` 的 8 个（只看原图）；
- Step1 产物量：列数、列宽变异、抬头框数、界行 w80、上下外框有无，以及按 Step1 列窗口切开的
  各列墨量分布（墨占比、纵向占用、上下半页比、首列相对中位列）、版心字距 period 及其自相关强度。

坐标：Step1 产物是右上角原点（x 向左），转图像坐标 `x_img = W - x`。
"""
from __future__ import annotations

import numpy as np

SIGNAL_VERSION = "1"

PAGE_FEATURES = ("ink", "txt_ink", "n_vline", "n_glyph", "glyph_h", "glyph_w", "x_cover", "y_cover")
STEP1_FEATURES = (
    "n_cols", "colw_cv", "colw_med_rel", "n_head_raise", "bend_w80_med", "bend_w80_max",
    "top_outer_none", "bottom_outer_none", "top_single", "bottom_single", "n_segmented",
)
COL_FEATURES = (
    "col_ink_mean", "col_ink_cv", "col_ink_min", "col_ink_max", "col_empty_n",
    "col_cover_mean", "col_cover_min", "col_updown", "col_first_rel", "col_last_rel",
    "col_updown_min", "period_rel", "period_strength", "col_period_cv",
)
FEATURES: tuple[str, ...] = PAGE_FEATURES + STEP1_FEATURES + COL_FEATURES
GROUP_OF = {**{f: "page" for f in PAGE_FEATURES}, **{f: "step1" for f in STEP1_FEATURES},
            **{f: "col" for f in COL_FEATURES}}


def _x_at(v: dict, y: float) -> float:
    """VLine 在高度 y 处的 x（右上原点）。折线只取第一段外推——这里只要列窗口的大致位置。"""
    return v["x_at_top"] + v["slope"] * y


def _period(strip: np.ndarray) -> tuple[float, float]:
    """一列的行投影自相关：返回 (周期px, 峰强度)。"""
    prof = strip.sum(axis=1).astype(float)
    if prof.sum() <= 0 or len(prof) < 200:
        return 0.0, 0.0
    prof -= prof.mean()
    ac = np.correlate(prof, prof, mode="full")[len(prof) - 1:]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac /= ac[0]
    lo, hi = 40, min(400, len(ac) - 1)
    if hi <= lo:
        return 0.0, 0.0
    seg = ac[lo:hi]
    k = int(np.argmax(seg))
    return float(lo + k), float(seg[k])


def extract(gray: np.ndarray, borders: dict | None, binary_t: int = 128) -> dict:
    """gray：原图灰度。borders：Step1 `borders` 产物（dict，可 None=只有灰度量，Step1 量记 NaN）。"""
    import cv2
    from ..clustering.page_type import page_features
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    f: dict = dict(page_features(gray))
    nan = float("nan")
    for k in STEP1_FEATURES + COL_FEATURES:
        f[k] = nan
    if not borders:
        return f
    h, w = gray.shape
    b = (gray < binary_t).astype(np.uint8)
    vs = borders.get("verticals") or []
    f["n_cols"] = float(max(0, len(vs) - 1))
    f["n_head_raise"] = float(len(borders.get("head_raise") or []))
    f["bend_w80_med"] = borders.get("bend_w80_med") if borders.get("bend_w80_med") is not None else nan
    f["bend_w80_max"] = borders.get("bend_w80_max") if borders.get("bend_w80_max") is not None else nan
    f["top_outer_none"] = float(borders.get("top_outer_offset") is None)
    f["bottom_outer_none"] = float(borders.get("bottom_outer_offset") is None)
    f["top_single"] = float(borders.get("top_frame_kind") == "single")
    f["bottom_single"] = float(borders.get("bottom_frame_kind") == "single")
    f["n_segmented"] = float(sum(1 for v in vs if v.get("k2") is not None))
    if len(vs) < 2:
        return f
    W = int(borders.get("width") or w)
    xs_mid = sorted(W - _x_at(v, h / 2) for v in vs)
    gaps = np.diff(xs_mid)
    gaps = gaps[gaps > 5]
    if len(gaps):
        f["colw_cv"] = float(gaps.std() / gaps.mean())
        f["colw_med_rel"] = float(np.median(gaps) / W)
    # 各列墨：每列按其左右界行在 y 处的位置逐行取窗口，这里用中点列边界近似（直线）
    inks, covers, updowns, periods, strengths = [], [], [], [], []
    for i in range(len(xs_mid) - 1):
        x0, x1 = int(xs_mid[i]) + 6, int(xs_mid[i + 1]) - 6
        x0, x1 = max(0, x0), min(w, x1)
        if x1 - x0 < 20:
            continue
        strip = b[:, x0:x1]
        inks.append(float(strip.mean()))
        rows = strip.sum(axis=1) > 0
        covers.append(float(rows.mean()))
        t = strip[: h // 2].sum()
        bt = strip[h // 2:].sum()
        updowns.append(float((t + 1) / (bt + 1)))
        p, s = _period(strip)
        if s > 0:
            periods.append(p)
            strengths.append(s)
    if not inks:
        return f
    ia = np.array(inks)
    med = float(np.median(ia)) + 1e-9
    f["col_ink_mean"] = float(ia.mean())
    f["col_ink_cv"] = float(ia.std() / (ia.mean() + 1e-9))
    f["col_ink_min"] = float(ia.min())
    f["col_ink_max"] = float(ia.max())
    f["col_empty_n"] = float((ia < 0.01).sum())
    f["col_cover_mean"] = float(np.mean(covers))
    f["col_cover_min"] = float(np.min(covers))
    ud = np.log(np.array(updowns))
    f["col_updown"] = float(ud.mean())
    f["col_updown_min"] = float(ud.min())
    # xs_mid 从左到右；首列（读序第一列）在最右
    f["col_first_rel"] = float(ia[-1] / med)
    f["col_last_rel"] = float(ia[0] / med)
    if periods:
        pa = np.array(periods)
        f["period_rel"] = float(np.median(pa) / h)
        f["period_strength"] = float(np.median(strengths))
        f["col_period_cv"] = float(pa.std() / pa.mean())
    return f
