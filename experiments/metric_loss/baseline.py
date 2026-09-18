# -*- coding: utf-8 -*-
"""用现役 r4 checkpoint 在留出集上打基线——先确认这个集合可用，再花 GPU 训练。

r4 的类表是 4,654，留出的 1,200 字全在类表外，所以：
- **分类头对这些字必然 0%**（无法输出不存在的类）——顺手实测印证 06 卡 §二；
- embedding 检索能给出数字——这就是基线。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data import load_heldout_eval          # noqa: E402
from evaluate import retrieval_eval         # noqa: E402


class Block(nn.Module):
    def __init__(self, i, o, s):
        super().__init__()
        self.c1 = nn.Conv2d(i, o, 3, s, 1, bias=False)
        self.b1 = nn.BatchNorm2d(o)
        self.c2 = nn.Conv2d(o, o, 3, 1, 1, bias=False)
        self.b2 = nn.BatchNorm2d(o)
        self.sc = nn.Sequential(nn.Conv2d(i, o, 1, s, bias=False), nn.BatchNorm2d(o)) \
            if (s != 1 or i != o) else nn.Identity()

    def forward(self, x):
        y = F.relu(self.b1(self.c1(x)))
        y = self.b2(self.c2(y))
        return F.relu(y + self.sc(x))


class Net(nn.Module):
    """与现役 scripts/train_glyph_cnn.py 的 Net 完全一致。"""

    def __init__(self, n_cls, n_comp, d=256):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False),
                                  nn.BatchNorm2d(32), nn.ReLU())
        self.l1 = Block(32, 64, 2)
        self.l2 = Block(64, 128, 2)
        self.l3 = Block(128, 256, 2)
        self.l4 = Block(256, 256, 2)
        self.emb = nn.Linear(256 * 4 * 4, d)
        self.cls = nn.Linear(d, n_cls)
        self.comp = nn.Linear(d, n_comp)

    def forward(self, x):
        x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
        e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
        return e, self.cls(e), self.comp(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="models/glyph_cnn_r4/best.pt")
    ap.add_argument("--split", default="experiments/metric_loss/out/split.json")
    a = ap.parse_args()
    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    classes, comps = ck["classes"], ck["comps"]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = Net(len(classes), len(comps)).to(dev)
    net.load_state_dict(ck["state"])
    net.eval()

    sp = json.loads(Path(a.split).read_text(encoding="utf-8"))
    held = sorted(sp["heldout"])
    inside = [c for c in held if c in set(classes)]
    print(f"ckpt {a.ckpt}  类数 {len(classes)}")
    print(f"留出字 {len(held)}，其中落在类表内的 {len(inside)}（应为 0）")

    ev = load_heldout_eval(held)
    print(f"query {len(ev['q_chars'])} / 字种 {len(set(ev['q_chars']))}  "
          f"template {len(ev['t_chars'])}")
    r = retrieval_eval(net, dev, ev)
    print(json.dumps(r, ensure_ascii=False, indent=1))

    # 分类头在类外必然 0：实测一下当护栏
    with torch.no_grad():
        xb = torch.tensor(ev["q_imgs"][:512][:, None].astype(np.float32), device=dev)
        _, lg, _ = net(xb)
        top = lg.topk(10, 1).indices.cpu().numpy()
    hit = sum(1 for i in range(len(top))
              if ev["q_chars"][i] in {classes[j] for j in top[i]})
    print(f"分类头 top10 命中 {hit}/{len(top)}（类外字必为 0）")
    Path("experiments/metric_loss/out/baseline_r4.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
