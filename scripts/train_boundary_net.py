"""字间界线判官（`impl/keben/boundary_net`）：出训练样本、训练、留出册验证。

银标＝一本书已跑完的 row_segment 产物（含人钉列，产物包或工作区 products 均可），不用人标：
正样本＝全正文列里相邻两字格的界线（及同一条干净白缝里随机一处），负样本＝离界线 ≥0.2 格距的行墨谷（多半是字内白缝）。
窗口与推理同一函数（`boundary_net._patch`：线上下各一格、内容宽，缩 64×96），网络结构同 `boundary_net._net`。

    # 1. 出样本（每册随机 40 页；原图在 <raw>/<册>/<页>.png，产物在 <products>/<册>/row_segment/）
    python scripts/train_boundary_net.py build --products <产物根> --raw <原图根> --vols 20,21,…,41 --per-vol 40 --out bn.npz
    # 2. 训练（留出一册验证；1 轮通常就够，AUC 0.99+）
    python scripts/train_boundary_net.py train --data bn.npz --val-vol 41 --epochs 1 --out models/boundary_net_<书>_v1/model.pt
    # 3. 之后：guji model registry → guji model upload --execute → 补 core/model_pack.KINDS 与 config/model-provenance.json

借用还是单独训、怎么验收：doc/2-切字/字间判官.md。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.impl.keben import boundary_net as BN  # noqa: E402

CLEAN = 0.02       # 行墨（5 行平滑）低于它算干净白缝
NEG_GAP = 0.2      # 负样本离任何界线至少这么多格距
NEG_PER_POS = 2.0


def _col_lines(col: dict):
    """全正文、≥4 字的列 → (按 y 排序的界线, 内容左右 x)；其余列不出样本。"""
    cells = [c for c in col["cells"] if c.get("kind") not in ("blank", None)]
    if len(cells) < 4 or any(c.get("kind") != "char" for c in cells):
        return None
    bx = []
    for c in cells:
        xs = [p[0] for p in c["quad_page"]]
        ys = [p[1] for p in c["quad_page"]]
        bx.append((min(xs), min(ys), max(xs), max(ys)))
    bx.sort(key=lambda b: b[1])
    lines = [bx[0][1]] + [(bx[i - 1][3] + bx[i][1]) / 2 for i in range(1, len(bx))] + [bx[-1][3]]
    return lines, float(np.median([b[0] for b in bx])), float(np.median([b[2] for b in bx]))


def page_samples(img: np.ndarray, rs: dict, rng: random.Random):
    """一页 → (窗口列表, 标签列表)。quad_page 是右上原点（x 从右往左），原图按左上原点取。"""
    H, W = img.shape
    P = rs["cells"].get("period") or 120
    X, Y = [], []
    for col in rs["cells"]["columns"]:
        r = _col_lines(col)
        if not r:
            continue
        lines, x0, x1 = r
        X0, X1 = int(W - x1), int(W - x0)
        if X1 - X0 < 20:
            continue
        gcol = img[:, max(0, X0):min(W, X1)]
        lo, hi = max(0, int(lines[0] - 0.3 * P)), int(lines[-1] + 0.3 * P)
        curve = (gcol[lo:hi] < BN.INK_THRESHOLD).mean(axis=1)
        cs = np.convolve(curve, np.ones(5) / 5, mode="same")
        inner = lines[1:-1]
        for y in inner:
            X.append(BN._patch(gcol, y, P)); Y.append(1)
            yi = int(round(y)) - lo
            if 0 <= yi < len(cs) and cs[yi] < CLEAN:      # 同一条干净白缝里的别处也算界
                a = b = yi
                while a > 0 and cs[a - 1] < CLEAN and yi - a < 0.3 * P:
                    a -= 1
                while b < len(cs) - 1 and cs[b + 1] < CLEAN and b - yi < 0.3 * P:
                    b += 1
                if b - a >= 6:
                    X.append(BN._patch(gcol, rng.randint(a, b) + lo, P)); Y.append(1)
        negs = [v + lo for v in BN._valleys(curve)]
        negs = [v for v in negs if lines[0] < v < lines[-1] and min(abs(v - l) for l in lines) > NEG_GAP * P]
        rng.shuffle(negs)
        for v in negs[:int(NEG_PER_POS * len(inner)) + 1]:
            X.append(BN._patch(gcol, v, P)); Y.append(0)
    return X, Y


def cmd_build(a) -> None:
    rng = random.Random(a.seed)
    X, Y, G = [], [], []
    for v in a.vols.split(","):
        rsd = Path(a.products) / v / "row_segment"
        pages = sorted(int(p.stem[1:]) for p in rsd.glob("p*.json"))
        pages = [p for p in pages if p > a.skip_pages]
        rng.shuffle(pages)
        for p in pages[:a.per_vol]:
            img = cv2.imread(str(Path(a.raw) / v / f"{p}.png"), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            x, y = page_samples(img, json.loads((rsd / f"p{p:04d}.json").read_text(encoding="utf-8")), rng)
            X += x; Y += y; G += [f"{v}:{p}"] * len(x)
        print(f"{v}: 累计 {len(X)} 窗口（正 {sum(Y)}）", flush=True)
    np.savez_compressed(a.out, X=np.stack(X), Y=np.array(Y, np.int8), G=np.array(G))


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    n1 = int((y > 0.5).sum()); n0 = len(y) - n1
    return float((r[y > 0.5].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cmd_train(a) -> None:
    import torch
    import torch.nn as nn
    torch.set_num_threads(a.threads); torch.manual_seed(a.seed); np.random.seed(a.seed)
    d = np.load(a.data)
    X, Y, G = torch.from_numpy(d["X"]), d["Y"].astype(np.float32), d["G"]
    val = np.array([g.startswith(a.val_vol + ":") for g in G])
    Yt = torch.tensor(Y)

    def batch(ix):   # 按批转 float：整份转会 OOM（24 万窗口）
        return (1 - X[torch.as_tensor(ix)].float() / 255.0).unsqueeze(1)

    m = BN._net(); opt = torch.optim.AdamW(m.parameters(), 2e-3, weight_decay=1e-4)
    tr, va = np.where(~val)[0], np.where(val)[0]
    lossf = nn.BCEWithLogitsLoss()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    if not len(tr):
        raise SystemExit("训练集是空的：--val-vol 以外没有样本")
    for ep in range(a.epochs):
        m.train(); np.random.shuffle(tr)
        for i in range(0, len(tr), 256):
            b = tr[i:i + 256]; x = batch(b)
            if np.random.rand() < 0.5:
                x = torch.flip(x, [3])
            opt.zero_grad(); loss = lossf(m(x).squeeze(1), Yt[b]); loss.backward(); opt.step()
        m.eval()
        with torch.no_grad():
            p = torch.cat([torch.sigmoid(m(batch(va[i:i + 1024])).squeeze(1)) for i in range(0, len(va), 1024)]).numpy()
        acc = float(((p > 0.5) == (Y[va] > 0.5)).mean()) if len(va) else float("nan")
        auc = _auc(Y[va], p) if len(va) else float("nan")
        print(f"轮 {ep}：loss {float(loss):.4f}，留出 {a.val_vol} 准确率 {acc:.4f}、AUC {auc:.4f}", flush=True)
        torch.save(m.state_dict(), a.out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="从产物＋原图出训练窗口")
    b.add_argument("--products", required=True); b.add_argument("--raw", required=True)
    b.add_argument("--vols", required=True); b.add_argument("--per-vol", type=int, default=40)
    b.add_argument("--skip-pages", type=int, default=2, help="跳过前几页（卷首题署）")
    b.add_argument("--seed", type=int, default=1126); b.add_argument("--out", required=True)
    t = sub.add_parser("train", help="训练并在留出册上验")
    t.add_argument("--data", required=True); t.add_argument("--val-vol", required=True)
    t.add_argument("--epochs", type=int, default=1); t.add_argument("--threads", type=int, default=4)
    t.add_argument("--seed", type=int, default=0); t.add_argument("--out", required=True)
    a = ap.parse_args()
    {"build": cmd_build, "train": cmd_train}[a.cmd](a)


if __name__ == "__main__":
    main()
