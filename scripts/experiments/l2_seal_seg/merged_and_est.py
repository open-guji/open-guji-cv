"""(A) 次选方案离线估计：遮挡格 Step4 框若只认「面积>150 的连通块」，框宽/列宽 → ?（不改 extractor，只在现框内重算）
(B) 并格频率：格高 > 1.15×period 的 char 格数，遮挡格 vs 非遮挡格 vs 干净页。
用法: python merged_and_est.py <prods> <book> <page>"""
import json, sys, os, types
import numpy as np, cv2
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
prods, book, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
W = os.environ["GUJI_WORKSPACE"]
img = cv2.imread(f"{W}/data_full/zongmu/{book}/{page}.png", 0)
L = lambda s: json.load(open(f"{prods}/{book}/{s}/p{page:04d}.json"))
cs = L("row_segment")["cells"]["columns"]; ci = L("cell_shrink")["char_index"]["columns"]
cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x.get("slot", x["pos"]), sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs])
occ = occluded_cells(cell_densities(img, cells))
n, lab, st, _ = cv2.connectedComponentsWithStats((img < 128).astype(np.uint8), connectivity=8)
ok = np.zeros(n, bool); ok[1:] = st[1:, 4] > 150
# (B)
M = {True: [0, 0], False: [0, 0]}; ex = []
for c in cs:
    per = c.get("period") or np.median([abs(x["quad_page"][3][1] - x["quad_page"][0][1]) for x in c["cells"] if x.get("quad_page")])
    for x in c["cells"]:
        if x["kind"] not in ("char", "blank") or not x.get("quad_page"): continue
        q = np.array(x["quad_page"]); h = q[:, 1].max() - q[:, 1].min()
        o = (c["col"], x.get("slot", x["pos"]), x.get("sub") or "") in occ
        M[o][1] += 1
        if h > 1.15 * per: M[o][0] += 1; ex.append((c["col"], x["pos"], int(h), int(per), o))
print(f"{book} p{page} 并格候选(格高>1.15 period): 遮挡格 {M[True][0]}/{M[True][1]}  非遮挡格 {M[False][0]}/{M[False][1]}  例: {ex[:6]}")
# (A)
cw = {c["col"]: np.median([np.linalg.norm(np.array(x["quad_page"][0]) - np.array(x["quad_page"][1])) for x in c["cells"] if x.get("quad_page")]) for c in cs}
slot = {(c["col"], x["pos"]): (x.get("slot", x["pos"]), x.get("sub") or "") for c in cs for x in c["cells"]}
b4, a4 = [], []
for c in ci:
    for ch in c["chars"]:
        if ch["cell_type"] != "char" or not ch.get("bbox_page"): continue
        s, sub = slot.get((c["col"], ch["pos"]), (ch["pos"], ""))
        if (c["col"], s, sub) not in occ: continue
        x0, y0, x1, y1 = [int(round(v)) for v in ch["bbox_page"]]
        sub_l = lab[y0:y1, x0:x1]; m = ok[sub_l]
        # 只在格内重算；纵向长线（界行残段）不算
        if m.sum() < 30: continue
        xs = np.where(m.any(0))[0]; b4.append((x1 - x0) / cw[c["col"]]); a4.append((xs.max() - xs.min() + 1) / cw[c["col"]])
if b4: print(f"   (A) 遮挡格框宽/列宽 现 {np.median(b4):.2f} → 只认大块 {np.median(a4):.2f}；>0.9 占比 {np.mean(np.array(b4)>.9)*100:.0f}% → {np.mean(np.array(a4)>.9)*100:.0f}%  (n={len(b4)})")
