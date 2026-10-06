# -*- coding: utf-8 -*-
"""字框「包没包全墨」：对每个 CV 字框，取与它重叠最大的 YOLO 原生框，比两框各自漏掉的墨。

    python inkcheck.py <probe2_raw.json> <原图目录> <guji-page 目录> <输出目录>

只看两框的并集范围内的墨（同列、上下各外扩 0）：
- cv_miss  = 墨在 YOLO 框里、不在 CV 框里 / 并集内墨
- yo_miss  = 墨在 CV 框里、不在 YOLO 框里 / 并集内墨
「一」这类单笔字 YOLO 框大、CV 框紧，但多出来的地方没有墨，两个数都≈0——IoU 低不算分歧。
并集里也可能混进上下邻字的笔画（粘连处 YOLO 框互相重叠），所以 >0.25 的都出图人看。
"""
import json, os, random, sys
from collections import Counter
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from open_guji_cv.formats import guji_page as gp
from sheets import tile, sheet, cv_boxes_near, yo_boxes_near, im, imgs, pages  # noqa

RAW, IMG, GPD, OUT = sys.argv[1:5]
d = json.load(open(RAW))
ink = {}
res = []
for r in d["rows"]:
    p = r["page"]
    if p not in ink:
        ink[p] = (cv2.cvtColor(im(p), cv2.COLOR_BGR2GRAY) < 128)
    cvb = r["box"]
    cands = [e["box"] for e in d["extra"] if e["page"] == p and e["feed"] == "native"] + \
            [x["nat_box"] for x in d["rows"] if x["page"] == p and x["nat_box"]]
    best = max(cands, key=lambda b: gp.iou(b, cvb), default=None)
    if best is None or gp.iou(best, cvb) == 0:
        res.append(dict(r, cv_miss=None, yo_miss=None)); continue
    u = gp.union_xywh([cvb, best])
    m = ink[p][u[1]:u[1] + u[3], u[0]:u[0] + u[2]]
    def mask(b):
        z = np.zeros_like(m)
        z[max(0, b[1] - u[1]):b[1] + b[3] - u[1], max(0, b[0] - u[0]):b[0] + b[2] - u[0]] = True
        return z
    mc, my = mask(cvb), mask(best)
    tot = max(1, int(m.sum()))
    res.append(dict(r, yo_box=best, cv_miss=float((m & my & ~mc).sum() / tot), yo_miss=float((m & mc & ~my).sum() / tot)))

def cnt(sub, k, t=0.25):
    return sum(1 for x in sub if x[k] is not None and x[k] > t)
tags = ["(全部)", "正文", "双行夹注", "单行小注", "列首字", "列尾字", "粘连", "粘连·难", "印章压字", "短列"]
print("== 并集内墨被某一方漏掉 >25% 的字框数（CV 漏 / YOLO 漏 / 无 YOLO 框）")
for t in tags:
    sub = res if t == "(全部)" else [x for x in res if t in x["tags"]]
    if sub:
        print(f"  {t:6s} n={len(sub):5d}  CV漏 {cnt(sub,'cv_miss'):4d}  YOLO漏 {cnt(sub,'yo_miss'):4d}  无框 {sum(1 for x in sub if x['cv_miss'] is None)}")
random.seed(3)
for k, name in (("cv_miss", "9_cv_partial"), ("yo_miss", "10_yolo_partial")):
    sub = sorted([x for x in res if x[k] is not None and x[k] > 0.25], key=lambda x: -x[k])
    pick = sub[:12] + random.sample(sub[12:], min(18, max(0, len(sub) - 12)))
    T = []
    for x in pick:
        u = gp.union_xywh([x["box"], x["yo_box"]]); reg = [u[0] - 40, u[1] - 50, u[2] + 80, u[3] + 100]
        T.append(tile(x["page"], reg, [x["box"]], [x["yo_box"]], f"p{x['page']}c{x['col']}s{x['slot']} {x[k]:.2f} {''.join(x['tags'][1:3])}"))
    sheet(T, f"{OUT}/{name}.jpg")
json.dump(res, open(f"{OUT}/inkcheck.json", "w"), ensure_ascii=False)
