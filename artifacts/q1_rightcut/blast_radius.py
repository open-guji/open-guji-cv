# -*- coding: utf-8 -*-
"""Q1：改 RIGHT_RESCUE_MAX 的波及面——全部 body 列上，新旧上限下 widen_right_for_crossing 的结果差异。
sx1 只在 extractor 里被这一个函数外扩，故这就是改动的完整影响面（不必整册跑 Step4）。
用法：python artifacts/q1_rightcut/blast_radius.py NEW_MAX
"""
import sys, json
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "artifacts/m1_gold/left_cut"))
from _v2_step4 import V2Book, dataset_root
from scan_cut_crossings_v2 import body_pages
from open_guji_cv.clustering import extractor as X

new = int(sys.argv[1]); old = X.RIGHT_RESCUE_MAX
diffs = []; n = 0
for book, pgs in body_pages(dataset_root()).items():
    v = V2Book(book)
    for pg in pgs:
        cells = v.cells(pg)
        if cells is None: continue
        for cc in cells.columns:
            if not cc.ok or not cc.content_x: continue
            img = v.col_img(pg, cc.col); n += 1
            cs = [c for c in cc.cells if c.kind != "blank"]
            if not cs: continue
            sy0, sy1 = int(min(c.y0 for c in cs)), int(max(c.y1 for c in cs))
            x0, x1 = int(round(cc.content_x[0])), int(round(cc.content_x[1]))
            X.RIGHT_RESCUE_MAX = old; a = X.widen_right_for_crossing(img, x0, x1, sy0, sy1)
            X.RIGHT_RESCUE_MAX = new; b = X.widen_right_for_crossing(img, x0, x1, sy0, sy1)
            if a != b: diffs.append({"book": book, "page": pg, "col": cc.col, "x1": x1, "old": a, "new": b, "W": img.shape[1]})
print(f"列 {n}；MAX {old}→{new} 下 sx1 有差异的列 {len(diffs)}")
for d in diffs: print(d)
