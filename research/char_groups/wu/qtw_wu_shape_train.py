"""嗚鳴 书级刻形判法训练（全唐文 995ejelvk0，形近字线 2026-11-14）→ `config/groups/wu_shape.json`（schema `wu_shape/1`，
管线前向见 `open_guji_cv/groups/wu_shape.py`，numpy 算、不依赖 torch）。

数据：字块目录（<格号>.png，char_patch 灰度）＋ 标签 JSON {格号: 嗚|鳴}。全唐文用的是 031–105 嗚鳴放行格（按文意核过，1,183）
加 Sheldon 11-14「嗚鳴17格」刻形点选；嗚呼刻成 鳴 的格记 鳴（照刻形）。
预处理同 `wu_shape.prep`（口旁右边那一半的上 75%，64×64）；小卷积网（3×[3×3 卷积→ReLU→2×2 池化]、Dropout、64、1），
随机小旋转／缩放／平移增广，Adam 1e-3、30 轮；三个种子取平均。

    python research/char_groups/wu/qtw_wu_shape_train.py --patches <目录> --labels labels.json --out wu_shape.json [--cv]

`--cv`：按册分 5 折留出（格号前 3 位是册），报准确率与 p≥0.99/≤0.01 的覆盖、错数（11-14：1,199 格两次各错 2、0；覆盖约 98%、0 错）。
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

from open_guji_cv.groups.wu_shape import SCHEMA, prep

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


def train(X, Y, ep=30, seed=0):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patches", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cv", action="store_true")
    a = ap.parse_args()
    lab = json.loads(Path(a.labels).read_text(encoding="utf-8"))
    cs = sorted(lab)
    X = np.array([prep(cv2.imread(str(Path(a.patches) / f"{c}.png"), 0)) for c in cs])
    Y = np.array([lab[c] == "鳴" for c in cs]).astype(int)
    if a.cv:
        V = np.array([c[:3] for c in cs])
        vols = sorted(set(V))
        P = np.zeros(len(cs))
        for f in (vols[i::5] for i in range(5)):
            m = np.isin(V, f)
            P[m] = predict(train(X[~m], Y[~m]), X[m])
        err, hi = (P > .5) != Y, (P >= .99) | (P <= .01)
        print(f"n={len(cs)} 错 {int(err.sum())}；p≥0.99/≤0.01 覆盖 {hi.mean():.3f}、错 {int((err & hi).sum())}")
    nets = [train(X, Y, seed=s) for s in (0, 1, 2)]
    model = {"schema": SCHEMA, "chars": ["嗚", "鳴"], "size": S, "top": 0.75, "t": 0.99,
             "nets": [{k: _enc(v.numpy()) for k, v in n.state_dict().items()} for n in nets]}
    Path(a.out).write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
