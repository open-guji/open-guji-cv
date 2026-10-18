# -*- coding: utf-8 -*-
"""M7 IDS 扩展：两段版留一评测。

    python research/m7/ids2/eval_two.py <shen|can> <done.jsonl> <crops_dir>

done.jsonl 每行 {"id","f":字形,"p":[[x,y],…]}（harvest_verdicts.py 从标注页收回；f 为 ?／x 的行忽略）。
对每个已标格：模板库只用**其余**格的人标（留一）；分别用人标切线（oracle）与自动缝（auto）判字，
报 right／abstain／wrong（按 min_margin 0／0.02／0.05），并报自动缝与人标切线在墨迹像素上的归边一致率。
"""
import json, sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from open_guji_cv.groups import ids_two as T
from open_guji_cv.groups.ids import IdsResolver
from open_guji_cv.groups.ids_segment import ink_of

CFG = {"shen": dict(members="慎愼", orient="v", prior=0.33, frame="⿰忄{}", dir="config/groups/shen"),
       "can": dict(members="參㕘", orient="h", prior=0.52, frame="⿱厽{}", dir="config/groups/can")}
c = CFG[sys.argv[1]]
rows = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
rows = [r for r in rows if r["f"] in c["members"] and len(r["p"]) >= 2]
crops = Path(sys.argv[3])
G = {r["id"]: np.asarray(Image.open(crops / (r["id"].replace(":", "_") + ".png")).convert("L")) for r in rows}
res = resolver = IdsResolver(list(c["members"]), c["dir"])
print("labeled", len(rows), dict(Counter(r["f"] for r in rows)))
# 自动缝与人标切线的一致率
acc = []
for r in rows:
    g = G[r["id"]]; ink = ink_of(g)
    a = T.cut_mask(g.shape, T.auto_cut(g, c["orient"], c["prior"]) or r["p"], c["orient"])
    b = T.cut_mask(g.shape, r["p"], c["orient"])
    acc.append(float((a[ink] == b[ink]).mean()))
print("auto-cut ink-pixel agreement: mean %.3f  min %.3f" % (np.mean(acc), np.min(acc)))
out = {(m, cut): Counter() for m in (0.0, 0.02, 0.05) for cut in ("oracle", "auto")}; wrong = []
for r in rows:
    bank = {}
    for o in rows:
        if o["id"] != r["id"]:
            T.add_real(bank, G[o["id"]], T.slot_name(resolver, o["f"], c.get("which", 1)), o["p"], c["orient"], c.get("which", 1))
    for m in (0.0, 0.02, 0.05):
        for cut in ("oracle", "auto"):
            v = T.solve_two(G[r["id"]], bank, resolver, c["frame"], c["orient"], c["prior"],
                            polyline=r["p"] if cut == "oracle" else None, which=c.get("which", 1), min_margin=m)
            k = "abstain" if v.char is None else "right" if v.char == r["f"] else "wrong"
            out[(m, cut)][k] += 1
            if k == "wrong" and m == 0.02: wrong.append((r["id"], r["f"], v.char, cut, v.margins))
for k, v in out.items(): print("min_margin %.2f %-6s" % k, dict(v))
for w in wrong: print("WRONG", *w)
