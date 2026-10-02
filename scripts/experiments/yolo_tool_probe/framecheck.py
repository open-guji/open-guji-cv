# -*- coding: utf-8 -*-
"""列首列尾的版框噪声：字框有没有压到上/下版框线（Step1 内框线心 ±3px），按喂法分开数。

    python framecheck.py <probe2_raw.json>
"""
import json, sys
from collections import Counter

d = json.load(open(sys.argv[1]))
TOL = 3


def crosses(b, ytop, ybot):
    y0, y1 = b[1], b[1] + b[3]
    return ("上框" if y0 <= ytop + TOL else "") + ("下框" if y1 >= ybot - TOL else "")


c = Counter()
lst = []
for r in d["rows"]:
    for who, b in (("CV", r["box"]), ("YOLO原生", r["nat_box"]), ("YOLO列条", r["strip_box"])):
        if not b:
            continue
        k = crosses(b, r["frame_top"], r["frame_bot"])
        c[(who, "n")] += 1
        if k:
            c[(who, k)] += 1
            if who == "CV":
                lst.append((r["page"], r["col"], r["slot"], k))
for who in ("CV", "YOLO原生", "YOLO列条"):
    print(who, "字框数", c[(who, "n")], "压上框", c[(who, "上框")], "压下框", c[(who, "下框")])
print("CV 压框的字位", lst)
for feed in ("native", "cvstrip"):
    e = [x for x in d["extra"] if x["feed"] == feed and x["where"].startswith("版框")]
    print(feed, "落在版框沿、CV 没有对应字的 YOLO 多余框", len(e), "其中置信≥0.5", sum(1 for x in e if x["conf"] >= 0.5))
