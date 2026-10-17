# -*- coding: utf-8 -*-
"""M7 C5 端到端：k 折，U-Net 横切（折线）+ vertical_seam 竖切 + 真实模板 kNN；模板库只用训练折的人标。"""
import argparse, json
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups import ids_unet as U
from open_guji_cv.groups.ids import IdsResolver
from open_guji_cv.groups.ids_solver import add_real, solve
NM = {"⺕": "彐", "彑": "彑", "糸": "米糸", "米+分": "米分", "廾": "廾", "大": "大"}
ap = argparse.ArgumentParser(); ap.add_argument("--dataset"); ap.add_argument("--hpoly"); ap.add_argument("--vdone")
ap.add_argument("--epochs", type=int, default=120); ap.add_argument("--cv", type=int, default=5)
a = ap.parse_args()
D = Path(a.dataset) / "char-groups/variant/yi_560"
def lp(fn):
    o = {}
    for l in open(fn):
        r = json.loads(l); v = r["verdict"]
        if isinstance(v, str) and v.startswith("poly:"): o[r["id"]] = json.loads(v[5:])
    return o
H, V = lp(a.hpoly), lp(a.vdone)
labs = {json.loads(l)["id"]: json.loads(l) for l in open(D / "user_parts_labels.jsonl")}
ids = list(H)
G = {i: np.asarray(Image.open(D / "crops" / (i.replace(":", "_") + ".png")).convert("L")) for i in ids}
from open_guji_cv.groups.ids_segment import polylines_to_mask
M = {i: polylines_to_mask(G[i].shape, *H[i]) for i in ids}
rng = np.random.default_rng(0); folds = np.array_split(rng.permutation(len(ids)), a.cv)
res = {m: Counter() for m in (0.0, 0.02, 0.05)}; wrong = []
for k, f in enumerate(folds):
    test = [ids[j] for j in f]; train = [i for i in ids if i not in test]
    net = U.train([(G[i], M[i]) for i in train], epochs=a.epochs, seed=k)
    bank = {0: {}, 1: {}, 2: {}}
    for i in train: add_real(bank, G[i], tuple(NM[labs[i][s]] for s in ("top", "mid", "bot")), tuple(H[i]), V[i][0])
    for i in test:
        pl = U.prob_to_polylines(U.predict_prob(net, G[i]))
        want = tuple(NM[labs[i][s]] for s in ("top", "mid", "bot"))
        for m in res:
            v = solve(G[i], bank, IdsResolver(list("彝彞彜彛𢑴𢑱"), "config/groups/yi_560"), pl, min_margin=m)
            c = "abstain" if v.char is None else "right" if v.slots == want else "wrong"
            res[m][c] += 1
            if m == 0.0 and c == "wrong": wrong.append((i, want, v.slots, v.margins))
    print("fold", k, flush=True)
for m, c in res.items(): print("min_margin", m, dict(c))
for w in wrong: print("WRONG", *w)
