#!/usr/bin/env python3
"""公众意见台账（M10·D3，GUJI-690）：一个 rev 的意见快照里每一票现在是什么状态，未处理的有几条。

意见快照是中心库 `feedback/lists/web/<书>/<rev>.jsonl`（网站每日同步写的，一行一票）。台账逐票给状态：

  test         测试票（note 以「【测试】」开头或含 eden-test）
  adopted      有人裁事件在 payload.opinion_ids 或 payload.source 里引用了这条意见 id
  abstained    「看不清」，只计数
  consistent   没被引用，但该格已有人裁（任何来源）定的结果和这一票一致
  overridden   该格已有人裁，和这一票不一致（这票不再处理；要翻案走 1.0 后修订）
  open         以上都不是——还没人处理。G7「意见池清零」查的就是它

意见 id ＝ `<book>:<vol>:<a>:<voter>`（与 web_opinions.py、H-web 事件 source 里的写法一致）。
「已有人裁」的口径同 pending_route.py：confirm 带字、not_a_char、damaged、seg_defect 且 quality≠clean。

用法：
  python scripts/zhengli/opinion_ledger.py --snapshot 001-r2.jsonl --events <数据目录>/feedback/events \
      [--out 001-r2.state.jsonl]
末行打一行统计；--strict 时有 open 退出码 3。只读，不写事件。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pending_route import cell_of, deciding, iter_events  # noqa: E402

# 意见六档 → 定字裁决的 v（web_opinions.py 的映射）
CHOICE_V = {"char": "confirm", "none": "not_a_char", "cut": "seg_defect", "jiazhu": "seg_defect", "main": "seg_defect"}


def cv_book(vol) -> str:
    v = str(vol)
    return v if v.startswith("vol") else f"vol{int(v):02d}"


def opinion_id(o: dict) -> str:
    return f"{o.get('book')}:{o.get('vol')}:{o.get('a')}:{o.get('voter')}"


def is_test(o: dict) -> bool:
    note = o.get("note") or ""
    return note.startswith("【测试】") or "eden-test" in note


def agrees(o: dict, e: dict) -> bool:
    pl = e.get("payload") or {}
    want = CHOICE_V.get(o.get("choice"))
    if want != pl.get("v"):
        return False
    return o.get("choice") != "char" or (o.get("char") or "") == (pl.get("shape") or "")


def build(snapshot: list[dict], events: list[dict]) -> list[dict]:
    # 引用：事件 payload 里提到的意见 id
    cited: dict[str, str] = {}
    human: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in events:
        pl = e.get("payload") or {}
        refs = list(pl.get("opinion_ids") or [])
        src = str(pl.get("source") or "")
        for o_id in refs:
            cited.setdefault(o_id, e["id"])
        if "意见 " in src:
            for part in src.split("意见 ")[1:]:
                o_id = part.split("）")[0].split("；")[0].strip()
                for one in o_id.split(","):
                    cited.setdefault(one.strip(), e["id"])
        if deciding(e):
            book = (e.get("target") or {}).get("book")
            cell = cell_of(e, book) if book else None
            if cell:
                human[(book, cell)].append(e)
    rows = []
    for o in snapshot:
        oid = opinion_id(o)
        row = {"opinion_id": oid, "a": o.get("a"), "choice": o.get("choice"), "char": o.get("char"), "voter": o.get("voter")}
        if is_test(o):
            row["status"] = "test"
        elif oid in cited:
            row.update(status="adopted", event_id=cited[oid])
        elif o.get("choice") == "unsure":
            row["status"] = "abstained"
        else:
            hits = sorted(human.get((cv_book(o.get("vol")), o.get("a")), []), key=lambda e: str(e.get("ts", "")))
            if hits:
                last = hits[-1]
                row.update(status="consistent" if agrees(o, last) else "overridden", event_id=last["id"])
            else:
                row["status"] = "open"
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--events", action="append", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    snap = [json.loads(ln) for ln in a.snapshot.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = build(snap, list(iter_events(a.events)))
    if a.out:
        a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    c = Counter(r["status"] for r in rows)
    print(f"意见 {len(rows)} 条：" + "、".join(f"{k} {c[k]}" for k in
          ("adopted", "consistent", "overridden", "abstained", "test", "open")) + f"｜未处理 {c['open']}")
    return 3 if (a.strict and c["open"]) else 0


if __name__ == "__main__":
    sys.exit(main())
