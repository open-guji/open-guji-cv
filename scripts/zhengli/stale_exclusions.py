# -*- coding: utf-8 -*-
"""列出人裁排除名单里「裁决锚点和当前切图对不上」的格（GUJI-659／623）：

    python scripts/zhengli/stale_exclusions.py --book vol02 [--out stale.json]

只报告，不改名单。每条给出：编号、原因（not_text／damaged）、绑定状态、现在该落的编号。
撤条目走 `scripts/apply_exclusion_recheck.py`。
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", required=True)
    ap.add_argument("--out", default=None, help="写成 json；不给就打印")
    a = ap.parse_args(argv)
    from open_guji_cv.feedback.exclusion_check import stale_by_binding
    from open_guji_cv.feedback.bindings import book_bindings
    rows = stale_by_binding(a.book, book_bindings(a.book))
    text = json.dumps(rows, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    else:
        print(text)
    print(f"{a.book}：对不上的排除格 {len(rows)} 个", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
