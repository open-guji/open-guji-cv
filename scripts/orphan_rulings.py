#!/usr/bin/env python
"""孤儿人裁普查：换图源后被 RevGate 挡在外面、又没有现行迁移孪生的定字人裁（confirm）。

背景（11-13 ZM）：human_chars 的提示「N 条事件锚里的页表 rev 与册 yaml 的 source_rev 不符，不采信」把三类混在一起——
  ① 旧代迁移事件（`~q`，source_rev 3／4）：已被现行代（source_rev＝册 yaml）取代，正常；
  ② 换源前的原始事件（锚里没有 source_rev）：有现行代孪生的，正常；
  ③ **没有现行孪生的原始事件**＝迁移时对不到新格（格没了／IoU 低），被静默挡在外面——这类才是要人看的。
本脚本只列第③类，按册出 TSV（册 \\t 旧格 \\t 字 \\t 时刻 \\t 事件 id），交该册线复核（是不是还有效、要不要补投）。

用法：python scripts/orphan_rulings.py [--data <数据目录>] [--books vol03,vol04] [--out 目录]
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.core.event_files import RevGate, _book_page, iter_event_records  # noqa: E402


def scan(data: Path, books: set[str] | None = None) -> dict[str, list[dict]]:
    gate = RevGate(data / "books")
    events = [e for _f, e in iter_event_records(data / "feedback" / "events", gate=False)]
    twins: dict[str, list[dict]] = collections.defaultdict(list)
    for e in events:
        i = e.get("id") or ""
        if "~" in i:
            twins[i.split("~")[0]].append(e)
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for e in events:
        i = e.get("id") or ""
        t = e.get("target") or {}
        book, page = _book_page(t)
        if e.get("kind") != "confirm" or "~" in i or not book or page is None or (books and book not in books):
            continue
        want = gate.rev(book)
        if want is None:
            continue
        got = (t.get("anchor") or {}).get("source_rev")
        if got is not None and str(got) == str(want):
            continue
        if any(str(((x.get("target") or {}).get("anchor") or {}).get("source_rev")) == str(want) for x in twins.get(i, [])):
            continue
        out[book].append(e)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=None, help="数据目录（缺省取 GUJI_DATA_HOME 下当前分支的工作区数据）")
    ap.add_argument("--books", default="", help="逗号分隔的册，缺省全部")
    ap.add_argument("--out", default=None, help="TSV 输出目录；不给只打印计数")
    a = ap.parse_args(argv)
    if a.data:
        data = Path(a.data)
    else:
        from open_guji_cv.core.workspace import data_root
        import os
        data = data_root(Path(os.environ["GUJI_WORKSPACE"]))
    res = scan(data, set(filter(None, a.books.split(","))) or None)
    for book in sorted(res):
        print(f"{book}\t{len(res[book])}")
        if a.out:
            d = Path(a.out)
            d.mkdir(parents=True, exist_ok=True)
            with open(d / f"{book}.tsv", "w", encoding="utf-8") as fh:
                for e in res[book]:
                    t = e.get("target") or {}
                    fh.write(f"{book}\t{t.get('cell') or t.get('key') or ''}\t{(e.get('payload') or {}).get('shape') or ''}\t{e.get('ts') or ''}\t{e.get('id')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
