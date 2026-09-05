# -*- coding: utf-8 -*-
"""零样本正面对比：HOG 字体检索 vs CNN 分类 vs 两者融合。同一批样本、同一字表。

融合用倒数排名（RRF）：score = Σ 1/(60+rank)。不用分数相加——HOG 余弦与
softmax 概率量纲不同，RRF 只看名次，不用校准。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

BENCH = Path("cache/glyph_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="cache/glyph_cnn/best.pt")
    ap.add_argument("--split", default="unseen")
    ap.add_argument("--n", type=int, default=0, help="0=全部")
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--rare", action="store_true", help="改测 rare-char 21 条")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--tta", action="store_true", help="CNN 测试时增广：5 个视角平均 logits")
    ap.add_argument("--w-cnn", type=float, default=1.0, help="RRF 里 CNN 名次的权重（HOG=1）")
    ap.add_argument("--w-hog", type=float, default=1.0, help="RRF 里 HOG 名次的权重")
    ap.add_argument("--w-emb", type=float, default=1.0, help="RRF 里 embedding 检索名次的权重")
    ap.add_argument("--emb", action="store_true",
                    help="第三源：CNN embedding 对字体模板做余弦检索（CCR-CLIP-lite）")
    ap.add_argument("--wear", type=float, default=0.0,
                    help="评测时给查询图加磨损：0=不加；0.5=腐蚀+抹白一次；1=两次")
    a = ap.parse_args()

    import torch
    from open_guji_cv.clustering.font_candidates import book_charset, candidates
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.variants import are_variants

    if a.rare:
        items = [json.loads(l) for l in Path("../open-guji-dataset/rare-char/items.jsonl").read_text(encoding="utf-8").splitlines()]
        items = [{"png": i["input"]["patch"], "char": i["expected"]["char"]} for i in items]
    else:
        items = [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines()]
        items = [i for i in items if i["split"] == a.split]
        if a.n:
            import random
            random.Random(1).shuffle(items)
            items = items[:a.n]
    cs = tuple(book_charset(a.corpus))

    ck = torch.load(a.model, map_location="cpu", weights_only=False)
    classes = ck["classes"]
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("tg", "scripts/train_glyph_cnn.py")
    # 复用训练脚本里的 Net 定义：把 main 里的类抠出来太绕，这里直接重建同结构
    import torch.nn as nn, torch.nn.functional as F

    class Block(nn.Module):
        def __init__(self, i, o, s):
            super().__init__()
            self.c1 = nn.Conv2d(i, o, 3, s, 1, bias=False); self.b1 = nn.BatchNorm2d(o)
            self.c2 = nn.Conv2d(o, o, 3, 1, 1, bias=False); self.b2 = nn.BatchNorm2d(o)
            self.sc = nn.Sequential(nn.Conv2d(i, o, 1, s, bias=False), nn.BatchNorm2d(o)) if (s != 1 or i != o) else nn.Identity()
        def forward(self, x):
            y = F.relu(self.b1(self.c1(x))); y = self.b2(self.c2(y)); return F.relu(y + self.sc(x))

    class Net(nn.Module):
        def __init__(self, n_cls, n_comp, d=256):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())
            self.l1 = Block(32, 64, 2); self.l2 = Block(64, 128, 2); self.l3 = Block(128, 256, 2); self.l4 = Block(256, 256, 2)
            self.emb = nn.Linear(256 * 16, d); self.cls = nn.Linear(d, n_cls); self.comp = nn.Linear(d, n_comp)
        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
            return e, self.cls(e), self.comp(e)

    net = Net(len(classes), len(ck["comps"]))
    net.load_state_dict(ck["state"]); net.eval()
    cs_idx = {c: i for i, c in enumerate(classes)}
    allowed = torch.tensor([cs_idx[c] for c in cs if c in cs_idx])

    emb_mat = None
    emb_chars: list[str] = []
    if a.emb:
        from open_guji_cv.clustering.font_candidates import _font_files
        from open_guji_cv.clustering.synth import render_char
        fonts = _font_files()
        vecs, names = [], []
        with torch.no_grad():
            for ch in cs:
                ims = []
                for f in fonts:
                    try:
                        im = render_char(ch, f, size=64)
                    except Exception:
                        continue
                    if im is not None and im.any():
                        ims.append(im.astype(np.uint8))
                if not ims:
                    continue
                x = torch.tensor(np.stack(ims)[:, None].astype(np.float32))
                e, _, _ = net(x)
                v = e.mean(0)
                vecs.append((v / (v.norm() + 1e-9)).numpy())
                names.append(ch)
        emb_mat = np.stack(vecs)
        emb_chars = names
        print(f"embedding 模板 {len(emb_chars)} 字")

    def wear(q: np.ndarray) -> np.ndarray:
        """评测用磨损：腐蚀一圈 + 横向抹白，模拟断墨。确定性（按图求种子）。"""
        if a.wear <= 0:
            return q
        import random
        rng = random.Random(int(q.sum()))
        x = cv2.erode(q, np.ones((2, 2), np.uint8))
        for _ in range(1 if a.wear < 1 else 2):
            y = rng.randint(6, 56)
            x[y:y + 2, :] = 0
        return x

    def hit(order, g):
        r = next((i + 1 for i, c in enumerate(order) if c == g or are_variants(c, g)), 999)
        return r

    rk = {k: Counter() for k in ("hog", "cnn", "emb", "rrf")}
    n = 0
    with torch.no_grad():
        for it in items:
            img = cv2.imread(it["png"], cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            q = wear(normalize_patch(img)); g = it["char"]; n += 1
            hog = [h.char for h in candidates(q, cs, k=a.k)]
            views = [q]
            if a.tta:
                for ang in (-4, 4):
                    M = cv2.getRotationMatrix2D((32, 32), ang, 1.0)
                    views.append(cv2.warpAffine(q, M, (64, 64), flags=cv2.INTER_NEAREST, borderValue=0))
                views.append(cv2.dilate(q, np.ones((2, 2), np.uint8)))
                views.append(cv2.erode(q, np.ones((2, 2), np.uint8)))
            x = torch.tensor(np.stack(views)[:, None].astype(np.float32))
            e_all, lg, _ = net(x)
            lg = torch.log_softmax(lg, dim=1).mean(0)
            emb_order: list[str] = []
            if emb_mat is not None:
                qe = e_all.mean(0); qe = (qe / (qe.norm() + 1e-9)).numpy()
                sims = emb_mat @ qe
                emb_order = [emb_chars[int(i)] for i in np.argsort(-sims)[:a.k]]
            sub = lg[allowed]
            top = sub.topk(a.k).indices
            cnn = [classes[int(allowed[i])] for i in top]
            fused = Counter()
            srcs = [(hog, a.w_hog), (cnn, a.w_cnn)] + ([(emb_order, a.w_emb)] if emb_order else [])
            for order, w in srcs:
                for r, c in enumerate(order):
                    fused[c] += w / (60 + r)
            rrf = [c for c, _ in fused.most_common(a.k)]
            pairs = [("hog", hog), ("cnn", cnn)] + ([("emb", emb_order)] if emb_order else []) + [("rrf", rrf)]
            for name, order in pairs:
                r = hit(order, g)
                rk[name]["t1"] += r == 1; rk[name]["t5"] += r <= 5; rk[name]["t10"] += r <= 10
    tag = "rare-char" if a.rare else f"{a.split}"
    print(f"{tag} n={n}（异体算对）")
    for name in ("hog", "cnn", "emb", "rrf"):
        c = rk[name]
        if not sum(c.values()) and name == "emb":
            continue
        print(f"  {name:4s} top1 {c['t1']/n:5.1%}  top5 {c['t5']/n:5.1%}  top10 {c['t10']/n:5.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
