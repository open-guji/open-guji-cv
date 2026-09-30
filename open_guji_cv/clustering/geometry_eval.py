"""版面几何评测：列框有没有把界行圈进去 + 形变有没有被矫正掉。

主指标 rule_in_col
------------------
金标界行在**三个高度**上共 3N 个采样点，看有多少落进管线切出的列框内部。
落进去就是下游「图块混入界行竖线」的直接前因，所以这是个有因果链的指标，
不是代理量。三个高度一起算，是因为列框是竖直矩形——线只要在**某个**高度
探进框里，那一段的图块就脏了。

次指标 residual_tilt
--------------------
把管线声明的几何变换（`grid.shear`，将来可能是单应）作用到金标点上，再看
同一条界行的三个 x 还差多少。它直接回答「矫正做干净了没有」，与列拟合无关。

形变性质（诊断用，不打分）
--------------------------
`projective_span` 逐条界行斜率随 x 的系统变化 —— 错切下为 0，射影下不为 0；
`foreshortening` 列距沿 x 的系统变化 —— 同上，且与前者独立。
两者一起决定「错切校正够不够，要不要上单应」。这是本数据集要回答的问题，
所以只报，不并进分数。
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .page_geometry import PageGeometry

# 界行在列框内多深才算「圈进去」：界行半宽 + 一点余量，小于此按贴边处理
IN_COL_MARGIN = 3.0


def outside_ink(gray, cols: list[tuple[float, float]],
                shear: float = 0.0) -> tuple[float, float]:
    """落在**最外侧列框之外**的字墨比例，返回 (左侧, 右侧)。

    为什么单独量这个：判断「有没有整列丢掉」，列数对不对是个很差的代理量。
    实测非 9 列页的外侧漏墨中位 1.97%，**比 9 列页的 2.79% 还低**——那些页
    的第 9 个框落在图外，而图外本来就没有像素。漏得最多的反而全是 9 列页
    （最高 14.1%）。所以列数不该当危害指标，这个才是。

    只算列框**外侧**、不算列间缝：缝里本来就有笔画外溢与内缩留白，把它算
    进来会淹没真正的信号（全书框外字墨中位 10.5%，外侧漏墨中位才 2.7%）。

    不需要金标——它是图与管线输出之间的关系，可以在任意页上直接算。
    """
    from .page_geometry import BAND_FRACS  # noqa: F401  (仅为文档一致性)
    import cv2 as _cv2
    from .grid_segment import deshear, page_column_projection
    if gray.ndim == 3:
        gray = _cv2.cvtColor(gray, _cv2.COLOR_BGR2GRAY)
    d = deshear(gray, shear)
    proj = page_column_projection(d)      # 已剔除长竖线/横线，剩的是字墨
    total = float(proj.sum())
    if total <= 0 or not cols:
        return 0.0, 0.0
    lo = int(max(0, min(l for l, _ in cols)))
    hi = int(min(len(proj), max(r for _, r in cols)))
    return (float(proj[:lo].sum()) / total,
            float(proj[hi:].sum()) / total)


def _deshear_x(x: float, y: float, h: float, tan_t: float) -> float:
    """与 grid_segment.deshear 一致：以纵向中点为不动点的水平错切。"""
    return x - tan_t * (y - h / 2)


def compare_page(gold: PageGeometry, cols: list[tuple[float, float]],
                 shear: float = 0.0, gray=None) -> dict:
    """cols 为管线切出的列框 [(left_x, right_x)]，坐标在**去错切帧**。

    给了 gray 时额外算「外侧漏墨」——列框之外还剩多少字墨，即有没有整列
    被排除在网格之外。它不需要金标，是图与输出之间的直接关系。
    """
    h = float(gold.image_size["height"])
    n_in = n_tot = 0
    per_rule = []
    resid = []
    for r in gold.rules:
        xs = [_deshear_x(x, y, h, shear)
              for x, y in zip(r.xs, gold.band_ys)]
        hits = [any(l + IN_COL_MARGIN <= x <= rr - IN_COL_MARGIN
                    for l, rr in cols) for x in xs]
        n_in += sum(hits)
        n_tot += len(xs)
        resid.append(max(xs) - min(xs))
        per_rule.append({"x_mid": r.x_mid, "in_col": sum(hits),
                         "residual": round(max(xs) - min(xs), 2)})
    lost_l = lost_r = 0.0
    if gray is not None and cols:
        lost_l, lost_r = outside_ink(gray, cols, shear)
    return {
        "book": gold.book, "page": gold.page,
        "page_class": gold.page_class,
        "outside_ink_left": round(lost_l, 4),
        "outside_ink_right": round(lost_r, 4),
        "outside_ink": round(lost_l + lost_r, 4),
        "n_rules": len(gold.rules),
        "n_samples": n_tot,
        "n_in_col": n_in,
        "rule_in_col": round(n_in / n_tot, 4) if n_tot else 0.0,
        "residual_tilt": round(float(np.median(resid)), 2) if resid else 0.0,
        "residual_tilt_max": round(float(max(resid)), 2) if resid else 0.0,
        "n_cols_gold": gold.n_cols,
        "n_cols_pred": len(cols),
        "n_cols_exact": gold.n_cols is None or gold.n_cols == len(cols),
        "gold_period": round(gold.period(), 1),
        "projective_span": round(gold.projective_span(), 5),
        "foreshortening": round(gold.foreshortening(), 4),
        "slope_scatter": round(gold.slope_scatter(), 5),
        "per_rule": per_rule,
    }


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {"n_pages": 0}
    n_in = sum(r["n_in_col"] for r in rows)
    n_s = sum(r["n_samples"] for r in rows)
    return {
        "n_pages": len(rows),
        "n_rules": sum(r["n_rules"] for r in rows),
        "rule_in_col": round(n_in / n_s, 4) if n_s else 0.0,
        "pages_clean": sum(1 for r in rows if r["n_in_col"] == 0),
        "pages_bad": sum(1 for r in rows if r["rule_in_col"] > 0.3),
        "residual_tilt_median": round(
            float(np.median([r["residual_tilt"] for r in rows])), 2),
        "residual_tilt_p90": round(
            float(np.percentile([r["residual_tilt"] for r in rows], 90)), 2),
        "n_cols_exact_pages": sum(1 for r in rows if r["n_cols_exact"]),
        "outside_ink_median": round(
            float(np.median([r.get("outside_ink", 0.0) for r in rows])), 4),
        "outside_ink_p90": round(
            float(np.percentile([r.get("outside_ink", 0.0) for r in rows], 90)),
            4),
        "pages_losing_a_column": sum(
            1 for r in rows if r.get("outside_ink", 0.0) > 0.08),
    }


def evaluate(pairs: list) -> dict:
    """pairs = [(gold, cols, shear)] 或 [(gold, cols, shear, gray)]。"""
    rows = [compare_page(*t) for t in pairs]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r["page_class"] or "unknown"].append(r)
    return {"overall": _aggregate(rows),
            "by_page_class": {k: _aggregate(v)
                              for k, v in sorted(by_class.items())},
            "pages": rows}


def format_report(report: dict) -> str:
    def line(name: str, a: dict) -> str:
        return (f"{name:<10} 页{a['n_pages']:>3} 界行{a['n_rules']:>4}  "
                f"界行落入列框 {a['rule_in_col']:>6.2%}  "
                f"全清页 {a['pages_clean']:>3}/{a['n_pages']:<3}  "
                f"残余倾斜 中位 {a['residual_tilt_median']:>5.1f}px "
                f"/ 90分位 {a['residual_tilt_p90']:>5.1f}px  "
                f"外侧漏墨 中位 {a.get('outside_ink_median', 0):>6.2%}")

    out = ["【总体】", line("all", report["overall"]), "",
           "【按页型分层】"]
    for k, a in report["by_page_class"].items():
        out.append(line(k, a))
    out += ["", "【形变性质（诊断，不打分）】",
            f"{'页':<12}{'射影分量':>10}{'列距渐变':>10}{'斜率散布':>10}"
            f"{'界行落框':>10}"]
    for r in sorted(report["pages"], key=lambda r: -abs(r["projective_span"])):
        tag = "射影" if (abs(r["projective_span"]) > 0.008
                         or abs(r["foreshortening"]) > 0.04) else ""
        out.append(f"{r['book']}/{r['page']:<7}{r['projective_span']:>+10.4f}"
                   f"{r['foreshortening']:>+10.3f}{r['slope_scatter']:>10.4f}"
                   f"{r['rule_in_col']:>9.0%}  {tag}")
    o = report["overall"]
    out += ["", f"列数完全正确的页 {o['n_cols_exact_pages']}/{o['n_pages']}，"
                f"界行落入列框 >30% 的坏页 {o['pages_bad']}",
            f"外侧漏墨 >8%（疑似整列被排除在网格外）的页 "
            f"{o.get('pages_losing_a_column', 0)}/{o['n_pages']}"]
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════
# v2 链口径（2026-09-30，M1·D 道）：列框来自 Step2 column_windows，不再读 v1 phase3_char_grid
# ══════════════════════════════════════════════════════════════════════
#
# v1 口径 → v2 口径的对应与差异（详见 artifacts/m1_gold/geometry/MIGRATION.md）：
#
# | 量 | v1 | v2 |
# |---|---|---|
# | 列框 | 去错切帧里的竖直矩形 (left_x, right_x) | 每列文字带 band（Step2 列图 x∈[band0,band1]）经 Step2 逆映射
# |      |                                        | 回原图的四边形（与 Step3 `quad_page` 同一映射 ColumnMapper），在金标三个高度上各取一次 [左,右] |
# | 坐标帧 | v1 预处理输出（透视校正+裁到版框，金标原坐标） | 原图 raw_page_px（金标已迁移到原图，左上原点；
# |        |                                          | 产物是右上原点，比较前统一换成左上） |
# | shear | grid.shear（整页一个错切角） | **不存在**：v2 每列各有自己的射影（三段折线页分带）|
# | rule_in_col | 界行点落进矩形内部 | 界行点落进**该高度处**的列带内部（边距 IN_COL_MARGIN 不变）|
# | residual_tilt | 金标点去错切后三点 x 的极差 | 界行相对其**最近列带边缘**的水平偏移在三个高度上的极差
# |               | （矫正完残余多少）          | （= 界行在 v2 列带坐标里还剩多歪；金标自身未矫正的极差另报 raw_tilt）|
# | outside_ink | 列框矩形之外、整页（已裁到版框）字墨比例 | 版框窗口（金标界行 x 跨度 × 金标 frame_y）内，最外列带端（金标中高处）之外的字墨比例 |
#
# 一条线被多列共享：左列的右缘与右列的左缘对应同一条界行，任一命中即算「圈进去」。


def _column_interval_fn(mapper, band: tuple[int, int], page_w: int, step: int = 6):
    """返回 f(y_page)->(x_left, x_right) 或 None。列带两边各取密集采样，按页坐标 y 插值。

    mapper.to_page_tl 给的是左上原点的原图坐标，与迁移后的金标同帧。"""
    ys_col = list(range(0, int(mapper.out_h) + 1, step))
    if ys_col[-1] != int(mapper.out_h):
        ys_col.append(int(mapper.out_h))
    L = [mapper.to_page_tl(float(band[0]), float(y)) for y in ys_col]
    R = [mapper.to_page_tl(float(band[1]), float(y)) for y in ys_col]
    ly = np.array([p[1] for p in L]); lx = np.array([p[0] for p in L])
    ry = np.array([p[1] for p in R]); rx = np.array([p[0] for p in R])
    lo, hi = max(ly.min(), ry.min()), min(ly.max(), ry.max())

    def f(y: float):
        if not (lo <= y <= hi):
            return None
        oi, oj = np.argsort(ly), np.argsort(ry)
        xl = float(np.interp(y, ly[oi], lx[oi])); xr = float(np.interp(y, ry[oj], rx[oj]))
        return (min(xl, xr), max(xl, xr))
    return f


def compare_page_v2(gold: PageGeometry, col_fns: list, gray=None) -> dict:
    """col_fns：每列一个 f(y_page)->(左,右)|None（见 _column_interval_fn）。

    指标定义见本节头部表。`n_cols_pred` = 这一页 Step2 产出的列数。"""
    n_in = n_tot = 0
    per_rule, resid, raw_t, clear = [], [], [], []
    ys = gold.band_ys
    for r in gold.rules:
        xs = r.xs
        hits = []
        for x, y in zip(xs, ys):
            ivs = [iv for iv in (f(y) for f in col_fns) if iv is not None]
            hits.append(any(l + IN_COL_MARGIN <= x <= rr - IN_COL_MARGIN for l, rr in ivs))
            # 净空：界行点到最近列带边缘的距离（落进带内记负值）——rule_in_col 触底（0%）后仍有分辨力的诊断量
            cl = [min(abs(x - l), abs(x - rr)) * (-1 if l <= x <= rr else 1) for l, rr in ivs]
            if cl:
                clear.append(min(cl, key=abs))
        n_in += sum(hits); n_tot += len(xs)
        raw_t.append(max(xs) - min(xs))
        # 最近列带边缘（中高处定「哪条边」，三个高度沿同一条边量）
        best = None
        for ci, f in enumerate(col_fns):
            iv = f(ys[1])
            if iv is None:
                continue
            for side in (0, 1):
                d = abs(xs[1] - iv[side])
                if best is None or d < best[0]:
                    best = (d, ci, side)
        off = None
        if best is not None and best[0] <= 40:
            vals = []
            for x, y in zip(xs, ys):
                iv = col_fns[best[1]](y)
                vals.append(None if iv is None else x - iv[best[2]])
            if all(v is not None for v in vals):
                off = max(vals) - min(vals)
                resid.append(off)
        per_rule.append({"x_mid": r.x_mid, "in_col": sum(hits),
                         "residual": None if off is None else round(off, 2)})
    lost_l = lost_r = 0.0
    if gray is not None and col_fns:
        lost_l, lost_r = _outside_ink_v2(gray, col_fns, gold)
    return {
        "book": gold.book, "page": gold.page, "page_class": gold.page_class,
        "outside_ink_left": round(lost_l, 4), "outside_ink_right": round(lost_r, 4),
        "outside_ink": round(lost_l + lost_r, 4),
        "n_rules": len(gold.rules), "n_samples": n_tot, "n_in_col": n_in,
        "rule_in_col": round(n_in / n_tot, 4) if n_tot else 0.0,
        "residual_tilt": round(float(np.median(resid)), 2) if resid else 0.0,
        "residual_tilt_max": round(float(max(resid)), 2) if resid else 0.0,
        "n_resid_rules": len(resid),
        "clearance_min": round(float(min(clear)), 2) if clear else None,
        "clearance_median": round(float(np.median(clear)), 2) if clear else None,
        "clearances": [round(float(v), 1) for v in clear],
        "raw_tilt": round(float(np.median(raw_t)), 2) if raw_t else 0.0,
        "n_cols_gold": gold.n_cols, "n_cols_pred": len(col_fns),
        "n_cols_exact": gold.n_cols is None or gold.n_cols == len(col_fns),
        "gold_period": round(gold.period(), 1),
        "projective_span": round(gold.projective_span(), 5),
        "foreshortening": round(gold.foreshortening(), 4),
        "slope_scatter": round(gold.slope_scatter(), 5),
        "per_rule": per_rule,
    }


def _outside_ink_v2(gray, col_fns, gold: PageGeometry) -> tuple[float, float]:
    """版框窗口内、最外列带端之外的字墨比例 (左, 右)。墨 = page_column_projection（已剔长竖线/横线）。

    窗口：x ∈ [金标界行最小 x, 最大 x]（三个高度取并），y ∈ gold.frame_y（缺省整页）。"""
    import cv2 as _cv2
    from .grid_segment import page_column_projection
    if gray.ndim == 3:
        gray = _cv2.cvtColor(gray, _cv2.COLOR_BGR2GRAY)
    H, W = gray.shape[:2]
    y0, y1 = (int(gold.frame_y[0]), int(gold.frame_y[1])) if gold.frame_y else (0, H)
    allx = [x for r in gold.rules for x in r.xs]
    xa, xb = int(max(0, min(allx))), int(min(W, max(allx) + 1))
    proj = page_column_projection(gray[y0:y1])
    win = proj[xa:xb]
    total = float(win.sum())
    ivs = [iv for iv in (f(gold.band_ys[1]) for f in col_fns) if iv is not None]
    if total <= 0 or not ivs:
        return 0.0, 0.0
    lo = int(max(xa, min(l for l, _ in ivs))) - xa
    hi = int(min(xb, max(r for _, r in ivs))) - xa
    return float(win[:max(lo, 0)].sum()) / total, float(win[max(hi, 0):].sum()) / total


def _aggregate_v2(rows: list[dict]) -> dict:
    a = _aggregate(rows)
    cl = [v for r in rows for v in r.get("clearances", [])]
    if cl:
        a["clearance_min"] = round(float(min(cl)), 1)
        a["clearance_p5"] = round(float(np.percentile(cl, 5)), 1)
        a["clearance_median"] = round(float(np.median(cl)), 1)
        a["n_samples_inside_col"] = int(sum(1 for v in cl if v < 0))
    return a


def evaluate_v2(pairs: list) -> dict:
    """pairs = [(gold, col_fns, gray)]。汇总口径与 evaluate() 相同，另加净空诊断（clearance_*）。"""
    rows = [compare_page_v2(*t) for t in pairs]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r["page_class"] or "unknown"].append(r)
    return {"overall": _aggregate_v2(rows),
            "by_page_class": {k: _aggregate_v2(v) for k, v in sorted(by_class.items())},
            "pages": rows}
