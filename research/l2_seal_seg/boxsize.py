"""Step4 字框被撑大了吗：bbox 宽/列宽、高/格高，遮挡格 vs 非遮挡格 vs 干净页。
用法: python boxsize.py <prods> <book> <page> [img]"""
import json, sys, os, types
import numpy as np, cv2
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
prods, book, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
W = os.environ["GUJI_WORKSPACE"]
img = cv2.imread(sys.argv[4] if len(sys.argv) > 4 else f"{W}/data_full/zongmu/{book}/{page}.png", 0)
L = lambda s: json.load(open(f"{prods}/{book}/{s}/p{page:04d}.json"))
cs = L("row_segment")["cells"]; ci = L("cell_shrink")["char_index"]
cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x.get("slot", x["pos"]), sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs["columns"]])
occ = occluded_cells(cell_densities(img, cells))
cw = {c["col"]: np.median([np.linalg.norm(np.array(x["quad_page"][0]) - np.array(x["quad_page"][1])) for x in c["cells"] if x.get("quad_page")]) for c in cs["columns"]}
slotof = {(c["col"], x["pos"]): (x.get("slot", x["pos"]), x.get("sub") or "") for c in cs["columns"] for x in c["cells"]}
R = {True: [], False: []}
for c in ci["columns"]:
    for ch in c["chars"]:
        if ch["cell_type"] != "char": continue
        s, sub = slotof.get((c["col"], ch["pos"]), (ch["pos"], ""))
        b = ch["bbox_col"]; w = (b[2] - b[0]) / cw[c["col"]]; h = (b[3] - b[1]) / cw[c["col"]]
        R[(c["col"], s, sub) in occ].append((w, h, ch["ink_ratio"], "boundary_ink" in ch["flags"] or "edge_blob" in ch["flags"]))
for k, nm in ((True, "遮挡格"), (False, "非遮挡")):
    v = np.array(R[k], float)
    if len(v): print(f"{book} p{page} {nm}: n={len(v)} 框宽/列宽 中位 {np.median(v[:,0]):.2f} (>0.9: {(v[:,0]>0.9).mean()*100:.0f}%)  框高/列宽 中位 {np.median(v[:,1]):.2f}  ink中位 {np.median(v[:,2]):.2f}  boundary/edge 旗 {v[:,3].mean()*100:.0f}%")
