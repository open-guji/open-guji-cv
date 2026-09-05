# -*- coding: utf-8 -*-
"""Step3 格线位置 vs 人工金标：逐像素误差（char-segmentation/row-boundaries）。

金标（vol01/33、vol02/135，各 9 列 × 22 条格线）记在**旧链路射影矫正后的列坐标系**里，
现役 v2 列图的高度与之相差几十像素（不同的矫正矩形）。金标随样本存了当时的行墨量曲线
`row_proj`，所以不必重标：把它与现役列图的行墨量曲线做**尺度 + 平移的互相关**，找到
映射后再比格线位置。对齐质量（相关系数）一并报出，低于 0.9 的列不计入。

    python scripts/eval_row_boundaries.py [--book vol01] [--json out.json]

指标：
  mean / median / p90 / max 像素误差；≤3px、≤5px、≤10px 的比例；
  按「现役切点是否 R2s（真粘连）」分层——粘连处的切点离人工金标有多远，是本轮要优化的靶子。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.rulers import INK_ON_LINE, STUCK_FLOOR, _col_profile  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

MIN_CORR = 0.9


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean(); b = b - b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 0 else 0.0


def align(gold_proj: np.ndarray | None, cur: np.ndarray, s0: float, off0: float,
          comb: list[float] | None = None) -> tuple[float, float, float]:
    """返回 (scale, offset, corr)：y_cur ≈ scale * y_gold + offset。

    先验来自版框：金标与现役都记了 border_top / border_bottom，两段线性对应给出 (s0, off0)；
    金标若带 row_proj 再用互相关在先验附近（尺度 ±2%、平移 ±30px）细化，否则直接用先验。
    """
    if gold_proj is None:
        # 没有曲线就用金标格线本身当梳齿：映射后落在现役曲线低谷处的均值最小
        best = (s0, off0, -1.0)
        inner = np.asarray(comb[1:-1], dtype=np.float64)
        for s in np.linspace(s0 * 0.97, s0 * 1.03, 13):
            for off in range(int(off0) - 40, int(off0) + 41, 1):
                ys = np.clip(np.round(s * inner + off).astype(int), 0, len(cur) - 1)
                score = float(1.0 - cur[ys].mean())
                if score > best[2]:
                    best = (float(s), float(off), score)
        return best
    h_cur, h_gold = len(cur), len(gold_proj)
    best = (s0, off0, -1.0)
    for s in np.linspace(s0 * 0.98, s0 * 1.02, 9):
        ys = np.arange(int(h_gold * s))
        g = np.interp(ys / s, np.arange(h_gold), gold_proj)
        for off in range(int(off0) - 30, int(off0) + 31, 1):
            lo, hi = max(0, off), min(h_cur, off + len(g))
            if hi - lo < h_cur * 0.6:
                continue
            c = _ncc(g[lo - off:hi - off], cur[lo:hi])
            if c > best[2]:
                best = (float(s), float(off), c)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None, help="只评这一册；默认全部")
    ap.add_argument("--json", default=None)
    ap.add_argument("--anchor", default="refine", choices=("refine", "border"),
                    help="border = 只用版框线性映射，不做互相关/梳齿细化（用来核对细化有没有引入偏差）")
    a = ap.parse_args()

    gs = GoldStore()
    st = ProductStore()
    items = [i for i in gs.list("char-segmentation/row-boundaries")
             if not a.book or i.anchor.book == a.book]
    rows: list[dict] = []
    skipped: list[str] = []
    for it in items:
        book, pg = it.anchor.book, it.anchor.page
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            skipped.append(f"{book}/{pg}: 没有现役 cells 产物")
            continue
        # 金标条目里可能没带 row_proj（GoldStore 条目瘦身），回样本文件取
        sample = gs.root / "char-segmentation" / "row-boundaries" / "samples" / f"{book}_{pg}.json"
        sample_cols = {}
        if sample.exists():
            sample_cols = {c["index"]: c for c in json.loads(sample.read_text(encoding="utf-8"))["columns"]}
        cur_cols = {c.col: c for c in cells.columns if c.ok}
        profiles = {col: _col_profile(st, book, pg, col) for col in cur_cols}
        profiles = {k: v for k, v in profiles.items() if v is not None}
        for gc in it.expected["columns"]:
            if "row_proj" not in gc:
                gc = {**sample_cols.get(gc["index"], {}), **gc}
            gp = (np.asarray(gc["row_proj"], dtype=np.float32) / max(1.0, float(gc["dst_w"]))
                  if "row_proj" in gc else None)
            gbt, gbb = float(gc["border_top_y"]), float(gc["border_bottom_y"])
            # 列对应：金标 index 0..8 与现役 col 1..9 同向（两边都按版面从右到左编号）；
            # 有 row_proj 时再用互相关在全部列里核对一次，取相关最高的。
            cand_cols = list(profiles) if gp is not None else [gc["index"] + 1]
            best_col, best_map = None, (1.0, 0.0, -2.0)
            for col in cand_cols:
                if col not in cur_cols or col not in profiles:
                    continue
                cc0 = cur_cols[col]
                s0 = (cc0.border_bottom - cc0.border_top) / max(1.0, gbb - gbt)
                off0 = cc0.border_top - s0 * gbt
                m = ((s0, off0, float("nan")) if a.anchor == "border"
                     else align(gp, profiles[col], s0, off0, comb=gc["boundaries"]))
                key = m[2] if gp is not None else 0.0
                if key > best_map[2]:
                    best_col, best_map = col, m
            s, off, corr = best_map
            if best_col is None or (gp is not None and a.anchor != "border" and corr < MIN_CORR):
                skipped.append(f"{book}/{pg} 金标列 {gc['index']}: 对齐相关只有 {corr:.2f}")
                continue
            cc = cur_cols[best_col]
            prof = profiles[best_col]
            cur_b = np.asarray(cc.boundaries, dtype=np.float64)
            for bi, gy in enumerate(gc["boundaries"]):
                y = s * gy + off
                j = int(np.argmin(np.abs(cur_b - y)))
                err = float(abs(cur_b[j] - y))
                yc = int(round(cur_b[j]))
                stuck = False
                if 0 <= yc < len(prof) and prof[yc] > INK_ON_LINE:
                    lo, hi = max(0, yc - 12), min(len(prof), yc + 13)
                    stuck = float(prof[lo:hi].min()) > STUCK_FLOOR
                rows.append(dict(book=book, page=pg, gold_col=gc["index"], col=best_col, corr=round(corr, 3),
                                 bi=bi, gold_y=round(y, 1), cur_y=round(float(cur_b[j]), 1), err=round(err, 1),
                                 edge=bi in (0, len(gc["boundaries"]) - 1), stuck=stuck))
    if not rows:
        print("没有可比的格线", skipped)
        return 1
    errs = np.array([r["err"] for r in rows])

    def line(tag: str, e: np.ndarray) -> None:
        if not len(e):
            print(f"  {tag:<22} n=0")
            return
        print(f"  {tag:<22} n={len(e):<4} mean {e.mean():5.1f}  median {np.median(e):5.1f}  p90 {np.percentile(e, 90):5.1f}"
              f"  max {e.max():5.1f}   ≤3px {100*(e<=3).mean():5.1f}%  ≤5px {100*(e<=5).mean():5.1f}%  ≤10px {100*(e<=10).mean():5.1f}%")

    print("row-boundaries 逐像素误差（现役 Step3 vs 人工金标，互相关重锚定）")
    line("全部格线", errs)
    inner = np.array([r["err"] for r in rows if not r["edge"]])
    line("内部格线", inner)
    line("其中现役切点 R2s 粘连", np.array([r["err"] for r in rows if not r["edge"] and r["stuck"]]))
    line("其中现役切点非粘连", np.array([r["err"] for r in rows if not r["edge"] and not r["stuck"]]))
    for (book, pg) in sorted({(r["book"], r["page"]) for r in rows}):
        line(f"{book}/{pg}", np.array([r["err"] for r in rows if r["book"] == book and r["page"] == pg and not r["edge"]]))
    seen = {}
    for r in rows:
        seen.setdefault((r["book"], r["page"], r["gold_col"]), (r["col"], r["corr"]))
    print("  列对应（金标列→现役列，相关）:", [(k[0], k[1], k[2], v[0], v[1]) for k, v in sorted(seen.items())])
    for key in list(seen)[:2]:
        rr = [r for r in rows if (r["book"], r["page"], r["gold_col"]) == key]
        print(f"  对照 {key}: 金标→现役 " + " ".join(f"{r['gold_y']:.0f}/{r['cur_y']:.0f}" for r in rr))
    worst = sorted(rows, key=lambda r: -r["err"])[:8]
    print("  最差 8 条:", [(r["book"], r["page"], r["col"], r["bi"], r["err"]) for r in worst])
    if skipped:
        print("  跳过:", skipped)
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "skipped": skipped}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
