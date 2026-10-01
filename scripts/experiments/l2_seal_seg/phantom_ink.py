"""遮挡格里「格内大块字身墨」分布（判幻影 char 格用）。大块=面积>150 的连通块；x 方向各缩 15% 避开列边界线。
用法: python phantom_ink.py <prods> <book> <page> [--list col]"""
import json, sys, os, types
import numpy as np, cv2
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
prods, book, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
W = os.environ["GUJI_WORKSPACE"]
img = cv2.imread(f"{W}/data_full/zongmu/{book}/{page}.png", 0)
cs = json.load(open(f"{prods}/{book}/row_segment/p{page:04d}.json"))["cells"]
cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x.get("slot", x["pos"]), sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs["columns"]])
occ = occluded_cells(cell_densities(img, cells))
n, lab, st, _ = cv2.connectedComponentsWithStats((img < 128).astype(np.uint8), connectivity=8)
big = np.zeros(n, bool); big[1:] = st[1:, 4] > 150; ink = big[lab]
rows = []
for c in cs["columns"]:
    for x in c["cells"]:
        if x["kind"] != "char" or not x.get("quad_page"): continue
        q = np.array(x["quad_page"]); x0, x1 = q[:, 0].min(), q[:, 0].max(); y0, y1 = q[:, 1].min(), q[:, 1].max()
        w = x1 - x0; r = ink[int(y0):int(y1), int(x0 + .15 * w):int(x1 - .15 * w)].mean()
        rows.append((c["col"], x["pos"], (c["col"], x.get("slot", x["pos"]), x.get("sub") or "") in occ, r))
for sel, nm in ((True, "遮挡格"), (False, "非遮挡")):
    v = np.array([r[3] for r in rows if r[2] == sel])
    if len(v): print(f"{book} p{page} {nm} n={len(v)} 分位 5/25/50/75: {np.percentile(v,[5,25,50,75]).round(3)}  <0.03:{(v<.03).sum()} <0.06:{(v<.06).sum()} <0.10:{(v<.10).sum()}")
if "--list" in sys.argv:
    col = int(sys.argv[sys.argv.index("--list") + 1])
    for r in rows:
        if r[0] == col: print(f"  col{r[0]} pos{r[1]:>2} occ={r[2]} 内部大块墨率 {r[3]:.3f}")
