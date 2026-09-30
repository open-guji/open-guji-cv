# -*- coding: utf-8 -*-
"""`v2:vol01:48:2:-1`：库里存的字是「王」，目视核对后应为「聖」——改字命令。

    GUJI_GLYPH_DB=<glyph.db> GUJI_FEEDBACK_DIR=<workspace>/feedback \
        PYTHONPATH=. python scripts/relabel_vol01_48_2_neg1.py [--apply]

默认（不带 `--apply`）：只打印当前库里这条实例记的字 + 写一条 `glyph_audit`
`relabel` 事件（留痕，不改库）+ 过一遍 `dry_run=True` 的路由（同上，glyph_audit
的 dry-run 分支不做存在性检查，前面的 SELECT 已经做过）。

带 `--apply`：真的改字——`glyph_audit` 消费者的 `relabel` 分支会撤掉旧的
`instance_id` 记录，同一张图（原 `patch_png`）以人裁身份重新按新字入库
（`provenance="human"`），`page`/`col`/`idx`/`bbox` 都原样保留，只换字。

## 目视核对记录（任务书 附·v1 重键的收尾，2026-09-27）

- `output/glyph_store/patches/v2_vol01_48_2_-1.png`（库里现在的样子）：只有下半
  「王」形三横一竖，裁得很紧——像是被切了顶部。
- `output/glyph_store/patches/vol01_48_2_0.png`（同页同列紧邻的下一格，v1 来源，
  OCR/align 都判「聖」）：完整的「聖」字（耳＋口＋王），比对下来 `-1` 那张图的
  「王」形笔画位置与「聖」字下半部分（王）吻合——`-1` 这一格大概率是「聖」被
  切分算法误切出来的下半截（抬头列常见：`聖` 作抬头字，`idx=-1` 这种负数格号
  正是抬头/页边格的编号方式，见 `products/kinds/rows.py` 字格类型），不是独立
  的「王」字。**这是目视比对，不是像素级配准**——落库前请再看一眼两张原图。

结论：改「聖」。若核对后判断不是「聖」（比如确认是两个不同物理格、`-1` 那格
真的独立成字），**不要跑 `--apply`**，把结论写回 ask 单即可。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.feedback.consumers import route_and_consume  # noqa: E402
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event  # noqa: E402

TARGET_IID = "v2:vol01:48:2:-1"
OLD_CHAR = "王"
NEW_CHAR = "聖"
BATCH = "vol01-48-2-neg1-relabel-20260927"


def _preview() -> None:
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    exists = db.conn.execute("SELECT source_id FROM instances WHERE instance_id=?", (TARGET_IID,)).fetchone()
    if exists is None:
        print(f"  [!] 库里没有 {TARGET_IID}——已经改过？或者不在这个工作区")
        return
    char_row = db.conn.execute(
        "SELECT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id "
        "WHERE e.instance_id=?", (TARGET_IID,)).fetchone()
    char = char_row[0] if char_row else "（没有 exemplars 行）"
    print(f"  {TARGET_IID}  库里记的字={char!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的改字；不给只写事件+过一遍 dry-run 路由")
    a = ap.parse_args()

    print("== 改字前预览 ==")
    _preview()

    log = EventLog()
    ev = make_event(BATCH, 1, "glyph_audit",
                    EventTarget(step="seed_admit", unit="cell", key=TARGET_IID, book="vol01"),
                    {"v": "relabel", "instance_id": TARGET_IID, "char": NEW_CHAR,
                     "note": f"48:2:-1 目视核对：紧邻 vol01:48:2:0（v1，聖）下半部分吻合，"
                             f"原记 {OLD_CHAR!r} 疑似切分误切出的半截字，改 {NEW_CHAR!r}"})
    n = log.append([ev])
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(BATCH)} ==")

    res = route_and_consume(log, BATCH, dry_run=not a.apply)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    if not a.apply:
        print("\n（这是 dry-run：glyph.db 还没有改。确认无误后加 --apply 真的改字。）")
    else:
        print("\n== 改字后复核 ==")
        _preview()


if __name__ == "__main__":
    main()
