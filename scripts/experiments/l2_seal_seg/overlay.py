"""L2 印章页切分叠图：Step1 线 / Step3 列窗 / Step4 格框 + 遮挡格(红)。
用法: GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=… python overlay.py vol03 3 out.png [crop=x0,y0,x1,y1] [--prods DIR]"""
import json, sys, os
import cv2, numpy as np

def vline_x(v, y):
    x0, k1 = v["x_at_top"], v["slope"]
    k2, k3, y1, y2 = v.get("k2"), v.get("k3"), v.get("y1"), v.get("y2")
    if k2 is None: return x0 + k1 * y
    x = x0 + k1 * min(y, y1)
    if y > y1: x += k2 * (min(y, y2) - y1)
    if y > y2: x += k3 * (y - y2)
    return x

def main():
    book, page, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    crop = None
    for a in sys.argv[4:]:
        if a.startswith("crop="): crop = [int(t) for t in a[5:].split(",")]
    P = os.environ["GUJI_PRODUCTS_DIR"]; W = os.environ["GUJI_WORKSPACE"]
    ld = lambda s: json.load(open(f"{P}/{book}/{s}/p{page:04d}.json"))
    img = cv2.imread(os.environ.get("OVL_IMG") or f"{W}/data_full/zongmu/{book}/{page}.png", 0)
    bd = ld("border_detect")["borders"]; cs = ld("row_segment")["cells"]
    from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
    class C: columns = None
    import types
    cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x["pos"] if "slot" not in x else x["slot"], sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs["columns"]])
    dens = cell_densities(img, cells); occ = occluded_cells(dens)
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    H, Wd = img.shape
    for v in bd["verticals"]:
        pts = np.array([[vline_x(v, y), y] for y in range(0, H, 20)], np.int32)
        cv2.polylines(vis, [pts], False, (255, 0, 0), 3)
    for k in ("top", "bottom"):
        b = bd[k]; 
        if b: cv2.line(vis, (0, int(b["y_at_right"] - b["slope"] * Wd)), (Wd, int(b["y_at_right"])), (255, 0, 255), 3)
    for c in cs["columns"]:
        for x in c["cells"]:
            q = x.get("quad_page")
            if not q: continue
            key = (c["col"], x.get("slot", x["pos"]), x.get("sub") or "")
            col = (0, 0, 255) if key in occ else (0, 160, 0)
            cv2.polylines(vis, [np.array(q, np.int32)], True, col, 2)
    cs4 = ld("cell_shrink")["char_index"]
    for c in cs4["columns"]:
        for ch in c["chars"]:
            b = ch["bbox_page"]; cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 200, 255), 2)
    if crop: vis = vis[crop[1]:crop[3], crop[0]:crop[2]]
    cv2.imwrite(out, vis)
    print(book, page, "occluded cells:", len(occ), "size", img.shape)
main()
