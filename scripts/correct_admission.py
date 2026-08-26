"""改判已入库人裁字位的**释读**——不碰字形，不是重新裁决图块。

起因（用户 2026-08-26 定）：已/巳/己 这类字，古代刻工本就不分（详见
`.claude/doc/charset_and_lm.md` §四考据）。校对古籍的默认规矩是「字形
是什么我们就录什么」（diplomatic transcription，绝不因为「觉得该是
别的字」就改字形）——但这三个字是**唯一的例外**：字形上「封不封口」
不是可靠判据，古人自己都不当回事，所以只在这三个字上改按上下文文意
判**释读**，字形照录不动。

**字形（shape）与释读（reading）是两件事，别用同一个字段改：**

* `instances.label` / `glyphs` / `exemplars` / `GlyphMatcher` 索引
  ——**字形层**，按刻本实际刻的形状分类，供未来实例做形状匹配用。
  这三个字的字形照样互相长得像，字形层的 near_form 护栏本来就该继续
  拦——如果这里也被改成释读，未来一个真的刻成同一形状、该读别的字
  的实例会错误继承这次的释读，字形匹配整个失真。
* `instances.semantic` / `admissions.char` ——**释读层**，「这个字位
  说的是什么」，本脚本改的就是这个。

`admit_instance()` 是幂等的（同一 instance_id 第二次调用直接返回
False）——那是防重复入库的闸，不是改判入口。已入库的字位要纠正释读，
只碰 `instances.semantic` 与 `admissions.char` 这两处；`label` /
`glyphs` / `exemplars` / `unicode_cp`（字形层）与 `derived`（图块的
纯函数，图块没变）一律不动。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def correct_one(cur: sqlite3.Cursor, instance_id: str, new_reading: str,
                reason: str, dry_run: bool) -> dict:
    row = cur.execute(
        "SELECT char, evidence FROM admissions WHERE instance_id=?",
        (instance_id,)).fetchone()
    if row is None:
        return {"instance_id": instance_id, "skipped": "not_admitted"}
    old_reading, evidence_raw = row
    if old_reading == new_reading:
        return {"instance_id": instance_id, "skipped": "already_correct"}

    if dry_run:
        return {"instance_id": instance_id, "old": old_reading,
                "new": new_reading, "would_correct": True}

    now = _now()
    old_evidence = json.loads(evidence_raw) if evidence_raw else None
    new_evidence = {"correction": {"old_reading": old_reading,
                                   "new_reading": new_reading,
                                   "reason": reason, "corrected_at": now,
                                   "corrected_by": "human:modern_usage_policy",
                                   "note": "只改释读，字形层（label/glyphs/"
                                           "exemplars）未动"},
                    "original_evidence": old_evidence}

    # 释读只在 instances.semantic 与 admissions.char 两处——字形层
    # （label/glyphs/exemplars/unicode_cp）保持刻本实际形状不变
    cur.execute(
        "UPDATE instances SET semantic=?, updated_at=? WHERE instance_id=?",
        (new_reading, now, instance_id))
    cur.execute(
        "UPDATE admissions SET char=?, evidence=?, admitted_at=?"
        " WHERE instance_id=?",
        (new_reading, json.dumps(new_evidence, ensure_ascii=False), now,
         instance_id))

    return {"instance_id": instance_id, "old": old_reading,
            "new": new_reading, "corrected": True}


def main() -> None:
    ap = argparse.ArgumentParser(description="改判已入库人裁字位的释读（不碰字形）")
    ap.add_argument("db")
    ap.add_argument("--queue", required=True,
                    help="phase9_seed/queue.jsonl，同步改 decided_char"
                        "（队列里没有字形/释读之分，历来就是释读——展示"
                        "给人看的、进最终文本的就是这个）")
    ap.add_argument("--corrections", required=True,
                    help="JSON 数组：[{instance_id, new_char, reason}, …]"
                        "（new_char 是新释读，字段名沿用旧协议不动）")
    ap.add_argument("--apply", action="store_true", help="缺省只演练不落地")
    args = ap.parse_args()

    corrections = json.loads(Path(args.corrections).read_text(encoding="utf-8"))
    con = sqlite3.connect(args.db)
    cur = con.cursor()
    results = [correct_one(cur, c["instance_id"], c["new_char"], c["reason"],
                           dry_run=not args.apply) for c in corrections]
    if args.apply:
        con.commit()
    con.close()

    for r in results:
        print(r)

    if args.apply:
        # 队列同步不依赖「DB 里有没有这条准入」——not_admitted（人裁过
        # 但还没走入库批次）也要改，queue.jsonl 才是人裁决定的真源。
        # 只跳过 already_correct（无事可做）。
        by_id = {c["instance_id"]: c["new_char"] for c in corrections
                 if not any(x["instance_id"] == c["instance_id"] and
                           x.get("skipped") == "already_correct"
                           for x in results)}
        if by_id:
            lines = Path(args.queue).read_text(encoding="utf-8").splitlines()
            out = []
            n = 0
            for line in lines:
                row = json.loads(line)
                if row.get("instance_id") in by_id:
                    old = row.get("decided_char")
                    row["decided_char"] = by_id[row["instance_id"]]
                    row["note"] = (row.get("note") or "") + \
                        f";corrected:modern_usage_over_shape(was {old})"
                    n += 1
                out.append(json.dumps(row, ensure_ascii=False))
            Path(args.queue).write_text("\n".join(out) + "\n", encoding="utf-8")
            print(f"\n队列同步改判 {n} 行：{args.queue}")
    else:
        print("\n（演练模式，未落地。加 --apply 执行。）")


if __name__ == "__main__":
    main()
