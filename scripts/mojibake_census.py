#!/usr/bin/env python3
"""H 道乱码普查（2026-09-27）：全库扫 `feedback/events/*.jsonl`，找出 `shape`／
`reading`／`char` 字段长度 ≠ 1 且不是合法多码位（IDS 串／PUA+选择符）的记录，
按事件文件、字段、条数出表；对能机械还原的给出还原字，出不了的归"需人判"。

用法：
    .venv/bin/python scripts/mojibake_census.py <feedback_root> [<feedback_root> ...]
    .venv/bin/python scripts/mojibake_census.py --write-fixes <feedback_root> --book vol01 --out-batch <batch名>

`--write-fixes` 需要同时给 `--book`：只对可还原的记录、且 target.book==该 book
的，追加一条同格 `confirm` 更正事件（`reason=mojibake_fix_20260916`），走
`EventLog.append()`（同一把写锁），不改写旧行。默认只普查、不写（dry-run）。

这是**诊断/修复脚本**，不是 `open_guji_cv` 包的一部分——旧行不动、新增的更正
事件走正常写入口（含字段合法性校验），不会因为这个脚本本身而绕过闸门。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from open_guji_cv.feedback.mojibake import classify_shape_field, is_legal_shape, unmojibake  # noqa: E402

FIELDS = ("shape", "reading", "char")


def scan_root(root: Path) -> list[dict]:
    """扫一个 book 的 `feedback/events/` 目录，返回每条命中记录的明细。"""
    events_dir = root / "events"
    if not events_dir.exists():
        return []
    out = []
    for path in sorted(events_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = ev.get("payload") or {}
                for field in FIELDS:
                    val = payload.get(field)
                    if val is None or is_legal_shape(val):
                        continue
                    cls = classify_shape_field(val)
                    fixed = unmojibake(val) if cls == "recoverable" else None
                    out.append({
                        "file": path.name,
                        "lineno": lineno,
                        "event_id": ev.get("id"),
                        "batch": ev.get("batch"),
                        "seq": ev.get("seq"),
                        "ts": ev.get("ts"),
                        "target_key": (ev.get("target") or {}).get("key"),
                        "book": (ev.get("target") or {}).get("book"),
                        "field": field,
                        "raw": val,
                        "class": cls,
                        "fixed": fixed,
                    })
    return out


def summarize(rows: list[dict]) -> None:
    by_file = defaultdict(lambda: defaultdict(int))
    by_class = defaultdict(int)
    for r in rows:
        by_file[r["file"]][r["field"]] += 1
        by_class[r["class"]] += 1
    print(f"\n共命中 {len(rows)} 条（legal 不计入，本表只列不合格记录）")
    print(f"  可还原 recoverable: {by_class['recoverable']}")
    print(f"  需人判 needs_human: {by_class['needs_human']}")
    print("\n按文件×字段：")
    for fn in sorted(by_file):
        parts = ", ".join(f"{f}={n}" for f, n in sorted(by_file[fn].items()))
        print(f"  {fn}: {parts}")


def write_fixes(root: Path, rows: list[dict], batch: str, dry_run: bool) -> list[str]:
    """对 `recoverable` 记录，每个 target_key 只追加**一条**同格更正事件（取该 key
    最新一条乱码事件的还原值即可——后到覆盖语义下，一条更正事件就能压过之前
    同 key 的所有旧事件，不需要逐条对应）。

    **先核对"最终生效的那条是不是乱码"**：如果同一 key 之后已经有一条合法的
    confirm 事件（人重新裁过），乱码那条早就不是"生效值"了，不用再修——
    但仍旧检查一遍，不假设普查到的就是最终态（普查只看单条记录合不合法）。
    """
    sys.path.insert(0, str(REPO_ROOT))
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

    log = EventLog(root=root)
    evs_by_key: dict[str, list] = {}
    for e in sorted(log.iter_all(), key=lambda e: (e.ts, e.batch, e.seq)):
        if e.kind == "confirm" and e.target.unit == "cell":
            evs_by_key.setdefault(e.target.key, []).append(e)

    recoverable = [r for r in rows if r["class"] == "recoverable"]
    by_key: dict[str, dict] = {}
    for r in recoverable:
        by_key[r["target_key"]] = r          # 同 key 多条，后面的覆盖前面的（与事件重放语义一致）

    to_fix = []
    skipped_already_ok = []
    for key, r in sorted(by_key.items()):
        kevs = evs_by_key.get(key, [])
        if not kevs:
            print(f"  跳过 {key}：找不到原事件（普查与重放对不上，需要人看）")
            continue
        final = kevs[-1]
        p = final.payload or {}
        sh = p.get("shape")
        from open_guji_cv.feedback.mojibake import is_legal_shape
        if sh is None or is_legal_shape(sh):
            skipped_already_ok.append(key)
            continue
        to_fix.append((r, final))

    print(f"\n待追加更正事件 {len(to_fix)} 条（已经合法/无需修的 {len(skipped_already_ok)} 条跳过）")
    if dry_run:
        for r, final in to_fix:
            print(f"  [dry-run] {r['target_key']}: {r['raw']!r} -> {r['fixed']!r}"
                  f"（原事件 {final.id}, book={r['book']}）")
        return [r["target_key"] for r, _ in to_fix]

    base = log.latest_seq(batch)
    new_events = []
    for i, (r, final) in enumerate(to_fix, 1):
        new_events.append(make_event(
            batch, base + i, "confirm",
            EventTarget(step="H_mojibake_fix", unit="cell", key=r["target_key"],
                        book=final.target.book, page=final.target.page,
                        col=final.target.col, slot=final.target.slot),
            {"v": "confirm", "shape": r["fixed"], "no_glyph_lib": False,
             "reason": "mojibake_fix_20260916",
             "note": f"UTF-8 被按 cp1252/latin-1 误解码再存盘的乱码机械还原："
                     f"{r['raw']!r} -> {r['fixed']!r}（原事件 {final.id}，"
                     f"P cross 1717／H 任务书-人裁事件乱码修复）"},
            actor="model", source_format="server"))
    n = log.append(new_events)
    print(f"  已追加 {n} 条更正事件到 {log.batch_path(batch)}")
    return [r["target_key"] for r, _ in to_fix]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", type=Path, help="每本书的 feedback/ 目录（含 events/ 子目录）")
    ap.add_argument("--json-out", type=Path, help="把全部命中记录写成 jsonl（供后续脚本/spot-check 用）")
    ap.add_argument("--write-fixes", action="store_true",
                    help="对可还原记录追加更正事件（默认只普查/dry-run，配合本参数真的写）")
    ap.add_argument("--fix-batch", default="H-mojibake-fix-20260927",
                    help="更正事件写进哪个批次（--write-fixes 时用）")
    ap.add_argument("--apply", action="store_true",
                    help="真的落盘（不给就是 dry-run，只打印会写什么）")
    args = ap.parse_args()

    all_rows: list[dict] = []
    for root in args.roots:
        rows = scan_root(root)
        print(f"\n=== {root} ===")
        summarize(rows)
        all_rows.extend(rows)
        if args.write_fixes:
            write_fixes(root, rows, args.fix_batch, dry_run=not args.apply)

    print(f"\n\n=== 全库合计 {len(all_rows)} 条 ===")
    by_class = defaultdict(int)
    for r in all_rows:
        by_class[r["class"]] += 1
    print(f"  可还原 recoverable: {by_class['recoverable']}")
    print(f"  需人判 needs_human: {by_class['needs_human']}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            for r in all_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n明细写到 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
