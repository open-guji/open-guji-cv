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

    # ── embedding 检索（第三源）────────────────────────────────────
    #
    # 2026-09-05 实测（unseen 1,327，异体算对）：分类头 83.9 / 96.8 / 98.2，
    # **embedding 对字体模板做余弦检索 91.9 / 98.1 / 98.6**——同一个网络，换一种
    # 读法就高 8 个点。原因：unseen 类的分类头权重只在字体渲染上训过，是一组
    # 线性权重；而 embedding 检索比的是「查询图的 256-d 向量」与「该字 4 张字体
    # 渲染向量的均值」的夹角，归一化空间里的度量比线性头泛化得好（CCR-CLIP 一路
    # 的结论）。rare-char 21 条 top-5 100%。
    #
    # 模板向量按「checkpoint 指纹 + 字表」落盘（cache/glyph_cnn/emb_<key>.npz），
    # 4,636 字 × 4 字体首建约 1 分钟，之后毫秒级。

    def _emb_index(self, charset) -> tuple[np.ndarray, list[str]]:
        import hashlib
        import torch
        from .font_candidates import _font_files
        from .synth import render_char

        cs = tuple(charset)
        key = hashlib.sha1((fingerprint(self.ckpt) + "".join(cs)).encode("utf-8")).hexdigest()[:16]
        f = self.ckpt.parent / f"emb_{key}.npz"
        if f.exists():
            z = np.load(f, allow_pickle=False)
            return z["mat"], z["chars"].tolist()
        fonts = _font_files()
        vecs, names = [], []
        with torch.no_grad():
            for ch in cs:
                ims = []
                for fp in fonts:
                    try:
                        im = render_char(ch, fp, size=64)
                    except Exception:
                        continue
                    if im is not None and im.any():
                        ims.append(im.astype(np.uint8))
                if not ims:
                    continue
                x = torch.tensor(np.stack(ims)[:, None].astype(np.float32), device=self._dev)
                e, _, _ = self._net(x)
                v = e.mean(0)
                vecs.append((v / (v.norm() + 1e-9)).cpu().numpy())
                names.append(ch)
        mat = np.stack(vecs).astype(np.float32) if vecs else np.zeros((0, 256), np.float32)
        f.parent.mkdir(parents=True, exist_ok=True)
        np.savez(f, mat=mat, chars=np.array(names))
        return mat, names

    def emb_topk(self, norm_patch: np.ndarray, charset, k: int = 10) -> list[tuple[str, float]]:
        """归一化 64² 二值图 → 与字体模板 embedding 的余弦 top-k。"""
        if not self._ensure():
            return []
        import torch
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0:
            return []
        with torch.no_grad():
            x = torch.tensor(norm_patch[None, None].astype(np.float32), device=self._dev)
            e, _, _ = self._net(x)
            q = e[0]
            q = (q / (q.norm() + 1e-9)).cpu().numpy()
        sims = mat @ q
        order = np.argsort(-sims)[:k]
        return [(names[int(i)], float(sims[int(i)])) for i in order]


HOG_WEIGHT = 0.5
CNN_WEIGHT = 1.0
EMB_WEIGHT = 3.0
"""三源 RRF 权重（HOG 字体检索 / CNN 分类头 / CNN embedding 检索）。

2026-09-05 扫描（run-2 checkpoint；unseen 1,327 / rare 21，异体算对）：

| hog / cls / emb | unseen top1 / 5 / 10 | rare top1 / 5 / 10 |
|---|---|---|
| 1 / 2 / 2 | 91.9 / 98.2 / 98.8 | 66.7 / 90.5 / 100 |
| 1 / 2 / 3 | 92.0 / 98.4 / 98.8 | 66.7 / 95.2 / 100 |
| 0 / 1 / 2 | 91.6 / 98.0 / 98.6 | 76.2 / 100 / 100 |
| 0 / 1 / 1 | 90.9 / 97.7 / 98.5 | 71.4 / 100 / 100 |
| 1 / 1 / 3 | 92.3 / 98.3 / 98.9 | 66.7 / 90.5 / 100 |
| **0.5 / 1 / 3** | **92.8 / 98.3 / 98.9** | 71.4 / **100 / 100** |

两条规律：**embedding 检索权重越高越好**（它是最强单源，91.9%）；**HOG 权重要压
低**——它在最难那撮（rare）只有 47.6% top-1，模拟磨损下再掉 14 个点，权重 1 时
把 rare top-5 拖到 90.5%。取 0.5 / 1 / 3：unseen top-1 最高，rare top-5/10 100%。
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
