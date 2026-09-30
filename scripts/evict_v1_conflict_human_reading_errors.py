# -*- coding: utf-8 -*-
"""v1 重键 `conflict_human` 里「v1 把字形记成了读法」的例子：撤 v1 实例（不动人裁）。

    GUJI_GLYPH_DB=<glyph.db> GUJI_FEEDBACK_DIR=<workspace>/feedback \
        PYTHONPATH=. python scripts/evict_v1_conflict_human_reading_errors.py <v1_map.jsonl> \
        [--book <书 id>] [--apply]

## 目标格怎么定（2026-09-27 改，任务书 H·v1重键与撤例按B后重定 §4）

不再写死 id 清单——**目标格按当前库现算**：对 `<v1_map.jsonl>`（`glyph_v1_map.py`
的形状对照表，与 `glyph_v1_rekey.py` 吃的是同一份）跑一遍
`glyph_v1_rekey.plan()`（`--book` 给了就把该书 `codepoints` 配置的同字异码位对
排除在外——那类不是「读错」，是「同字异码位」，该走 `glyph_v1_rekey.py --book`
重键落地，不该撤，见该脚本模块头），取当前的 `conflict_human` 列表：**剩下的
就是「v1 与人裁落在同一格、cov ≥0.999（同一块图），但记的字不一样，且按书级
码位也不是同一个字」——这唯一还剩的解释就是 v1 当年把字形认错了**（读音相近
被读成了另一个字，如 08 卡记的「應/代」被认成「卽/厯」那批）。人裁的字形是
现算的（`clustering.verify` 逐像素比对 ≥0.999），比 v1 的旧读法可信，所以撤 v1、
人裁不动。

之前那版写死 4 个 id（`148:5:18`/`148:5:8`/`148:6:11`/`5:7:7`）是给定一次
B 段挪绑之前的对位算的；B 段又把人裁往前挪了一格，写死的目标格全部失效
（撤不到东西、或者撤错格），所以改成每次现算。

## 预览 vs 落地（同一次改，修的是「预览会写真库」这个 bug）

默认（不带 `--apply`）：**只读——不碰 glyph.db，也不写 feedback 事件**。只打印
现算出来的 conflict_human 清单、每条现在库里记的字，供人核对。

带 `--apply`：这时才真的写 4 条 `glyph_audit` 事件（留痕，方便回看/重放），
再跑一次 `route_and_consume(dry_run=False)`，调 `clustering.audit.evict_instance`
删库（四表行 + 字头 `n_confirmed` 计数）。整段过 `feedback_write_lock`
（`route_and_consume` 自带），不用额外加锁。

**旧 bug**：改之前，预览模式也会调 `EventLog.append()` 真写一份
`feedback/events/<batch>.jsonl`（`route_and_consume(dry_run=True)` 本身不碰
glyph.db，但落盘的事件文件已经是真事件了，不是「预览」）。17:26Z 那次服务器跑
预览命令，意外往真 feedback 写出了 4 条事件（`inbox/…`「回执」记过，服务器值守
已把那份文件挪到隔离区，没被消费过）。现在预览分支直接不碰 `EventLog`，
`tests/test_evict_v1_conflict_human_reading_errors.py` 钉住这条。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BATCH_PREFIX = "v1-conflict-human-evict"


def _current_char(iid: str) -> str | None:
    """`instances` 没有 `glyph_id`/`pipeline_version` 列，字与版本要分别经
    `exemplars→glyphs`、`sources` 两条路径查（同 `clustering.audit.evict_instance`
    自己找 glyph_id 的路数）。找不到实例本身返回 None。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    exists = db.conn.execute("SELECT source_id FROM instances WHERE instance_id=?", (iid,)).fetchone()
    if exists is None:
        return None
    char_row = db.conn.execute(
        "SELECT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id "
        "WHERE e.instance_id=?", (iid,)).fetchone()
    return char_row[0] if char_row else None


def _conflict_human_targets(v1_map: Path, book_id: str | None) -> list[dict]:
    """现算 `glyph_v1_rekey.plan()` 的 `conflict_human`：`--book` 给了就先把该书
    `codepoints` 配置的同字异码位对排除（那类走 `glyph_v1_rekey.py --book` 重键，
    不归本脚本管），剩下的才是本脚本要撤的「读错」。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("glyph_v1_rekey", REPO / "scripts" / "glyph_v1_rekey.py")
    rekey = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rekey)

    from open_guji_cv.core.workspace import glyph_db_path

    book = None
    if book_id:
        from open_guji_cv.core.book import load_book
        book = load_book(book_id)
    rows = [json.loads(l) for l in open(v1_map, encoding="utf-8") if l.strip()]
    c = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    try:
        return rekey.plan(c, rows, book=book)["conflict_human"]
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("v1_map", type=Path, help="glyph_v1_map.py 的形状对照表（与 glyph_v1_rekey.py 同一份）")
    ap.add_argument("--book", help="书 id：排除该书 codepoints 配置里同字异码位那几对（不归本脚本撤）")
    ap.add_argument("--apply", action="store_true", help="真的撤库；不给只打印现算的目标，不写盘")
    a = ap.parse_args()

    targets = _conflict_human_targets(a.v1_map, a.book)
    print(f"== 现算 conflict_human：{len(targets)} 条（book={a.book!r}）==")
    for t in targets:
        cur = _current_char(t["v1"])
        print(f"目标格 {t['cell']}（v1 {t['v1']} 记 {t['v1_char']!r}，"
              f"人裁 {t['v2']} = {t['v2_char']!r}，cov={t['cov']}）：")
        if cur is None:
            print(f"  [!] 库里没有 {t['v1']}——已经撤过？或者不在这个工作区")
        else:
            print(f"  {t['v1']}  库里记的字={cur!r}")

    if not targets:
        print("\n没有要撤的目标，什么都不做。")
        return 0

    if not a.apply:
        print(f"\n（这是预览：不碰 glyph.db，也没写 feedback 事件。确认无误后加 --apply 真的撤库。）")
        return 0

    from open_guji_cv.feedback.consumers import route_and_consume
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

    batch = f"{BATCH_PREFIX}-{targets[0]['v1'].split(':')[0]}"
    log = EventLog()
    base = log.latest_seq(batch)
    evs = [make_event(batch, base + i, "glyph_audit",
                      EventTarget(step="seed_admit", unit="cell", key=t["v1"],
                                 book=t["v1"].split(":")[0]),
                      {"v": "evict", "target": t["v1"],
                       "note": f"v1 重键 conflict_human：v1 记 {t['v1_char']!r}，实为 {t['v2_char']!r}"
                               f"（cov {t['cov']}），撤 v1 不动人裁"})
           for i, t in enumerate(targets, 1)]
    n = log.append(evs)
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(batch)} ==")

    res = route_and_consume(log, batch, dry_run=False)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    print("\n== 撤库后复核 ==")
    for t in targets:
        cur = _current_char(t["v1"])
        print(f"  {t['v1']}  库里记的字={cur!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
