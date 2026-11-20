"""书级部件刻形判法训练（全唐文 995ejelvk0，码位线 2026-11-15）→ `config/groups/part_shape.json`（schema `part_shape/1`，
管线前向见 `open_guji_cv/groups/part_shape.py`，numpy 算、不依赖 torch）。网络、增广、训练与 `wu/qtw_wu_shape_train.py` 相同，
只把「口旁右半的上 75%」换成每对自带的 `box`（占墨边宽高的比例）。一份文件挂多对，一次训一对、`--out` 已有就并进去（同对覆盖）。

数据：字块目录（<格号>.png，char_patch 灰度）＋标签 JSON {格号: 字}（字必须是这一对里的）。

    # 训一对并并入模型文件；--cv 按册（格号前 3 位）5 折留出，报准确率、高把握覆盖、错
    python research/char_groups/part_shape/train.py --patches P --labels L.json --pair 剌刺 --box 0,0.65,0,1 --t 0.95 --out part_shape.json --cv
    # 用已有模型给一批字块打分（p＝对里第二个字的概率），挑低把握格补标
    python research/char_groups/part_shape/train.py --score P --pair 剌刺 --out part_shape.json > scores.tsv

11-15 全唐文（Sheldon 按字形标 319 格，001–120）：剌刺 左 65% 全高 留出 96.6%、p≥0.95 覆盖 67% 错 0；疎踈 左 50% 上 60% 99.2%、覆盖 78% 错 1。
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn

from open_guji_cv.groups.part_shape import SCHEMA, prep

S = 64


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.f = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                               nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                               nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2), nn.Flatten(), nn.Dropout(.3),
                               nn.Linear(64 * 8 * 8, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, x):
        return self.f(x).squeeze(1)


def aug(x):
    out = []
    for im in x:
        M = cv2.getRotationMatrix2D((S / 2, S / 2), np.random.uniform(-4, 4), np.random.uniform(.92, 1.08))
        M[:, 2] += np.random.uniform(-3, 3, 2)
        out.append(cv2.warpAffine(im, M, (S, S)))
    return np.array(out)


def train(X, Y, ep=40, seed=0):
    torch.manual_seed(seed)
    np.random.seed(seed)
    net = Net()
    opt = torch.optim.Adam(net.parameters(), 1e-3, weight_decay=1e-4)
    lf = nn.BCEWithLogitsLoss()
    for _ in range(ep):
        net.train()
        idx = np.random.permutation(len(X))
        for j in range(0, len(X), 32):
            b = idx[j:j + 32]
            opt.zero_grad()
            lf(net(torch.tensor(aug(X[b]))[:, None]), torch.tensor(Y[b], dtype=torch.float32)).backward()
            opt.step()
    return net


def predict(net, X):
    net.eval()
    with torch.no_grad():
        return torch.sigmoid(net(torch.tensor(X)[:, None])).numpy()


def _enc(a):
    return {"shape": list(a.shape), "dtype": "<f2", "b64": base64.b64encode(a.astype("<f2").tobytes()).decode()}


def _patches(d: Path, cells, box):
    X, keep = [], []
    for c in cells:
        x = prep(cv2.imread(str(d / f"{c}.png"), 0), box, S)
        if x is not None:
            X.append(x)
            keep.append(c)
    return np.array(X), keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patches")
    ap.add_argument("--labels")
    ap.add_argument("--score", help="字块目录：用 --out 里这一对的模型打分，输出 格号\\tp")
    ap.add_argument("--pair", required=True, help="两个字，如 剌刺（p＝第二个字的概率）")
    ap.add_argument("--box", default="0,1,0,1", help="x0,x1,y0,y1，占墨边宽高的比例")
    ap.add_argument("--t", type=float, default=0.95)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cv", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    model = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"schema": SCHEMA, "pairs": []}
    if a.score:
        from open_guji_cv.groups import part_shape
        pr = part_shape.pair_of(part_shape.load(str(out)), a.pair[0])
        d = Path(a.score)
        for f in sorted(d.glob("*.png")):
            p = part_shape.prob(cv2.imread(str(f), 0), pr)
            print(f"{f.stem}\t{'' if p is None else round(p, 4)}")
        return
    box = [float(v) for v in a.box.split(",")]
    lab = json.loads(Path(a.labels).read_text(encoding="utf-8"))
    X, cs = _patches(Path(a.patches), sorted(lab), box)
    Y = np.array([lab[c] == a.pair[1] for c in cs]).astype(int)
    if a.cv:
        V = np.array([c[:3] for c in cs])
        vols = sorted(set(V))
        P = np.zeros(len(cs))
        for f in (vols[i::5] for i in range(5)):
            m = np.isin(V, f)
            P[m] = np.mean([predict(train(X[~m], Y[~m], seed=sd), X[m]) for sd in (0, 1, 2)], 0)      # 同正式模型：三个种子取平均
        err, hi = (P > .5) != Y, (P >= a.t) | (P <= 1 - a.t)
        print(f"{a.pair} n={len(cs)} 准确率 {1 - err.mean():.3f}；p≥{a.t}/≤{1 - a.t:.2f} 覆盖 {hi.mean():.3f}、错 {int((err & hi).sum())}")
    nets = [train(X, Y, seed=s) for s in (0, 1, 2)]
    pair = {"chars": list(a.pair), "box": box, "size": S, "t": a.t,
            "nets": [{k: _enc(v.numpy()) for k, v in n.state_dict().items()} for n in nets]}
    model["pairs"] = [p for p in model["pairs"] if p["chars"] != list(a.pair)] + [pair]
    out.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
