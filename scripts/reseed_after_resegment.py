# -*- coding: utf-8 -*-
"""重切分之后，判定旧裁决哪些还能沿用、哪些必须重审，并重建队列。

    PYTHONPATH=. python scripts/reseed_after_resegment.py output/vol01 \
        --old /tmp/rerun_base/vol01_index_old.jsonl [--apply]

## 判定

字位 id 是序号不是内容，切分一动同一个 id 可能换了字（char-segmentation
第九轮教训）。所以逐字位按新旧 bbox 的 IoU 分档：

- **keep**（IoU ≥ 0.90）：同一格、框几乎没动 → 旧裁决沿用，图块换成新的；
- **recheck**（0.50 ≤ IoU < 0.90）：还是那一格但框动了 → 字大概率没变，
  但图块变了，**退回待审**（进库的字形必须是当前图块）；
- **drop**（IoU < 0.50 / id 消失）：内容可能换了人 → 裁决作废、撤库。

`--apply` 才真动数据：队列改状态、库里撤掉 recheck/drop 的实例
（它们的字形已经不是当初那一块了）。不带就是干跑，只报数。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

KEEP, RECHECK = 0.90, 0.50
DECIDED = ("auto_admitted", "confirmed", "confirmed_label_only",
           "rejected", "not_a_char")


def load_index(p):
    out = {}
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["id"]] = d
    return out


def iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out_dir")
    ap.add_argument("--old", required=True, help="重切分前的 index.jsonl")
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    old = load_index(args.old)
    new = load_index(book_dir / "phase4_chars" / "index.jsonl")
    qp = book_dir / "phase9_seed" / "queue.jsonl"
    rows = [json.loads(l) for l in qp.read_text(encoding="utf-8").splitlines()
            if l.strip()]

    verdict, per_page = {}, defaultdict(Counter)
    n = Counter()
    for r in rows:
        iid, st = r["instance_id"], r["status"]
        if st not in DECIDED:
            continue
        if iid not in new:
            v, sc = "drop", 0.0
        elif iid not in old:
            v, sc = "recheck", 0.0          # 旧版没有这一格，裁决无从对应
        else:
            sc = iou(old[iid]["bbox"], new[iid]["bbox"])
            v = "keep" if sc >= KEEP else ("recheck" if sc >= RECHECK else "drop")
        verdict[iid] = (v, sc)
        per_page[r["page"]][v] += 1
        n[v] += 1

    tot = sum(n.values()) or 1
    print(f"{book_dir.name} 已裁决 {tot}：" + "  ".join(
        f"{k}={n[k]}({n[k]*100//tot}%)" for k in ("keep", "recheck", "drop") if n[k]))
    print(f"\n{'页':>4} {'已裁':>5} {'keep':>6} {'recheck':>8} {'drop':>6}  需重审")
    need = []
    for p in sorted(per_page, key=lambda x: int(x)):
        c = per_page[p]
        bad = c["recheck"] + c["drop"]
        if bad:
            need.append(p)
        print(f"{p:>4} {sum(c.values()):>5} {c['keep']:>6} {c['recheck']:>8} "
              f"{c['drop']:>6}  {'←' if bad else ''}")
    print(f"\n需重审的页：{'、'.join(need) if need else '无'}")

    if not args.apply:
        print("\n（干跑：未改队列与库。加 --apply 落地）")
        return

    from open_guji_cv.clustering.audit import evict_instance
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db = GlyphDB(args.db)
    ev = 0
    try:
        for r in rows:
            iid = r["instance_id"]
            v = verdict.get(iid, (None, 0))[0]
            if v in ("recheck", "drop"):
                if db.conn.execute("SELECT 1 FROM admissions WHERE instance_id=?",
                                   (iid,)).fetchone():
                    evict_instance(db, iid)
                    ev += 1
                r["status"] = "pending_review"
                r["decided_char"] = None
                r["provenance"] = None
                r["note"] = f"resegment_{v}"
    finally:
        db.close()
    # 新增字位补进队列（seed 会补齐证据，这里只占位不行——交给重跑 seed）
    qp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                  encoding="utf-8")
    print(f"\n已落地：撤库 {ev}，队列退回 {n['recheck'] + n['drop']} 行。"
          f"\n下一步：重建 OCR 载体 → 重跑 seed（新字位会补进队列）。")


if __name__ == "__main__":
    main()
