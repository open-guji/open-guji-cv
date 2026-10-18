# -*- coding: utf-8 -*-
"""M7 IDS 扩展：从 cells.json 选出要标的格，机器预画一条切线，写 cells_<组>.jsonl（冻结顺序）。
    python research/m7/ids2/make_cards.py <cells.json> <crops_dir> <out_dir>
shen：全部 core 格（33）；can：㕘 全部（整理本/放行为㕘）+ 随机 41 个參（seed 0），打乱。
"""
import json, random, sys
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups.ids_segment import ink_of, seam_polyline

cells, crops, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rows = [r for r in json.load(open(cells, encoding="utf-8")) if r["core"]]
def form(r, m): return next((x for x in (r["ref"], r["admit_char"], r["char"]) if x and x in m), None)
def pre(i, orient, prior):
    g = np.asarray(Image.open(crops / (i.replace(":", "_") + ".png")).convert("L"))
    ink = ink_of(g)
    if not ink.any(): return None
    if orient == "h":
        return [[round(x, 4), round(y, 4)] for x, y in seam_polyline(ink, prior, band=0.15, step=8)]
    t = seam_polyline(ink.T, prior, band=0.12, step=8)           # 转置：横向缝 → 竖向缝
    return [[round(y, 4), round(x, 4)] for x, y in t]
def write(name, sel, orient, prior, m):
    with open(out / f"cells_{name}.jsonl", "w", encoding="utf-8") as f:
        for r in sel:
            f.write(json.dumps({"id": r["id"], "hint": form(r, m) or r["char"], "pre": pre(r["id"], orient, prior)}, ensure_ascii=False) + "\n")
    print(name, len(sel))
out.mkdir(parents=True, exist_ok=True)
shen = sorted([r for r in rows if r["group"] == "shen"], key=lambda r: r["id"])
write("shen", shen, "v", 0.33, "慎愼")
can = [r for r in rows if r["group"] == "can"]
a = [r for r in can if form(r, "參㕘") == "㕘"]
b = [r for r in can if form(r, "參㕘") == "參"]
random.Random(0).shuffle(b); sel = a + b[:41]; random.Random(1).shuffle(sel)
write("can", sel, "h", 0.52, "參㕘")
