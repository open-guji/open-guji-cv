# -*- coding: utf-8 -*-
"""`v2:vol01:48:2:-1`（"王"）—— 撤库，不改标。

    GUJI_GLYPH_DB=<glyph.db> GUJI_FEEDBACK_DIR=<workspace>/feedback \
        PYTHONPATH=. python scripts/evict_vol01_48_2_neg1.py [--apply]

## 为什么是撤，不是改标（推翻 `scripts/relabel_vol01_48_2_neg1.py` 的方案）

`relabel_vol01_48_2_neg1.py`（H-border_class 那道，2026-09-27）只凭目视比对两张
库里的静态图，判定 `-1` 这格是"聖"被切分误切出的下半截，主张改标"聖"。

本轮（H-A类漂移九条任务书）用云端真实重跑快照 `products-snap/vol01-20260927-54d08d3`
在沙箱里现算了**当前** `row_segment` 产物的第 48 页第 2 列实际字格列表：

```
col=2 ok=True n_body_slots=21 n_raised=0
slot 1..21 全部 kind=char，没有 slot 0，没有 slot -1，没有任何 raised 格
```

也就是说，**当前管线的这一列压根不产生 slot=-1 或 slot=0 这两个位置**（无论是
不是抬头格）——`v2:vol01:48:2:-1` 这条人裁记录对应的物理格早就不存在了，
`vol01:48:2:0`（v1 来源，"聖"）同样查无此格（`instances` 表里还有这一行，但
它也是同一批孤儿记录，不在本任务书范围内，留给 v1 重键那条线处理，见「下一道
要知道的」）。

在同页 col 1/2/3 的全部 21×3 现有字格里搜索（`verify_pair_elastic` 弹性覆盖率），
"王"这张图与任何现存字格的最高 cov 只有 0.8723（`vol01:48:1:3`）——远低于
`glyph_rekey_drift.py` 用的挪格阈值 0.92，说明这不是"挪一格就能找回"的普通漂移，
而是这一格本身已经不在当前切分结果里了。**改标不能解决"挂在一个不存在的格
上"这件事**——`v2:vol01:48:2:-1` 的 `page/col/idx=(48,2,-1)` 无论标成"王"还是"聖"，
都不会指向任何一个现在真实存在的字位，留着只会在字头"聖"或"王"下面挂一条
死引用。应该撤库：这份刻例（图像本身没有问题）如果将来想保留，可以在真正的
"聖"所在格（现在的 `vol01:48:2:1`，需要人核对是不是这个字）上由人裁重新定字，
但那是另一件事，不在本任务书范围内（本任务书铁律 2：不碰库，只写命令）。

## 命令做什么

同 `evict_v1_conflict_human_reading_errors.py` 的写法：`glyph_audit` 事件
（`v="evict"`）→ `route_and_consume`；默认 dry-run 只留痕不改库，`--apply`
才真的调 `clustering.audit.evict_instance` 删四表行。

**沙箱验证**（`/tmp` 下临时 `glyph.db` 拷贝 + 沙箱 `feedback/` 拷贝，`rebuild_from_store`
只读真实 `glyph_store/`）：dry-run 与 `--apply` 全流程跑通，`--apply` 后
`v2:vol01:48:2:-1` 从四表清空、字头"王"的 `n_confirmed` 相应减一。**从未碰真库、
真 feedback**。
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
BATCH = "vol01-48-2-neg1-evict-20260927"


def _preview() -> None:
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    exists = db.conn.execute("SELECT source_id FROM instances WHERE instance_id=?", (TARGET_IID,)).fetchone()
    if exists is None:
        print(f"  [!] 库里没有 {TARGET_IID}——已经撤过？或者不在这个工作区")
        return
    char_row = db.conn.execute(
        "SELECT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id "
        "WHERE e.instance_id=?", (TARGET_IID,)).fetchone()
    char = char_row[0] if char_row else "（没有 exemplars 行）"
    print(f"  {TARGET_IID}  库里记的字={char!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的撤库；不给只写事件+过一遍 dry-run 路由")
    a = ap.parse_args()

    print("== 撤库前预览 ==")
    _preview()

    log = EventLog()
    ev = make_event(BATCH, 1, "glyph_audit",
                    EventTarget(step="seed_admit", unit="cell", key=TARGET_IID, book="vol01"),
                    {"v": "evict", "target": TARGET_IID,
                     "note": "48:2:-1 现在的 row_segment（vol01-20260927-54d08d3 快照）里 col2 "
                             "只有 slot 1..21，没有 slot -1/0：这格已不对应任何现存字位，同列邻近"
                             "21x3 格里最高 cov 只有 0.8723（<0.92 挪格阈值），不是普通漂移，撤库"
                             "而非改标（推翻同页 relabel_vol01_48_2_neg1.py 的改标方案）"})
    n = log.append([ev])
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(BATCH)} ==")

    res = route_and_consume(log, BATCH, dry_run=not a.apply)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    if not a.apply:
        print("\n（这是 dry-run：glyph.db 还没有改。确认无误后加 --apply 真的撤库。）")
    else:
        print("\n== 撤库后复核 ==")
        _preview()


if __name__ == "__main__":
    main()
