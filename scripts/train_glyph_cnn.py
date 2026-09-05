# -*- coding: utf-8 -*-
"""拆字识别 v2：学到的特征。小 CNN + 部件多标签辅助头 + 字体合成补类。

## 为什么走这条

零样本第一轮（`eval_zero_shot.py`）：整字 HOG 检索在 unseen 字上 top1 73% /
top10 93%，而按 IDS 结构手工切半再 HOG 的四个变体**全输给它**。手工拆分只丢
信息不增；要在 unseen 字上赢，特征得学出来。文献里零样本汉字识别的主流也都是
「图像编码器 + 结构标签」（RAN / HDE / CCR-CLIP），本脚本是它的最小可用版。

## 三个设计点

1. **字体合成补类**（arXiv 2506.04807 那条路）：分类头覆盖**整理本全部 4,636 字
   种**，而不是只有库里见过的 658 个。库里没刻例的类，训练样本全部来自
   I.Ming / Jigmo 渲染 + 强增广（磨损/断墨/粘连模拟）。于是 unseen 字对分类器
   来说不是「没见过」，是「只见过字体版」——这正是生僻字的真实处境。
2. **部件多标签辅助头**：每个字的 IDS 部件（出现在 ≥3 个字里的 ~500 个）作为
   多标签目标，逼着 backbone 学出「氵在左」「言在左」这类可迁移的局部特征。
   没有它，网络会记整字外形，对只见过字体版的类泛化差。
3. **增广模拟刻本退化**：随机腐蚀/膨胀（笔画粗细）、随机横条抹白（断墨）、
   随机小仿射（刻/扫描形变）、随机贴边噪点（框线残渣）。用户点名要考虑
   「字符磨损的情况」，这里是它的着力点。

## 评什么（与零样本基线同口径）

- seen_test（真刻例、见过的类）top1：分类器基本功；
- **unseen（真刻例、只见过字体版的类）top1/5/10**：这才是目标数字，
  对照 HOG 基线 73 / 90 / 93。

用法：
    python scripts/train_glyph_cnn.py [--epochs 12] [--bs 256] [--out cache/glyph_cnn]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

BENCH = Path("cache/glyph_bench")
SIZE = 64


# ── 数据 ─────────────────────────────────────────────────────────
def load_items():
    return [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()]


def degrade(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """模拟刻本退化。img: uint8 {0,1} 64×64，1=墨。"""
    x = img.copy()
    r = rng.random()
    if r < 0.3:                                   # 笔画变粗（墨晕）
        x = cv2.dilate(x, np.ones((2, 2), np.uint8))
    elif r < 0.55:                                # 笔画变细/断墨
        x = cv2.erode(x, np.ones((2, 2), np.uint8))
    if rng.random() < 0.35:                       # 横向抹白：断墨/磨损
        for _ in range(rng.randint(1, 3)):
            y = rng.randint(4, SIZE - 6)
            h = rng.randint(1, 3)
            x[y:y + h, :] = 0
    if rng.random() < 0.25:                       # 竖向抹白
        for _ in range(rng.randint(1, 2)):
            c = rng.randint(4, SIZE - 6)
            x[:, c:c + rng.randint(1, 2)] = 0
    if rng.random() < 0.6:                        # 小仿射
        ang = rng.uniform(-6, 6)
        sc = rng.uniform(0.9, 1.08)
        tx, ty = rng.uniform(-3, 3), rng.uniform(-3, 3)
        M = cv2.getRotationMatrix2D((SIZE / 2, SIZE / 2), ang, sc)
        M[:, 2] += (tx, ty)
        x = cv2.warpAffine(x, M, (SIZE, SIZE), flags=cv2.INTER_NEAREST, borderValue=0)
    if rng.random() < 0.3:                        # 贴边残渣
        side = rng.randint(0, 3)
        w = rng.randint(1, 3)
        if side == 0:
            x[:w, :] = 1
        elif side == 1:
            x[-w:, :] = 1
        elif side == 2:
            x[:, :w] = 1
        else:
            x[:, -w:] = 1
    return x


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--bs", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--font-per-class", type=int, default=4, help="每类每 epoch 采几张字体渲染")
    ap.add_argument("--out", default="cache/glyph_cnn")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--real-frac", type=float, default=1.0,
                    help="只用这一比例的真刻例训练（按类分层抽样）——学习曲线实验用，"
                         "测试集不受影响")
    a = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from open_guji_cv.clustering.font_candidates import _font_files, book_charset
    from open_guji_cv.clustering.ids_guard import components
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.synth import render_char

    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("device", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "")

    # 类表：整理本字种 ∪ 基准集字种
    items = load_items()
    classes = sorted(set(book_charset(a.corpus)) | {i["char"] for i in items})
    cidx = {c: i for i, c in enumerate(classes)}
    print("类数", len(classes))

    # 部件表：出现在 ≥3 个类里的部件
    comp_cnt = Counter(k for c in classes for k in set(components(c)))
    comps = sorted(k for k, n in comp_cnt.items() if n >= 3)
    kidx = {k: i for i, k in enumerate(comps)}
    print("部件数", len(comps))

    def comp_vec(ch: str) -> np.ndarray:
        v = np.zeros(len(comps), np.float32)
        for k in components(ch):
            if k in kidx:
                v[kidx[k]] = 1.0
        return v

    # 真刻例
    def load_real(split):
        xs, ys = [], []
        for it in items:
            if it["split"] != split:
                continue
            img = cv2.imread(it["png"], cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            xs.append(normalize_patch(img).astype(np.uint8))
            ys.append(cidx[it["char"]])
        return np.stack(xs), np.array(ys)

    t0 = time.time()
    Xtr, Ytr = load_real("seen_train")
    if a.real_frac < 1.0:
        # 按类分层抽样：每类至少留 1 张，避免整类消失（那会变成"少了几个类"而非"少了数据"）
        rs = np.random.RandomState(a.seed)
        keep: list[int] = []
        for c in np.unique(Ytr):
            idx = np.where(Ytr == c)[0]
            k = max(1, int(round(len(idx) * a.real_frac)))
            keep += list(rs.choice(idx, k, replace=False))
        keep = np.array(sorted(keep))
        print(f"真刻例采样 {a.real_frac:.0%}: {len(Xtr)} → {len(keep)}（{len(np.unique(Ytr))} 类全保留）")
        Xtr, Ytr = Xtr[keep], Ytr[keep]
    Xte, Yte = load_real("seen_test")
    Xun, Yun = load_real("unseen")
    print(f"真刻例 train {len(Xtr)} / seen_test {len(Xte)} / unseen {len(Xun)}  载入 {time.time()-t0:.0f}s")

    # 字体渲染：每类 × 每字体一张（缓存）
    fonts = _font_files()
    t0 = time.time()
    font_imgs: dict[int, list[np.ndarray]] = {}
    for ch, ci in cidx.items():
        lst = []
        for f in fonts:
            try:
                im = render_char(ch, f, size=SIZE)
            except Exception:
                continue
            if im is not None and im.any():
                lst.append(im.astype(np.uint8))
        if lst:
            font_imgs[ci] = lst
    print(f"字体渲染 {sum(len(v) for v in font_imgs.values())} 张 / {len(font_imgs)} 类  {time.time()-t0:.0f}s")

    # ── 模型 ──
    class Block(nn.Module):
        def __init__(self, i, o, s):
            super().__init__()
            self.c1 = nn.Conv2d(i, o, 3, s, 1, bias=False)
            self.b1 = nn.BatchNorm2d(o)
            self.c2 = nn.Conv2d(o, o, 3, 1, 1, bias=False)
            self.b2 = nn.BatchNorm2d(o)
            self.sc = nn.Sequential(nn.Conv2d(i, o, 1, s, bias=False), nn.BatchNorm2d(o)) if (s != 1 or i != o) else nn.Identity()

        def forward(self, x):
            y = F.relu(self.b1(self.c1(x)))
            y = self.b2(self.c2(y))
            return F.relu(y + self.sc(x))

    class Net(nn.Module):
        def __init__(self, n_cls, n_comp, d=256):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())
            self.l1 = Block(32, 64, 2)      # 32
            self.l2 = Block(64, 128, 2)     # 16
            self.l3 = Block(128, 256, 2)    # 8
            self.l4 = Block(256, 256, 2)    # 4
            self.emb = nn.Linear(256 * 4 * 4, d)
            self.cls = nn.Linear(d, n_cls)
            self.comp = nn.Linear(d, n_comp)

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0   # cos-like logits
            return e, self.cls(e), self.comp(e)

    net = Net(len(classes), len(comps)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    comp_tr = torch.tensor(np.stack([comp_vec(c) for c in classes]), device=dev)

    def batch_iter():
        """每 epoch：全部真刻例 + 每类 font-per-class 张字体渲染，混洗。"""
        xs, ys = [], []
        for x, y in zip(Xtr, Ytr):
            xs.append(degrade(x, rng)); ys.append(y)
        for ci, lst in font_imgs.items():
            for _ in range(a.font_per_class):
                xs.append(degrade(rng.choice(lst), rng)); ys.append(ci)
        idx = list(range(len(xs)))
        rng.shuffle(idx)
        for i in range(0, len(idx), a.bs):
            j = idx[i:i + a.bs]
            X = torch.tensor(np.stack([xs[k] for k in j])[:, None].astype(np.float32), device=dev)
            Y = torch.tensor([ys[k] for k in j], device=dev)
            yield X, Y

    @torch.no_grad()
    def evaluate(X, Y, name):
        net.eval()
        r1 = r5 = r10 = 0
        for i in range(0, len(X), 512):
            xb = torch.tensor(X[i:i + 512][:, None].astype(np.float32), device=dev)
            _, lg, _ = net(xb)
            top = lg.topk(10, dim=1).indices.cpu().numpy()
            yb = Y[i:i + 512]
            r1 += (top[:, 0] == yb).sum()
            r5 += (top[:, :5] == yb[:, None]).any(1).sum()
            r10 += (top == yb[:, None]).any(1).sum()
        n = len(X)
        print(f"  {name:10s} top1 {r1/n:5.1%}  top5 {r5/n:5.1%}  top10 {r10/n:5.1%}")
        net.train()
        return r1 / n, r10 / n

    steps_per_epoch = math.ceil((len(Xtr) + a.font_per_class * len(font_imgs)) / a.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * steps_per_epoch)
    best = 0.0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for ep in range(a.epochs):
        t0 = time.time()
        tot = n = 0
        for X, Y in batch_iter():
            _, lg, cp = net(X)
            loss = F.cross_entropy(lg, Y, label_smoothing=0.1) \
                + 0.5 * F.binary_cross_entropy_with_logits(cp, comp_tr[Y])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss) * len(Y)
            n += len(Y)
        print(f"epoch {ep+1}/{a.epochs} loss {tot/n:.3f}  {time.time()-t0:.0f}s")
        evaluate(Xte, Yte, "seen_test")
        _, u10 = evaluate(Xun, Yun, "unseen")
        if u10 > best:
            best = u10
            torch.save({"state": net.state_dict(), "classes": classes, "comps": comps}, out / "best.pt")
    print("best unseen top10", f"{best:.1%}", "→", out / "best.pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
