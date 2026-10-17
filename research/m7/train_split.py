# -*- coding: utf-8 -*-
"""M7 C3：训练/评测折线切分 U-Net。
用法: python research/m7/train_split.py --dataset <open-guji-dataset> --verdicts verdicts.jsonl [--cv 5] [--epochs 150] [--out net.pt] [--predict-rest out.jsonl]
--cv k: k 折交叉验证，报墨迹像素归段准确率（对比直线基线）；--predict-rest: 全量训练后给没有人标的格出预测折线。"""
import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image
from open_guji_cv.groups import ids_segment as S, ids_unet as U

ap = argparse.ArgumentParser()
ap.add_argument("--dataset"); ap.add_argument("--verdicts"); ap.add_argument("--cv", type=int, default=0)
ap.add_argument("--epochs", type=int, default=150); ap.add_argument("--out"); ap.add_argument("--predict-rest")
ap.add_argument("--cards", default="research/m7/cutline_cards.jsonl")
a = ap.parse_args()
D = Path(a.dataset) / "char-groups/variant/yi_560"
img = lambda i: np.asarray(Image.open(D / "crops" / (i.replace(":", "_") + ".png")).convert("L"))
V = {}
for l in open(a.verdicts):
    r = json.loads(l)
    if isinstance(r["verdict"], str) and r["verdict"].startswith("poly:"): V[r["id"]] = json.loads(r["verdict"][5:])
ids = list(V)
G = {i: img(i) for i in ids}
M = {i: S.polylines_to_mask(G[i].shape, *V[i]) for i in ids}
print("标注格数", len(ids))
def evaluate(net, test):
    ps, pb = [], []
    for i in test:
        ink = S.ink_of(G[i]); prob = U.predict_prob(net, G[i]); pred = prob.argmax(0)
        ps.append(S.pixel_accuracy(pred, M[i], ink))
        y1, y2 = S.straight_baseline(ink, 3)
        pb.append(S.pixel_accuracy(S.polylines_to_mask(G[i].shape, [[0, y1], [1, y1]], [[0, y2], [1, y2]]), M[i], ink))
    return ps, pb
if a.cv:
    rng = np.random.default_rng(0); order = rng.permutation(len(ids)); folds = np.array_split(order, a.cv)
    allu, allb = [], []
    for k, f in enumerate(folds):
        test = [ids[j] for j in f]; train = [i for i in ids if i not in test]
        net = U.train([(G[i], M[i]) for i in train], epochs=a.epochs, seed=k)
        pu, pb = evaluate(net, test); allu += pu; allb += pb
        print(f"fold {k}: unet {np.mean(pu):.3f} straight {np.mean(pb):.3f}", flush=True)
    print(f"CV 总: unet {np.mean(allu):.3f} (min {min(allu):.3f})  直线 {np.mean(allb):.3f}")
if a.out or a.predict_rest:
    net = U.train([(G[i], M[i]) for i in ids], epochs=a.epochs)
    if a.out:
        import torch; torch.save(net.state_dict(), a.out)
    if a.predict_rest:
        with open(a.predict_rest, "w") as fo:
            for l in open(a.cards):
                c = json.loads(l); i = c["id"] if isinstance(c, dict) else c
                if i in V: continue
                g = img(i); pl = U.prob_to_polylines(U.predict_prob(net, g))
                fo.write(json.dumps({"id": i, "pre": [[[round(x, 4), round(y, 4)] for x, y in line] for line in pl]}) + "\n")
