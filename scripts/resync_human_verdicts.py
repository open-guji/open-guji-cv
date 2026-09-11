# -*- coding: utf-8 -*-
"""把字形库里的人裁记录对齐到**最新**人裁事件：改判被幂等闸挡住的，撤旧进新。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/resync_human_verdicts.py [--dry]

## 为什么需要它

`admit_instance` 有主键幂等闸：一个字位进过库就不再写。人第一次裁 巳、后来改判 已，
第二个事件被闸掉，库里留的是 巳；admit_decide 的人裁通道读库，产物就跟着错，判据 E 报
「存 巳 人裁 已」。同一个坑咬了三次（蠹、vol01:32:7:10、vol01:29:4:19 / 80:5:7）。
2026-09-07 起 `glyphdb_admit` 消费者遇到**人裁改判**会自己撤旧进新；本脚本处理此前积压的，
以及任何绕过消费者写库留下的不一致。

口径：每个字位取 ts 最新的 confirm 事件（与 round_check.load_verdicts 一致），
比库里的字形层（glyphs 经 exemplars）与释读层（admissions.char）；任一不同就撤库重放该事件。
只看 v2 字位（v1 id 是另一个命名空间）。回执追加进 output/mislabel_evictions.jsonl。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.audit import evict_instance  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.feedback.consumers import glyphdb_admit  # noqa: E402
from open_guji_cv.feedback.events import EventLog  # noqa: E402

SPLIT = frozenset("己已巳")


class _Normalized:
    """重放用的事件影子：释读按规则归一（非 己已巳 跟随字形），不改事件日志本身。"""

    def __init__(self, e, reading: str):
        self.id, self.batch, self.kind, self.target, self.ts = e.id, e.batch, e.kind, e.target, e.ts
        p = dict(e.payload or {})
        p["reading"] = reading
        p["conversion"] = 1 if reading != p.get("shape") else 0
        self.payload = p


def latest_confirms(log: EventLog) -> dict[str, object]:
    out: dict[str, object] = {}
    for e in log.iter_all():
        if e.kind != "confirm":
            continue
        p = e.payload or {}
        if p.get("v") != "confirm" or not p.get("shape"):
            continue
        key = e.target.key
        if not key:
            continue
        cur = out.get(key)
        if cur is None or (e.ts or "") >= (cur.ts or ""):
            out[key] = e
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    log = EventLog()
    latest = latest_confirms(log)
    c = sqlite3.connect(a.db)
    shape_of = {r[0]: r[1] for r in c.execute(
        "SELECT e.instance_id, g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id")}
    read_of = {r[0]: (r[1], r[2]) for r in c.execute("SELECT instance_id, char, provenance FROM admissions")}
    c.close()

    todo = []
    for key, e in latest.items():
        iid = "v2:" + key
        if iid not in read_of:
            continue                      # 从没进过库：消费者会正常处理，不归这里管
        p = e.payload
        shape = p["shape"]
        reading = p.get("reading") or shape
        if len(reading) != 1 or ord(reading) < 0x2E80:
            reading = shape               # 拼音首字母那类脏释读
        if shape not in SPLIT:
            reading = shape               # 只有 己已巳 分字形/文意；旧组视图 bug 留下的「卽 读 即」不算数
        db_shape, (db_read, prov) = shape_of.get(iid), read_of[iid]
        if db_shape == shape and db_read == reading:
            continue
        todo.append((iid, db_shape, db_read, prov, shape, reading, e))
    print(f"人裁字位 {len(latest)}，库里有 {sum(1 for k in latest if 'v2:' + k in read_of)}，"
          f"与最新人裁不一致 {len(todo)}")
    for iid, ds, dr, prov, s, r, e in todo[:20]:
        print(f"  {iid}: 库 形{ds}/读{dr}({prov}) → 最新人裁 形{s}/读{r}  [{e.batch}]")
    if a.dry or not todo:
        return 0

    db = GlyphDB(a.db)
    receipts = []
    for iid, ds, dr, prov, s, r, e in todo:
        orig = evict_instance(db, iid)
        receipts.append({"instance_id": iid, "char": orig or dr, "human_shape": s, "human_reading": r,
                         "reason": "human_rejudged_blocked_by_idempotency",
                         "superseded_by": e.id, "batch": e.batch,
                         "note": f"库里 形{ds}/读{dr}（{prov}），最新人裁 形{s}/读{r}；幂等闸挡住了改判，撤旧重放",
                         "evicted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    res = glyphdb_admit([(_Normalized(e, r), None) for _iid, _ds, _dr, _pv, _s, r, e in todo], db_path=a.db)
    print(f"重放：added {res.added} skipped {res.skipped} errors {len(res.errors)}")
    for x in res.errors[:10]:
        print("   ", x)
    with open(REPO / "output" / "mislabel_evictions.jsonl", "a", encoding="utf-8") as f:
        for rec in receipts:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 复核
    c = sqlite3.connect(a.db)
    shape_of = {r[0]: r[1] for r in c.execute(
        "SELECT e.instance_id, g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id")}
    read_of = {r[0]: r[1] for r in c.execute("SELECT instance_id, char FROM admissions")}
    still = [(iid, shape_of.get(iid), read_of.get(iid), s, r) for iid, *_x, s, r, _e in todo
             if shape_of.get(iid) != s or read_of.get(iid) != r]
    print(f"复核：仍不一致 {len(still)} {still[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
