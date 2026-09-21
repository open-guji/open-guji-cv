# -*- coding: utf-8 -*-
"""M0 零训练结构重排的验收：在 oov_bench 上量「开 / 关」的 top-1 / top-5 / top-10。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_struct_rerank.py \
        [--charset unicode-cjk-ab] [--ckpt <path>] [--json out.json]

口径与 `scripts/eval_oov.py` 完全一致（同一个 `cache/oov_bench`、同一个基集、
同样的 cls+emb RRF 当基线），只多做一件事：拿现役部件袋头的 sigmoid 概率
（`CnnCandidates.comp_probs_batch`）对 RRF 前 30 名做一致性重排
（`ids_struct.struct_rerank`），并扫权重 × top_m 两个旋钮。

## 读数纪律

- **主指标 top-10 不掉、top-1 不掉才算过**；重排只是排序信号，掉一个都不接。
- 分层报：`src` 列（woodblock / user）分开看，用户裁决那一档才是真难题。
- 部件袋头的词表是一级部件（`ids_guard.components`），`components_of` 必须传它——
  传 `ids_struct` 的停集词表会把分打到不相干的表上，结果看着像没效果。
- 这个头对**类外字**的部件也有输出（部件是跨字共享的），这正是重排可能有效的理由；
  但它也只在字体渲染 + 真刻例上训过，所以先在这里量，别直接开。
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
    ap.add_argument("--charset", default="unicode-cjk-ab")
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--weights", default="0.5,1,2,4")
    ap.add_argument("--top-m", default="10,30")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    import cv2
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import (CNN_WEIGHT, DEFAULT_CKPT,
                                                        EMB_WEIGHT, CnnCandidates, rrf)
    from open_guji_cv.clustering.ids_guard import components as first_level
    from open_guji_cv.clustering.ids_struct import struct_rerank

    items = [json.loads(l) for l in
             (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    imgs, gold, src = [], [], []
    for it in items:
        im = cv2.imread(str(BENCH / it["png"]), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        imgs.append((im > 127).astype(np.uint8)); gold.append(it["char"])
        src.append(it.get("src") or it.get("source") or "?")
    cs = base_charset(a.charset)
    cnn = CnnCandidates(a.ckpt or DEFAULT_CKPT)
    if not cnn.available:
        print("没有 checkpoint / torch，量不了", file=sys.stderr)
        return 2
    print(f"集 {len(gold)} 条 / {len(set(gold))} 字种；字表 {a.charset} {len(cs)} 字；"
          f"部件袋头 {len(cnn.comps)} 个部件", flush=True)

    t0 = time.time()
    cls = [[c for c, _ in r] for r in cnn.topk_batch(imgs, cs, k=30)]
    emb = [[c for c, _ in r] for r in cnn.emb_topk_batch(imgs, cs, k=30)]
    base = [rrf(c, e, k=30, weights=(CNN_WEIGHT, EMB_WEIGHT)) for c, e in zip(cls, emb)]
    probs = cnn.comp_probs_batch(imgs)
    print(f"基线候选 + 部件概率 {time.time() - t0:.0f}s", flush=True)

    def acc(ranks, k, mask=None):
        idx = [i for i in range(len(gold)) if mask is None or mask[i]]
        return 100.0 * np.mean([gold[i] in ranks[i][:k] for i in idx]) if idx else float("nan")

    def report(name, ranks) -> dict:
        row = {f"top{k}": acc(ranks, k) for k in (1, 5, 10)}
        for s in sorted(set(src)):
            m = [x == s for x in src]
            row[f"top10@{s}"] = acc(ranks, 10, m); row[f"top1@{s}"] = acc(ranks, 1, m)
        print(f"{name:14s} top1 {row['top1']:5.1f}  top5 {row['top5']:5.1f}  top10 {row['top10']:5.1f}  "
              + "  ".join(f"{s}: {row[f'top1@{s}']:.1f}/{row[f'top10@{s}']:.1f}" for s in sorted(set(src))))
        return row

    res = {"n": len(gold), "charset": a.charset, "ckpt": str(a.ckpt or DEFAULT_CKPT), "rows": {}}
    print("\n配置            top-1  top-5  top-10   按来源 top1/top10")
    res["rows"]["baseline"] = report("baseline", base)
    for tm in (int(x) for x in a.top_m.split(",")):
        for w in (float(x) for x in a.weights.split(",")):
            rk = [struct_rerank(b, p, first_level, k=10, weight=w, top_m=tm)
                  for b, p in zip(base, probs)]
            res["rows"][f"m{tm}_w{w:g}"] = report(f"m={tm} w={w:g}", rk)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("→", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
