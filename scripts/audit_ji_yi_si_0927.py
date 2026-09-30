# -*- coding: utf-8 -*-
"""D 铁证复核（2026-09-27）第 5 条：己/已/巳 一族在 `split_ref`/`ji_yi_si` 通道系统性
判偏（vol03 Z14 全量穷举 47 格 55.3% 错、vol04 Z10 34 处），复现统计并试评估
`resolve()` 的 `use_ref` 口径要不要放宽（当前 `_resolve_ji_yi_si` 固定传 `ji_only`）。

只读产物现算，不改任何产物/库。

    GUJI_PRODUCTS_DIR=<snap dir> PYTHONPATH=. .venv/bin/python \
        scripts/audit_ji_yi_si_0927.py vol04 --pages 1-218
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.ji_yi_si import FAMILY, resolve  # noqa: E402
from open_guji_cv.utils.jiazhu_order import sort_by_reading  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--dump", action="store_true", help="逐格打印")
    a = ap.parse_args()

    st = ProductStore()
    lo, _, hi = a.pages.partition("-")

    variants = ("ji_only", "all", "none")
    n_gold = 0
    gold_dist = Counter()
    pred_now_dist = Counter()
    correct_now = 0
    correct_variant = {v: 0 for v in variants}
    pred_variant_dist = {v: Counter() for v in variants}
    rows = []

    for pg in range(int(lo), int(hi or lo) + 1):
        sadm = st.read(a.book, "seed_admit", f"p{pg:04d}", "seed_admit")
        if sadm is None:
            continue
        aref = st.read(a.book, "align_ref", f"p{pg:04d}", "align_ref")
        amap = ({c.id: (c.align_char, c.align_op) for c in aref.chars}
               if aref is not None and aref.anchored else {})
        seq = [r for c in sorted(sadm.columns, key=lambda c: c.col)
              for r in sort_by_reading(c.chars)
              if not (r.doubts and "excluded" in r.doubts)]
        for i, r in enumerate(seq):
            ref, op = amap.get(r.id, (None, None))
            if not ref or ref not in FAMILY:
                continue
            n_gold += 1
            gold_dist[ref] += 1
            pred_now_dist[r.char] += 1
            if r.char == ref:
                correct_now += 1
            prev = seq[i - 1].char if i else None
            nxt = seq[i + 1].char if i + 1 < len(seq) else None
            nxt2 = seq[i + 2].char if i + 2 < len(seq) else None
            preds = {}
            for v in variants:
                ch, why = resolve(prev, nxt, ref, use_ref=v, next2=nxt2)
                preds[v] = (ch, why)
                pred_variant_dist[v][ch] += 1
                if ch == ref:
                    correct_variant[v] += 1
            if a.dump:
                rows.append((r.id, ref, op, r.char, r.channel, preds, prev, nxt, nxt2))

    print(f"=== {a.book} 己/已/巳 一族：gold 覆盖 {n_gold} 格 ===")
    print(f"gold 分布：{dict(gold_dist)}")
    print(f"现产物 pred 分布：{dict(pred_now_dist)}  与 gold 一致 {correct_now}/{n_gold} "
         f"({100*correct_now/max(n_gold,1):.1f}%)")
    for v in variants:
        print(f"resolve(use_ref={v!r}) 分布：{dict(pred_variant_dist[v])}  一致 "
             f"{correct_variant[v]}/{n_gold} ({100*correct_variant[v]/max(n_gold,1):.1f}%)")

    if a.dump:
        print("\nid  prev/next/next2  gold(op)  现pred(chan)  ji_only  all  none")
        for iid, ref, op, cur, chan, preds, prev, nxt, nxt2 in rows:
            if preds["all"][0] == ref:
                continue
            print(f"{iid}  {prev}/{nxt}/{nxt2}  {ref}({op})  {cur}({chan})  "
                 f"{preds['ji_only'][0]}/{preds['ji_only'][1]}  "
                 f"{preds['all'][0]}/{preds['all'][1]}  "
                 f"{preds['none'][0]}/{preds['none'][1]}")


if __name__ == "__main__":
    main()
