# -*- coding: utf-8 -*-
"""实验十六：漂移金标能不能靠一个变换整体搬回来？

每条金标带 `y_old`（旧坐标系里拖动前的原格线）和 `bi`（格线序号）；当前产物里同一 `bi` 的格线
`cc.boundaries[bi]` 就是新坐标系的位置。这就是一对锚点，802 条 vol01 金标 = 802 对。

拟合 y_new = f(y_old)，三种模型 × 三种粒度：
  模型：shift（y+b）/ scale（a·y）/ affine（a·y+b）
  粒度：全局 / 按页 / 按列
报残差中位/p90，以及**留出**误差（按列拟合时留一测一；按页拟合时列间交叉）。
留出残差 ≤2–3px 才算「有稳定联系」。

    python exp16_drift_fit.py [--book vol01]
"""
import argparse
import statistics as S
from collections import defaultdict

import cv2
import numpy as np

from open_guji_cv.core.spec import column_key
from open_guji_cv.core.step import page_key
from open_guji_cv.eval.touching import SHARD
from open_guji_cv.feedback.consumers import verdict_store
from open_guji_cv.products import kinds as _k  # noqa: F401
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


def fit(model, xs, ys):
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if model == "shift":
        return 1.0, float(np.median(ys - xs))
    if model == "scale":
        return float(np.sum(xs * ys) / max(np.sum(xs * xs), 1e-9)), 0.0
    if len(xs) < 2:
        return 1.0, float(np.median(ys - xs))
    a, b = np.polyfit(xs, ys, 1)
    return float(a), float(b)


def resid(model, xs, ys, a, b):
    return np.abs(np.asarray(ys, float) - (a * np.asarray(xs, float) + b))


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    items = [i for i in verdict_store().list(SHARD)
             if str(i.anchor.book) == a.book and getattr(i, "status", "active") == "active"]

    pairs = []          # (page, col, bi, y_old, y_new, h_old, h_new, ex)
    skip = defaultdict(int)
    cells_cache, h_cache = {}, {}
    for it in items:
        ex = it.expected or {}
        pg, col = it.anchor.page, it.anchor.col
        bi, yo, ho = ex.get("bi"), ex.get("y_old"), ex.get("col_h")
        if None in (pg, col, bi, yo, ho):
            skip["缺字段"] += 1
            continue
        if pg not in cells_cache:
            cells_cache[pg] = st.read(a.book, "row_segment", page_key(pg), "cells")
        cells = cells_cache[pg]
        cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
        if cc is None:
            skip["无列产物"] += 1
            continue
        k = (pg, col)
        if k not in h_cache:
            p = ic.get(a.book, "column_image", column_key(pg, col))
            im = cv2.imread(str(p), 0) if p else None
            h_cache[k] = None if im is None else im.shape[0]
        hn = h_cache[k]
        if hn is None:
            skip["无列图"] += 1
            continue
        if abs(hn - int(ho)) <= 2:
            skip["未漂移"] += 1
            continue
        if not (0 <= int(bi) < len(cc.boundaries)):
            skip["bi 越界"] += 1
            continue
        pairs.append((pg, col, int(bi), float(yo), float(cc.boundaries[int(bi)]), int(ho), hn, ex))
    print(f"{a.book} 金标 {len(items)}，锚点对 {len(pairs)}，跳过 {dict(skip)}")
    if not pairs:
        return

    xs = [p[3] for p in pairs]
    ys = [p[4] for p in pairs]
    raw = np.abs(np.asarray(ys) - np.asarray(xs))
    print(f"\n不变换（y_new − y_old）：中位 {np.median(raw):.1f}  p90 {pct(raw, .9):.1f}  max {raw.max():.0f}")
    dh = [p[6] - p[5] for p in pairs]
    print(f"列高变化 h_new − h_old：中位 {S.median(dh):+.0f}  范围 {min(dh):+d}…{max(dh):+d}")
    # bi 是否错位一格：看 raw 里是不是集中在 ~一个格高
    print(f"  raw 分布：≤3 {np.mean(raw<=3):.0%}  3–20 {np.mean((raw>3)&(raw<=20)):.0%}  20–80 {np.mean((raw>20)&(raw<=80)):.0%}  >80 {np.mean(raw>80):.0%}")

    print(f"\n{'粒度':6s} {'模型':7s} | {'拟合残差 中位/p90':>16s} | {'留出残差 中位/p90':>16s} | {'留出≤2px':>7s} {'≤3px':>5s}")
    by_page = defaultdict(list)
    by_col = defaultdict(list)
    for p in pairs:
        by_page[p[0]].append(p)
        by_col[(p[0], p[1])].append(p)

    for model in ("shift", "scale", "affine"):
        # 全局
        A, B = fit(model, xs, ys)
        r = resid(model, xs, ys, A, B)
        # 全局的留出：按页对半
        pgs = sorted(by_page)
        tr = [p for pg in pgs[::2] for p in by_page[pg]]
        te = [p for pg in pgs[1::2] for p in by_page[pg]]
        A2, B2 = fit(model, [p[3] for p in tr], [p[4] for p in tr])
        ho = resid(model, [p[3] for p in te], [p[4] for p in te], A2, B2)
        print(f"{'全局':6s} {model:7s} | {np.median(r):7.1f}/{pct(r,.9):6.1f}  | {np.median(ho):7.1f}/{pct(ho,.9):6.1f}  | {np.mean(ho<=2):6.0%} {np.mean(ho<=3):5.0%}   a={A:.4f} b={B:+.1f}")

        # 按页：页内列间交叉（奇列训偶列测）
        r_all, ho_all = [], []
        for pg, ps in by_page.items():
            A, B = fit(model, [p[3] for p in ps], [p[4] for p in ps])
            r_all += list(resid(model, [p[3] for p in ps], [p[4] for p in ps], A, B))
            cols = sorted({p[1] for p in ps})
            if len(cols) >= 2:
                tr = [p for p in ps if p[1] in cols[::2]]
                te = [p for p in ps if p[1] in cols[1::2]]
                if tr and te:
                    A2, B2 = fit(model, [p[3] for p in tr], [p[4] for p in tr])
                    ho_all += list(resid(model, [p[3] for p in te], [p[4] for p in te], A2, B2))
        r_all, ho_all = np.asarray(r_all), np.asarray(ho_all)
        print(f"{'按页':6s} {model:7s} | {np.median(r_all):7.1f}/{pct(r_all,.9):6.1f}  | {np.median(ho_all):7.1f}/{pct(ho_all,.9):6.1f}  | {np.mean(ho_all<=2):6.0%} {np.mean(ho_all<=3):5.0%}   (留出 n={len(ho_all)})")

        # 按列：留一测一（列内 ≥3 个锚点才做）
        r_all, ho_all = [], []
        for k, ps in by_col.items():
            A, B = fit(model, [p[3] for p in ps], [p[4] for p in ps])
            r_all += list(resid(model, [p[3] for p in ps], [p[4] for p in ps], A, B))
            if len(ps) >= 3:
                for i in range(len(ps)):
                    tr = ps[:i] + ps[i + 1:]
                    A2, B2 = fit(model, [p[3] for p in tr], [p[4] for p in tr])
                    ho_all += list(resid(model, [ps[i][3]], [ps[i][4]], A2, B2))
        r_all, ho_all = np.asarray(r_all), np.asarray(ho_all)
        print(f"{'按列':6s} {model:7s} | {np.median(r_all):7.1f}/{pct(r_all,.9):6.1f}  | {np.median(ho_all):7.1f}/{pct(ho_all,.9):6.1f}  | {np.mean(ho_all<=2):6.0%} {np.mean(ho_all<=3):5.0%}   (留出 n={len(ho_all)}，列内≥3锚点的列 {sum(1 for v in by_col.values() if len(v)>=3)}/{len(by_col)})")

    # 残差是不是随 y 变（顶部裁切平移 vs 整体缩放）：全局 shift 后残差 vs y_old
    A, B = fit("shift", xs, ys)
    r_signed = np.asarray(ys) - (np.asarray(xs) + B)
    order = np.argsort(xs)
    xs_s, rs_s = np.asarray(xs)[order], r_signed[order]
    n = len(xs_s)
    print("\n全局纯平移后，带符号残差按 y_old 五段：")
    for q in range(5):
        seg = rs_s[q * n // 5:(q + 1) * n // 5]
        xseg = xs_s[q * n // 5:(q + 1) * n // 5]
        print(f"  y_old {xseg.min():5.0f}–{xseg.max():5.0f}: 残差中位 {np.median(seg):+5.1f}  p10/p90 {pct(seg,.1):+5.1f}/{pct(seg,.9):+5.1f}")

    # 每列的锚点数分布
    cnt = defaultdict(int)
    for v in by_col.values():
        cnt[min(len(v), 5)] += 1
    print("\n每列锚点数分布（≥5 合并）:", dict(sorted(cnt.items())))
    print(f"每页锚点数中位 {S.median(len(v) for v in by_page.values())}，页数 {len(by_page)}")


main()
