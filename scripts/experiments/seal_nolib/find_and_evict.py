# -*- coding: utf-8 -*-
"""找出「已进字形库的印章遮挡格」并撤库（H-seal，2026-09-30）。

用户 09-30：印章遮挡块里的格一律不入字形库。vol03 第 3 页有 8 格遮挡格的人裁「确认」事件
`no_glyph_lib` 是 false，已经进了库（不是有意的）。本脚本在**服务器上**由值守跑：

    # 干跑（缺省，只读库、只读事件、不写任何东西）
    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/experiments/seal_nolib/find_and_evict.py \\
        --book vol03 --page 3 --out /tmp/seal_nolib.json

    # 执行（要显式 --apply；--expect 是条数闸：实际要撤的库例数不等于它就整批不动）
    ... --book vol03 --page 3 --apply --expect 8

## 判据

遮挡格 = `steps.occlusion.page_occluded`（与 seed_admit `occluded_gate`、`glyphdb_admit` 入库闸
**同一个来源**，参数取该书 `seed_admit` 解析结果）。事件只用来列「谁裁的」，是否撤库只看
「这格现在在库里吗」：`v2:<book>:p:c:s`（人裁）与同格机器副本 `<book>:p:c:s`（非 v1 来源）。

## 撤库

走 `clustering.audit.evict_instance`（写 `evictions` 撤例审计，`glyph_store_sync` 的删除护栏
只放行有审计的删除），在 `feedback_write_lock` 里做，与控制台裁决互斥。**不改事件**：
人裁的「确认」事件留着（文本层照出字）；同格以后再有事件也会被 `glyphdb_admit` 的遮挡闸挡住。
撤完 store 由 `guji-glyph-store-sync.timer` 下一轮导出（或手跑 `scripts/glyph_store_sync.py`）。
幂等：撤完再跑，找到 0 例。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

REASON = "H-seal 2026-09-30：印章遮挡格一律不入字形库（用户 09-30）"


def _parse_key(key: str):
    """`[v2:]<book>:<页>:<列>:<格>[a|b]` → (book, page, col, slot, sub)；解析不了 → None。"""
    parts = (key or "").split(":")
    if parts and parts[0] == "v2":
        parts = parts[1:]
    if len(parts) != 4 or not (parts[1].isdigit() and parts[2].isdigit()):
        return None
    slot, sub = parts[3], ""
    if slot and slot[-1] in "ab":
        slot, sub = slot[:-1], slot[-1]
    if not slot.lstrip("-").isdigit():
        return None
    return parts[0], int(parts[1]), int(parts[2]), int(slot), sub


def confirm_events(events, book: str, page: int) -> dict[tuple[int, int, str], list]:
    """本页人裁「确认」事件，按格 (col, slot, sub) 分组，保持 (batch, seq) 序。"""
    out: dict[tuple[int, int, str], list] = {}
    for e in sorted(events, key=lambda e: e.order):
        if e.kind != "confirm" or (e.payload.get("v") or "confirm") != "confirm":
            continue
        k = _parse_key(e.target.key)
        if k is None or k[0] != book or k[1] != page:
            continue
        out.setdefault(k[2:], []).append(e)
    return out


def _lib_row(conn: sqlite3.Connection, iid: str):
    return conn.execute(
        "SELECT a.provenance, a.char, s.pipeline_version FROM admissions a "
        "  JOIN instances i USING(instance_id) LEFT JOIN sources s ON s.source_id=i.source_id "
        " WHERE a.instance_id=?", (iid,)).fetchone()


def find(book: str, page: int, occluded: set, events, conn: sqlite3.Connection) -> list[dict]:
    """遮挡格里现在在库的刻例。一格一行；`instances` 里是要撤的库例 id。"""
    by_cell = confirm_events(events, book, page)
    rows = []
    for col, slot, sub in sorted(occluded):
        ids = []
        base = f"{book}:{page}:{col}:{slot}{sub}"
        for iid, human in ((f"v2:{base}", True), (base, False)):
            r = _lib_row(conn, iid)
            if r is None:
                continue
            prov, ch, pv = r
            if not human and pv == "v1":       # v1 来源同名 id 不是同一格（idx 坐标），不动
                continue
            ids.append({"instance_id": iid, "char": ch, "provenance": prov})
        evs = by_cell.get((col, slot, sub), [])
        if not ids and not evs:
            continue
        rows.append({
            "cell": f"{page}:{col}:{slot}{sub}",
            "events": [{"id": e.id, "batch": e.batch, "shape": e.payload.get("shape"),
                        "no_glyph_lib": bool(e.payload.get("no_glyph_lib"))} for e in evs],
            "in_lib": bool(ids), "instances": ids})
    return rows


def evict(db, rows: list[dict]) -> int:
    from open_guji_cv.clustering.audit import evict_instance
    n = 0
    for r in rows:
        for it in r["instances"]:
            if evict_instance(db, it["instance_id"], reason=REASON) is not None:
                n += 1
    return n


def main(argv=None, occluded_of=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--db", help="字形库路径（缺省取工作区）")
    ap.add_argument("--apply", action="store_true", help="真撤库；缺省干跑")
    ap.add_argument("--expect", type=int, help="apply 时要撤的库例数，对不上就整批不动")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    from open_guji_cv.core.workspace import feedback_root, glyph_db_path
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.consumers import _occluded_lookup

    log = EventLog()
    events = [e for b in log.batches() if b.startswith(f"{a.book}-") for e in log.read(b)]
    occ = (occluded_of or _occluded_lookup)(a.book, a.page)
    db_path = Path(a.db) if a.db else glyph_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = find(a.book, a.page, occ, events, conn)
    finally:
        conn.close()
    n_inst = sum(len(r["instances"]) for r in rows)
    rep = {"book": a.book, "page": a.page, "occluded_cells": len(occ), "applied": False,
           "cells_in_lib": sum(r["in_lib"] for r in rows), "instances_to_evict": n_inst, "rows": rows}
    if not occ:
        print("⚠️ 遮挡检测返回空集：读不到该页 cells 产物/原图，或该页没有遮挡。"
              "服务器上出现这条要先确认产物在（guji status）。", file=sys.stderr)
    if a.apply:
        if a.expect is not None and n_inst != a.expect:
            print(f"要撤 {n_inst} 例 ≠ --expect {a.expect}，整批不动。", file=sys.stderr)
            print(json.dumps(rep, ensure_ascii=False, indent=1))
            return 2
        from open_guji_cv.clustering.glyph_db import GlyphDB
        from open_guji_cv.feedback.lock import feedback_write_lock
        with feedback_write_lock(feedback_root()):
            db = GlyphDB(str(db_path))
            try:
                rep["evicted"] = evict(db, rows)
            finally:
                db.close()
        rep["applied"] = True
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if not a.apply:
        print("\n（干跑，未写库。核对 rows 后加 --apply --expect <instances_to_evict> 执行。）")
    if a.out:
        a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
