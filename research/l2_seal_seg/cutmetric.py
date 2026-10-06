"""切点切字率：每个格上沿（页坐标）是否压在「字身墨」上。字身墨 = 原图面积>150 的连通块
（印章斑点面积≤150，被排除；字的笔画主体都 >150）。
用法: python cutmetric.py <prods> <book> <page> [img.png]   输出 遮挡格内/外 分开报。"""
import json, sys, os, types
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells

def metric(prods, book, page, imgpath, verbose=True):
    cs = json.load(open(f"{prods}/{book}/row_segment/p{page:04d}.json"))["cells"]
    img = cv2.imread(imgpath, 0)
    b = (img < 128).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    big = np.zeros(n, bool); big[1:] = st[1:, cv2.CC_STAT_AREA] > 150
    ink = big[lab]
    cells = types.SimpleNamespace(columns=[types.SimpleNamespace(col=c["col"], cells=[types.SimpleNamespace(slot=x.get("slot", x["pos"]), sub=x.get("sub"), quad_page=x.get("quad_page")) for x in c["cells"]]) for c in cs["columns"]])
    occ = occluded_cells(cell_densities(img, cells))
    rows = []
    for c in cs["columns"]:
        for x in c["cells"]:
            q = x.get("quad_page")
            if not q or x["kind"] != "char": continue
            (xr, yr), (xl, yl) = q[0], q[1]   # 上沿 右→左
            m = 0.12 * abs(xr - xl)
            ts = np.linspace(m, abs(xr - xl) - m, 40)
            xs = xr + (xl - xr) * ts / abs(xr - xl); ys = yr + (yl - yr) * ts / abs(xr - xl)
            fr = []
            for dy in (-2, -1, 0, 1, 2):
                yy = np.clip((ys + dy).astype(int), 0, img.shape[0] - 1); xx = np.clip(xs.astype(int), 0, img.shape[1] - 1)
                fr.append(ink[yy, xx].mean())
            key = (c["col"], x.get("slot", x["pos"]), x.get("sub") or "")
            rows.append((key in occ, float(np.mean(fr)), c["col"], x["pos"]))
    return rows

if __name__ == "__main__":
    prods, book, page = sys.argv[1], sys.argv[2], int(sys.argv[3])
    W = os.environ["GUJI_WORKSPACE"]
    rows = metric(prods, book, page, sys.argv[4] if len(sys.argv) > 4 else f"{W}/data_full/zongmu/{book}/{page}.png")
    for name, sel in (("遮挡格", True), ("非遮挡", False)):
        v = np.array([r[1] for r in rows if r[0] == sel])
        if len(v): print(f"{book} p{page} {name}: n={len(v)} 上沿字身墨率均值 {v.mean():.3f}  >0.25 的 {int((v>0.25).sum())} ({(v>0.25).mean()*100:.0f}%)")
