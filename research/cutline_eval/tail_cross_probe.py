"""探针:末格顶边(=上一格下沿)处,字墨是否"跨切线连续"(顶边上下 4px 窗内同一 x 两侧都有墨的占比,取顶边中间 76%)。
用于检验"末格矮→并回上格"能否加这个条件区分「末字被劈」与「空/框尾格」。用法: python3 -I tail_cross_probe.py  (读 tail_runt_scan_all.json;路径见脚本内 ROOT/WS)"""
import json, cv2, numpy as np
WS = "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本"
ROOT = {"vol01": "/home/user/wsall/vol01/cloud-20260927-32b9c2b/vol01", "vol02": WS + "/products/vol02", "vol03": "/home/user/wsall/vol03/products/vol03", "vol04": "/home/user/ws4/products/vol04",
        "vol05": "/home/user/wsall/vol05/products/vol05", "vol06": "/home/user/wsall/vol06/products/vol06", "vol07": "/home/user/wsall/vol07/products/vol07",
        "vol08": "/home/user/wsall/vol08/products/vol08", "vol09": "/home/user/wsall/vol09/products/vol09", "vol10": "/home/user/wsall/vol10/products/vol10"}
SPLIT = {("vol01", 95, 6), ("vol03", 67, 9), ("vol04", 196, 2), ("vol04", 196, 8), ("vol05", 3, 5), ("vol05", 46, 8), ("vol05", 108, 2), ("vol05", 154, 8), ("vol06", 18, 9), ("vol06", 46, 1), ("vol06", 46, 6),
         ("vol07", 87, 8), ("vol08", 21, 4), ("vol09", 108, 2), ("vol09", 132, 2), ("vol09", 255, 9), ("vol10", 175, 6)}   # 我对叠图的读法:末字被劈
scan = json.load(open(__file__.replace("tail_cross_probe.py", "tail_runt_scan_all.json"))); rows = []
for bk, (_, _, _, hits) in scan.items():
    for pg, col, h, per, ratio, ink in hits:
        g = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{bk}/{pg}.png", np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is None: continue
        cc = next(x for x in json.load(open(f"{ROOT[bk]}/row_segment/p{pg:04d}.json"))["cells"]["columns"] if x["col"] == col)
        cell = max(cc["cells"], key=lambda x: x["slot"]); W = g.shape[1]; q = [(W - 1 - x, y) for x, y in cell["quad_page"]]
        a, b = np.array(q[0]), np.array(q[1]); n = 80; cross = 0
        for t in np.linspace(0.12, 0.88, n):
            x, y = a + (b - a) * t; x, y = int(round(x)), int(round(y))
            cross += bool((g[max(0, y - 5):y - 1, x] < 128).any() and (g[y + 1:y + 5, x] < 128).any())
        rows.append((bk, pg, col, round(cross / n, 2), ink, (bk, pg, col) in SPLIT))
for r in sorted(rows, key=lambda r: (not r[5], -r[3])): print(r)
sp = [r[3] for r in rows if r[5]]; em = [r[3] for r in rows if not r[5]]
print("被劈 cross 范围", min(sp), max(sp), "中位", float(np.median(sp)), "| 空/框", min(em), max(em), "中位", float(np.median(em)))
