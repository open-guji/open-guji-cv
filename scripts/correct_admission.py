"""改判已入库的人裁字位——不是重新裁决图块，是纠正之前的判据。

起因（用户 2026-08-26 定）：已/巳 这类字对，古代刻工本就不分（详见
`.claude/doc/charset_and_lm.md` §四考据），字形上「封不封口」不是可靠
判据。此前有几条人裁按字形（照着刻本封口与否）判成了「巳」，但按现代
用法（除干支纪年纪日/专名外一律用「已」）看，上下文文意明明白白是
「已经」——这是本末倒置，字形不该赢过文意。用户裁定：**以后一律以
上下文文意为准，不以字形为准**，并要求把此前判错的改回来。

`admit_instance()` 是幂等的（同一 instance_id 第二次调用直接返回
False）——那是防重复入库的闸，不是改判入口。已入库的字位要纠正，
必须显式改这四张表：`instances.label/semantic/unicode_cp`（真源）、
`admissions.char`（审计行，旧判据保留在 evidence 里，不是删掉重写）、
`glyphs.n_confirmed`（旧字减一、新字加一，各自按 K_MIN 重算 status）、
`exemplars`（旧字形下的示例挪到新字形下）。derived（norm/skeleton/feat）
不动——图块本身没变，变的只是贴的标签。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

K_MIN = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def correct_one(cur: sqlite3.Cursor, instance_id: str, new_char: str,
                reason: str, dry_run: bool) -> dict:
    row = cur.execute(
        "SELECT char, provenance, evidence FROM admissions WHERE instance_id=?",
        (instance_id,)).fetchone()
    if row is None:
        return {"instance_id": instance_id, "skipped": "not_admitted"}
    old_char, provenance, evidence_raw = row
    if old_char == new_char:
        return {"instance_id": instance_id, "skipped": "already_correct"}

    source_id = instance_id.split(":")[0]
    edition = cur.execute(
        "SELECT edition_tag FROM sources WHERE source_id=?",
        (source_id,)).fetchone()[0]

    if dry_run:
        return {"instance_id": instance_id, "old": old_char,
                "new": new_char, "would_correct": True}

    now = _now()
    old_evidence = json.loads(evidence_raw) if evidence_raw else None
    new_evidence = {"correction": {"old_char": old_char, "new_char": new_char,
                                   "reason": reason, "corrected_at": now,
                                   "corrected_by": "human:modern_usage_policy"},
                    "original_evidence": old_evidence}
    cp = ord(new_char) if len(new_char) == 1 else None

    cur.execute(
        "UPDATE instances SET label=?, semantic=?, unicode_cp=?, updated_at=?"
        " WHERE instance_id=?", (new_char, new_char, cp, now, instance_id))
    cur.execute(
        "UPDATE admissions SET char=?, evidence=?, admitted_at=?"
        " WHERE instance_id=?",
        (new_char, json.dumps(new_evidence, ensure_ascii=False), now,
         instance_id))

    old_gid = cur.execute(
        "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
        (edition, old_char)).fetchone()
    if old_gid:
        old_gid = old_gid[0]
        cur.execute("DELETE FROM exemplars WHERE glyph_id=? AND instance_id=?",
                    (old_gid, instance_id))
        cur.execute(
            "UPDATE glyphs SET n_confirmed = n_confirmed - 1, updated_at=?"
            " WHERE glyph_id=?", (now, old_gid))
        n = cur.execute("SELECT n_confirmed FROM glyphs WHERE glyph_id=?",
                        (old_gid,)).fetchone()[0]
        if n < K_MIN:
            cur.execute("UPDATE glyphs SET status='sparse' WHERE glyph_id=?",
                        (old_gid,))

    cur.execute(
        """INSERT INTO glyphs (edition_tag, char, semantic, unicode_cp, ids,
             status, n_confirmed, updated_at)
           VALUES (?,?,?,?,NULL,'sparse',1,?)
           ON CONFLICT(edition_tag, char) DO UPDATE SET
             n_confirmed = n_confirmed + 1,
             status = CASE WHEN n_confirmed + 1 >= {} THEN 'stable' ELSE status END,
             updated_at = excluded.updated_at""".format(K_MIN),
        (edition, new_char, new_char, cp, now))
    new_gid = cur.execute(
        "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
        (edition, new_char)).fetchone()[0]
    cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                (new_gid, instance_id, "seed", now))

    return {"instance_id": instance_id, "old": old_char, "new": new_char,
            "corrected": True}


def main() -> None:
    ap = argparse.ArgumentParser(description="改判已入库的人裁字位")
    ap.add_argument("db")
    ap.add_argument("--queue", required=True,
                    help="phase9_seed/queue.jsonl，同步改 decided_char")
    ap.add_argument("--corrections", required=True,
                    help="JSON 数组：[{instance_id, new_char, reason}, …]")
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
