# -*- coding: utf-8 -*-
"""**单字体** CNN：一套字体一个模型，用时多模型各出候选再比较。

与 `train_glyph_cnn.py` 的分工（用户 2026-09-15 定）：

| | `train_glyph_cnn.py`（既有，混合训练）| 本脚本（单字体）|
|---|---|---|
| 字体 | `fonts/` 下全部（I.Ming + Jigmo + 康熙）混进同一个模型 | **一套** |
| 真刻例 | 混入 `cache/glyph_bench` 的真刻本图 | 不用（纯字体） |
| 增广 | 刻本退化（断墨/磨损/粘连/框线残渣）| 可选 `--degrade print`（现代印刷）|
| 用途 | 刻本链的通用候选源 | 按书选字体后，用对应模型出候选 |

**为什么要单字体模型**：混合训练把「同字多写法」摊平成一个类中心，好处是覆盖广、
对没见过的写法稳；坏处是它不知道**这本书用的是哪一套写法**。现代排印本的情形恰好相反
——我们已经标定出这本书就是 SimSun 一系（`books/<id>.yaml` 的 `font.editions`），
这时「广」不是优点，「准」才是。单字体模型 + 多模型比较，把选哪一套的权力交回调用方。

既有的混合模型**不动**（`models/glyph_cnn_r4/`）：换 checkpoint 会让全部下游产物过期。

## 字表

`--charset gbk`：GBK 可编码的 CJK 基本区汉字 20,902 个。**不要用 Big5**——
Big5 是台湾标准字形，缺 内/强/户/换/摇/却/吕/吴/墙 这些**大陆新字形**，
而北行日錄（大陆出版的繁体竖排本）正用这一套：实测 Big5 缺它 81 个用字、
CP950 缺 77 个，GBK 缺 0 个（2026-09-15）。

    python scripts/train_font_cnn.py --font "C:/Windows/Fonts/simsun.ttc" \
        --name simsun --charset gbk --degrade print --epochs 12
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SIZE = 64


def gbk_charset() -> list[str]:
    """GBK 可编码的 CJK 基本区汉字。简繁都收——这本书用的大陆新字形只有它全覆盖。"""
    out = []
    for cp in range(0x4E00, 0xA000):
        ch = chr(cp)
        try:
            ch.encode("gbk")
            out.append(ch)
        except Exception:
            pass
    return out


def degrade_print(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """**现代印刷 + 扫描**的退化，不是刻本那一套。

    这本书是 1-bit 扫描的现代排印本：笔画整齐、没有断墨磨损、没有版框残渣，
    真实的变形来自**墨扩（笔画变粗）、二值化抖动、轻微倾斜、切分抖动**。
    刻本那套增广（横向抹白模拟断墨、贴边残渣模拟框线）在这里是**噪声**，
    会逼模型去容忍根本不会出现的形变。
    """
    x = img.copy()
    r = rng.random()
    if r < 0.45:                                  # 墨扩：1-bit 扫描最常见的偏差
        x = cv2.dilate(x, np.ones((2, 2), np.uint8))
    elif r < 0.6:                                 # 偏细
        x = cv2.erode(x, np.ones((2, 2), np.uint8))
    if rng.random() < 0.5:                        # 小仿射：扫描倾斜 + 切分抖动
        ang = rng.uniform(-3, 3)
        sc = rng.uniform(0.94, 1.06)
        tx, ty = rng.uniform(-2, 2), rng.uniform(-2, 2)
        M = cv2.getRotationMatrix2D((SIZE / 2, SIZE / 2), ang, sc)
        M[:, 2] += (tx, ty)
        x = cv2.warpAffine(x, M, (SIZE, SIZE), flags=cv2.INTER_NEAREST, borderValue=0)
    if rng.random() < 0.25:                       # 二值化抖动：边缘像素翻转
        n = rng.randint(4, 20)
        ys = np.random.randint(0, SIZE, n)
        xs = np.random.randint(0, SIZE, n)
        x[ys, xs] ^= 1
    return x


def degrade_keben(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """刻本退化：沿用 `train_glyph_cnn.degrade`（同一套判据，别在两处各写一份）。"""
    from scripts.train_glyph_cnn import degrade as _d
    return _d(img, rng)


def main() -> None:
    ap = argparse.ArgumentParser(description="单字体 CNN 训练")
    ap.add_argument("--font", required=True, help="字体文件（ttf/otf/ttc）")
    ap.add_argument("--name", required=True, help="模型名，落 models/font_cnn_<name>/")
    ap.add_argument("--charset", default="gbk", help="gbk | 文件路径（一行一字或连写）")
    ap.add_argument("--degrade", default="print", choices=("print", "keben"))
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--bs", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--per-class", type=int, default=6, help="每类每 epoch 采几张增广")
    ap.add_argument("--val-book", default=None,
                    help="用真实字块做验证：工作区路径（如 D:/workspace/beixingrilu-workspace）。"
                         "字块与训练的字体渲染零同源，才测得出泛化")
    ap.add_argument("--val-name", default="bxrl", help="--val-book 里的册 id")
    ap.add_argument("--val-per-class", type=int, default=2, help="每个字头最多取几张真实字块")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from open_guji_cv.clustering.ids_guard import components
    from open_guji_cv.clustering.synth import render_char

    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("device", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "")

    # ── 字表 ──
    if a.charset == "gbk":
        chars = gbk_charset()
    else:
        txt = Path(a.charset).read_text(encoding="utf-8")
        chars = sorted({c for c in txt if "\u3400" <= c <= "\u9fff"})
    print(f"字表 {len(chars)}（{a.charset}）")

    # ── 渲染：一套字体，每类一张 ──
    t0 = time.time()
    imgs: dict[str, np.ndarray] = {}
    for ch in chars:
        try:
            im = render_char(ch, a.font, size=SIZE)
        except Exception:
            continue
        if im is not None and im.any():
            imgs[ch] = im.astype(np.uint8)
    print(f"渲染 {len(imgs)}/{len(chars)} 类  {time.time()-t0:.0f}s"
          f"（字体没有的字直接不建类——排序再好也出不来，见 charset_and_lm.md §一）")

    classes = sorted(imgs)
    cidx = {c: i for i, c in enumerate(classes)}

    # ── 部件多标签辅助头：逼 backbone 学局部特征（沿用混合模型的设计）──
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

    degrade = degrade_print if a.degrade == "print" else degrade_keben

    # 验证集：单字体每类只有一张原图，**没法留出整类**（留了就没有正样本）。
    # 拿「同一张原图的另一个增广」当验证也**测不出泛化**——训练见过同一张底图，
    # 冒烟测试里 4 个 epoch 就 100%，量的是记忆不是识别（2026-09-15 实测）。
    #
    # 真正要回答的是「**书上印的那个字**认不认得」，所以验证集用**真实字块**：
    # `--val-book` 给一册书，从它的证人标签里取图（`labels.jsonl` + `char_patch`），
    # 字块是扫描件、标签是校對本，与训练用的字体渲染零同源。没给就退回
    # 增广自比，并在日志里标明那只是 sanity check。
    val_x, val_y, val_kind = [], [], "增广自比（只是 sanity check，测不出泛化）"
    if a.val_book:
        import json as _json
        from open_guji_cv.core.spec import cell_key
        ws = Path(a.val_book)
        lab_p = ws / f"products/{a.val_name}/witness_align/labels.jsonl"
        seen = Counter()
        for ln in lab_p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            d = _json.loads(ln)
            ch = d["char"]
            if ch not in cidx or d.get("cell_kind") != "char" or seen[ch] >= a.val_per_class:
                continue
            g = cv2.imread(str(ws / f"cache/{a.val_name}/char_patch"
                               / (cell_key(d["page"], d["col"], d["slot"]) + ".png")), 0)
            if g is None:
                continue
            from open_guji_cv.clustering.normalize import normalize_patch
            val_x.append(normalize_patch(g).astype(np.uint8))
            val_y.append(cidx[ch]); seen[ch] += 1
        val_kind = f"真实字块（{a.val_name}，{len(set(val_y))} 个字头）"
    if not val_x:
        vr = random.Random(a.seed + 1)
        for ch in classes:
            val_x.append(degrade(imgs[ch], vr)); val_y.append(cidx[ch])
    Xva = torch.tensor(np.stack(val_x)[:, None].astype(np.float32), device=dev)
    Yva = torch.tensor(np.array(val_y), device=dev)
    print(f"验证 {len(val_y)} 张 —— {val_kind}")

    # `render_char` 出来就是 64×64 {0,1}，不要再过 `normalize_patch`（那个吃灰度图）

    class Block(nn.Module):
        def __init__(self, cin, cout, stride):
            super().__init__()
            self.c1 = nn.Conv2d(cin, cout, 3, stride, 1, bias=False)
            self.b1 = nn.BatchNorm2d(cout)
            self.c2 = nn.Conv2d(cout, cout, 3, 1, 1, bias=False)
            self.b2 = nn.BatchNorm2d(cout)
            self.sc = (nn.Sequential() if stride == 1 and cin == cout else
                       nn.Sequential(nn.Conv2d(cin, cout, 1, stride, bias=False), nn.BatchNorm2d(cout)))

        def forward(self, x):
            y = F.relu(self.b1(self.c1(x)))
            y = self.b2(self.c2(y))
            return F.relu(y + self.sc(x))

    class Net(nn.Module):
        def __init__(self, n_cls, n_comp, d=256):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())
            self.l1, self.l2 = Block(32, 64, 2), Block(64, 128, 2)
            self.l3, self.l4 = Block(128, 256, 2), Block(256, 256, 2)
            self.emb = nn.Linear(256 * 4 * 4, d)
            self.cls = nn.Linear(d, n_cls)
            self.comp = nn.Linear(d, n_comp)

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
            return e, self.cls(e), self.comp(e)

    net = Net(len(classes), len(comps)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    comp_tr = torch.tensor(np.stack([comp_vec(c) for c in classes]), device=dev)

    def batch_iter():
        xs, ys = [], []
        for ch in classes:
            base = imgs[ch]
            for _ in range(a.per_class):
                xs.append(degrade(base, rng)); ys.append(cidx[ch])
        idx = list(range(len(xs)))
        rng.shuffle(idx)
        for i in range(0, len(idx), a.bs):
            j = idx[i:i + a.bs]
            yield (torch.tensor(np.stack([xs[t] for t in j])[:, None].astype(np.float32), device=dev),
                   torch.tensor(np.array([ys[t] for t in j]), device=dev))

    @torch.no_grad()
    def evaluate():
        net.eval()
        r1 = r10 = 0
        for i in range(0, len(Yva), 512):
            _, lg, _ = net(Xva[i:i + 512])
            top = lg.topk(10, dim=1).indices
            y = Yva[i:i + 512]
            r1 += int((top[:, 0] == y).sum())
            r10 += int((top == y[:, None]).any(dim=1).sum())
        net.train()
        n = len(Yva)
        return r1 / n, r10 / n

    steps = math.ceil(len(classes) * a.per_class / a.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * steps)
    out = Path(a.out or f"models/font_cnn_{a.name}")
    out.mkdir(parents=True, exist_ok=True)
    best = 0.0
    for ep in range(a.epochs):
        t0 = time.time()
        tot = n = 0
        for xb, yb in batch_iter():
            e, lg, cp = net(xb)
            loss = F.cross_entropy(lg, yb) + 0.3 * F.binary_cross_entropy_with_logits(cp, comp_tr[yb])
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += float(loss) * len(yb); n += len(yb)
        a1, a10 = evaluate()
        print(f"ep{ep+1}/{a.epochs} loss {tot/max(n,1):.4f}  val top1 {a1:.4f} top10 {a10:.4f}"
              f"  {time.time()-t0:.0f}s")
        if a1 > best:
            best = a1
            torch.save({"state": net.state_dict(), "classes": classes, "comps": comps,
                        "font": a.font, "charset": a.charset, "degrade": a.degrade},
                       out / "best.pt")
            (out / "meta.json").write_text(json.dumps(
                {"name": a.name, "font": a.font, "charset": a.charset, "n_classes": len(classes),
                 "degrade": a.degrade, "val_top1": a1, "val_top10": a10,
                 "epochs": a.epochs, "seed": a.seed}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"最好 val top1 {best:.4f} → {out}/best.pt")


if __name__ == "__main__":
    main()
