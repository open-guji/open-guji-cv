# -*- coding: utf-8 -*-
"""把数据集里的人工重切框重新贴回产物（整册重跑之后必跑）。

    # 只报不改
    PYTHONPATH=. python scripts/replay_recrops.py output/vol01
    # 落地：改 index.jsonl 的 bbox、重裁 patch、库内实例同步换图
    PYTHONPATH=. python scripts/replay_recrops.py output/vol01 --apply

## 为什么需要它

人工重切（审查页拖框）改的是 **index.jsonl 的 bbox + 磁盘上的 patch**，
而 `segment` / `chars` 一重跑就把这两样整份重写——重切成果无声无息地
没了。实测 vol01：库里曾有 24 条重切（`8dc0009435`），到
`1beec69a83 裁剪定版` 之后 index.jsonl 里带 `recropped` 旗的**归零**。
用户 2026-08-25 反馈「切分似乎没有被改」正是这个。

重切的**真源不在产物里**，在数据集：
`open-guji-dataset/char-segmentation/instances/expected.json` 里
`seed == "review_recrop"` 的条目带 `corrected_bbox`（人工金标）与
`old_bbox`（当时的坏框）。所以产物可以重建，重切不能——每次整册重跑
之后把这份金标重放回去即可。

## 字位漂移怎么办

`instance_id` 是序号，整页格位挪一格它就换人（见
migrate_labels_after_resegment.py）。所以先按 id 找，IoU 太低就在同页
内按 `corrected_bbox` 的最佳 IoU 重新认领；都不行就跳过并报出来，
宁可少改一格，也不能把人工框贴到别的字上。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.extractor import load_index  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.clustering.seeding import apply_recrop  # noqa: E402

CLAIM_IOU = 0.35      # 低于此不认领（宁可不改）


def iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    i = (x1 - x0) * (y1 - y0)
    return i / ((a[2] - a[0]) * (a[3] - a[1])
                + (b[2] - b[0]) * (b[3] - b[1]) - i)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out_dir")
    ap.add_argument("--dataset", default="../open-guji-dataset")
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    book = book_dir.name
    root = book_dir / "phase4_chars"
    shard = (Path(args.dataset) / "char-segmentation" / "instances"
             / "expected.json")
    gold = [x for x in json.loads(shard.read_text(encoding="utf-8"))
            if x.get("seed") == "review_recrop" and x.get("book") == book]
    if not gold:
        print(f"{shard} 里没有 {book} 的人工重切")
        return

    recs = {r.id: r for r in load_index(root)}
    by_page: dict[str, list] = {}
    for r in recs.values():
        by_page.setdefault(r.page, []).append(r)

    plan, unclaimed, already = [], [], []
    for g in gold:
        iid = f"{book}:{g['page']}:{g['col']}:{g['idx']}"
        want = g["corrected_bbox"]
        rec = recs.get(iid)
        if rec is not None and iou(rec.bbox, want) >= 0.98:
            already.append(iid)
            continue
        if rec is None or iou(rec.bbox, want) < CLAIM_IOU:
            # id 漂了：同页内按最佳 IoU 重新认领
            cands = [(iou(r.bbox, want), r) for r in by_page.get(g["page"], [])]
            best = max(cands, default=(0.0, None), key=lambda t: t[0])
            if best[0] < CLAIM_IOU:
                unclaimed.append((iid, round(best[0], 2)))
                continue
            rec = best[1]
        j = iou(rec.bbox, want)
        if j >= 0.98:              # 认领之后再判一次，否则漂过号的字位
            already.append(rec.id)  # 每次跑都会被当成「要贴回」（不幂等）
            continue
        plan.append((rec, want, j))

    print(f"{book}：数据集里 {len(gold)} 条人工重切")
    print(f"  已经是修正框（不用动）  {len(already)}")
    print(f"  要贴回                  {len(plan)}")
    print(f"  认领不到、跳过          {len(unclaimed)}  {unclaimed}")
    for rec, want, j in plan:
        print(f"    {rec.id:<16} 现框 IoU {j:.2f} → {[round(v) for v in want]}")
    if not args.apply:
        print("\n（干跑：未改产物。加 --apply 落地）")
        return

    db = GlyphDB(args.db)
    n_patch = n_db = 0
    try:
        for rec, want, _ in plan:
            png = apply_recrop(book_dir, rec, list(want))
            if png is None:
                print(f"  ⚠ {rec.id} 重裁失败（页图缺失或框越界）")
                continue
            n_patch += 1
            row = db.conn.execute(
                "SELECT 1 FROM instances WHERE instance_id=?",
                (rec.id,)).fetchone()
            if row:
                # 库里存的必须是重切后的字形（用户 2026-08-24 定的口径）。
                # bbox 与派生缓存要一起动：derived 里的归一化/canonical 是
                # 从**旧图块**算的，留着就等于换了图却还用老特征匹配。
                db.conn.execute(
                    "UPDATE instances SET patch_png=?, bbox=? "
                    "WHERE instance_id=?",
                    (png, json.dumps([float(v) for v in want]), rec.id))
                db.conn.execute("DELETE FROM derived WHERE instance_id=?",
                                (rec.id,))
                n_db += 1
        db.conn.commit()
    finally:
        db.close()
    print(f"\n落地：重裁 {n_patch} 块，库内同步 {n_db} 条"
          f"（patch + bbox 换新、派生缓存清掉重算）")


if __name__ == "__main__":
    main()
