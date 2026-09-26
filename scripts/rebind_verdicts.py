# -*- coding: utf-8 -*-
"""人裁重绑定：重算全书绑定表并报告（设计见 overview 总览/15）。

    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/bin/python scripts/rebind_verdicts.py <book> -w <工作区> [--refresh] [--out 报告.json]

绑定表平时不用手工跑——`human_chars` 与 Step7 读人裁时按页自动重算（Step3 产物或裁决变了才算）。
本脚本用于重切之后看一眼「自动改绑 / 待重核 / 作废」各多少、各是哪些。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--refresh", action="store_true", help="无视缓存全部重算")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    from open_guji_cv.feedback.bindings import book_bindings

    rows = book_bindings(a.book, refresh=a.refresh)
    latest: dict[str, dict] = {}
    for r in sorted(rows.values(), key=lambda r: r["ts"]):
        latest[r["key"]] = r
    c_all = Counter(r["status"] for r in rows.values())
    c_last = Counter(r["status"] for r in latest.values())
    print(f"{a.book}：裁决事件 {len(rows)} 条（{len(latest)} 个字位）")
    print("  按事件：", dict(c_all))
    print("  按字位（取该位最后一条裁决）：", dict(c_last))
    for st in ("rebound", "review", "void", "unanchored"):
        ks = [r for r in latest.values() if r["status"] == st]
        if ks:
            print(f"  {st}（{len(ks)}）例：" + "、".join(
                f"{r['key']}→{r['bound']}" if st == "rebound" else r["key"] for r in ks[:8]))
    if a.out:
        Path(a.out).write_text(json.dumps(list(latest.values()), ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
