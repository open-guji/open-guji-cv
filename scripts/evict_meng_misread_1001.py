# -*- coding: utf-8 -*-
"""四庫 vol01 五条机器进库的「蒙」实为 𫎇 形——撤库（overview#332，用户 10-01 同意）。

M5 道（近形决胜）在四庫字形库里发现：8 条「蒙」刻例中，3 条人裁的是「艹」头（真蒙），
5 条机器进库（align 照抄整理本 / match）的其实是「业」头的 𫎇。它们留在库里会给「蒙」抬 cov，
是 𫎇/蒙 打平（0.984 vs 0.979）的主因之一。证据图：cv 仓 artifacts/m5_near_shape/
meng_library_exemplars.png、meng_heads_zoom.png。

在**本地整理工作区**跑（字形库真源在本地）：

    GUJI_WORKSPACE=<四庫工作区> python scripts/evict_meng_misread_1001.py          # dry-run：只写事件、预览
    GUJI_WORKSPACE=<四庫工作区> python scripts/evict_meng_misread_1001.py --apply  # 真的撤库

写法同 `evict_vol01_48_2_neg1.py`：`glyph_audit`（v=evict）事件 → `route_and_consume`；
撤库经 `clustering.audit.evict_instance`，有 `evictions` 审计。之后照常导出 store、推 guji-workspace。
库里某条字不是「蒙」或已不存在时整批不动（防撤错）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.feedback.consumers import route_and_consume  # noqa: E402
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event  # noqa: E402

TARGETS = ["vol01:10:1:15", "vol01:86:4:3", "vol01:143:3:10", "vol01:133:8:6", "vol01:149:3:17"]
EXPECT_CHAR = "蒙"
BATCH = "vol01-meng-misread-evict-20261001"
NOTE = "机器进库的「蒙」实为 𫎇 形（业头），M5 近形决胜核出，overview#332 用户 10-01 同意撤库"


def _check() -> bool:
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    ok = True
    for iid in TARGETS:
        r = db.conn.execute(
            "SELECT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
            "WHERE e.instance_id=?", (iid,)).fetchone()
        ch = r[0] if r else None
        flag = "ok" if ch == EXPECT_CHAR else "!!"
        ok &= ch == EXPECT_CHAR
        print(f"  [{flag}] {iid}  库里记的字={ch!r}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的撤库；不给只写事件+dry-run 路由")
    a = ap.parse_args()

    print("== 撤库前核对 ==")
    if not _check():
        sys.exit("有条目不是「蒙」或已不在库里，整批不动；请先查清。")

    log = EventLog()
    evs = [make_event(BATCH, i + 1, "glyph_audit",
                      EventTarget(step="seed_admit", unit="cell", key=iid, book="vol01"),
                      {"v": "evict", "target": iid, "note": NOTE})
           for i, iid in enumerate(TARGETS)]
    n = log.append(evs)
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(BATCH)} ==")

    res = route_and_consume(log, BATCH, dry_run=not a.apply)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    if not a.apply:
        print("\n（dry-run：glyph.db 未改。确认后加 --apply。）")


if __name__ == "__main__":
    main()
