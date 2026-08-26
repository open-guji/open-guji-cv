# -*- coding: utf-8 -*-
"""种子队列体检 + 修复：唯一性、幽灵行、上下文错位。

    # 只报不改
    PYTHONPATH=. python scripts/repair_seed_queue.py output/vol01
    # 落地修复
    PYTHONPATH=. python scripts/repair_seed_queue.py output/vol01 --apply

queue.jsonl 的隐含契约是 **一个 instance_id 一行**：审查页按 id 取证据
（ocr / align / match / context），图块却按当前 index.jsonl 取。两者一旦
不同源，页面就会拿着 A 的证据配 B 的图——用户 2026-08-25 实锤：
``vol01:4:2:20`` 卡片显示「第」，上下文条却高亮下一位的「一」。

三类病灶（都由重切分后的迁移留下）：

1. **幽灵行**：instance_id 已不在 index.jsonl 里（那一格被新切分并掉了）；
2. **重号**：迁移行落到旧行头上，同一 id 两行（旧队列 125 处）；
3. **上下文错位**：``context.pos`` 与该字位在列内的 char 位次对不上，
   即证据是旧切分算的。

1、2 这里直接修（删）；3 修不了——证据得重算，本脚本只报出来，用

    python -m open_guji_cv seed <book> ... --force-pages <逗号分隔页号>

重跑那些页（人裁过的行不会被覆盖）。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# 同号取谁：裁决过的压倒待审的
RANK = {s: i for i, s in enumerate(
    ("confirmed", "confirmed_label_only", "rejected", "not_a_char",
     "confirmed_recropped", "auto_admitted", "excluded",
     "skipped", "pending_review"))}


def char_seq(index_path: Path) -> tuple[dict[str, int], set[str]]:
    """→ (instance_id → 列内 char 位次（1 起）, index 里的全部 id)。

    位次只按 char 格位数（与审查页的「第几字」、``context.pos + 1`` 同源）。
    **幽灵行要按「id 在不在 index 里」判，不能按在不在 seq 里判**：切分层
    可能把一个真字改判成 ``empty``（实锤 vol01:9:3:20「一」——单横字墨少，
    ink_ratio 判据把它当空格位，而人裁确认是真字），那种行不是幽灵，是
    **切分层的误判**，要留着并回流上游，删掉等于把证据也删了。
    """
    by_col: dict[tuple, list] = defaultdict(list)
    all_ids: set[str] = set()
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        all_ids.add(d["id"])
        if d.get("cell_type", "char") != "char":
            continue
        _, page, col, _ = d["id"].split(":")
        by_col[(page, col)].append(d)
    seq: dict[str, int] = {}
    for group in by_col.values():
        for n, d in enumerate(sorted(group, key=lambda x: x["idx"]), 1):
            seq[d["id"]] = n
    return seq, all_ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out_dir")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    qp = book_dir / "phase9_seed" / "queue.jsonl"
    seq, all_ids = char_seq(book_dir / "phase4_chars" / "index.jsonl")
    rows = [json.loads(l) for l in qp.read_text(encoding="utf-8").splitlines()
            if l.strip()]

    ghosts = [r for r in rows if r["instance_id"] not in all_ids]
    live = [r for r in rows if r["instance_id"] in all_ids]
    # 切分层把真字改判成非 char 的：留着并报出来（见 char_seq 的注释）
    demoted = [r for r in live
               if r["instance_id"] not in seq and r.get("decided_char")]

    best: dict[str, dict] = {}
    for r in live:
        cur = best.get(r["instance_id"])
        if cur is None or RANK.get(r["status"], 99) < RANK.get(cur["status"], 99):
            best[r["instance_id"]] = r
    kept = [r for r in live if best[r["instance_id"]] is r]
    dup_dropped = len(live) - len(kept)

    stale_pages: Counter = Counter()
    for r in kept:
        pos = (r.get("context") or {}).get("pos")
        if r["instance_id"] not in seq:
            continue                       # 已被改判成非 char，位次无从谈起
        if pos is not None and pos != seq[r["instance_id"]] - 1:
            stale_pages[r["page"]] += 1

    print(f"{qp}：{len(rows)} 行")
    print(f"  幽灵行（id 不在 index 里）  {len(ghosts)}")
    if demoted:
        print(f"  ⚠ 切分层改判成非 char、却已被裁定为真字  {len(demoted)}"
              f"（不删，回流切分层）："
              f"{[(r['instance_id'], r['decided_char']) for r in demoted[:5]]}")
    print(f"  重号丢弃                    {dup_dropped}")
    print(f"  上下文错位（证据是旧切分算的）{sum(stale_pages.values())} 行，"
          f"分布在 {len(stale_pages)} 页")
    if stale_pages:
        pages = sorted(stale_pages, key=lambda x: (len(x), x))
        print("  受影响页：" + ",".join(pages))
        print("  → 重跑这些页刷新证据：--force-pages " + ",".join(pages))

    if not args.apply:
        print("\n（干跑：未改队列。加 --apply 落地删幽灵行与重号）")
        return
    qp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                          for r in kept), encoding="utf-8")
    print(f"\n已写回 {len(kept)} 行")


if __name__ == "__main__":
    main()
