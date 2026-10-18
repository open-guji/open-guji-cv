# -*- coding: utf-8 -*-
"""M7 IDS 扩展：复审卡——挑出机器与整理本/放行字不一致、弃权、margin<阈值的未标格，隐藏参考字，顺序打乱，机器预画切线。
    python research/m7/ids2/make_review_cards.py <can|shen> <evidence.json> <crops_dir> <out.jsonl> [margin=0.05] [--also id,id…]
"""
import json, random, sys
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups.ids_segment import ink_of, seam_polyline

P = {"can": ("h", 0.52), "shen": ("v", 0.33)}
g, ev, crops, out = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")), Path(sys.argv[3]), Path(sys.argv[4])
thr = float(sys.argv[5]) if len(sys.argv) > 5 and not sys.argv[5].startswith("--") else 0.05
also = set(sys.argv[sys.argv.index("--also") + 1].split(",")) if "--also" in sys.argv else set()
orient, prior = P[g]
def cut(i):
    gr = np.asarray(Image.open(crops / (i.replace(":", "_") + ".png")).convert("L")); ink = ink_of(gr)
    if orient == "h": t = seam_polyline(ink, prior, band=0.15, step=8)
    else: t = [[y, x] for x, y in seam_polyline(ink.T, prior, band=0.12, step=8)]
    return [[round(x, 4), round(y, 4)] for x, y in t]
sel = []
for e in ev:
    if e["labeled"] and e["id"] not in also: continue
    ref = e["ref"] or e["admit"]
    if e["char"] is None or (ref and e["char"] != ref) or e["margins"][0] < thr or e["id"] in also: sel.append(e)
random.Random(7).shuffle(sel)
with open(out, "w", encoding="utf-8") as f:
    for e in sel: f.write(json.dumps({"id": e["id"], "hint": "", "pre": cut(e["id"])}, ensure_ascii=False) + "\n")
print(len(sel))
