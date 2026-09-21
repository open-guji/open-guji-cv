# -*- coding: utf-8 -*-
"""北行刻本 383 条裁决上的 r4 / r5 **同条件 A/B**。

## 为什么不各跑一遍管线

checkpoint 只影响 `rare_candidates` 的**候选排序**，不影响切分/取块。
所以拿同一批字块图（当下产物的 `cell_shrink` 列图切出来的那些），
对两个 checkpoint 各算一次候选，就是严格同条件的对比——
而各跑一遍全管线反而会引入别的差异（且要把生产常量来回改，风险大）。

字表与权重口径完全走生产：`charset_spec` 读册配置（本册 base=unicode-cjk-a
+ 阶梯 unicode-ext-b + corpus/variants 叠加 + no-simplified），
`rare_panel` 那套 `cls_gate_weight` 软门控与 RRF 也照用。

    PYTHONIOENCODING=utf-8 GUJI_WORKSPACE=D:/workspace/guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一 \
      .venv/Scripts/python.exe experiments/metric_loss/ab_bxgb.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WS = Path(os.environ.get("GUJI_WORKSPACE", "D:/workspace/guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"))
CKPTS = {"r4": "models/glyph_cnn_r4/best.pt", "r5": "models/glyph_cnn_r5/best.pt"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", default="experiments/metric_loss/out/ab_bxgb.json")
    a = ap.parse_args()

    import torch
    from open_guji_cv.clustering import cnn_candidates as cnn_mod
    from open_guji_cv.clustering.rare_panel import rare_batch
    from open_guji_cv.eval.round_check import load_verdicts

    gold = load_verdicts(a.book, WS)
    print(f"裁决金标 {len(gold)} 条", flush=True)
    # key 形如 "bxgb:20:1:1"，rare_batch 要的是 "20:1:1"
    slots, keys = [], []
    for key in sorted(gold):
        parts = key.split(":")
        if len(parts) == 4 and parts[0] == a.book:
            slots.append(":".join(parts[1:])); keys.append(key)
    print(f"字位 {len(slots)}", flush=True)

    out = {}
    for tag, rel in CKPTS.items():
        if not Path(rel).exists():
            print(f"[skip] {tag} 没有 {rel}"); continue
        # ⚠️ 光改 `cnn_mod.DEFAULT_CKPT` **不管用**：`shared()` 的签名是
        # `def shared(ckpt: str = str(DEFAULT_CKPT))`，默认值在**函数定义时**
        # 就求值了，之后改模块变量不影响它——会静默拿旧 checkpoint 算，
        # 两档得出一模一样的数（2026-09-17 差点这么误报）。
        # 所以要连 lru 缓存一起清，并把路径**显式**灌进去。
        cnn_mod.shared.cache_clear()
        old = cnn_mod.DEFAULT_CKPT
        cnn_mod.DEFAULT_CKPT = Path(rel)
        orig_shared = cnn_mod.shared
        cnn_mod.shared = lambda ckpt=None, _r=rel: _pinned(cnn_mod, _r)
        try:
            res_raw = rare_batch(a.book, slots, k=a.k)
        finally:
            cnn_mod.shared = orig_shared
            cnn_mod.DEFAULT_CKPT = old
            cnn_mod.shared.cache_clear()
        cc = cnn_mod.CnnCandidates(rel); cc._ensure()
        classes = set(cc._classes)
        ranks, got = [], []
        for key, sl in zip(keys, slots):
            lst = res_raw["rare"].get(sl) or []
            chars = [it.get("char") for it in lst if isinstance(it, dict) and it.get("char")]
            if chars:
                ranks.append(chars); got.append(key)
        print(f"{tag}: 出候选 {len(got)}/{len(keys)}", flush=True)
        res = _score(ranks, got, gold, classes)
        out[tag] = res
        print(f"=== {tag}  ({rel})")
        _report(res)
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("→", a.json)
    if "r4" in out and "r5" in out:
        print("=== delta (r5 − r4，百分点)")
        for st in ("全体", "类内", "类外"):
            if st in out["r4"] and st in out["r5"]:
                d1 = (out["r5"][st]["top1"] - out["r4"][st]["top1"]) * 100
                d10 = (out["r5"][st]["top10"] - out["r4"][st]["top10"]) * 100
                print(f"  {st:4s} n={out['r4'][st]['n']:4d}  top-1 {d1:+.1f}  top-10 {d10:+.1f}")
    return 0


_PINNED: dict[str, object] = {}


def _pinned(cnn_mod, rel):
    """把指定 checkpoint 的 CnnCandidates 实例钉住（每档只建一次，索引复用）。"""
    if rel not in _PINNED:
        c = cnn_mod.CnnCandidates(rel)
        c._ensure()
        _PINNED[rel] = c
    return _PINNED[rel]


def _score(ranks, keys, gold, classes):
    strata = {"全体": [], "类内": [], "类外": []}
    for key, order in zip(keys, ranks):
        shape = gold[key]
        rec = (shape, order)
        strata["全体"].append(rec)
        strata["类内" if shape in classes else "类外"].append(rec)
    res = {}
    for nm, rows in strata.items():
        if not rows:
            continue
        n = len(rows)
        res[nm] = {"n": n, **{f"top{k}": sum(1 for s, l in rows if s in l[:k]) / n
                              for k in (1, 5, 10)}}
    return res


def _report(res):
    print(f"{'档':6s} {'n':>5s} {'top-1':>8s} {'top-5':>8s} {'top-10':>8s}")
    for nm, r in res.items():
        print(f"{nm:6s} {r['n']:5d} {r['top1']:7.1%} {r['top5']:7.1%} {r['top10']:7.1%}")


if __name__ == "__main__":
    raise SystemExit(main())
