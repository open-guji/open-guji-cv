# -*- coding: utf-8 -*-
"""Q1：recrop 未过条目逐条量「哪一侧越界多少、越界带里是什么墨」并出叠图。"""
import sys, json
from pathlib import Path
import cv2, numpy as np
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from _v2_step4 import V2Book, tr2tl
ds = REPO.parent / "open-guji-dataset/char-segmentation/instances"
gold = json.loads((ds / "recrop_v2.json").read_text(encoding="utf-8"))["items"]
TOL = 8
want = set(sys.argv[1:])
books = {}
out = REPO / "artifacts/q1_rightcut"
for e in gold:
    tag = f"{e['page']}:{e['col']}:{e['slot']}"
    if tag not in want: continue
    v = books.setdefault(e["book"], V2Book(e["book"])); pg = int(e["page"])
    pc = v.chars(pg); cc = pc.column(e["col"])
    rec = next(r for r in cc.chars if r.slot == e["slot"] and not r.sub and r.cell_type == "char" and r.bbox_page)
    scan = v.scan(pg); W = scan.shape[1]
    g = tr2tl(e["corrected_bbox"], W); o = tr2tl(e["old_bbox"], W); c = tr2tl(rec.bbox_page, W)
    side = {"L": g[0] - c[0], "T": g[1] - c[1], "R": c[2] - g[2], "B": c[3] - g[3]}   # >0 = 该侧超出金标框
    bad = {k: round(x, 1) for k, x in side.items() if x > TOL}
    ink = scan < 128
    # 超出金标框(+TOL)的那部分里的墨量
    x0, y0, x1, y1 = [int(round(t)) for t in c]
    gx0, gy0, gx1, gy1 = [int(round(t)) for t in g]
    mask = np.zeros(ink.shape, bool); mask[y0:y1, x0:x1] = True
    mask[max(0, gy0 - TOL):gy1 + TOL, max(0, gx0 - TOL):gx1 + TOL] = False
    extra = int((ink & mask).sum())
    print(f"{e['book']}/{tag} defect={e.get('defect')} 越界侧(px) {bad} 框外墨 {extra}px  flags={list(rec.flags)}  gold={tuple(round(t) for t in g)} cur={tuple(round(t) for t in c)}")
    pad = 60
    ya, yb, xa, xb = max(0, min(gy0, y0) - pad), min(scan.shape[0], max(gy1, y1) + pad), max(0, min(gx0, x0) - pad), min(W, max(gx1, x1) + pad)
    vis = cv2.cvtColor(scan[ya:yb, xa:xb], cv2.COLOR_GRAY2BGR)
    for b, col in ((g, (0, 160, 0)), (o, (0, 0, 255)), (c, (255, 0, 0))):
        cv2.rectangle(vis, (int(b[0] - xa), int(b[1] - ya)), (int(b[2] - xa), int(b[3] - ya)), col, 1)
    cv2.imwrite(str(out / f"recrop_{e['book']}_{e['page']}_c{e['col']}_s{e['slot']}.png"), cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
