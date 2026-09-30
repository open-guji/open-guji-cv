"""幻影格判据候选：格内「粗笔画」像素占比（距离变换≥R，即笔画宽≥2R）。印章篆文/斑点笔画细，字的笔画粗。
用法: python phantom_thick.py <prods> <book> <page> [R=4] [--list col]"""
import json, sys, os, types
import numpy as np, cv2
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
prods, book, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
R = float(sys.argv[4]) if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else 4.0
W = os.environ["GUJI_WORKSPACE"]
img = cv2.imread(f"{W}/data_full/zongmu/{book}/{page}.png", 0)
cs = json.load(open(f"{prods}/{book}/row_segment/p{page:04d}.json"))["cells"]
cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x.get("slot", x["pos"]), sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs["columns"]])
occ = occluded_cells(cell_densities(img, cells))
dt = cv2.distanceTransform((img < 128).astype(np.uint8), cv2.DIST_L2, 3)
thick = dt >= R
rows = []
for c in cs["columns"]:
    for x in c["cells"]:
        if x["kind"] != "char" or not x.get("quad_page"): continue
        q = np.array(x["quad_page"]); x0, x1 = q[:, 0].min(), q[:, 0].max(); y0, y1 = q[:, 1].min(), q[:, 1].max()
        w = x1 - x0; r = thick[int(y0):int(y1), int(x0 + .15 * w):int(x1 - .15 * w)].mean()
        rows.append((c["col"], x["pos"], (c["col"], x.get("slot", x["pos"]), x.get("sub") or "") in occ, r))
for sel, nm in ((True, "遮挡格"), (False, "非遮挡")):
    v = np.array([r[3] for r in rows if r[2] == sel])
    if len(v): print(f"{book} p{page} R={R} {nm} n={len(v)} 分位 5/25/50: {np.percentile(v,[5,25,50]).round(3)} <0.01:{(v<.01).sum()} <0.02:{(v<.02).sum()}")
if "--list" in sys.argv:
    col = int(sys.argv[sys.argv.index("--list") + 1])
    for r in rows:
        if r[0] == col: print(f"  col{r[0]} pos{r[1]:>2} occ={r[2]} 粗笔画率 {r[3]:.3f}")
