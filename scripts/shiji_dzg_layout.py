# -*- coding: utf-8 -*-
"""史記文淵閣本：daizhige 源记录 + 页钉位 → 逐列格位表（`row_segment.layout_prior` 读的那张）与页对照。

    python scripts/shiji_dzg_layout.py --dz <daizhige 目录> --pins <page_pins.jsonl> [--books 01,02,03]

和四庫總目的 `scripts/dzg_layout.py` 同一口径（`utils/daizhige.column_layout`），差在两处：
- 史記一个半叶 8 列（daizhige `geom.ncol`=8），`no` 0–7 前半叶、8–15 后半叶，列号 ＝ `no % 8 + 1`；
- 我们的页与半叶的对应不靠配页，直接读页钉位表（`{book, page, head}`，head 形如 `0243-0049 243-12b h1`）。

职名列（daizhige 记 `zm: true`）不写：职名页走 roster 分支，密排段在 daizhige 里按一字一格记，不是几何格位。
2026-10-31 起 Step3 自动配页 `page_map: pins` 边跑边按钉位出同一张表（`steps/row_segment_pagemap.build_from_pins`，
逐行相同），书 yaml 改用 pins 档后就不必再跑本脚本；留作离线核对。
输出（写进 --dz 目录）：`layout_slots.jsonl`（vol＝册 id）、`page_map.jsonl`（vol、page、dzg_id、side）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.utils.daizhige import column_layout, load_records  # noqa: E402

NCOL = 8


def build(dz: Path, pins: Path, books: set[str] | None):
    recs = {}
    for f in sorted(dz.glob("[0-9][0-9][0-9][0-9].jsonl")):
        for r in load_records(f):
            recs[r["id"]] = r
    rows, pm = [], []
    for ln in pins.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        p = json.loads(ln)
        if books and p["book"] not in books:
            continue
        rid, _leaf, side = p["head"].split()
        side = int(side[1:])
        rec = recs.get(rid)
        pm.append({"vol": p["book"], "page": p["page"], "dzg_id": rid, "side": side})
        if rec is None or not isinstance(rec.get("cols"), list):
            continue
        for c in rec["cols"]:
            if c["no"] // NCOL != side or c.get("zm"):
                continue
            lay = column_layout(c)
            if lay:
                rows.append({"vol": p["book"], "page": p["page"], "col": c["no"] % NCOL + 1,
                             "dzg": f"{rid}h{side}", **lay})
    return rows, pm


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dz", required=True, help="daizhige 目录（放 0243.jsonl 等源文件）")
    ap.add_argument("--pins", required=True)
    ap.add_argument("--books", default="")
    a = ap.parse_args(argv)
    dz = Path(a.dz)
    books = {b.zfill(2) for b in a.books.split(",") if b} or None
    rows, pm = build(dz, Path(a.pins), books)
    with open(dz / "layout_slots.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(dz / "page_map.jsonl", "w", encoding="utf-8") as f:
        for r in pm:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"格位表 {len(rows)} 列，页对照 {len(pm)} 页 → {dz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
