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


def _deshear_x(x: float, y: float, h: float, tan_t: float) -> float:
    """与 grid_segment.deshear 一致：以纵向中点为不动点的水平错切。"""
    return x - tan_t * (y - h / 2)


def compare_page(gold: PageGeometry, cols: list[tuple[float, float]],
                 shear: float = 0.0) -> dict:
    """cols 为管线切出的列框 [(left_x, right_x)]，坐标在**去错切帧**。"""
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
    return {
        "book": gold.book, "page": gold.page,
        "page_class": gold.page_class,
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
    }


def evaluate(pairs: list[tuple[PageGeometry, list, float]]) -> dict:
    rows = [compare_page(g, c, s) for g, c, s in pairs]
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
                f"/ 90分位 {a['residual_tilt_p90']:>5.1f}px")

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
                f"界行落入列框 >30% 的坏页 {o['pages_bad']}"]
    return "\n".join(out)
