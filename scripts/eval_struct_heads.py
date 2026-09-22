# -*- coding: utf-8 -*-
"""Step A（结构头 + 槽位部件头）的验收：在 oov_bench 上量三件事。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_struct_heads.py \
        --ckpt models/glyph_cnn_r6/best.pt [--charset unicode-cjk-ab] [--json out.json]

1. **结构头准确率**：预测的顶层算符 == `ids_struct.structure_of(金标字).top`；
   独体字单列（它们没有部件，结构路线对它们一分不加，别混进总数虚高）。
2. **槽位头 top-3**：金标字的每个 `部件@槽` 落在预测前 3 的比例（按标签数）。
3. **重排**：cls+emb RRF 基线 vs 槽位头一致性重排 vs 部件袋头重排（M0 版），
   同一批候选、同一口径（`scripts/eval_struct_rerank.py`），看 top-1/top-10。

通过线（设计稿 §5 M1）：unseen 严格 top-1 ≥ 96.9 / oov ≥ 73.2 **不掉**（用
`eval_oov.py` 另量），结构头 ≥ 95%，重排 top-1、top-10 不掉。
checkpoint 没有结构头（r4/r5）时只报第 3 项的部件袋头那一路。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BENCH = Path("cache/oov_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--charset", default="unicode-cjk-ab")
    ap.add_argument("--weight", type=float, default=1.0)
    ap.add_argument("--json", default=None)
    ap.add_argument("--probe", default=None, help="外挂结构头 probe_<arch>.pt（Step A′，scripts/probe_struct_heads.py）")
    a = ap.parse_args()

    import cv2
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import CNN_WEIGHT, EMB_WEIGHT, CnnCandidates, rrf
    from open_guji_cv.clustering.ids_guard import components as first_level
    from open_guji_cv.clustering.ids_struct import (SINGLE, slot_keys_of, struct_rerank,
                                                    structure_of)

    items = [json.loads(l) for l in
             (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    imgs, gold = [], []
    for it in items:
        im = cv2.imread(str(BENCH / it["png"]), cv2.IMREAD_GRAYSCALE)
        if im is not None:
            imgs.append((im > 127).astype(np.uint8)); gold.append(it["char"])
    cnn = CnnCandidates(a.ckpt, probe=a.probe)
    if not cnn.available:
        print("没有 checkpoint / torch", file=sys.stderr); return 2
    res: dict = {"n": len(gold), "ckpt": a.ckpt, "has_struct_heads": cnn.has_struct_heads,
                 "struct_source": cnn.struct_source}
    print(f"集 {len(gold)} 条；checkpoint 结构头: {cnn.has_struct_heads}", flush=True)

    if cnn.has_struct_heads:
        t0 = time.time()
        sp = cnn.struct_probs_batch(imgs)
        lp = cnn.slot_probs_batch(imgs)
        ok = n = ok_single = n_single = 0
        hit = tot = 0
        labels = set(cnn.slot_labels)
        for g, s, l in zip(gold, sp, lp):
            st = structure_of(g)
            pred = max(s.items(), key=lambda kv: kv[1])[0]
            if st.top == SINGLE:
                n_single += 1; ok_single += int(pred == SINGLE)
            else:
                n += 1; ok += int(pred == st.top)
            top3 = {k for k, _ in sorted(l.items(), key=lambda kv: -kv[1])[:3]}
            for key in slot_keys_of(g):
                if key in labels:               # 词表外的标签谁都答不对，不算分母
                    tot += 1; hit += int(key in top3)
        res["struct_acc_compound"] = 100.0 * ok / max(n, 1)
        res["struct_acc_single"] = 100.0 * ok_single / max(n_single, 1)
        res["slot_top3"] = 100.0 * hit / max(tot, 1)
        print(f"结构头：合体字 {res['struct_acc_compound']:.1f}% (n={n})  独体 {res['struct_acc_single']:.1f}% (n={n_single})")
        print(f"槽位头 top-3：{res['slot_top3']:.1f}% (标签 {tot})   {time.time()-t0:.0f}s")

    cs = base_charset(a.charset)
    cls = [[c for c, _ in r] for r in cnn.topk_batch(imgs, cs, k=30)]
    emb = [[c for c, _ in r] for r in cnn.emb_topk_batch(imgs, cs, k=30)]
    base = [rrf(c, e, k=30, weights=(CNN_WEIGHT, EMB_WEIGHT)) for c, e in zip(cls, emb)]

    def acc(ranks, k):
        return 100.0 * np.mean([gold[i] in ranks[i][:k] for i in range(len(gold))])

    def report(name, rk):
        row = {f"top{k}": acc(rk, k) for k in (1, 5, 10)}
        print(f"{name:12s} top1 {row['top1']:5.1f}  top5 {row['top5']:5.1f}  top10 {row['top10']:5.1f}")
        return row

    print("\n重排（前 30 名内）")
    res["baseline"] = report("baseline", base)
    cp = cnn.comp_probs_batch(imgs)
    res["rerank_comp"] = report("comp-bag", [struct_rerank(b, p, first_level, k=10, weight=a.weight)
                                            for b, p in zip(base, cp)])
    if cnn.has_struct_heads:
        res["rerank_slot"] = report("slot-head", [struct_rerank(b, p, slot_keys_of, k=10, weight=a.weight)
                                                 for b, p in zip(base, lp)])
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
