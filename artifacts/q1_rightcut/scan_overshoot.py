# -*- coding: utf-8 -*-
"""Q1：右缘穿边组件「越界量」无上限重扫（给 RIGHT_RESCUE_MAX 定依据）。

与 scan_cut_crossings_v2.crossings_right 同判据（高≤30、面积≥25、内≥6、外≥4），
但探测窗右端开到 sx1+WIN（默认 60，受列图宽限制），不受 RIGHT_RESCUE_MAX 截断；
每个穿边组件记形状/位置，供区分「笔画尖」与「列尾版框残段」。
用法：python artifacts/q1_rightcut/scan_overshoot.py out.jsonl
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "artifacts/m1_gold/left_cut"))
from _v2_step4 import V2Book, dataset_root
from open_guji_cv.clustering import extractor as X
from scan_cut_crossings_v2 import body_pages

WIN = 60
def main(out):
    pages = body_pages(dataset_root())
    f = open(out, "w", encoding="utf-8")
    for book, pgs in pages.items():
        v = V2Book(book); v.ensure(pgs)
        for pg in pgs:
            cells = v.cells(pg)
            if cells is None or v.chars(pg) is None: continue
            for cc in cells.columns:
                if not cc.ok or not cc.content_x: continue
                img = v.col_img(pg, cc.col); H, W = img.shape
                x1 = int(round(cc.content_x[1]))
                if x1 + X.RIGHT_RESCUE_OUT >= W: continue
                ink_cells = [c for c in cc.cells if c.kind != "blank"]
                last_y1 = max((c.y1 for c in ink_cells), default=0)
                a, b = max(0, x1 - 40), min(W, x1 + WIN)
                zone = (img[:, a:b] < X.BINARY_THRESHOLD_PATCH).astype(np.uint8)
                fence = x1 - a
                n, _l, st, _c = cv2.connectedComponentsWithStats(zone, 8)
                for k in range(1, n):
                    x, y, w, h, area = (int(t) for t in st[k])
                    if h > X.RIGHT_RESCUE_H or area < X.RIGHT_RESCUE_AREA: continue
                    if x <= fence - X.RIGHT_RESCUE_IN and x + w >= fence + X.RIGHT_RESCUE_OUT:
                        cy = y + h // 2
                        if 12 < cy < H - 12:
                            f.write(json.dumps({"book": book, "page": pg, "col": cc.col, "y": cy, "h": h, "w": w,
                                "area": area, "over": x + w - fence, "in": fence - x, "W": W, "x1": x1,
                                "room": W - x1, "hit_edge": int(a + x + w >= W - 1), "win_clip": int(x + w >= b - a),
                                "tail_gap": int(cy - last_y1), "H": H}) + "\n")
            f.flush()
main(sys.argv[1])
