# -*- coding: utf-8 -*-
"""重切分之后把旧裁决平移到新字位，避免重复校对。

    # 干跑：只探测偏移并报命中率
    PYTHONPATH=. python scripts/migrate_labels_after_resegment.py output/vol01
    # 落地：迁移队列裁决 + 用新图块重建库内实例
    PYTHONPATH=. python scripts/migrate_labels_after_resegment.py output/vol01 --apply

## 为什么需要它

字位 id 是 `book:page:col:idx` —— **序号**。上游修一次行相位（如
`0fa0f8d51f 第五轮定版：墨底兜底救回 59 页相位`），整页的格位就集体挪一格，
同一个 id 指向的字跟着换人。实测 vol01：库内 2292 条里 1213 条（52%）
就是这么错位的，其中第 18 页还叠加了列偏移。

但错位是**系统性平移**而非内容乱掉——旧裁决的「字」本身没错，只是挂在了
错的号上。所以不必重校，把标注按偏移搬过去即可。

## 怎么定偏移

拿库里存的**旧字形**去新切分里找同一个字：对每页（必要时每列）试
(col+dc, idx+di)，用 elastic cov ≥ MATCH_T 算命中，取命中率最高且
≥ CONFIDENT 的那个偏移。命中率不够就**不迁移这一页**，退回人工重审——
宁可让人多看一页，也不能把标注搬到错的格子上。

## 落地时做什么

- 队列：已裁决行的 instance_id 换成新号（note 记 `migrated:+dc+di`）；
- 库：旧 id 撤库（evict），用新 id + **新切分的图块**重新进库，
  字与 provenance 沿用（evidence 里记 migrated_from）。
  存的是新图块——上游清理改进的收益一并吃到。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.audit import evict_instance  # noqa: E402
from open_guji_cv.clustering.canonical import to_canonical  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402

MATCH_T = 0.95        # 单格算「同一个字」的 cov 门槛
CONFIDENT = 0.85      # 页级命中率低于此就不迁移（退人工）
PROBE_N = 24          # 每页探测用多少个样本
SHIFTS = [(0, 1), (0, 2), (0, -1), (0, -2), (1, 1), (1, 0), (-1, 0),
          (-1, -1), (1, 2), (0, 3), (0, -3)]
DECIDED = ("auto_admitted", "confirmed", "confirmed_label_only",
           "rejected", "not_a_char")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out_dir")
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    book = book_dir.name
    root = book_dir / "phase4_chars"
    idx = {}
    for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            idx[d["id"]] = d
    db = GlyphDB(args.db)
    store = dict(db.conn.execute(
        "SELECT instance_id, patch_png FROM instances").fetchall())
    chars = dict(db.conn.execute(
        """SELECT e.instance_id, g.char FROM exemplars e
           JOIN glyphs g ON g.glyph_id = e.glyph_id""").fetchall())

    _cache: dict[str, np.ndarray | None] = {}

    def new_norm(iid):
        if iid not in _cache:
            d = idx.get(iid)
            g = (cv2.imread(str(root / d["patch_path"]), cv2.IMREAD_GRAYSCALE)
                 if d else None)
            _cache[iid] = None if g is None else normalize_patch(to_canonical(g))
        return _cache[iid]

    def old_norm(iid):
        png = store.get(iid)
        if png is None:
            return None
        return normalize_patch(cv2.imdecode(np.frombuffer(png, np.uint8),
                                            cv2.IMREAD_GRAYSCALE))

    # 哪些库内实例与当前同号图块对不上 → 需要迁移
    drift_by_page = defaultdict(list)
    ok_by_page = Counter()
    for iid in store:
        if not iid.startswith(book + ":"):
            continue
        o, n = old_norm(iid), new_norm(iid)
        page = iid.split(":")[1]
        if n is not None and o is not None and \
                float(verify_pair_elastic(o, n).f1) >= MATCH_T:
            ok_by_page[page] += 1
        else:
            drift_by_page[page].append(iid)

    print(f"{book}：库内 {sum(1 for i in store if i.startswith(book+':'))} 条，"
          f"对得上 {sum(ok_by_page.values())}，需迁移 "
          f"{sum(len(v) for v in drift_by_page.values())}")
    print(f"\n{'页':>4} {'需迁':>5} {'偏移':>9} {'命中率':>7}  处置")
    plan: dict[str, tuple[int, int]] = {}
    for page in sorted(drift_by_page, key=lambda x: int(x)):
        ids = drift_by_page[page][:PROBE_N]
        best = (0.0, None)
        for dc, di in SHIFTS:
            hit = tot = 0
            for iid in ids:
                _, p, c, i = iid.split(":")
                cand = f"{book}:{p}:{int(c)+dc}:{int(i)+di}"
                nn = new_norm(cand)
                oo = old_norm(iid)
                if nn is None or oo is None:
                    continue
                tot += 1
                hit += float(verify_pair_elastic(oo, nn).f1) >= MATCH_T
            if tot and hit / tot > best[0]:
                best = (hit / tot, (dc, di))
        rate, sh = best
        if sh and rate >= CONFIDENT:
            plan[page] = sh
            note = f"迁移 col{sh[0]:+d} idx{sh[1]:+d}"
        else:
            note = "**不迁移，退人工重审**"
        print(f"{page:>4} {len(drift_by_page[page]):>5} "
              f"{(f'{sh[0]:+d},{sh[1]:+d}' if sh else '-'):>9} "
              f"{rate*100:>6.1f}%  {note}")

    if not args.apply:
        print("\n（干跑：未改队列与库。加 --apply 落地）")
        db.close()
        return

    # ── 落地 ──
    qp = book_dir / "phase9_seed" / "queue.jsonl"
    rows = [json.loads(l) for l in qp.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    n = Counter()
    for r in rows:
        iid = r["instance_id"]
        page = r["page"]
        if r["status"] not in DECIDED or page not in plan:
            continue
        if iid not in {x for v in drift_by_page.values() for x in v} \
                and iid in store:
            continue                       # 本来就对得上，不动
        dc, di = plan[page]
        new_id = f"{book}:{page}:{r['col']+dc}:{r['idx']+di}"
        if new_id not in idx:
            r["status"] = "pending_review"
            r["note"] = "resegment_lost"
            n["lost"] += 1
            continue
        ch = chars.get(iid) or r.get("decided_char")
        if iid in store:                   # 库里有 → 撤旧、用新图块重进
            evict_instance(db, iid)
            n["evicted"] += 1
            if ch:
                d = idx[new_id]
                db.admit_instance(
                    new_id, ch, (root / d["patch_path"]).read_bytes(),
                    provenance=r.get("provenance") or "human",
                    evidence={"migrated_from": iid, "shift": [dc, di],
                              "reason": "resegment"},
                    page=page, col=r["col"] + dc, idx=r["idx"] + di,
                    bbox=list(d["bbox"]), ink_ratio=d.get("ink_ratio"),
                    width=d.get("width"), height=d.get("height"))
                n["readmitted"] += 1
        r["instance_id"] = new_id
        r["col"], r["idx"] = r["col"] + dc, r["idx"] + di
        r["patch_path"] = idx[new_id]["patch_path"]
        r["note"] = f"migrated:{dc:+d}{di:+d}"
        n["migrated"] += 1
    qp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                          for r in rows), encoding="utf-8")
    db.close()
    print(f"\n落地：{dict(n)}")


if __name__ == "__main__":
    main()
