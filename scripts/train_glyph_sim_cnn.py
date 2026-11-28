"""训 5a 精验用的度量学习 CNN（`clustering.sim_cnn.SimNet`），权重给 `glyph_match.sim_model` 用。

    python scripts/train_glyph_sim_cnn.py --db <书的 glyph.db> --out models/glyph_sim_qtw/model.pt \\
        [--exclude <评测分片>/expected.json ...] [--epochs 15] [--seed 0]

做法（2026-11-10，A23；数字见 ai-team `domain/CV/字形领域/5a相似度算法-2026-11-09.md`）：
- 训练集＝这本书字形库的刻例（`seeding.load_matcher_from_db`，归一图与生产匹配器同一份），
  `--exclude` 给的分片里出现的物理格一律不进训练（评测格不许见过）；
- 每个码位一类，CosFace（m=0.25, s=24），嵌入 128 维；
- 增强：±3° 旋转、0.9–1.1 缩放、±4px 平移；膨胀 15%、腐蚀 2×2 15%、腐蚀 3×3 10%（细笔）；
  25% 擦掉 1–2 块 4–14px 的矩形（残笔）；30% 加 1–5 个小墨点；
- CPU 单机，全唐文 3 万例 15 轮约 40 分钟。

训完要做的：`scripts/eval_sim_bench.py` 量逐对分、`scripts/eval_match_bench.py` 端到端标 same 门槛；
换现役权重走 `models/README.md`（登记表＋R2），并按书重标共识升档门槛。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _cell(iid: str) -> str:
    return iid.split(":", 1)[1] if iid.startswith(("v2:", "v1:")) else iid


def augment(b: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = np.empty_like(b)
    for i, a in enumerate(b):
        s = rng.uniform(0.9, 1.1)
        M = cv2.getRotationMatrix2D((31.5, 31.5), rng.uniform(-3, 3), s)
        M[:, 2] += rng.uniform(-4, 4, 2)
        a = cv2.warpAffine(a, M, (64, 64), flags=cv2.INTER_LINEAR)
        r = rng.random()
        if r < 0.15:
            a = cv2.dilate(a, np.ones((2, 2), np.uint8))
        elif r < 0.30:
            a = cv2.erode(a, np.ones((2, 2), np.uint8))
        elif r < 0.40:
            a = cv2.erode(a, np.ones((3, 3), np.uint8))
        if rng.random() < 0.25:
            for _ in range(int(rng.integers(1, 3))):
                x0, y0 = rng.integers(0, 64, 2)
                w, h = rng.integers(4, 14, 2)
                a[y0:y0 + h, x0:x0 + w] = 0
        if rng.random() < 0.3:
            for _ in range(int(rng.integers(1, 6))):
                cv2.circle(a, (int(rng.integers(64)), int(rng.integers(64))), int(rng.integers(1, 3)), 1.0, -1)
        out[i] = a > 0.5
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exclude", action="append", default=[], help="评测分片 expected.json（其中的格不进训练），可重复")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", help="从已训权重起步微调（库小的书，如史記：拿全唐文权重做起点、只用本书刻例训）")
    ap.add_argument("--lr", type=float, default=3e-3, help="OneCycle 峰值学习率（微调可调小）")
    a = ap.parse_args(argv)

    import torch
    import torch.nn.functional as F
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.clustering.sim_cnn import SimNet

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    m, _ = load_matcher_from_db(GlyphDB(a.db))
    held: set[str] = set()
    for f in a.exclude:
        held |= {_cell(x["instance_id"]) for x in json.loads(Path(f).read_text(encoding="utf-8"))["instances"]}
    keep = [j for j, iid in enumerate(m._ids) if _cell(str(iid)) not in held and not str(iid).startswith("font:")]
    chars = sorted({m._chars[j] for j in keep})
    cid = {c: i for i, c in enumerate(chars)}
    X = np.stack([m._patches[j] for j in keep]).astype(np.float32)
    Y = np.array([cid[m._chars[j]] for j in keep])
    print(f"训练 {len(keep)} 例、{len(chars)} 类（排除评测格 {len(held)}）", flush=True)

    net = SimNet(n_cls=len(chars))
    if a.init:
        sd = {k: v for k, v in torch.load(a.init, map_location="cpu").items() if k != "W"}
        miss = net.load_state_dict(sd, strict=False)
        assert set(miss.missing_keys) <= {"W"} and not miss.unexpected_keys, miss
        with torch.no_grad():                # 类中心用起点权重下各类刻例嵌入的均值，免得头几步把骨干冲坏
            net.eval()
            Z = torch.cat([net.embed(torch.from_numpy(X[i:i + 512])[:, None]) for i in range(0, len(X), 512)])
            net.W.copy_(F.normalize(torch.zeros(len(chars), Z.shape[1]).index_add_(0, torch.from_numpy(Y), Z), dim=1))
    opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-4)
    steps = a.epochs * (len(X) // a.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=steps)
    t0 = time.time()
    for ep in range(a.epochs):
        net.train()
        perm = rng.permutation(len(X))
        tot = 0.0
        for k in range(len(X) // a.batch):
            idx = perm[k * a.batch:(k + 1) * a.batch]
            xb = torch.from_numpy(augment(X[idx], rng))[:, None].float()
            yb = torch.from_numpy(Y[idx])
            z = net.embed(xb)
            cos = z @ F.normalize(net.W, dim=1).t()
            loss = F.cross_entropy(24.0 * (cos - 0.25 * F.one_hot(yb, cos.shape[1])), yb)   # CosFace
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item()
        print(ep, round(tot / max(1, len(X) // a.batch), 3), round(time.time() - t0), flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sd = {k: v for k, v in net.state_dict().items() if k != "W"}     # 推理不要类中心
    torch.save(sd, a.out)
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
