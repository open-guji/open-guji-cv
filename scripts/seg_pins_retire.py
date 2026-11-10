#!/usr/bin/env python3
"""钉子退役报告（A22 F2，2026-11-10）：哪些格级钉子（manual-cells），算法不带钉子也已经能切对。

做法：把有钉子的页拷进临时沙箱，本册钉子全部拿掉，从 row_segment 跑到 cell_shrink（要装 torch），
逐列与钉子比（`feedback/pins_check.retire_verdict`）：

  retire  格号集合（含 a/b）相同，每格上下沿差 ≤ 0.1 格高——可以撤；
  near    格号相同，差 ≤ 0.25 格高——看图再定；
  keep    格号不同或偏差大——钉子还要留着。

本机产物、缓存、中心库都不动。撤钉子由书线把 item 置 `status: retired` 并写 history，撤前跑 seg_pins_check 核人裁。

用法：
    export GUJI_WORKSPACE=<工作区>
    python scripts/seg_pins_retire.py --books 01 02 … [--out <目录>]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", nargs="+", required=True)
    ap.add_argument("--out", default="seg_pins_retire_out")
    a = ap.parse_args(argv)

    from open_guji_cv.core.spec import page_key
    from open_guji_cv.feedback import pins_check as pc
    from open_guji_cv.feedback.lookup import MANUAL_CELLS_SHARD
    from open_guji_cv.gold.store import verdict_store
    from open_guji_cv.report.slots import CELLS_KIND, cells_step

    items = pc.read_items(verdict_store().items_path(MANUAL_CELLS_SHARD))
    why_of = {}
    for it in items:
        anc = it.get("anchor") or {}
        hist = it.get("history") or []
        why_of[(str(anc.get("book")), anc.get("page"), anc.get("col"))] = (hist[-1].get("why") if hist else "") or ""
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, tally = [], {}
    for book in a.books:
        pins = pc.pins_of(items, book)
        if not pins:
            continue
        pages = sorted({p for p, _c in pins})
        tmp = Path(tempfile.mkdtemp(prefix=f"pins_retire_{book}_"))
        store, _cache, _rep = pc.sandbox_rerun(book, pages, tmp, pins={})
        step = cells_step(book)
        for (pg, col), pin in sorted(pins.items()):
            pcells = store.read(book, step, page_key(pg), CELLS_KIND)
            cc = None if pcells is None else next((c for c in pcells.columns if c.col == col), None)
            v = pc.retire_verdict(pin, cc)
            rows.append((book, pg, col, v["verdict"], v["max_dev"], v["why"], why_of.get((book, pg, col), "")))
            tally.setdefault(book, {"retire": 0, "near": 0, "keep": 0})[v["verdict"]] += 1
    with open(out / "retire.tsv", "w", encoding="utf-8") as f:
        f.write("book\tpage\tcol\tverdict\tmax_dev\twhy\tpin_why\n")
        f.writelines("\t".join("" if x is None else str(x) for x in r) + "\n" for r in rows)
    lines = ["# 钉子退役报告", "", "| 册 | 可撤 | 接近 | 留 |", "| --- | --- | --- | --- |"]
    lines += [f"| {b} | {t['retire']} | {t['near']} | {t['keep']} |" for b, t in tally.items()]
    lines += ["", "明细 `retire.tsv`。可撤的抽几列看图，再由书线撤（置 retired、写 history），撤前跑 seg_pins_check。"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
