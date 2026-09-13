# -*- coding: utf-8 -*-
"""切分裁决台（A/B 盲裁）的裁决 → `char-segmentation/touching-cuts` 金标。

    PYTHONPATH=. python scripts/ingest_cutline_flip_verdicts.py \
        --verdicts /tmp/v3.jsonl --cards artifacts/cutline_flip_cards.jsonl

⚠️ **一次性脚本，留着是为了记住这批金标是怎么来的。** 出卡脚本
（`build_cutline_flip_review.py`）已删除——它挑样本用的判据「候选切法下
上下两格 top1 都命中整理本期望字」**已被这批裁决证伪**：准确率 6/58 = 10%，
且系统性偏向 straight（字形库刻例多为 straight 切出，切法一致就更像，是数据
自证的循环）。详见 `.claude/doc/row_boundaries_design.md` 的「负结果」一节。
别照着这个脚本再挖一批同口径的样本。

## 为什么走事件而不是直接写 items.jsonl

金标仓的条目带 `source_events` / `history`，是从 `feedback/events` 经
`gold_add` 消费者落进去的。直接改 items.jsonl 会造出没有来源的孤儿条目，
下次谁跑 harvest 又会把同一批塞一遍。所以这里只发事件，落盘交给消费者。

## 口径对齐（关键，别想当然）

审查页的四档是**页面自己的语义**（蓝线对／黄线对／都不对／拿不准），
与金标分片既有的 `verdict` 词表（ok / moved / seam_ok / overlap / idk）
不是一套东西。映射按「人选中的那条切法**是不是**算法现役那条」翻译：

| 页面裁决 | 人选中的是 | 落成 verdict | 含义 |
|---|---|---|---|
| 蓝线对／黄线对 | 现役那条 | `ok` | 现役切法正确，不用动 |
| 蓝线对／黄线对 | 另一条 | `moved` | 现役切错，该换成选中那条（带 polyline） |
| 都不对 | —— | `overlap` | 两条切法都坏，需要手画 |
| 拿不准 | —— | `idk` | 落 status=uncertain |

⚠️ `moved` 必须带**选中那条候选的折线**，否则金标只说"现役错了"却没说
该切在哪，评测用不了。straight 候选没有逐列 y（`y=None`），补一条水平线。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import open_guji_cv.steps  # noqa: F401,E402  注册产物种类，读 row_segment 要用
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.feedback.events import EventTarget, make_event  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

BATCH = "vol02-cutline-flip-blind"
# 页面自测留下的那一条（check_fixedpoint 点的），不是人裁，必须剔除
TEST_TS = 1789266969318


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--cards", default="artifacts/cutline_flip_cards.jsonl")
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--apply", action="store_true",
                    help="真写事件；不加只打印将要写什么（默认演练）")
    args = ap.parse_args()

    cards = {}
    for line in Path(args.cards).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            cards[r["id"]] = r

    st = ProductStore()
    cut_cache: dict = {}

    def cut_point(pg: int, col: int, slot_above: int):
        k = (pg, col, slot_above)
        if k in cut_cache:
            return cut_cache[k]
        cells = st.read(args.book, "row_segment", page_key(pg), "cells")
        hit = None
        for cc in (cells.columns if cells else []):
            if cc.col != col:
                continue
            for cp in (getattr(cc, "cut_candidates", None) or []):
                if cp.slot_above == slot_above:
                    hit = cp
        cut_cache[k] = hit
        return hit

    events, stat = [], Counter()
    seq = 0
    for line in Path(args.verdicts).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        v = json.loads(line)
        if v.get("t") == TEST_TS:
            stat["剔除·定点自测"] += 1
            continue
        c = cards.get(v["id"])
        if c is None:
            stat["跳过·卡片对不上"] += 1
            continue

        pick = {"ok": "A", "other": "B"}.get(v["verdict"])
        if pick is None:
            verdict = "overlap" if v["verdict"] == "fix" else "idk"
            polyline, cand = None, None
        else:
            role = c["ident"][pick]["role"]
            cand = c["ident"][pick]["kind"]
            verdict = "ok" if role == "chosen" else "moved"
            polyline = None
            if verdict == "moved":
                idx = c["chosen_idx"] if role == "chosen" else c["flip_idx"]
                cp = cut_point(c["page"], c["col"], c["slot_above"])
                if cp is None:
                    stat["跳过·产物里找不到切点"] += 1
                    continue
                ys = cp.candidates[idx].y
                if ys:
                    step = 6
                    polyline = [[c["col"], int(ys[j])] for j in range(0, len(ys), step)]
                else:
                    polyline = None      # straight：没有逐列 y，评测按 y 走
        stat[f"verdict={verdict}"] += 1

        seq += 1
        payload = {
            "verdict": verdict,
            "slot_above": c["slot_above"], "slot_below": c["slot_below"],
            "char_above": c["exp_a"], "char_below": c["exp_b"],
            "bi": c["slot_above"],
            # 盲裁的出处与分层，事后要能还原这批是怎么来的
            "note": "A/B 盲裁（切分裁决台）；候选左右随机、卡上不标现役",
            "stratum": c["stratum"],
        }
        if cand:
            payload["cand"] = cand
        if polyline:
            payload["polyline"] = polyline

        events.append(make_event(
            BATCH, seq, "cutline",
            EventTarget(step="row_segment", unit="boundary", key=c["id"],
                        book=args.book, page=c["page"], col=c["col"],
                        slot=c["slot_above"]),
            payload))

    print(f"将写入 {len(events)} 条事件 → 批次 {BATCH}")
    for k, v in stat.most_common():
        print(f"  {k:24} {v}")

    if not args.apply:
        print("\n（演练，未写入。加 --apply 真写）")
        return

    from open_guji_cv.console import deps
    # append 收的是可迭代的一批，并按 (batch, seq) 去重——重跑本脚本不会灌重
    n = deps.event_log().append(events)
    print(f"\n已写入 {n} 条（重复的自动跳过）。接着跑 harvest 落金标：")
    print(f"  PYTHONPATH=. python -m open_guji_cv.cli_v2 feedback harvest --batch {BATCH}")


if __name__ == "__main__":
    main()
