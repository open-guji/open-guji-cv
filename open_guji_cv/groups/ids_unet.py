"""IDS 路切分器（M7 块 C3，GUJI-563）：小 U-Net，只吃一个组的样本，把字块按像素分成 0 上／1 中／2 下。

用户 10-17 设计：非均匀切分用小 U-Net，只在该组样本上训练。训练标签＝人标的两条折线（`ids_segment.polylines_to_mask`）。
预测→折线：每列把"属于上/中的概率之和"当两条界线的位置，所以折线连续、不交叉，可直接回到标注页给人改。
torch 是可选依赖：没装就 import 报错，只影响这个模块。
"""
from __future__ import annotations

import numpy as np

SIZE = 96


def _torch():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    return torch, nn, F


def make_net(base: int = 12, n_out: int = 3):
    torch, nn, F = _torch()

    def blk(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            # 输入 3 通道：灰度、归一化 y、归一化 x（位置先验；折线大体在 y≈0.3/0.65）
            self.e1, self.e2, self.e3 = blk(3, base), blk(base, base * 2), blk(base * 2, base * 4)
            self.b = blk(base * 4, base * 8)
            self.u3, self.d3 = nn.ConvTranspose2d(base * 8, base * 4, 2, 2), blk(base * 8, base * 4)
            self.u2, self.d2 = nn.ConvTranspose2d(base * 4, base * 2, 2, 2), blk(base * 4, base * 2)
            self.u1, self.d1 = nn.ConvTranspose2d(base * 2, base, 2, 2), blk(base * 2, base)
            self.out = nn.Conv2d(base, n_out, 1)

        def forward(self, x):
            e1 = self.e1(x); e2 = self.e2(F.max_pool2d(e1, 2)); e3 = self.e3(F.max_pool2d(e2, 2))
            b = self.b(F.max_pool2d(e3, 2))
            d3 = self.d3(torch.cat([self.u3(b), e3], 1)); d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
            d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.out(d1)

    return Net()


def _coords():
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) / (SIZE - 1)
    return yy, xx


def to_input(gray: np.ndarray) -> np.ndarray:
    """灰度原图 → (3,SIZE,SIZE) float32：墨为 1、底为 0 的灰度 + y + x。"""
    import cv2
    g = cv2.resize(gray, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    ink = 1.0 - g / 255.0
    yy, xx = _coords()
    return np.stack([ink, yy, xx])


def augment(gray: np.ndarray, mask: np.ndarray, rng: np.random.Generator):
    """同一仿射作用于图和掩码（掩码最近邻）；再随机浓淡/对比。返回 (3,S,S) 输入与 (S,S) int64 标签。"""
    import cv2
    h, w = gray.shape
    ang = rng.uniform(-4, 4); sc = rng.uniform(0.9, 1.1)
    tx, ty = rng.uniform(-0.05, 0.05) * w, rng.uniform(-0.05, 0.05) * h
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc); M[:, 2] += (tx, ty)
    g = cv2.warpAffine(gray, M, (w, h), borderValue=255, flags=cv2.INTER_LINEAR)
    m = cv2.warpAffine(mask.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
    g = np.clip((g.astype(np.float32) - 128) * rng.uniform(0.8, 1.2) + 128 + rng.uniform(-20, 20), 0, 255).astype(np.uint8)
    x = to_input(g)
    y = cv2.resize(m, (SIZE, SIZE), interpolation=cv2.INTER_NEAREST).astype(np.int64)
    return x, y


def train(cells, epochs: int = 150, seed: int = 0, base: int = 12, lr: float = 3e-3, n_out: int = 3):
    """cells = [(gray, mask)]。返回训练好的网络（CPU）。`n_out` 类数：三段版 3，两段版（一条切线）2。"""
    torch, nn, F = _torch()
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    net = make_net(base, n_out); opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * ((len(cells) * 4 + 15) // 16))
    for ep in range(epochs):
        net.train()
        batch = [augment(g, m, rng) for g, m in cells for _ in range(4)]
        order = rng.permutation(len(batch))
        for s in range(0, len(order), 16):
            idx = order[s:s + 16]
            x = torch.from_numpy(np.stack([batch[i][0] for i in idx])); y = torch.from_numpy(np.stack([batch[i][1] for i in idx]))
            loss = F.cross_entropy(net(x), y)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    net.eval()
    return net


def predict_prob(net, gray: np.ndarray) -> np.ndarray:
    """→ (3,H,W) 概率，回到原图尺寸。"""
    import cv2
    torch, _, F = _torch()
    with torch.no_grad():
        p = F.softmax(net(torch.from_numpy(to_input(gray))[None]), 1)[0].numpy()
    h, w = gray.shape
    return np.stack([cv2.resize(c, (w, h), interpolation=cv2.INTER_LINEAR) for c in p])


def prob_to_polylines(prob: np.ndarray, step: int = 4, smooth: int = 5):
    """概率 → 两条折线（归一化）。第 x 列：上/中界＝上段概率之和÷h，中/下界＝(上＋中)之和÷h。"""
    _, h, w = prob.shape
    y1 = prob[0].sum(axis=0) / h; y2 = (prob[0] + prob[1]).sum(axis=0) / h
    k = np.ones(smooth) / smooth
    pad = smooth // 2
    sm = lambda a: np.convolve(np.r_[[a[0]] * pad, a, [a[-1]] * pad], k, mode="valid")
    y1, y2 = sm(y1), sm(y2)
    y2 = np.maximum(y2, y1)
    xs = list(range(0, w, step)) + [w - 1]
    return ([[(x + 0.5) / w, float(y1[x])] for x in xs], [[(x + 0.5) / w, float(y2[x])] for x in xs])


def prob_to_polyline2(prob: np.ndarray, orient: str = "h", step: int = 4, smooth: int = 5):
    """两类概率 → 一条折线（归一化，点为 (x,y)，格式同 `ids_two.auto_cut`）。
    `h`（0 上 1 下）：第 x 列界线＝上段概率之和÷h；`v`（0 左 1 右）：第 y 行界线＝左段概率之和÷w。"""
    if orient == "v":
        t = prob_to_polyline2(prob[:, :, :].transpose(0, 2, 1), "h", step, smooth)
        return [[y, x] for x, y in t]
    _, h, w = prob.shape
    y1 = prob[0].sum(axis=0) / h
    k = np.ones(smooth) / smooth
    pad = smooth // 2
    y1 = np.convolve(np.r_[[y1[0]] * pad, y1, [y1[-1]] * pad], k, mode="valid")
    xs = list(range(0, w, step)) + [w - 1]
    return [[(x + 0.5) / w, float(y1[x])] for x in xs]


# —— 线上推理：纯 numpy，不需要 torch ——
# 训练（`train`）仍要 torch；训完 `save_weights` 存成 .npz（约 1.1MB），线上用 `NpNet` 前向，
# 结果与 torch eval 模式一致（`tests/test_groups_ids_unet_np.py`）。无随机、无 GPU，云端重跑逐字节相同。

def save_weights(net, path) -> None:
    """torch 网络 → .npz（state_dict 的 float32 数组，键名不变）。"""
    np.savez_compressed(path, **{k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items()
                                 if v.dtype.is_floating_point})


def _conv3(x, w, b):
    """x (C,H,W)，w (O,C,3,3)，padding=1。"""
    from numpy.lib.stride_tricks import sliding_window_view
    xp = np.pad(x, ((0, 0), (1, 1), (1, 1)))
    win = sliding_window_view(xp, (3, 3), axis=(1, 2))          # (C,H,W,3,3)
    return np.einsum("chwij,ocij->ohw", win, w, optimize=True) + b[:, None, None]


def _bn(x, p, pre):
    s = p[pre + ".weight"] / np.sqrt(p[pre + ".running_var"] + 1e-5)
    return (x - p[pre + ".running_mean"][:, None, None]) * s[:, None, None] + p[pre + ".bias"][:, None, None]


def _blk(x, p, pre):
    x = np.maximum(_bn(_conv3(x, p[pre + ".0.weight"], p[pre + ".0.bias"]), p, pre + ".1"), 0)
    return np.maximum(_bn(_conv3(x, p[pre + ".3.weight"], p[pre + ".3.bias"]), p, pre + ".4"), 0)


def _pool(x):
    c, h, w = x.shape
    return x.reshape(c, h // 2, 2, w // 2, 2).max(axis=(2, 4))


def _up(x, w, b):
    """ConvTranspose2d(k=2,s=2)：w (C,O,2,2)。"""
    c, h, ww = x.shape
    y = np.einsum("chw,coab->ohawb", x, w, optimize=True).reshape(w.shape[1], h * 2, ww * 2)
    return y + b[:, None, None]


class NpNet:
    def __init__(self, path):
        z = np.load(path)
        self.p = {k: z[k] for k in z.files}

    @classmethod
    def from_torch(cls, net):
        o = cls.__new__(cls)
        o.p = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items() if v.dtype.is_floating_point}
        return o

    def forward(self, x):
        p = self.p
        e1 = _blk(x, p, "e1"); e2 = _blk(_pool(e1), p, "e2"); e3 = _blk(_pool(e2), p, "e3")
        b = _blk(_pool(e3), p, "b")
        d3 = _blk(np.concatenate([_up(b, p["u3.weight"], p["u3.bias"]), e3]), p, "d3")
        d2 = _blk(np.concatenate([_up(d3, p["u2.weight"], p["u2.bias"]), e2]), p, "d2")
        d1 = _blk(np.concatenate([_up(d2, p["u1.weight"], p["u1.bias"]), e1]), p, "d1")
        return np.einsum("chw,oc->ohw", d1, p["out.weight"][:, :, 0, 0], optimize=True) + p["out.bias"][:, None, None]


def predict_prob_np(net: NpNet, gray: np.ndarray) -> np.ndarray:
    import cv2
    z = net.forward(to_input(gray))
    z = np.exp(z - z.max(axis=0)); p = z / z.sum(axis=0)
    h, w = gray.shape
    return np.stack([cv2.resize(c, (w, h), interpolation=cv2.INTER_LINEAR) for c in p])
