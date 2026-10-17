# -*- coding: utf-8 -*-
"""M7 C5 评测：42 格人标读法，留一法（真实模板不含自己）。
用法: python research/m7/eval_c5.py --dataset <open-guji-dataset> [--verdicts verdicts.jsonl] [--fonts]
有 --verdicts 时，已标折线的格用人标折线切（其余仍用直线基线）。"""
import argparse, json, copy
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups.ids import IdsResolver
from open_guji_cv.groups.ids_parts import build_bank
from open_guji_cv.groups.ids_solver import add_real, solve

NM = {"⺕": "彐", "彑": "彑", "糸": "米糸", "米+分": "米分", "廾": "廾", "大": "大"}
SL = {"彝": ("彑", "米糸", "廾"), "彞": ("彐", "米糸", "廾"), "彜": ("彑", "米分", "廾"),
      "彛": ("彐", "米分", "廾"), "𢑴": ("彐", "米糸", "大"), "𢑱": ("彑", "米分", "大")}
ap = argparse.ArgumentParser(); ap.add_argument("--dataset"); ap.add_argument("--verdicts"); ap.add_argument("--fonts", action="store_true")
a = ap.parse_args()
D = Path(a.dataset) / "char-groups/variant/yi_560"
labs = [json.loads(l) for l in open(D / "user_parts_labels.jsonl")]
poly = {}
if a.verdicts:
    for l in open(a.verdicts):
        r = json.loads(l); v = r["verdict"]
        if isinstance(v, str) and v.startswith("poly:"):
            g = json.loads(v[5:]); poly[r["id"]] = g
def load(L):
    g = np.asarray(Image.open(D / "crops" / (L["id"].replace(":", "_") + ".png")).convert("L"))
    pl = None
    if L["id"] in poly:
        h, w = g.shape; pl = tuple([[x * w, y * h] if False else [x, y] for x, y in line] for line in poly[L["id"]])
    return g, pl
cells = [(L, *load(L)) for L in labs]
base = build_bank(SL) if a.fonts else {0: {}, 1: {}, 2: {}}
res = {m: Counter() for m in (0.0, 0.02, 0.05)}; slot_ok = [0, 0, 0]
for i, (L, g, pl) in enumerate(cells):
    bank = copy.deepcopy(base)
    for j, (L2, g2, pl2) in enumerate(cells):
        if j != i: add_real(bank, g2, tuple(NM[L2[k]] for k in ("top", "mid", "bot")), pl2)
    want = tuple(NM[L[k]] for k in ("top", "mid", "bot"))
    for m in res:
        v = solve(g, bank, IdsResolver(list(SL), "config/groups/yi_560"), pl, min_margin=m)
        if m == 0.0:
            for k in range(3): slot_ok[k] += (v.slots[k] == want[k])
        res[m]["abstain" if v.char is None else "right" if v.ids == "⿳%s⿰%s%s" % (want[0], want[1][0], want[1][1:] + want[2]) or (v.slots == want) else "wrong"] += 1
print("per-slot correct (margin 0):", slot_ok, "of", len(cells), " polylines used:", len(poly))
for m, c in res.items(): print("min_margin", m, dict(c))
