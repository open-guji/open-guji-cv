# -*- coding: utf-8 -*-
"""v1 重键 `conflict_human` 里「v1 把字形记成了读法」的 4 例：撤 v1 实例（不动人裁）。

    GUJI_GLYPH_DB=<glyph.db> GUJI_FEEDBACK_DIR=<workspace>/feedback \
        PYTHONPATH=. python scripts/evict_v1_conflict_human_reading_errors.py [--apply]

默认（不带 `--apply`）：只读——打印这 4 个 v1 实例现在库里记的字，再把 4 条
`glyph_audit` 事件写进事件日志（**这一步本身不改 glyph.db**，只是留痕，方便回看/
重放），然后用 `dry_run=True` 过一遍路由（`glyph_audit` 消费者的 dry-run 分支只
数条数、不查库，真正的存在性检查在下面的只读 SELECT 里做过了）。

带 `--apply`：再跑一次 `route_and_consume(dry_run=False)`，这才真的调
`clustering.audit.evict_instance` 删库（四表行 + 字头 `n_confirmed` 计数）。
整段过 `feedback_write_lock`（`route_and_consume` 自带），不用额外加锁。

## 这 4 例是什么（任务书 附·v1 重键的收尾，2026-09-27）

来自 `artifacts/glyph_v1_rekey/siku_vol01_sandbox_report.json` 的 `conflict_human`
（沙箱 dry-run，服务器 `20260927-1355-ask-§三` 已确认与此逐项一致）：v1 与人裁
`v2:` 落在同一个格（cov ≥ 0.999，两者是同一块图），但 v1 记的字（读音）跟 v2
人裁的实际字形不一样——两组都是「即/卽」「歷/厯」这类**形近字被 OCR 按读音
认成了另一个字**，用户裁定（H-字形库下一步 0010-reply 第 1 条）：这 4 例撤 v1、
人裁不动。**同一批 `conflict_human` 里另外 3 例本脚本不管**：`52:6:2`（代→八）、
`63:7:6`（林→占）两例不是「读音混淆」这个模式，处置留给协调者另定；`53:2:16`
（禮→奉）不在 v1 重键的漂移名单里（现格字块本来就像这份刻例），任务书交代的
是「找回那份人裁'奉'真正的格」，跟撤库是另一件事，本脚本不碰。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.feedback.consumers import route_and_consume  # noqa: E402
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event  # noqa: E402

#: (v1 实例 id, v1 记的字, 目标格, 目标格人裁 v2 id, v2 实际字, cov)
#: 摘自 siku_vol01_sandbox_report.json::conflict_human，逐字段核对过。
TARGETS = [
    ("vol01:148:5:18", "應", "vol01:148:5:19", "v2:vol01:148:5:19", "卽", 0.9993),
    ("vol01:148:5:8", "代", "vol01:148:5:9", "v2:vol01:148:5:9", "厯", 0.9996),
    ("vol01:148:6:11", "應", "vol01:148:6:12", "v2:vol01:148:6:12", "卽", 0.9995),
    ("vol01:5:7:7", "代", "vol01:5:7:8", "v2:vol01:5:7:8", "厯", 0.9994),
]

BATCH = "vol01-v1-conflict-human-evict-20260927"


def _preview(iid: str) -> None:
    """`instances` 没有 `glyph_id`/`pipeline_version` 列，字与版本要分别经
    `exemplars→glyphs`、`sources` 两条路径查（同 `clustering.audit.evict_instance`
    自己找 glyph_id 的路数，在沙箱合成库上核实过这条查询）。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    exists = db.conn.execute("SELECT source_id FROM instances WHERE instance_id=?", (iid,)).fetchone()
    if exists is None:
        print(f"  [!] 库里没有 {iid}——已经撤过？或者不在这个工作区")
        return
    char_row = db.conn.execute(
        "SELECT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id "
        "WHERE e.instance_id=?", (iid,)).fetchone()
    src_row = db.conn.execute(
        "SELECT s.pipeline_version FROM sources s WHERE s.source_id=?", (exists[0],)).fetchone()
    char = char_row[0] if char_row else "（没有 exemplars 行，可能已不在任何字头下）"
    ver = src_row[0] if src_row else exists[0]
    print(f"  {iid}  库里记的字={char!r}  pipeline_version={ver!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的撤库；不给只写事件+过一遍 dry-run 路由")
    a = ap.parse_args()

    print("== 撤库前 SELECT 预览（真正的存在性检查，glyph_audit 的 dry-run 分支不做这个）==")
    for iid, v1_char, cell, v2_id, v2_char, cov in TARGETS:
        print(f"目标格 {cell}（人裁 {v2_id} = {v2_char!r}，cov={cov}）：")
        _preview(iid)

    log = EventLog()
    evs = [make_event(BATCH, i, "glyph_audit",
                      EventTarget(step="seed_admit", unit="cell", key=iid, book="vol01"),
                      {"v": "evict", "target": iid,
                       "note": f"v1 重键 conflict_human：v1 记读音 {v1_char!r}，实为 {v2_char!r}（cov {cov}），撤 v1 不动人裁"})
           for i, (iid, v1_char, cell, v2_id, v2_char, cov) in enumerate(TARGETS, 1)]
    n = log.append(evs)
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(BATCH)} ==")

    res = route_and_consume(log, BATCH, dry_run=not a.apply)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    if not a.apply:
        print("\n（这是 dry-run：glyph.db 还没有改。确认无误后加 --apply 真的撤库。）")
    else:
        print("\n== 撤库后复核 ==")
        for iid, *_ in TARGETS:
            _preview(iid)


if __name__ == "__main__":
    main()
