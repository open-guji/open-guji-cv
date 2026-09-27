"""a3：每个字挑 1～3 个代表刻例进书级库（任务书 22:15Z 追加：R #86 自举结论）。

  GUJI_WORKSPACE=$QTW_WS python a3_reps.py <imp_dir>   → <imp_dir>/reps.json

挑法（先稳后多）：
1. 候选 = 该字的确认格；**优先逐格确认的**（batch1 `ok`），再取簇代表；
2. 簇代表 = 簇内 medoid（归一 64² 图模糊后两两余弦，均值最高的那格）；簇里有「整理本对齐字也是
   这个字」的格时只在这些格里挑——两路独立来源都说是它，混进错格的风险最小；
3. 按簇大小从大到小，每簇出一个；簇不够 K 个时，从全字范围按 medoid 次序补，**不同页**；
4. K ∈ {1,2,3} 各出一份，形近三对（今/令、玉/王、大/天）一律 3。
"""
from __future__ import annotations

import collections
import json
import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import QTW_BOOKS, TRIO, align_chars  # noqa: E402


def vec(img):
    from open_guji_cv.clustering.normalize import normalize_patch
    n = normalize_patch(img).astype(np.float32)
    n = cv2.GaussianBlur(n, (5, 5), 1.2).ravel()
    n -= n.mean()
    return n / (np.linalg.norm(n) + 1e-6)


def order_by_medoid(keys, V):
    if len(keys) <= 2:
        return list(keys)
    M = np.stack([V[k] for k in keys])
    s = (M @ M.T).mean(1)
    return [keys[i] for i in np.argsort(-s)]


def page(k):
    return ":".join(k.split(":")[:2])


def pick(recs, V, align, K):
    per_cell = [r["key"] for r in recs if r.get("per_cell")]
    clusters = collections.defaultdict(list)
    for r in recs:
        clusters[r.get("cluster") or "_"].append(r["key"])
    chosen: list[str] = []
    for k in order_by_medoid(per_cell, V):
        if len(chosen) < K and page(k) not in {page(c) for c in chosen}:
            chosen.append(k)
    for cl, ks in sorted(clusters.items(), key=lambda x: -len(x[1])):
        if len(chosen) >= K:
            break
        ch = recs[0]["char"]
        agree = [k for k in ks if (align.get(k) or {}).get("align_char") == ch]
        for k in order_by_medoid(agree or ks, V):
            if k not in chosen and page(k) not in {page(c) for c in chosen}:
                chosen.append(k)
                break
    if len(chosen) < K:
        allk = [r["key"] for r in recs]
        for k in order_by_medoid(allk, V):
            if len(chosen) >= K:
                break
            if k not in chosen and page(k) not in {page(c) for c in chosen}:
                chosen.append(k)
    return chosen


def main():
    d = Path(sys.argv[1])
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    P = pickle.load(open(d / "patches.pkl", "rb"))
    align = {}
    for b in QTW_BOOKS:
        align.update(align_chars(b))
    by = collections.defaultdict(list)
    for r in final:
        if r["import"] and r["act"] == "confirm" and r["key"] in P:
            by[r["char"]].append(r)
    V = {r["key"]: vec(P[r["key"]]) for rs in by.values() for r in rs}
    out = {"n_chars": len(by), "by_K": {}}
    for K in (1, 2, 3):
        reps = {ch: pick(rs, V, align, 3 if ch in TRIO else K) for ch, rs in sorted(by.items())}
        out["by_K"][K] = reps
        n = sum(len(v) for v in reps.values())
        agree = sum((align.get(k) or {}).get("align_char") == ch for ch, ks in reps.items() for k in ks)
        print(f"K={K}: {n} 例 / {len(reps)} 字；其中整理本对齐也是该字 {agree}", flush=True)
    out["n_cells_by_char"] = {ch: len(rs) for ch, rs in sorted(by.items(), key=lambda x: -len(x[1]))}
    json.dump(out, open(d / "reps.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
