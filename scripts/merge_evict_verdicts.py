# -*- coding: utf-8 -*-
"""把出库裁决台的逐块人裁并进 char-segmentation/instances（图块质量金标）。

    PYTHONPATH=. python scripts/merge_evict_verdicts.py \
        --verdicts artifacts/glyph_evict_verdicts.jsonl \
        --cards artifacts/glyph_evict_cards.jsonl \
        --dataset ../open-guji-dataset/char-segmentation/instances

## 这批为什么值钱

该集 metadata 里写着一条限制：「**各类占比不是全书真实比例**……不能读作
缺陷率」——历史样本全是从人工标记过的问题位置定向抽的。这一批不一样：
出库裁决台的候选**分四层**，其中 `control` 层是从全池随机抽的、任何旗标
都没有的块。有了这一层，缺陷率**第一次可估**：

    全池缺陷率 ≈ P(有旗标)·P(缺陷|有旗标) + P(无旗标)·P(缺陷|无旗标)

所以并进来的每条都带 `stratum`（missed/flagged/newrule/control）与
`stratum_weight`（该层在全池里的占比）。**读这批数必须带着分层读**：
`missed` 层是定向富集（专挑判据漏掉的），单独看它的缺陷率没有意义。

## 标签怎么映

人裁给的是三档处置（出库 / 进测试集 / 留着），本集的 schema 是四分类
（clean / contaminated / truncated / not_text）。映法：

- `keep` → `clean`，**人裁直给**；
- `out` / `test` → 有缺陷。**具体是哪一类由旗标推**（带 truncated 旗标的
  记 truncated，带 residue/rule_bar/frame_bar 的记 contaminated，都没有的
  记 contaminated 并置 `needs_review`）。

「有没有缺陷」是人裁的，「是哪一类缺陷」是推的——两者分开记：
`human_verdict` 存原始裁决，`quality_subtype_origin` 标明子类是谁定的。
主指标 `defect_recall` 把三类缺陷合起来算，不受子类准确度影响。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

PIPE_REV = "502fa04d0c"

CONTAM = {"residue", "rule_bar_left", "rule_bar_right",
          "frame_bar_top", "frame_bar_bottom"}
# 四层在全池 6086 块里的占比（build_glyph_evict_review.py 的取样口径）
STRATUM_WEIGHT = {"flagged": 0.0996, "control": 0.9004,
                  "newrule": None, "missed": None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="artifacts/glyph_evict_verdicts.jsonl")
    ap.add_argument("--cards", default="artifacts/glyph_evict_cards.jsonl")
    ap.add_argument("--dataset",
                    default="../open-guji-dataset/char-segmentation/instances")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    V = {json.loads(l)["instance_id"]: json.loads(l)["verdict"]
         for l in Path(args.verdicts).read_text(encoding="utf-8").splitlines() if l.strip()}
    C = {json.loads(l)["iid"]: json.loads(l)
         for l in Path(args.cards).read_text(encoding="utf-8").splitlines() if l.strip()}

    root = Path(args.dataset)
    exp = root / "expected.json"
    data = json.loads(exp.read_text(encoding="utf-8"))
    have = {(e["book"], str(e["page"]), e["col"], e["idx"]) for e in data}

    added, skipped = [], 0
    for iid, v in sorted(V.items()):
        if v == "idk":
            continue
        book, page, col, idx = iid.split(":")
        key = (book, page, int(col), int(idx))
        if key in have:          # 已在集里的不覆盖——那条可能是别的轮次的人裁
            skipped += 1
            continue
        card = C[iid]
        gate = set(card["gate"])
        if v == "keep":
            quality, sub_origin, needs = "clean", "human", False
        elif "truncated" in gate:
            quality, sub_origin, needs = "truncated", "derived_from_flags", False
        elif gate & CONTAM:
            quality, sub_origin, needs = "contaminated", "derived_from_flags", False
        else:
            quality, sub_origin, needs = "contaminated", "derived_default", True
        e = {"book": book, "page": page, "col": int(col), "idx": int(idx),
             "quality": quality, "defect": None if v == "keep" else (
                 sorted(gate)[0] if gate else None),
             "layout": "unknown", "seed": "evict_review_r1",
             "label_origin": "human", "schema_version": 1,
             "human_verdict": v, "quality_subtype_origin": sub_origin,
             "stratum": card["layer"],
             "stratum_weight": STRATUM_WEIGHT[card["layer"]]}
        if needs:
            e["needs_review"] = True
        added.append(e)

    print(f"新增 {len(added)}  已在集里跳过 {skipped}  拿不准跳过 "
          f"{sum(1 for v in V.values() if v == 'idk')}")
    print("  quality:", dict(Counter(e["quality"] for e in added)))
    print("  stratum:", dict(Counter(e["stratum"] for e in added)))
    if args.dry_run:
        return

    # 图块拷进来——集里既有的 746 张都在，`--with-intrusion` 那条路要读它
    out = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}" / "output"
    pat = root / "patches"
    pat.mkdir(exist_ok=True)
    cp = miss = 0
    for e in added:
        src = (out / e["book"] / "phase4_chars" / "patches" / e["page"]
               / f'{e["col"]}_{e["idx"]}.png')
        dst = pat / f'{e["book"]}_{e["page"]}_{e["col"]}_{e["idx"]}.png'
        if src.exists():
            shutil.copyfile(src, dst); cp += 1
        else:
            miss += 1
    print(f"  图块拷入 {cp}  缺 {miss}")

    data.extend(added)
    exp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {exp}  共 {len(data)} 条")


if __name__ == "__main__":
    main()
