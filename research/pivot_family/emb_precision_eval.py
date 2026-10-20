# -*- coding: utf-8 -*-
"""向量包三种精度（fp32 / fp16 / int8）在真刻本字块上的对比（hanzi 库 B2，用户 10-20：默认 8 位，先量再切 Step5-b）。

只读：不改引擎、不碰 products；模板矩阵直接取向量包（`guji cache pull-rare-index` 拉到本机，或首次自动下载），
不用现建 7 万字索引。

    cd open-guji-cv && .venv/bin/python research/pivot_family/emb_precision_eval.py --out /tmp/emb_prec.json

要 `cache/` 下有 train_bundle.zip 解出的 oov_bench、glyph_bench（同 `pivot_family.py`）。

量两件事，每种精度一行：

1. **全表检索**（Step5-b 口径，字表 unicode-cjk-ab）：金标字排第 1 / 前 5 / 前 10 的比例，分 oov / unseen / seen_test；
   以及与 fp32 比，第 1 名相同、前 10 集合相同的比例。
2. **以字找字**（`rows.jsonl.gz` 里有近似字 p 的 414 条）：p 的候选池（`variant_sources.family_pool`，
   hanzi 库）按字块图余弦排序，金标排第 1 / 前 3 / 前 5。

**判据**（写进总设计 B2）：int8 在三档全表检索的第 1、前 5 都不比 fp32 低超过 0.5 个百分点，
以字找字前 3 不低于 fp32，就可以全队把 Step5-b 也切到 int8。
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

PRECISIONS = ("fp32", "fp16", "int8")


def retrieval_metrics(S: np.ndarray, truth: np.ndarray, tiers: list[str],
                      base_top: np.ndarray | None = None, k: int = 10) -> tuple[dict, np.ndarray]:
    """相似度矩阵 `S[查询, 模板]` → 分档的 top-1/5/10 命中率（金标不在字表里的条记为不中），
    给了 `base_top`（fp32 的前 k）再报第 1 名相同、前 k 集合相同的比例。返回 (指标, 本精度的前 k)。"""
    top = np.argsort(-S, axis=1)[:, :k]
    out: dict = {}
    groups = defaultdict(list)
    for i, t in enumerate(tiers):
        groups[t].append(i)
        groups["all"].append(i)
    for t, ix in groups.items():
        ix = np.array(ix)
        hit = top[ix] == truth[ix, None]
        row = {"n": len(ix), "top1": float(hit[:, 0].mean()), "top5": float(hit[:, :5].any(1).mean()),
               "top10": float(hit.any(1).mean())}
        if base_top is not None:
            row["same_top1"] = float((top[ix, 0] == base_top[ix, 0]).mean())
            row["same_top10_set"] = float(np.mean([set(a) == set(b) for a, b in zip(top[ix], base_top[ix])]))
        out[t] = row
    return out, top


def pool_rank(q: np.ndarray, g: str, pool: list[str], vec: dict[str, np.ndarray]) -> int | None:
    """候选池按与 q 的余弦排序，金标 g 排第几（1 起）；池里没有或渲染不出 → None。"""
    scored = sorted(((float(vec[c] @ q), c) for c in pool if c in vec), key=lambda t: (-t[0], t[1]))
    order = [c for _, c in scored]
    return order.index(g) + 1 if g in order else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", type=int, default=2621, help="seen_test 取前 N 条（与 rows.jsonl.gz 对齐用 2621）")
    a = ap.parse_args()

    from pivot_family import load_items

    from open_guji_cv.clustering import emb_pack
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.variant_sources import family_pool

    cs = tuple(base_charset("unicode-cjk-ab"))
    cnn = CnnCandidates(str(DEFAULT_CKPT))
    cnn._ensure()
    items = load_items(a.seen)
    tiers = [t for t, _, _ in items]
    Q = cnn.embed([im for _, _, im in items])
    print(f"靶子 {len(items)} 条", flush=True)

    with gzip.open(HERE / "rows.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f]
    aligned = len(rows) == len(items) and all(r["g"] == g for r, (_, g, _) in zip(rows, items))
    print(f"rows.jsonl.gz 与靶子对齐：{aligned}", flush=True)

    res: dict = {"n": len(items), "aligned_rows": aligned, "retrieval": {}, "pivot": {}}
    base_top = None
    for prec in PRECISIONS:
        pk = emb_pack.load_current(precision=prec)
        if pk is None:
            print(f"{prec}：没有与本机同规格的向量包，跳过")
            continue
        mat, names = pk.materialize(cs)
        pos = {c: i for i, c in enumerate(names)}
        truth = np.array([pos.get(g, -1) for _, g, _ in items])
        m, top = retrieval_metrics(Q @ mat.T, truth, tiers, base_top)
        if prec == "fp32":
            base_top = top
        res["retrieval"][prec] = m
        if aligned:
            ranks = []
            for i, r in enumerate(rows):
                p = r.get("pivot")
                if not p or p == r["g"]:
                    continue
                pool = list(family_pool([p]))
                ranks.append(pool_rank(Q[i], r["g"], pool, pk.vectors(pool)))
            n = len(ranks)
            res["pivot"][prec] = {"n": n, **{f"top{k}": sum(1 for x in ranks if x and x <= k) for k in (1, 3, 5)}}
        print(prec, json.dumps({"retrieval": m.get("all"), "pivot": res["pivot"].get(prec)}, ensure_ascii=False),
              flush=True)

    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n| 精度 | 档 | 第 1 | 前 5 | 前 10 | 第 1 名同 fp32 | 前 10 集合同 fp32 |\n|---|---|---|---|---|---|---|")
    for prec, m in res["retrieval"].items():
        for t in ("oov", "unseen", "seen_test", "all"):
            r = m.get(t)
            if r:
                print(f"| {prec} | {t} | {r['top1']:.1%} | {r['top5']:.1%} | {r['top10']:.1%} | "
                      f"{r.get('same_top1', 1):.1%} | {r.get('same_top10_set', 1):.1%} |")
    for prec, p in res["pivot"].items():
        print(f"以字找字 {prec}：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
