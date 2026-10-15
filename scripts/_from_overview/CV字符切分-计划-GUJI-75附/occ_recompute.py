"""GUJI-75 复评门槛数据：用 cv main 的 `steps/occlusion.py` 在「快照 row_segment 格＋原图」上重算遮挡格（只读）。
用于快照 seed_admit 里没有 `occluded` 标记的册（vol01 的快照 09-27 早于遮挡判据）。

用法：python3 occ_recompute.py <cv 仓根> <原图目录> <row_segment 产物目录> [页码表达式 如 1-206]
说明：row_segment 的 quad_page 横坐标是「第 1 列在右」的页坐标，对原图文件要用 W−x，所以先把原图水平翻转再喂给 cell_densities
（等价于 `ctx.raw_page` 给出的规范空间）。判据参数＝SeedAdmitParams 缺省（density 4.0／cells 12／cols 3／peak 8.0／contrast 2.5）。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np

repo, imgdir, rsdir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
rng = sys.argv[4] if len(sys.argv) > 4 else "all"
sys.path.insert(0, repo)
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells  # noqa: E402

pages = sorted(int(p.stem[1:]) for p in rsdir.glob("p*.json"))
if rng != "all":
    a, b = rng.split("-")
    pages = [p for p in pages if int(a) <= p <= int(b)]
out = {}
for p in pages:
    f = imgdir / f"{p}.png"
    if not f.is_file():
        continue
    gray = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        continue
    gray = gray[:, ::-1].copy()
    d = json.load(open(rsdir / f"p{p:04d}.json"))["cells"]
    cells = NS(columns=[NS(col=c["col"], cells=[NS(quad_page=x.get("quad_page"), slot=x["slot"], sub=x.get("sub")) for x in c["cells"] if x.get("kind") != "blank"]) for c in d["columns"]])
    occ = occluded_cells(cell_densities(gray, cells), min_density=4.0, min_cells=12, min_cols=3, min_peak=8.0, min_contrast=2.5)
    if occ:
        cols = sorted({k[0] for k in occ})
        out[p] = {"cells": len(occ), "cols": cols, "col1": sum(1 for k in occ if k[0] == 1)}
print(json.dumps(out, ensure_ascii=False))
