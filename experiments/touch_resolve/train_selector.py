# -*- coding: utf-8 -*-
"""在 `build_selector_dataset.py` 的表上训一个「切法选择器」，与单特征基线比。

    python experiments/touch_resolve/train_selector.py [--ds out/selector_ds/vol02.jsonl]

模型：逐候选打分的线性 softmax 排序器（torch，几十个参数），按**页**分 5 折交叉验证报折外命中率
——按切点分折会让同一页的切点分到两边，页内相关性会把成绩抬高。
基线：`agree 最高`（74.1%）。要打败它才值得上生产；打不过就说明特征不够，记为负结果。
产出 out/selector/<ds名>.json（每折权重、折外命中、逐特征权重）。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT_ROOT, jdump  # noqa: E402

FEATS = [
    ("agree", lambda r: r.get("agree"), 0.0),
    ("dis_unet_log", lambda r: math.log1p(r["dis_unet"]) if r.get("dis_unet") is not None else None, 0.0),
    ("agree_gap", lambda r: r.get("agree_gap_to_best"), 0.0),
    ("seam_ink_log", lambda r: math.log1p(max(r.get("seam_ink") or 0, 0)), 0.0),
    ("dev_max_log", lambda r: math.log1p(max(r.get("dev_max") or 0, 0)), 0.0),
    ("dev_mean_log", lambda r: math.log1p(max(r.get("dev_mean") or 0, 0)), 0.0),
    ("straight_ink_log", lambda r: math.log1p(max(r.get("straight_ink") or 0, 0)), 0.0),
    ("up_h", lambda r: r.get("up_h_ratio"), 1.0),
    ("dn_h", lambda r: r.get("dn_h_ratio"), 1.0),
    ("n_cand", lambda r: r.get("n_cand"), 2.0),
]
KINDS = ("straight", "seam_narrow", "seam_wide", "unet_seam", "period_up", "period_dn")


def vec(r: dict) -> list[float]:
    out = []
    for _, fn, dflt in FEATS:
        v = fn(r)
        out.append(float(dflt if v is None else v))
    out += [float(r.get(f"is_{k}", 0)) for k in KINDS]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default=None)
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()
    import torch
    ds = Path(a.ds) if a.ds else OUT_ROOT / "selector_ds" / "vol02.jsonl"
    rows = [json.loads(l) for l in ds.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_pt: dict[str, list[dict]] = {}
    for r in rows:
        by_pt.setdefault(r["id"], []).append(r)
    pts = [(pid, cs) for pid, cs in by_pt.items() if len(cs) >= 2 and any(c["is_pick"] for c in cs)]
    print(f"切点 {len(pts)}（候选 ≥2 且有人选）")
    pages = sorted({pid.rsplit(":", 2)[0] for pid, _ in pts})
    random.Random(0).shuffle(pages)
    folds = [set(pages[i::a.folds]) for i in range(a.folds)]
    dim = len(vec(pts[0][1][0]))
    picked: dict[str, dict] = {}
    weights = []
    for k in range(a.folds):
        tr = [(pid, cs) for pid, cs in pts if pid.rsplit(":", 2)[0] not in folds[k]]
        te = [(pid, cs) for pid, cs in pts if pid.rsplit(":", 2)[0] in folds[k]]
        if not tr or not te:
            continue
        X = [torch.tensor([vec(c) for c in cs], dtype=torch.float32) for _, cs in tr]
        Y = [torch.tensor([float(c["is_pick"]) for c in cs]) for _, cs in tr]
        allX = torch.cat(X)
        mu, sd = allX.mean(0), allX.std(0) + 1e-6
        w = torch.zeros(dim, requires_grad=True)
        b = torch.zeros(1, requires_grad=True)
        opt = torch.optim.Adam([w, b], lr=0.05, weight_decay=2e-3)
        for _ in range(a.epochs):
            opt.zero_grad()
            loss = 0.0
            for x, y in zip(X, Y):
                s = ((x - mu) / sd) @ w + b
                loss = loss - (torch.log_softmax(s, 0) * (y / y.sum())).sum()
            (loss / len(X)).backward()
            opt.step()
        for pid, cs in te:
            x = torch.tensor([vec(c) for c in cs], dtype=torch.float32)
            s = ((x - mu) / sd) @ w + b
            picked[pid] = cs[int(torch.argmax(s))]
        weights.append({"fold": k, "w": w.detach().tolist(), "b": float(b.detach()[0])})
    hit = sum(1 for pid, _ in pts if picked.get(pid, {}).get("is_pick"))
    print(f"\n学习排序器（按页 {a.folds} 折，折外）: {hit}/{len(pts)} = {hit / len(pts):.1%}")
    # 基线
    for name, key, rev in (("agree 最高", "agree", True), ("dis_unet 最小", "dis_unet", False)):
        h = 0
        t = 0
        for pid, cs in pts:
            v = [c for c in cs if c.get(key) is not None]
            if len(v) < 2:
                continue
            t += 1
            h += (max if rev else min)(v, key=lambda c: c[key])["is_pick"]
        if t:
            print(f"  基线「{name}」: {h}/{t} = {h / t:.1%}")
    print("  选中分布:", Counter(c["kind"] for c in picked.values()))
    # 平均权重（看哪些特征有用）
    if weights:
        W = np.array([x["w"] for x in weights]).mean(0)
        names = [n for n, _, _ in FEATS] + [f"is_{k}" for k in KINDS]
        print("\n平均权重（绝对值排序）:")
        for nm, wv in sorted(zip(names, W), key=lambda t: -abs(t[1]))[:10]:
            print(f"  {nm:18s} {wv:+.3f}")
    jdump({"n_points": len(pts), "acc": hit / len(pts), "weights": weights}, OUT_ROOT / "selector" / (ds.stem + ".json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
