# -*- coding: utf-8 -*-
"""`v2:vol03:7:8:17`：人裁历史回放判"日"，目视核对（+ align_ref 独立证据）应为"曰"——改字命令。

    GUJI_GLYPH_DB=<glyph.db> GUJI_FEEDBACK_DIR=<workspace>/feedback \
        PYTHONPATH=. python research/scripts_oneoff/relabel_vol03_7_8_17.py [--apply]

默认（不带 `--apply`）：只打印当前库里这条实例记的字 + 写一条 `glyph_audit`
`relabel` 事件（留痕，不改库）+ 过一遍 `dry_run=True` 的路由。

带 `--apply`：真的改字——`glyph_audit` 消费者的 `relabel` 分支撤掉旧的
`instance_id` 记录，同一张图以人裁身份重新按新字入库（`provenance="human"`），
`page`/`col`/`idx`/`bbox` 原样保留，只换字。

## 目视核对记录（任务书 H·人裁绑定核查三件 §2，2026-09-27）

- 用当前 vol03 云端快照（`cloud-20260927-4e2e0b7-iron`，snapshot `code_rev=4e2e0b7d`）
  在沙箱重算 `p0007c08s17` 的字块图，与库里冻结的 `v2_vol03_7_8_17.png`（2026-09-10 人裁）
  逐像素比对，`verify_pair_elastic` cov=0.9998——**这一格没有漂移**，人裁绑定的格位现在还是
  这一格，问题是当初判错了字。
- 图上：外框内部横笔右端与外框之间有明显缺口（不完全封闭），是「曰」的典型写法；「日」应该
  横笔两端都接满边框。整理 Z14《放行错穷举-v0》独立用 `v2_align`（Step9 整理本对齐参照本，
  与这条历史人裁绑定回放完全独立的证据源）核对同一格，`shape`（整理本判的刻本形）也是「曰」，
  两条独立证据一致，不是单人目视的主观判断。
- 历史人裁绑定回放（`seed_admit.py` 复用字形库里已验证实例的机制）本身没有二次校验，这条应该是
  当初这份刻例本身被判错了字（不是格位挂错——同一物理格从 2026-09-10 到现在都是这个「曰」字）。

结论：改「曰」。若核对后判断不是「曰」，**不要跑 `--apply`**，把结论写回 ask 单即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from open_guji_cv.feedback.consumers import route_and_consume  # noqa: E402
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event  # noqa: E402

TARGET_IID = "v2:vol03:7:8:17"
OLD_CHAR = "日"
NEW_CHAR = "曰"
BATCH = "vol03-7-8-17-relabel-20260927"


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
    apply = "--apply" in sys.argv

    print("== 改字前预览 ==")
    _preview()

    log = EventLog()
    ev = make_event(BATCH, 1, "glyph_audit",
                    EventTarget(step="seed_admit", unit="cell", key=TARGET_IID, book="vol03"),
                    {"v": "relabel", "instance_id": TARGET_IID, "char": NEW_CHAR,
                     "note": f"7:8:17 目视核对 + align_ref 独立交叉：外框内横笔右端有缺口，"
                             f"是「曰」的典型写法；历史人裁绑定回放当初判成 {OLD_CHAR!r} 是判错，"
                             f"不是挂错格（沙箱重算 cov=0.9998，格位没漂移），改 {NEW_CHAR!r}"})
    n = log.append([ev])
    print(f"\n== 事件已写入（{n} 条新增）：{log.batch_path(BATCH)} ==")

    res = route_and_consume(log, BATCH, dry_run=not apply)
    for r in res["results"]:
        print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    if not apply:
        print("\n（这是 dry-run：glyph.db 还没有改。确认无误后加 --apply 真的改字。）")
    else:
        print("\n== 改字后复核 ==")
        _preview()


if __name__ == "__main__":
    main()
