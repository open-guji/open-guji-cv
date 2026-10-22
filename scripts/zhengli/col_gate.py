"""R6 整页／整列丢字检查（GUJI-661）：

    python scripts/zhengli/col_gate.py --book vol04 [--pages 80,217] [--out col_gate.json]

读 Step3 产物与原图，列出 `col_missing`（整列没切出）与 `dropped`（单字墨段没被字格接住）。
只报告。判据与阈值见 `open_guji_cv/ops/col_gate.py`；出口取数 `collect_exit.py` 的 R6 调同一份。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", default=None, help="逗号分隔；缺省 = 产物里有的全部页")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from open_guji_cv.ops.col_gate import scan_book
    res, n = scan_book(a.book, [int(x) for x in a.pages.split(",")] if a.pages else None)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(f"{a.book}：{n} 页，报 {len(res)} 条", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
