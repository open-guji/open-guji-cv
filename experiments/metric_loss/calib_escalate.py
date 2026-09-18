# -*- coding: utf-8 -*-
"""重标 `escalate_threshold`（册配置 `font.charset.escalate_threshold`）。

## 为什么换 checkpoint 要重标这个值

阶梯的判据是「基集 emb top-1 分数 < th 就追加升级档」。
**分数分布绑在 checkpoint 上**：r5 训得短（60 epoch vs r4 的 160），
分数更挤、整体偏高，于是同一个 th=0.85 在 r5 上**该开的时候不开**——
答案在扩B 里的字位永远查不到。

北行 383 条实测（2026-09-17）：r5 在册配置（阶梯 th=0.85）下类外 top-1
只有 40.6%，而同一批字用平字表（70,304，不设门）是 53.6% / top-10 97.1%
——**门关死了 13 个点**，不是模型退步。

册配置注释里本来写着「⚠️ 在**这套基集**上标的，换 base 要重标」，
这次补一条：**换 checkpoint 也要重标**。

    PYTHONIOENCODING=utf-8 GUJI_WORKSPACE=D:/workspace/beixing-guben-workspace \
      .venv/Scripts/python.exe experiments/metric_loss/calib_escalate.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WS = Path(os.environ.get("GUJI_WORKSPACE", "D:/workspace/beixing-guben-workspace"))
GRID = [0.0, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99, 1.01]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--ckpt", default="models/glyph_cnn_r5/best.pt")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", default="experiments/metric_loss/out/calib_escalate.json")
    a = ap.parse_args()

    import torch
    from open_guji_cv.clustering.cnn_candidates import (
        CNN_WEIGHT, EMB_WEIGHT, CnnCandidates, cls_gate_weight, rrf)
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.rare_panel import (
        _book_norm_stroke, book_charsets, rare_patch)
    from open_guji_cv.steps.align_ref import book_corpus
    from open_guji_cv.eval.round_check import load_verdicts

    gold = load_verdicts(a.book, WS)
    cc = CnnCandidates(a.ckpt); cc._ensure()
    classes = set(cc._classes)
    cs_base, cs_esc, spec = book_charsets(a.book, book_corpus(a.book))
    print(f"checkpoint {a.ckpt}")
    print(f"字表 base {len(cs_base)} / escalate {len(cs_esc)}；"
          f"册配置 th={spec.get('escalate_threshold')}")

    ns = _book_norm_stroke(a.book)
    keys, imgs, G = [], [], []
    for key in sorted(gold):
        p, c, s = key.split(":")[1:]
        im = rare_patch(a.book, int(p), int(c), int(s))
        if im is None:
            continue
        keys.append(key); imgs.append(normalize_patch(im, stroke_width=ns))
        G.append(gold[key])
    print(f"字位 {len(keys)}（类外 {sum(1 for g in G if g not in classes)}）\n")

    # 两套候选各算一次（与 th 无关），扫阈值时只改「要不要归并」
    base_emb = cc.emb_topk_batch(imgs, cs_base, k=max(a.k, 10))
    base_cls = cc.topk_batch(imgs, cs_base, k=max(a.k, 10))
    esc_emb = cc.emb_topk_batch(imgs, cs_esc, k=max(a.k, 10)) if cs_esc else \
        [[] for _ in imgs]

    rows = []
    print(f"{'th':>5s} {'升级率':>7s} "
          f"{'类外t1':>7s} {'类外t10':>8s} {'类内t1':>7s} {'类内t10':>8s} "
          f"{'全体t1':>7s} {'全体t10':>8s}")
    for th in GRID:
        n_esc = 0
        stat = {"类外": [0, 0, 0], "类内": [0, 0, 0]}
        for be, bc, ee, g in zip(base_emb, base_cls, esc_emb, G):
            emb = list(be)
            if cs_esc and ((not be) or be[0][1] < th):
                n_esc += 1
                seen: dict[str, float] = {}
                for ch, sc in emb + list(ee):
                    if sc > seen.get(ch, -1.0):
                        seen[ch] = sc
                emb = sorted(seen.items(), key=lambda t: -t[1])[:max(a.k, 10)]
            eo = [x for x, _ in emb]
            co = [x for x, _ in bc]
            w = cls_gate_weight(eo, classes)
            order = rrf(co, eo, k=a.k, weights=(CNN_WEIGHT * w, EMB_WEIGHT))
            st = "类内" if g in classes else "类外"
            stat[st][0] += 1
            stat[st][1] += g in order[:1]
            stat[st][2] += g in order[:a.k]
        tot = [stat["类外"][i] + stat["类内"][i] for i in range(3)]
        r = {"th": th, "escalate_rate": n_esc / len(G)}
        for st in ("类外", "类内"):
            n, h1, h10 = stat[st]
            r[st] = {"n": n, "top1": h1 / n if n else 0, "top10": h10 / n if n else 0}
        r["全体"] = {"n": tot[0], "top1": tot[1] / tot[0], "top10": tot[2] / tot[0]}
        rows.append(r)
        print(f"{th:5.2f} {r['escalate_rate']:6.1%} "
              f"{r['类外']['top1']:6.1%} {r['类外']['top10']:7.1%} "
              f"{r['类内']['top1']:6.1%} {r['类内']['top10']:7.1%} "
              f"{r['全体']['top1']:6.1%} {r['全体']['top10']:7.1%}")

    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(
        {"ckpt": a.ckpt, "base": len(cs_base), "escalate": len(cs_esc),
         "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n→", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
