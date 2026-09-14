# -*- coding: utf-8 -*-
"""实验一：无整理本时，识别器 top-k 能把粘连点的真字对装进假设集的比例。

    python experiments/touch_resolve/exp1_hypothesis.py [--k 10] [--books vol01,vol02,vol03]

对每条带上下字的 touching-cuts 金标，用三种切法切出上下两张半字图：
  straight = 现役直线格线；chosen = 现役实际切法（缝）；gold = 人工金标折线/直线。
每张半字图归一化到 64² 后过现役 CNN 的分类头（cls）与 embedding 检索（emb），
以及两者的 RRF 融合（fused）。报：
  - 每侧 hit@1/5/10；
  - 字对同时进 k×k 假设集的比例（pair@k）；
  - 按 verdict（ok/seam_ok vs overlap/moved）、按半字所在侧（上/下）、
    按真字是否在字表（oov）分层。
产出 out/exp1/per_case.json（每条的 top-k，供实验二复用）与 summary.json。
"""
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from common import (Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize, rank_of,
                    seam_chosen, seam_gold, seam_straight, side_masks, window)

CONDS = ("straight", "chosen", "gold")


def fuse(cls, emb, k):
    from open_guji_cv.clustering.cnn_candidates import rrf
    return rrf([c for c, _ in cls], [c for c, _ in emb], k=k)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--out", default=str(OUT_ROOT / "exp1"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    K = a.k

    L = Loader()
    R = Recognizer()
    classes = set(R.classes)
    items = L.gold_items(books=a.books.split(","), need_chars=True)
    cases = []
    for it in items:
        c, _ = L.resolve(it)
        if c is not None and c.has_chars() and L.image_of(c) is not None:
            cases.append(c)
    print(f"用例 {len(cases)} 条（带上下字且对上产物）")

    # 1) 切出全部半字图
    t0 = time.time()
    recs = []      # (case_idx, cond, side, norm)
    norms = []
    for ci, c in enumerate(cases):
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        for cond, sfun in (("straight", seam_straight), ("chosen", seam_chosen), ("gold", seam_gold)):
            above, below = side_masks(win.shape, sfun(c), y0)
            for side, m in (("above", above), ("below", below)):
                hp = half_patch(win, m)
                if hp is None:
                    recs.append((ci, cond, side, None)); continue
                recs.append((ci, cond, side, len(norms)))
                norms.append(normalize(hp))
    print(f"半字图 {len(norms)} 张，切图 {time.time() - t0:.1f}s")

    # 2) 批量识别
    t0 = time.time()
    cls_all, emb_all = [], []
    B = 256
    for i in range(0, len(norms), B):
        chunk = norms[i:i + B]
        cls_all += R.cls_topk(chunk, k=K)
        emb_all += R.emb_topk(chunk, k=K)
    print(f"识别 {len(norms)} 张 × 2 源 {time.time() - t0:.1f}s")

    # 3) 汇总
    per_case = []
    hit = defaultdict(Counter)      # key=(cond, src, side or 'pair', stratum) → Counter{'@1','@5','@10','n'}
    for ci, c in enumerate(cases):
        rec = {"id": c.id, "verdict": c.verdict, "char_above": c.char_above, "char_below": c.char_below,
               "oov_above": c.char_above not in classes, "oov_below": c.char_below not in classes,
               "multi": bool(c.cp is not None and len(c.cp.candidates) >= 2), "topk": {}}
        strata = ["all", "easy" if c.verdict in ("ok", "seam_ok") else "hard", c.book]
        for cond in CONDS:
            rec["topk"][cond] = {}
            ranks = {}
            for side, truth in (("above", c.char_above), ("below", c.char_below)):
                idx = next(r[3] for r in recs if r[0] == ci and r[1] == cond and r[2] == side)
                if idx is None:
                    rec["topk"][cond][side] = None
                    for src in ("cls", "emb", "fused"):
                        ranks[(src, side)] = None
                    continue
                cls, emb = cls_all[idx], emb_all[idx]
                fused = fuse(cls, emb, K)
                rec["topk"][cond][side] = {"cls": cls[:K], "emb": emb[:K], "fused": fused[:K]}
                ranks[("cls", side)] = rank_of(truth, cls)
                ranks[("emb", side)] = rank_of(truth, emb)
                ranks[("fused", side)] = rank_of(truth, [(x, 0.0) for x in fused])
            for src in ("cls", "emb", "fused"):
                for side in ("above", "below"):
                    r = ranks[(src, side)]
                    for st in strata:
                        h = hit[(cond, src, side, st)]
                        h["n"] += 1
                        for kk in (1, 5, 10):
                            h[f"@{kk}"] += int(r is not None and r <= kk)
                ra, rb = ranks[(src, "above")], ranks[(src, "below")]
                for st in strata:
                    h = hit[(cond, src, "pair", st)]
                    h["n"] += 1
                    for kk in (1, 3, 5, 10):
                        h[f"@{kk}"] += int(ra is not None and rb is not None and ra <= kk and rb <= kk)
            rec.setdefault("rank", {})[cond] = {f"{s}_{sd}": ranks[(s, sd)] for s in ("cls", "emb", "fused") for sd in ("above", "below")}
        per_case.append(rec)

    def pct(h, key):
        return round(100.0 * h[key] / max(1, h["n"]), 1)

    summary = {"n_cases": len(cases), "k": K, "table": {}}
    print("\n== 每侧命中率（%）  条件 / 源 / 侧 / 分层: @1 @5 @10 (n)")
    for cond in CONDS:
        for src in ("cls", "emb", "fused"):
            for side in ("above", "below"):
                for st in ("all", "easy", "hard"):
                    h = hit[(cond, src, side, st)]
                    summary["table"][f"{cond}/{src}/{side}/{st}"] = {k: pct(h, k) for k in ("@1", "@5", "@10")} | {"n": h["n"]}
            h = hit[(cond, src, "above", "all")]; h2 = hit[(cond, src, "below", "all")]
            print(f"  {cond:8s} {src:5s} above {pct(h,'@1'):5.1f} {pct(h,'@5'):5.1f} {pct(h,'@10'):5.1f} | "
                  f"below {pct(h2,'@1'):5.1f} {pct(h2,'@5'):5.1f} {pct(h2,'@10'):5.1f}  (n={h['n']})")
    print("\n== 字对同时进 k×k 假设集（%）  条件 / 源 / 分层: @1 @3 @5 @10")
    for cond in CONDS:
        for src in ("cls", "emb", "fused"):
            row = []
            for st in ("all", "easy", "hard", "vol01", "vol02", "vol03"):
                h = hit[(cond, src, "pair", st)]
                summary["table"][f"{cond}/{src}/pair/{st}"] = {k: pct(h, k) for k in ("@1", "@3", "@5", "@10")} | {"n": h["n"]}
                row.append(f"{st}:{pct(h,'@1'):4.1f}/{pct(h,'@3'):4.1f}/{pct(h,'@5'):4.1f}/{pct(h,'@10'):4.1f}(n={h['n']})")
            print(f"  {cond:8s} {src:5s} " + "  ".join(row))
    n_oov = sum(1 for r in per_case if r["oov_above"] or r["oov_below"])
    oov_chars = sorted({r["char_above"] for r in per_case if r["oov_above"]} | {r["char_below"] for r in per_case if r["oov_below"]})
    summary["oov_cases"] = n_oov; summary["oov_chars"] = oov_chars
    print(f"\n真字不在 CNN 字表（oov）的用例 {n_oov}/{len(per_case)}：{''.join(oov_chars)}")

    jdump(per_case, out / "per_case.json")
    jdump(summary, out / "summary.json")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
