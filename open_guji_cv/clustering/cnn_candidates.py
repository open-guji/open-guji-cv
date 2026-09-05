# -*- coding: utf-8 -*-
"""CNN 候选源：`scripts/train_glyph_cnn.py` 训出的分类器，对字表打分取 top-k。

## 它在候选栈里的位置

零样本评测（`eval_zero_shot_fusion.py`，unseen 1,327 条，异体算对）：

| | top-1 | top-5 | top-10 |
|---|---|---|---|
| HOG 字体检索 | 75.5% | 91.9% | 94.7% |
| CNN 分类 | 72.4% | 95.3% | 97.6% |
| **RRF 融合** | **86.7%** | **97.2%** | **98.3%** |

两者错得不一样：HOG 看整体轮廓，CNN 被部件多标签头逼着看局部；倒数排名融合
（RRF，只看名次不看分数——余弦与 softmax 量纲不同）top-1 比任一单源高 11 个点。
rare-char 21 条上 CNN 单独 top-10 100%。

## 纪律

- **只出候选，不放行**——与字体模板同一条红线。它对 unseen 字的 top-1 只有 72%，
  离 precision ≥0.999 的放行门槛差几个数量级；
- 模型是外部可变状态：checkpoint 路径 + mtime 进指纹（`fingerprint()`），
  换了模型产物要过期——与 glyph.db、语料同一套做法。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

DEFAULT_CKPT = Path("cache/glyph_cnn/best.pt")
RRF_K = 60


def fingerprint(path: str | Path = DEFAULT_CKPT) -> str:
    p = Path(path)
    if not p.exists():
        return "nockpt"
    st = p.stat()
    return hashlib.sha1(f"{p}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]


def _build_net(n_cls: int, n_comp: int, d: int = 256):
    """与 train_glyph_cnn.Net 同构；结构改了这里要同步（用 checkpoint 里的维度校验）。"""
    import torch.nn as nn
    import torch.nn.functional as F

    class Block(nn.Module):
        def __init__(self, i, o, s):
            super().__init__()
            self.c1 = nn.Conv2d(i, o, 3, s, 1, bias=False)
            self.b1 = nn.BatchNorm2d(o)
            self.c2 = nn.Conv2d(o, o, 3, 1, 1, bias=False)
            self.b2 = nn.BatchNorm2d(o)
            self.sc = (nn.Sequential(nn.Conv2d(i, o, 1, s, bias=False), nn.BatchNorm2d(o))
                       if (s != 1 or i != o) else nn.Identity())

        def forward(self, x):
            y = F.relu(self.b1(self.c1(x)))
            y = self.b2(self.c2(y))
            return F.relu(y + self.sc(x))

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())
            self.l1 = Block(32, 64, 2)
            self.l2 = Block(64, 128, 2)
            self.l3 = Block(128, 256, 2)
            self.l4 = Block(256, 256, 2)
            self.emb = nn.Linear(256 * 16, d)
            self.cls = nn.Linear(d, n_cls)
            self.comp = nn.Linear(d, n_comp)

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
            return e, self.cls(e), self.comp(e)

    return Net()


class CnnCandidates:
    """懒加载；没有 checkpoint 或没装 torch 时 `available` 为 False，调用方跳过。"""

    def __init__(self, ckpt: str | Path = DEFAULT_CKPT, device: str | None = None):
        self.ckpt = Path(ckpt)
        self.device = device
        self._net = None
        self._classes: list[str] = []
        self._cidx: dict[str, int] = {}

    @property
    def available(self) -> bool:
        if not self.ckpt.exists():
            return False
        try:
            import torch  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self) -> bool:
        if self._net is not None:
            return True
        if not self.available:
            return False
        import torch
        ck = torch.load(self.ckpt, map_location="cpu", weights_only=False)
        self._classes = list(ck["classes"])
        self._cidx = {c: i for i, c in enumerate(self._classes)}
        net = _build_net(len(self._classes), len(ck["comps"]))
        net.load_state_dict(ck["state"])
        net.eval()
        dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._net = net.to(dev)
        self._dev = dev
        return True

    def topk(self, norm_patch: np.ndarray, charset, k: int = 10) -> list[tuple[str, float]]:
        """归一化 64² 二值图 → 字表内 top-k (char, prob)。字表外的字不会出现。"""
        if not self._ensure():
            return []
        import torch
        idx = [self._cidx[c] for c in charset if c in self._cidx]
        if not idx:
            return []
        with torch.no_grad():
            x = torch.tensor(norm_patch[None, None].astype(np.float32), device=self._dev)
            _, lg, _ = self._net(x)
            sub = lg[0][torch.tensor(idx, device=self._dev)]
            pr = torch.softmax(sub, 0)
            top = pr.topk(min(k, len(idx)))
        return [(self._classes[idx[int(i)]], float(p)) for p, i in zip(top.values, top.indices)]


CNN_WEIGHT = 2.0
"""RRF 里 CNN 名次的权重（HOG = 1）。2026-09-05 扫描（unseen 1,327 / rare 21）：

| w_cnn | unseen top1/5/10 | rare top1/5/10 |
|---|---|---|
| 1.0 | 87.9 / 97.8 / 98.3 | 66.7 / 85.7 / 90.5 |
| 1.5 | 88.8 / 97.9 / 98.4 | 66.7 / 85.7 / 90.5 |
| **2.0** | **89.3 / 97.7 / 98.6** | 66.7 / 85.7 / **100.0** |

HOG 在最难那撮（rare）上只有 47.6% top-1，权重相等时会把 CNN 的正确答案拖出
top-10；给 CNN 两倍权重，rare top-10 从 90.5% 回到 100%，unseen top-1 也涨。
"""


def rrf(*orders: list[str], k: int = 10, c: int = RRF_K,
        weights: tuple[float, ...] | None = None) -> list[str]:
    """倒数排名融合。只看名次，不看分数——各源量纲不同，分数相加没有意义。

    `weights` 与 `orders` 一一对应；缺省全 1。生产里 HOG=1、CNN=CNN_WEIGHT。
    """
    score: dict[str, float] = {}
    ws = weights or (1.0,) * len(orders)
    for order, w in zip(orders, ws):
        for r, ch in enumerate(order):
            score[ch] = score.get(ch, 0.0) + w / (c + r)
    return [ch for ch, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]


@lru_cache(maxsize=1)
def shared(ckpt: str = str(DEFAULT_CKPT)) -> CnnCandidates:
    return CnnCandidates(ckpt)
