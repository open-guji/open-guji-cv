# -*- coding: utf-8 -*-
"""比较两版切分（index.jsonl）：字位增减 + bbox 位移 + 已裁决字位的存活。

    PYTHONPATH=. python scripts/diff_segmentation.py \
        --old /tmp/rerun_base/vol01_index_old.jsonl \
        --new output/vol01/phase4_chars/index.jsonl \
        --queue output/vol01/phase9_seed/queue.jsonl

## 为什么要按 IoU 而不是按 id 比

字位 id 是 `book:page:col:idx`——**序号**，不是内容。格高/格线一动，
同一个 id 指向的字就可能换了人（char-segmentation 数据集第九轮的教训：
「10:2:6 从『列』变成『冬』」）。所以判「这一格还是不是原来那一格」只能
看几何：新旧 bbox 的 IoU。

三档（阈值取自 review_recrop 金标回归用的同一把尺）：

- **stable** IoU ≥ 0.90：同一格、切法几乎没变 → 旧裁决可直接沿用；
- **shifted** 0.50 ≤ IoU < 0.90：还是那一格但框动了（可能变好也可能变坏）
  → 图块变了，字大概率没变，**建议抽查**；
- **broken** IoU < 0.50 或 id 消失/新增 → 内容可能换了人，**必须重审**。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

STABLE, SHIFTED = 0.90, 0.50


def load(p):
    out = {}
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["id"]] = d
    return out


def iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def classify(v):
    return "stable" if v >= STABLE else ("shifted" if v >= SHIFTED else "broken")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--queue", help="种子队列：按已裁决/待审分开统计")
    ap.add_argument("--out", help="逐字位明细 json")
    args = ap.parse_args()

    old, new = load(args.old), load(args.new)
    decided = {}
    if args.queue and Path(args.queue).exists():
        for line in Path(args.queue).read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                decided[d["instance_id"]] = d

    detail = {}
    per_page = defaultdict(Counter)
    overall = Counter()
    dec_page = defaultdict(Counter)
    dec_overall = Counter()

    for iid in set(old) | set(new):
        if iid not in new:
            cls, v = "gone", 0.0
        elif iid not in old:
            cls, v = "added", 0.0
        else:
            v = iou(old[iid]["bbox"], new[iid]["bbox"])
            cls = classify(v)
        page = (new.get(iid) or old[iid])["page"]
        per_page[page][cls] += 1
        overall[cls] += 1
        detail[iid] = {"cls": cls, "iou": round(v, 4)}
        st = (decided.get(iid) or {}).get("status")
        if st and st not in ("pending_review", "skipped"):
            dec_page[page][cls] += 1
            dec_overall[cls] += 1

    def line(c):
        tot = sum(c.values()) or 1
        return " ".join(f"{k}={c[k]}({c[k]*100//tot}%)" for k in
                        ("stable", "shifted", "broken", "gone", "added") if c[k])

    print(f"全部字位 {sum(overall.values())}：{line(overall)}")
    if dec_overall:
        print(f"其中已裁决 {sum(dec_overall.values())}：{line(dec_overall)}")
        print("\n已裁决页逐页（只列有非 stable 的）：")
        print(f"{'页':>4} {'已裁':>5}  {'stable':>7} {'shifted':>7} {'broken':>6} {'gone':>5}")
        for p in sorted(dec_page, key=lambda x: int(x)):
            c = dec_page[p]
            if c["stable"] == sum(c.values()):
                print(f"{p:>4} {sum(c.values()):>5}  {c['stable']:>7} {'-':>7} {'-':>6} {'-':>5}")
            else:
                print(f"{p:>4} {sum(c.values()):>5}  {c['stable']:>7} "
                      f"{c['shifted']:>7} {c['broken']:>6} {c['gone']:>5}")
    if args.out:
        Path(args.out).write_text(json.dumps(detail, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"\n明细 → {args.out}")


if __name__ == "__main__":
    main()
