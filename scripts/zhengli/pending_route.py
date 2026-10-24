#!/usr/bin/env python3
"""待审单分流（M10·D1，GUJI-688）：已出的待审单 → 扣掉已裁的格 → 分成公众单、团队单，另出回流单。

`pending_list.py`（ai-team `team/整理/GUJI-543/`）只看产物快照里没放行的格：不扣快照之后已经有人裁过的格，
不分正文和非正文，也不分公众和团队。vol01 001-r2 上线 63 格里 59 格不该给公众（M10 调研 A 的 A1、A2）。
本脚本接在它后面，只读，不碰 products、不写事件：

  已裁   截止 --as-of（缺省现在），该格有一条「定了字」的人裁事件：confirm 带 shape、not_a_char、damaged、
         seg_defect 且 quality 不是 clean。cutline、needs_review、cell_review、看图结论（source=vision）都不算。
         待审单里带 stale（旧裁已失效）的格，只认 stale.ts 之后的事件。
  团队单 页在 --team-pages 里，或 --page-types 里不是 body 的页（非正文只给团队，用户 10-20 定）。
  公众单 其余。
  不扣   带 `recheck: true` 的格（pending_list --recheck 放回来的复审格，本来就是要人推翻或重定的）；
         --keep 名单上的格照旧留在单上（republish.py from-pack 传：人裁按锚框绑到了别的格或绑不上，
         原格号上的人裁不能算这一格定了字）。
  回流单 同一 (cls, why) 的格 ≥ --reflow-min（缺省 20）：成片的问题先交 M7／M9／CV 修，不逐格审（设计 GUJI-543 §4.2）。
         cls=other、why=none（机器没把握的兜底）不算同一个原因，不进回流单。
         只列出来；加 --reflow-hold 才把它们从两张单里拿掉。

用法：
  python scripts/zhengli/pending_route.py --pending 001.pending.json --book vol01 \
      --events <数据目录>/feedback/events [--events 另一个.jsonl] [--as-of 2026-10-17T20:00:00Z] \
      [--team-pages 89-132,196] [--page-types page_types.json] [--db-rev 12063] --out <目录>
产出：<章>.pending.json（公众）、<章>.team.pending.json（团队）、<章>.reflow.tsv，末行打一行统计。
事件文件是数据目录 `feedback/events/*.jsonl`（一行一条事件），也收中心库 `/v1/tables/events` 拉下来的行。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

DECIDING_V = {"not_a_char", "damaged"}
NOT_A_CAUSE_CLS = {"", "other"}
NOT_A_CAUSE_WHY = {(), ("none",)}


def deciding(e: dict) -> str | None:
    """这条事件定没定这一格的字：定了返回类别，没定返回 None。"""
    if e.get("kind") != "confirm":
        return None
    pl = e.get("payload") or {}
    if pl.get("source") == "vision":
        return None
    v = pl.get("v")
    if v == "confirm" and pl.get("shape"):
        return "char"
    if v in DECIDING_V:
        return v
    if v == "seg_defect" and pl.get("quality") not in (None, "", "clean"):
        return "seg_defect"
    return None


def cell_of(e: dict, book: str) -> str | None:
    t = e.get("target") or {}
    if t.get("unit") != "cell" or t.get("book") not in (None, book):
        return None
    key = t.get("key") or ""
    if key.startswith(f"{book}:"):
        return key[len(book) + 1:]
    if t.get("book") == book and t.get("page") is not None and t.get("col") is not None and t.get("slot") is not None:
        return f"{t['page']}:{t['col']}:{t['slot']}"
    return None


def iter_events(paths: list[Path]):
    for p in paths:
        files = sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)


def decided_cells(events, book: str, as_of: str) -> dict[str, list[tuple[str, str]]]:
    """{格号: [(ts, 类别)…]}，只收截止时刻之前、定了字的事件。"""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in events:
        if str(e.get("ts", "")) > as_of:
            continue
        kind = deciding(e)
        cell = cell_of(e, book) if kind else None
        if cell:
            out[cell].append((str(e.get("ts", "")), kind))
    return out


def parse_pages(spec: str | None) -> set[int]:
    pages: set[int] = set()
    for part in filter(None, (spec or "").replace("，", ",").split(",")):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", part)
        if not m:
            raise ValueError(f"页范围写错：{part!r}")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        pages.update(range(lo, hi + 1))
    return pages


def page_of(cell: str) -> int:
    return int(cell.split(":", 1)[0])


def route(pending: dict, decided: dict, team_pages: set[int], reflow_min: int, reflow_hold: bool) -> dict:
    cells = pending.get("cells", [])
    kept, dropped = [], []
    for c in cells:
        stale_ts = str((c.get("stale") or {}).get("ts") or "")
        hits = [] if c.get("recheck") else [h for h in decided.get(c["cell"], []) if h[0] > stale_ts]
        (dropped if hits else kept).append(c)
    groups = Counter((c.get("cls") or "", tuple(c.get("why") or ())) for c in kept)
    # 「other／none」是「机器没把握」的兜底，不是同一个原因，不进回流单
    big = {g for g, n in groups.items() if n >= reflow_min and g[0] not in NOT_A_CAUSE_CLS and g[1] not in NOT_A_CAUSE_WHY}
    reflow = [c for c in kept if (c.get("cls") or "", tuple(c.get("why") or ())) in big]
    if reflow_hold:
        kept = [c for c in kept if c not in reflow]
    public, team = [], []
    for c in kept:
        (team if page_of(c["cell"]) in team_pages else public).append(c)
    return {"public": public, "team": team, "reflow": reflow, "dropped": dropped,
            "stats": {"total": len(cells), "decided": len(dropped), "team": len(team),
                      "public": len(public), "reflow": len(reflow), "reflow_held": reflow_hold}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pending", required=True, type=Path)
    ap.add_argument("--book", required=True)
    ap.add_argument("--events", action="append", type=Path, required=True, help="事件 jsonl 文件或目录，可多个")
    ap.add_argument("--as-of", default=None, help="只认这个时刻（UTC ISO）之前的事件；缺省现在")
    ap.add_argument("--team-pages", default="", help="只给团队的页，如 89-132,196")
    ap.add_argument("--page-types", type=Path, default=None, help="{页: 页型} JSON；不是 body 的页进团队单")
    ap.add_argument("--reflow-min", type=int, default=20)
    ap.add_argument("--reflow-hold", action="store_true", help="回流单上的格不进公众单、团队单")
    ap.add_argument("--db-rev", default=None, help="分流时中心库的 rev，写进两张单的 based_on_db_rev")
    ap.add_argument("--keep", type=Path, default=None, help="不扣的格号，一行一个（可带「册:」前缀）")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    pending = json.loads(a.pending.read_text(encoding="utf-8"))
    as_of = a.as_of or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    team_pages = parse_pages(a.team_pages)
    if a.page_types:
        types = json.loads(a.page_types.read_text(encoding="utf-8"))
        team_pages |= {int(p) for p, t in types.items() if t != "body"}
    decided = decided_cells(iter_events(a.events), a.book, as_of)
    if a.keep:
        for line in a.keep.read_text(encoding="utf-8").split():
            decided.pop(line.removeprefix(f"{a.book}:"), None)
    res = route(pending, decided, team_pages, a.reflow_min, a.reflow_hold)

    stem = re.sub(r"(\.pending)?\.json$", "", a.pending.name)
    a.out.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in pending.items() if k != "cells"}
    meta = {"based_on_db_rev": a.db_rev, "routed_as_of": as_of}
    for name, cells, aud in ((f"{stem}.pending.json", res["public"], "public"),
                             (f"{stem}.team.pending.json", res["team"], "team")):
        doc = {**head, **meta, "cells": [{**c, "audience": aud} for c in cells]}
        (a.out / name).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (a.out / f"{stem}.reflow.tsv").open("w", encoding="utf-8") as f:
        f.write("cell\tcls\twhy\n")
        for c in res["reflow"]:
            f.write(f"{c['cell']}\t{c.get('cls') or ''}\t{','.join(c.get('why') or [])}\n")
    s = res["stats"]
    print(f"总待审 {s['total']}／扣已裁 {s['decided']}／团队 {s['team']}／公众 {s['public']}／回流 {s['reflow']}"
          f"{'（已拿出）' if s['reflow_held'] else '（只列出）'}｜截止 {as_of}")
    if s["total"] - s["decided"] - (s["reflow"] if s["reflow_held"] else 0) != s["team"] + s["public"]:
        print("统计对不上", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
