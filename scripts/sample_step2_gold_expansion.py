# -*- coding: utf-8 -*-
"""从全语料扫描表里抽一批列去扩 column-warp 金标。

    python scripts/sample_step2_gold_expansion.py --scan output/step2_corpus_scan.json \
        -o output/step2_expansion_cards.jsonl [--n-random 40 --n-tail 20]

**为什么要重新设计抽样**：现有 54 列全部是「难例优先」挑的（倾斜大/梯形大/
抬头/mixed 候选），metadata 里 `known_limitations` 第一条就写了「不是随机抽样，
不能当全书比例的估计」。于是有个一直没法回答的问题：**Step2 在全书上到底多少
列是干净的？** 没有无偏样本就没有分母。

所以这批分两层，标签写在 `tags` 里，评测时必须分层报，别混在一起算：

  * `抽样·随机` —— 从 **L1 放行**的页里等概率抽（固定种子）。这一层是**唯一**
    能拿来估计全书比例的；40 列对一个比例的 95% 区间约 ±15%，够看出量级。
  * `抽样·难例尾` —— 从 `side_floor > 0.01` 或 `edge_resid > 0.05` 的列里抽。
    这一层**只**用来找失败形态，比例无意义（是按分数挑出来的）。

两层都**排除**：已经在金标里的列、`excluded_pages` 里的页（上游切错的，
量它等于把 Step1 的锅算到 Step2 头上）。

L1（页级：探出 9 列 + 每列宽在本页中位数 ±15% 内）在这里是**抽样框**，
不是判据——被 L1 挡下的页本来就不该进 Step2 的准确率统计。
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT.parent / "open-guji-dataset" / "char-segmentation" / "column-warp"


def l1_blocked(rows: list[dict]) -> set[tuple[str, str]]:
    bypage = defaultdict(list)
    for r in rows:
        bypage[(r["book"], r["page"])].append(r)
    return {k for k, v in bypage.items()
            if len(v) != 9 or any(abs(x["w_dev"]) > 0.15 for x in v)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default="output/step2_corpus_scan.json")
    ap.add_argument("-o", "--out", default="output/step2_expansion_cards.jsonl")
    ap.add_argument("--n-random", type=int, default=40)
    ap.add_argument("--n-tail", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260903)
    args = ap.parse_args()

    rows = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    blocked = l1_blocked(rows)

    meta = json.loads((DATASET / "metadata.json").read_text(encoding="utf-8"))
    excluded = {(e["book"], e["page"]) for e in meta.get("excluded_pages", [])}
    have = set()
    for f in (DATASET / "samples").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        have.add((d["book"], d["page"], d["col"]))

    pool = [r for r in rows
            if (r["book"], r["page"]) not in blocked
            and (r["book"], r["page"]) not in excluded
            and (r["book"], r["page"], r["col"]) not in have]
    tail = [r for r in pool if r["side_floor"] > 0.01 or r["edge_resid"] > 0.05]
    plain = [r for r in pool if r not in tail]
    print(f"抽样框：L1 放行且未标过的 {len(pool)} 列（难例尾 {len(tail)}）"
          f"；已排除 {len(blocked)} 页 L1 挡下 + {len(excluded)} 页上游切错")

    rng = random.Random(args.seed)
    pick_r = rng.sample(pool, min(args.n_random, len(pool)))          # 随机层从全池抽
    rest = [r for r in tail if r not in pick_r]
    pick_t = rng.sample(rest, min(args.n_tail, len(rest)))

    cards = []
    for r, tag in [(x, "抽样·随机") for x in pick_r] + [(x, "抽样·难例尾") for x in pick_t]:
        cards.append(dict(book=r["book"], page=r["page"], col=r["col"], tags=[tag]))
    cards.sort(key=lambda c: (c["book"], int(c["page"]), c["col"]))
    Path(args.out).write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cards) + "\n", encoding="utf-8")

    n_tail_in_rand = sum(1 for r in pick_r if r in tail)
    print(f"随机层 {len(pick_r)} 列（其中落在难例尾的 {n_tail_in_rand} 列 "
          f"= {n_tail_in_rand/max(1,len(pick_r)):.1%}，这个数本身就是全书难例率的估计）")
    print(f"难例层 {len(pick_t)} 列 -> {args.out}")


if __name__ == "__main__":
    main()
