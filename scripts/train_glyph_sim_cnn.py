"""训 5a 精验用的度量学习 CNN（`clustering.sim_cnn.SimNet`），权重给 `glyph_match.sim_model` 用。

    python scripts/train_glyph_sim_cnn.py --db <书的 glyph.db> --out models/glyph_sim_qtw/model.pt \\
        [--exclude <评测分片>/expected.json ...] [--epochs 15] [--seed 0]

    # 几本书合训一个通用底座（2026-11-16）：--db 给多次，同一码位跨书合成一类
    python scripts/train_glyph_sim_cnn.py --db <殿本 glyph.db> --db <史記 glyph.db> --db <全唐文 glyph.db> \\
        --exclude <各书评测分片>/expected.json ... --epochs 8 --resume --out models/glyph_sim_all/model.pt

做法（2026-11-10，A23；数字见 ai-team `domain/CV/字形领域/5a相似度算法-2026-11-09.md`）：
- 训练集＝这本书字形库的刻例（`seeding.load_matcher_from_db`，归一图与生产匹配器同一份），
  `--exclude` 给的分片里出现的物理格一律不进训练（评测格不许见过）；
- 每个码位一类，CosFace（m=0.25, s=24），嵌入 128 维；
- 增强：±3° 旋转、0.9–1.1 缩放、±4px 平移；膨胀 15%、腐蚀 2×2 15%、腐蚀 3×3 10%（细笔）；
  25% 擦掉 1–2 块 4–14px 的矩形（残笔）；30% 加 1–5 个小墨点；
- CPU 单机，全唐文 3 万例 15 轮约 40 分钟。

合训与微调（2026-11-16，跨书通用底座实验；数字见 ai-team
`domain/CV/字形领域/5a相似度CNN深化-2026-11-15/跨书通用底座-2026-11-16.md`，用法见 guji-manager `doc/参考/5a相似度模型.md`）：
- `--db` 可给多次。缺省**合类**：同一码位不管出自哪本书都是一类（同形异码、异体不并）；`--per-book-classes` 改成每本书的每个字各一类
  （实验里处处不如合类，留着只为复现）。三书合训 8 轮与单书 15 轮步数相当；
- `--init` 从底座权重起步、只用本书刻例微调：本书刻例少（几千例以内）时远好于从零训，攒到两三万例后与合训持平；
- `--resume`：每轮末在 `<out>.ckpt` 存档，中断后同一条命令接着训（云端容器会被回收；纯 CPU 单线程约 44 张/秒）；
- `--limit N`：每本书只取 N 例（固定随机序），量「刻例只攒到 N 例」时用；
- `--exclude` 按物理格号排除，对所有 `--db` 一起生效（各书册名不同，格号不会撞）。

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


def _exclude_ids(p: Path) -> list[str]:
    """评测分片里的格号：expected.json 的 instances、jsonl 每行的 query_id／id（连同候选）、或 .txt 每行一个。"""
    t = p.read_text(encoding="utf-8")
    if p.suffix == ".txt":
        return [x.strip() for x in t.splitlines() if x.strip()]
    if p.suffix == ".jsonl":
        out = []
        for ln in t.splitlines():
            if ln.strip():
                x = json.loads(ln)
                out += [x[k] for k in ("query_id", "id", "instance_id") if k in x]
        return out
    return [x["instance_id"] for x in json.loads(t)["instances"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, action="append", help="书的 glyph.db；给多次＝几本书合训")
    ap.add_argument("--out", required=True)
    ap.add_argument("--exclude", action="append", default=[],
                    help="评测格不进训练，可重复：分片 expected.json、items.jsonl／rare.jsonl（取 query_id／id）、"
                         "或每行一个格号的 .txt（dataset glyph-match/train_exclude/<书>.cells.txt）")
    ap.add_argument("--exclude-chars", action="append", default=[],
                    help="整字类不进训练的字表（空白分隔），如对抗集的留出字 dataset glyph-match/train_exclude/<书>.held_chars.txt；"
                         "对所有 --db 生效，只在训那本书时给")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", help="从已训权重起步微调（库小的书，如史記：拿全唐文权重做起点、只用本书刻例训）")
    ap.add_argument("--lr", type=float, default=3e-3, help="OneCycle 峰值学习率（微调可调小）")
    ap.add_argument("--per-book-classes", action="store_true", help="合训时每本书的每个字各一类（缺省同码位跨书合一类）")
    ap.add_argument("--limit", type=int, default=0, help="每本书只取这么多例（固定随机序；0＝全用）")
    ap.add_argument("--resume", action="store_true", help="每轮末存档到 <out>.ckpt，有存档就接着训")
    ap.add_argument("--threads", type=int, default=0, help="torch 线程数（0＝不设；几个训练并行跑时设 1）")
    a = ap.parse_args(argv)

    import torch
    import torch.nn.functional as F
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.clustering.sim_cnn import SimNet

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    if a.threads:
        torch.set_num_threads(a.threads)
    held: set[str] = set()
    for f in a.exclude:
        held |= {_cell(i) for i in _exclude_ids(Path(f))}
    held_chars: set[str] = set()
    for f in a.exclude_chars:
        held_chars |= {x.strip() for x in Path(f).read_text(encoding="utf-8").split() if x.strip()}
    xs, keys = [], []
    for bi, db in enumerate(a.db):
        m, _ = load_matcher_from_db(GlyphDB(db))
        keep = [j for j, iid in enumerate(m._ids) if _cell(str(iid)) not in held and not str(iid).startswith("font:")
                and m._chars[j] not in held_chars]
        if a.limit:
            keep = sorted(np.random.default_rng(1).permutation(keep)[:a.limit].tolist())
        xs.append(np.stack([m._patches[j] for j in keep]).astype(np.float32))
        keys += [(bi, m._chars[j]) if a.per_book_classes else m._chars[j] for j in keep]
        print(f"{db}：{len(keep)} 例", flush=True)
    X = np.concatenate(xs)
    chars = sorted(set(keys))
    cid = {c: i for i, c in enumerate(chars)}
    Y = np.array([cid[c] for c in keys])
    print(f"训练 {len(X)} 例、{len(chars)} 类（排除评测格 {len(held)}）", flush=True)

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
    ck = Path(str(a.out) + ".ckpt")
    ep0, spent = 0, 0.0
    if a.resume and ck.is_file():
        c = torch.load(ck, map_location="cpu", weights_only=False)
        if c["n"] != len(X) or c["classes"] != len(chars) or c["epochs"] != a.epochs:
            raise SystemExit(f"{ck} 是另一份训练的存档（例数／类数／轮数对不上），删掉或换 --out")
        net.load_state_dict(c["net"])
        opt.load_state_dict(c["opt"])
        sched.load_state_dict(c["sched"])
        rng.bit_generator.state = c["rng"]
        ep0, spent = c["ep"] + 1, c["secs"]
        print(f"接着训：从第 {ep0} 轮", flush=True)
    t0 = time.time()
    for ep in range(ep0, a.epochs):
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
        secs = spent + time.time() - t0
        print(ep, round(tot / max(1, len(X) // a.batch), 3), round(secs), flush=True)
        if a.resume:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(ck) + ".tmp")
            torch.save({"net": net.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                        "rng": rng.bit_generator.state, "ep": ep, "secs": secs, "n": len(X),
                        "classes": len(chars), "epochs": a.epochs}, tmp)
            tmp.replace(ck)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sd = {k: v for k, v in net.state_dict().items() if k != "W"}     # 推理不要类中心
    torch.save(sd, a.out)
    ck.unlink(missing_ok=True)
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
