# -*- coding: utf-8 -*-
"""度量损失实验的训练器：与 `scripts/train_glyph_cnn.py` 同架构、同数据、同超参，
**只换损失函数**，以便 delta 干净。

支持的损失（`--loss`）：
- `ce`       ：现役（CrossEntropy + 0.5·部件 BCE）——基线
- `cosface`  ：cos(θ_y) − m（加性余弦边距，AM-Softmax）
- `arcface`  ：cos(θ_y + m)（加性角边距）
- 任一档都可叠 `--comp-w`（部件头权重，现役 0.5）与 `--sub-center`

## 与现役 `cls` 头的关系

现役 forward 是 `e = normalize(emb(x))*16; cls(e)`：`cls` 是普通 Linear
（**权重没归一化**、**有 bias**），所以它不是严格的余弦分类器，
只是「输入被归一化过」的线性头。本实验的 margin 档把它换成
权重归一化、无 bias 的严格余弦头 `W_norm @ e_norm`，再加 margin。
`--loss ce --cosine-head` 可单独隔离「换成严格余弦头」这一步的影响，
避免把它的效果误记到 margin 头上。
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SIZE = 64
BENCH = Path("cache/glyph_bench")


def load_items():
    return [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()]


def degrade(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """与 scripts/train_glyph_cnn.py 的 degrade 逐行一致（刻本退化增广）。"""
    x = img.copy()
    r = rng.random()
    if r < 0.3:
        x = cv2.dilate(x, np.ones((2, 2), np.uint8))
    elif r < 0.55:
        x = cv2.erode(x, np.ones((2, 2), np.uint8))
    if rng.random() < 0.35:
        for _ in range(rng.randint(1, 3)):
            y = rng.randint(4, SIZE - 6)
            h = rng.randint(1, 3)
            x[y:y + h, :] = 0
    if rng.random() < 0.25:
        for _ in range(rng.randint(1, 2)):
            c = rng.randint(4, SIZE - 6)
            x[:, c:c + rng.randint(1, 2)] = 0
    if rng.random() < 0.6:
        ang = rng.uniform(-6, 6)
        sc = rng.uniform(0.9, 1.08)
        tx, ty = rng.uniform(-3, 3), rng.uniform(-3, 3)
        M = cv2.getRotationMatrix2D((SIZE / 2, SIZE / 2), ang, sc)
        M[:, 2] += (tx, ty)
        x = cv2.warpAffine(x, M, (SIZE, SIZE), flags=cv2.INTER_NEAREST, borderValue=0)
    if rng.random() < 0.3:
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
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--bs", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--font-per-class", type=int, default=24)
    ap.add_argument("--extra-per-class", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--loss", default="ce", choices=("ce", "cosface", "arcface"))
    ap.add_argument("--margin", type=float, default=0.2)
    ap.add_argument("--scale", type=float, default=16.0)
    ap.add_argument("--comp-w", type=float, default=0.5)
    ap.add_argument("--cosine-head", action="store_true",
                    help="换成权重归一化、无 bias 的严格余弦头（margin 档强制开）")
    ap.add_argument("--warmup-frac", type=float, default=0.25,
                    help="margin 从 0 线性升到目标值所占的 epoch 比例")
    ap.add_argument("--label-smoothing", type=float, default=0.1)
    ap.add_argument("--extra-real", action="append", default=[])
    ap.add_argument("--heldout", default="experiments/metric_loss/out/split.json",
                    help="留出字种表（build_split 产物）——这些字的任何图都不进训练")
    ap.add_argument("--eval-every", type=int, default=5)
    a = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from data import base_classes, load_heldout_eval
    from evaluate import retrieval_eval

    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.ids_guard import components
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.synth import render_char

    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("device", dev, flush=True)

    sp = json.loads(Path(a.heldout).read_text(encoding="utf-8"))
    held = set(sp["heldout"])
    items = load_items()
    classes = base_classes()
    # 留出字本来就在类表外（build_split 只从类表外挑），这里再兜一道
    classes = [c for c in classes if c not in held]
    cidx = {c: i for i, c in enumerate(classes)}
    print("类数", len(classes), " 留出字", len(held), flush=True)

    comp_cnt = Counter(k for c in classes for k in set(components(c)))
    comps = sorted(k for k, n in comp_cnt.items() if n >= 3)
    kidx = {k: i for i, k in enumerate(comps)}
    print("部件数", len(comps), flush=True)

    def comp_vec(ch: str) -> np.ndarray:
        v = np.zeros(len(comps), np.float32)
        for k in components(ch):
            if k in kidx:
                v[kidx[k]] = 1.0
        return v

    def load_real(split):
        xs, ys = [], []
        for it in items:
            if it["split"] != split or it["char"] in held:
                continue
            img = cv2.imread(it["png"], cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            xs.append(normalize_patch(img).astype(np.uint8))
            ys.append(cidx[it["char"]])
        return np.stack(xs), np.array(ys)

    t0 = time.time()
    Xtr, Ytr = load_real("seen_train")
    Xte, Yte = load_real("seen_test")
    Xun, Yun = load_real("unseen")
    print(f"真刻例 train {len(Xtr)} / seen_test {len(Xte)} / unseen {len(Xun)}"
          f"  {time.time()-t0:.0f}s", flush=True)

    fonts = _font_files()
    t0 = time.time()
    font_imgs: dict[int, list[np.ndarray]] = {}
    for ch, ci in cidx.items():
        lst = []
        for f in fonts:
            try:
                im = render_char(ch, f, size=SIZE)
            except Exception:  # noqa: BLE001
                continue
            if im is not None and im.any():
                lst.append(im.astype(np.uint8))
        if lst:
            font_imgs[ci] = lst
    print(f"字体渲染 {sum(len(v) for v in font_imgs.values())} 张 / {len(font_imgs)} 类"
          f"  {time.time()-t0:.0f}s", flush=True)

    extra_imgs: dict[int, list[np.ndarray]] = {}
    if a.extra_real:
        from open_guji_cv.clustering.extra_glyphs import load_many
        t0 = time.time()
        ex = load_many(a.extra_real, classes)      # charset=classes 已排掉留出字
        for ch, lst in ex.items():
            if ch in held:
                continue
            extra_imgs[cidx[ch]] = [x.astype(np.uint8) for x in lst]
        print(f"外部真刻本 {sum(len(v) for v in extra_imgs.values())} 张 / "
              f"{len(extra_imgs)} 类  {time.time()-t0:.0f}s", flush=True)

    # ── 模型 ──
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

    cosine_head = a.cosine_head or a.loss in ("cosface", "arcface")

    class Net(nn.Module):
        def __init__(self, n_cls, n_comp, d=256):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False),
                                      nn.BatchNorm2d(32), nn.ReLU())
            self.l1 = Block(32, 64, 2)
            self.l2 = Block(64, 128, 2)
            self.l3 = Block(128, 256, 2)
            self.l4 = Block(256, 256, 2)
            self.emb = nn.Linear(256 * 4 * 4, d)
            self.comp = nn.Linear(d, n_comp)
            if cosine_head:
                self.W = nn.Parameter(torch.randn(n_cls, d) * 0.01)
                self.cls = None
            else:
                self.cls = nn.Linear(d, n_cls)

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * a.scale
            if cosine_head:
                # cos(θ) ∈ [-1,1]；乘 scale 在损失里做（要先加 margin）
                cos = F.normalize(e, dim=1) @ F.normalize(self.W, dim=1).t()
                return e, cos, self.comp(e)
            return e, self.cls(e), self.comp(e)

    net = Net(len(classes), len(comps)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    comp_tr = torch.tensor(np.stack([comp_vec(c) for c in classes]), device=dev)

    def batch_iter():
        xs, ys = [], []
        for x, y in zip(Xtr, Ytr):
            xs.append(degrade(x, rng)); ys.append(y)
        for ci, lst in font_imgs.items():
            for _ in range(a.font_per_class):
                xs.append(degrade(rng.choice(lst), rng)); ys.append(ci)
        for ci, lst in extra_imgs.items():
            for _ in range(a.extra_per_class):
                xs.append(degrade(rng.choice(lst), rng)); ys.append(ci)
        idx = list(range(len(xs)))
        rng.shuffle(idx)
        for i in range(0, len(idx), a.bs):
            j = idx[i:i + a.bs]
            X = torch.tensor(np.stack([xs[k] for k in j])[:, None].astype(np.float32), device=dev)
            Y = torch.tensor([ys[k] for k in j], device=dev)
            yield X, Y

    def head_loss(logits, Y, m_now):
        """logits: cosine_head 时是 cos(θ)（未乘 scale）；否则是普通 logits。"""
        if not cosine_head:
            return F.cross_entropy(logits, Y, label_smoothing=a.label_smoothing)
        cos = logits.clamp(-1 + 1e-7, 1 - 1e-7)
        if a.loss == "cosface" and m_now > 0:
            tgt = cos.gather(1, Y[:, None]) - m_now
        elif a.loss == "arcface" and m_now > 0:
            th = torch.acos(cos.gather(1, Y[:, None]))
            tgt = torch.cos(th + m_now)
        else:
            tgt = cos.gather(1, Y[:, None])
        out = cos.scatter(1, Y[:, None], tgt) * a.scale
        return F.cross_entropy(out, Y, label_smoothing=a.label_smoothing)

    @torch.no_grad()
    def cls_eval(X, Y, name):
        net.eval()
        r1 = r10 = 0
        for i in range(0, len(X), 512):
            xb = torch.tensor(X[i:i + 512][:, None].astype(np.float32), device=dev)
            _, lg, _ = net(xb)
            top = lg.topk(10, dim=1).indices.cpu().numpy()
            yb = Y[i:i + 512]
            r1 += (top[:, 0] == yb).sum()
            r10 += (top == yb[:, None]).any(1).sum()
        net.train()
        print(f"  {name:10s} cls top1 {r1/len(X):5.1%}  top10 {r10/len(X):5.1%}", flush=True)
        return r1 / len(X), r10 / len(X)

    ev = load_heldout_eval(sorted(held))
    print(f"留出评测 query {len(ev['q_chars'])} / 字种 {len(set(ev['q_chars']))}"
          f"  template {len(ev['t_chars'])}", flush=True)

    steps = math.ceil((len(Xtr) + a.font_per_class * len(font_imgs)
                       + a.extra_per_class * len(extra_imgs)) / a.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * steps)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    warm_ep = max(1, int(a.epochs * a.warmup_frac))
    hist = []
    best = -1.0
    for ep in range(a.epochs):
        m_now = a.margin * min(1.0, (ep + 1) / warm_ep) if a.loss != "ce" else 0.0
        t0 = time.time(); tot = n = 0
        for X, Y in batch_iter():
            _, lg, cp = net(X)
            loss = head_loss(lg, Y, m_now) + a.comp_w * \
                F.binary_cross_entropy_with_logits(cp, comp_tr[Y])
            opt.zero_grad(set_to_none=True)
            loss.backward(); opt.step(); sched.step()
            tot += float(loss) * len(Y); n += len(Y)
        line = {"ep": ep + 1, "loss": tot / n, "m": m_now, "s": time.time() - t0}
        print(f"epoch {ep+1}/{a.epochs} loss {tot/n:.3f} m={m_now:.3f} {time.time()-t0:.0f}s",
              flush=True)
        if (ep + 1) % a.eval_every == 0 or ep + 1 == a.epochs:
            line["seen_test"] = cls_eval(Xte, Yte, "seen_test")
            line["unseen_cls"] = cls_eval(Xun, Yun, "unseen")
            r = retrieval_eval(net, dev, ev, a.scale)
            line["heldout"] = r
            print(f"  heldout    emb top1 {r['top1']:5.1%}  top5 {r['top5']:5.1%}"
                  f"  top10 {r['top10']:5.1%}", flush=True)
            score = r["top10"]
            if score > best:
                best = score
                torch.save({"state": net.state_dict(), "classes": classes,
                            "comps": comps, "cfg": vars(a), "cosine_head": cosine_head},
                           out / "best.pt")
        hist.append(line)
        (out / "history.json").write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    torch.save({"state": net.state_dict(), "classes": classes, "comps": comps,
                "cfg": vars(a), "cosine_head": cosine_head}, out / "last.pt")
    print("best heldout top10", f"{best:.1%}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
