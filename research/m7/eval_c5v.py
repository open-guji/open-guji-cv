# -*- coding: utf-8 -*-
"""M7 C5 评测（含竖切）：42 格留一法。--hcut human|auto(直线)；--vcut human|auto(vertical_seam)。"""
import argparse, json, copy
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups.ids import IdsResolver
from open_guji_cv.groups.ids_solver import add_real, solve
NM = {"⺕": "彐", "彑": "彑", "糸": "米糸", "米+分": "米分", "廾": "廾", "大": "大"}
SL = {"彝": 0, "彞": 0, "彜": 0, "彛": 0, "𢑴": 0, "𢑱": 0}
ap = argparse.ArgumentParser(); ap.add_argument("--dataset"); ap.add_argument("--hpoly"); ap.add_argument("--vdone"); ap.add_argument("--vcut", default="human")
a = ap.parse_args()
D = Path(a.dataset) / "char-groups/variant/yi_560"
labs = [json.loads(l) for l in open(D / "user_parts_labels.jsonl")]
def load_poly(fn):
    out = {}
    for l in open(fn):
        r = json.loads(l); v = r["verdict"]
        if isinstance(v, str) and v.startswith("poly:"): out[r["id"]] = json.loads(v[5:])
    return out
H = load_poly(a.hpoly); V = load_poly(a.vdone)
cells = []
for L in labs:
    if L["id"] not in H: continue
    g = np.asarray(Image.open(D / "crops" / (L["id"].replace(":", "_") + ".png")).convert("L"))
    cells.append((L, g, tuple(H[L["id"]]), V[L["id"]][0] if L["id"] in V else None))
res = {m: Counter() for m in (0.0, 0.02, 0.05)}; slot = [0, 0, 0]
for i, (L, g, pl, vc) in enumerate(cells):
    bank = {0: {}, 1: {}, 2: {}}
    for j, (L2, g2, pl2, vc2) in enumerate(cells):
        if j != i: add_real(bank, g2, tuple(NM[L2[k]] for k in ("top", "mid", "bot")), pl2, vc2)
    want = tuple(NM[L[k]] for k in ("top", "mid", "bot"))
    for m in res:
        v = solve(g, bank, IdsResolver(list(SL), "config/groups/yi_560"), pl, min_margin=m, vcut=vc if a.vcut == "human" else None)
        if m == 0.0:
            for k in range(3): slot[k] += v.slots[k] == want[k]
        res[m]["abstain" if v.char is None else "right" if v.slots == want else "wrong"] += 1
print("per-slot (margin0):", slot, "/", len(cells), " vcut:", a.vcut)
for m, c in res.items(): print("min_margin", m, dict(c))
for i, (L, g, pl, vc) in enumerate(cells):
    bank = {0: {}, 1: {}, 2: {}}
    for j, (L2, g2, pl2, vc2) in enumerate(cells):
        if j != i: add_real(bank, g2, tuple(NM[L2[k]] for k in ("top", "mid", "bot")), pl2, vc2)
    want = tuple(NM[L[k]] for k in ("top", "mid", "bot"))
    v = solve(g, bank, IdsResolver(list(SL), "config/groups/yi_560"), pl, min_margin=0.0, vcut=vc)
    if v.slots != want: print("WRONG", L["id"], "want", want, "got", v.slots, v.margins)
