# -*- coding: utf-8 -*-
"""row-boundaries 金标（旧链 phase3 坐标系）→ 现役 v2 列图坐标。2026-09-30 M1 B 道。

判据 = **图像指纹**：金标样本随附当时人看的那张列图的行墨占比曲线 `row_proj`（dst_w 归一）。
把它和现役 Step2 列图（cache `column_image`）的行墨占比曲线做「尺度+平移」互相关；
只有相关系数 ≥ MIN_CORR 且落在搜索窗内部（不贴边）才算「人当时看的图还在」，该列金标才迁；
否则标「已失效」并写明最优相关与原因。**不以算法格线与金标一致当判据。**

与 eval_row_boundaries.align 的差别（有意的）：
  · 相关在**平滑后**（15 行）的曲线上、且只取金标版框之间的文字带——旧 row_proj 含界行/版框残墨，
    现役列图已清过界行与版框，原始曲线直接比相关系数被压低（vol01/33 原法 0.39~0.86 全 <0.9，
    平滑+文字带后 0.77~0.98），这是「同一张图经清理后形态变了」，不是「图不在了」。
  · 尺度 ±3%、位移 [-320,80] 全搜（新旧列图都近似 1:1；版框先验对 top=0 的抬头列是偏的），
    **最优落在网格边上、或同列内另一个相距>40px 的位移相关只差<0.05（周期歧义）的一律判不可信**
    （实测 vol01/33 金标列 2 用窄窗时最优贴着尺度上沿、映射后金标底端越出列图，高相关是尺度漂出来的假象）。
  · 金标列序与现役列序**相反**（旧链自左向右，现役自右向左）：逐列在全部现役列里找最优，并要求
    最优与次优（不同列）相关之差 ≥ MARGIN，防认错列。

输出 migrated.json：每个金标列一条 {status: migrated|invalid, col_now, scale, offset, corr, col_h, boundaries_now, page_xy...}；
migrated 的附当前列窗几何签名 + 页面坐标（eval/colgeom.py 口径），之后 Step2 几何再变可按页面坐标重映射/判漂移。

用法（cwd = 引擎仓；需 GUJI_WORKSPACE/GUJI_PRODUCTS_DIR/GUJI_CACHE_DIR，且 vol01/33、vol02/135 已有 row_segment）:
    python artifacts/m1_gold/row_boundaries/migrate_row_boundaries_v2.py [--out migrated.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.colgeom import current_geom  # noqa: E402
from open_guji_cv.eval.rulers import _col_profile  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

MIN_CORR = 0.90
MARGIN = 0.15
ALT_MARGIN = 0.05
SMOOTH = 15
S_TOL, OFF_LO, OFF_HI = 0.03, -320, 80
DATASET = ROOT.parent / "open-guji-dataset" / "char-segmentation" / "row-boundaries"


def _sm(x: np.ndarray) -> np.ndarray:
    return np.convolve(x, np.ones(SMOOTH) / SMOOTH, mode="same")


def _ncc(a, b) -> float:
    a = a - a.mean(); b = b - b.mean()
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d > 0 else 0.0


def fit(gp: np.ndarray, pr: np.ndarray, bt: float, bb: float, *_):
    """在 s∈[0.97,1.03]、off∈[-320,80] 上全搜（新旧列图都近似 1:1，不信版框先验——top=0 的抬头列先验是偏的）。
    返回 (corr, s, off, edge, alt)：edge=最优贴网格边；alt=与最优位移差 >40px 的最高相关（同列内歧义）。"""
    ys = np.arange(int(bt) + 10, int(bb) - 10)
    g = gp[ys]
    ss = np.linspace(1 - S_TOL, 1 + S_TOL, 25)
    offs = np.arange(OFF_LO, OFF_HI + 1)
    grid = np.full((len(ss), len(offs)), -2.0)
    for i, s in enumerate(ss):
        base = np.round(s * ys).astype(int)
        for j, off in enumerate(offs):
            yc = base + off
            ok = (yc >= 0) & (yc < len(pr))
            if ok.sum() < 0.8 * len(ys):
                continue
            grid[i, j] = _ncc(g[ok], pr[yc[ok]])
    i, j = np.unravel_index(int(np.argmax(grid)), grid.shape)
    far = np.abs(offs - offs[j]) > 40
    alt = float(grid[:, far].max()) if far.any() else -2.0
    edge = i in (0, len(ss) - 1) or j in (0, len(offs) - 1)
    return float(grid[i, j]), float(ss[i]), int(offs[j]), bool(edge), alt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).with_name("migrated.json")))
    a = ap.parse_args()
    st = ProductStore()
    recs: list[dict] = []
    for sf in sorted((DATASET / "samples").glob("*.json")):
        d = json.loads(sf.read_text(encoding="utf-8"))
        book, pg = d["book"], int(d["page"])
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        geoms = {}
        for gc in d["columns"]:
            rec = dict(book=book, page=pg, gold_col=gc["index"], n_points=len(gc["boundaries"]))
            if cells is None:
                recs.append({**rec, "status": "invalid", "why": "现役 row_segment 产物缺失（无法取指纹）"})
                continue
            if "row_proj" not in gc:
                recs.append({**rec, "status": "invalid",
                             "why": "样本没存当时列图的 row_proj（也没存原图；image_source=noenh_out/…/135.png 已不在）——无图像指纹可对，"
                                    "只剩格线自身当梳齿重锚定，那是拿金标点找谷、对周期信号有一格歧义，不算「图还在」"})
                continue
            gp = _sm(np.asarray(gc["row_proj"], dtype=np.float64) / max(1.0, float(gc["dst_w"])))
            bt, bb = float(gc["border_top_y"]), float(gc["border_bottom_y"])
            cands = []
            for cc in cells.columns:
                if not cc.ok:
                    continue
                prof = _col_profile(st, book, pg, cc.col)
                if prof is None:
                    continue
                c, s, off, edge, alt = fit(gp, _sm(prof), bt, bb)
                cands.append(dict(col=cc.col, corr=c, s=s, off=off, edge=edge, alt=alt, h=len(prof), cc=cc))
            if not cands:
                recs.append({**rec, "status": "invalid", "why": "没有可取列图的现役列（缺 column_image 缓存）"})
                continue
            cands.sort(key=lambda x: -x["corr"])
            b = cands[0]
            second = cands[1]["corr"] if len(cands) > 1 else -1.0
            rec.update(best_col=b["col"], corr=round(b["corr"], 3), second_corr=round(second, 3),
                       scale=round(b["s"], 4), offset=b["off"], edge=bool(b["edge"]), alt_corr=round(b["alt"], 3))
            why = None
            if b["corr"] < MIN_CORR:
                why = f"指纹相关 {b['corr']:.2f} < {MIN_CORR}（现役列图与当时所见行墨曲线对不上）"
            elif b["edge"]:
                why = "最优落在搜索窗边上（尺度/位移不可信）"
            elif b["corr"] - b["alt"] < ALT_MARGIN:
                why = f"同列内另一位移（差>40px）相关 {b['alt']:.2f}，与最优仅差 {b['corr'] - b['alt']:.2f} < {ALT_MARGIN}（周期歧义）"
            elif b["corr"] - second < MARGIN:
                why = f"最优与次优列相关仅差 {b['corr'] - second:.2f} < {MARGIN}（认列不唯一）"
            if why:
                recs.append({**rec, "status": "invalid", "why": why})
                continue
            cc = b["cc"]
            ys_now = [round(b["s"] * float(y) + b["off"], 1) for y in gc["boundaries"]]
            out_of_img = [i for i, y in enumerate(ys_now) if y < -2 or y > b["h"] + 2]
            geom = geoms.get(cc.col) or current_geom(st, book, pg, cc.col)
            stamp = {}
            if geom is not None:
                stamp["geom_sig"] = geom.sig
                stamp["page_xy"] = [[round(v, 2) for v in geom.row_to_page(y)] if i not in out_of_img else None
                                    for i, y in enumerate(ys_now)]
            recs.append({**rec, "status": "migrated", "col_now": cc.col, "col_h": b["h"],
                         "points_outside_current_column_image": out_of_img,   # 这些点在现役列图之外，评测里不计
                         "boundaries_old": gc["boundaries"], "boundaries_now": ys_now, **stamp})
    Path(a.out).write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    mig = [r for r in recs if r["status"] == "migrated"]
    print(f"金标列 {len(recs)}：迁 {len(mig)} / 失效 {len(recs) - len(mig)}  → {a.out}")
    for r in recs:
        print(f"  {r['book']}/{r['page']} 金标列{r['gold_col']} → "
              + (f"现役列{r['col_now']} corr={r['corr']} s={r['scale']} off={r['offset']}" if r['status'] == 'migrated'
                 else f"失效：{r['why']}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
