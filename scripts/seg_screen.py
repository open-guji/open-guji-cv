#!/usr/bin/env python3
"""切分筛查（A22 F4①②、F7、F8，2026-11-10）：只读本机产物与列图，各书通用，列出要看图的列与页。

判据在 `open_guji_cv/eval/seg_screen.py`，跑法在 `open_guji_cv/eval/seg_screen_run.py`（`guji seg check` 共用）。不改产物、不进指纹。

用法（GUJI_WORKSPACE 指向书的工作区，产物在本机）：

    python scripts/seg_screen.py --books 04 06 --out <报告目录>
    python scripts/seg_screen.py --books 001 002 --seal-blank     # 加 F8：列出 seed_admit 会按印框记空的格（要原图）

输出：每项一张 TSV（edge_ink、orphan、edge_frame_only、colnet_page、frame_margin、layout_col_shift、layout_fallback、
pitch_free_ignored、cell_flags、pin_slots、layout_slots、seal_blank）
和 summary.md（逐册计数）。要看图就把 TSV 交 `guji-manager review-pages build`。
格位表取本册 row_segment 的 `layout_prior` 参数（册配置里写的那份）；没开的册跳过 ②b 与 F7。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    from open_guji_cv.eval.seg_screen_run import screen_book, write_report
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", nargs="+", required=True)
    ap.add_argument("--pages", help="只查这些页（逗号分隔，各册通用）")
    ap.add_argument("--seal-blank", action="store_true", help="加 F8（要原图，慢）")
    ap.add_argument("--no-cell", action="store_true", help="不跑格级 flags（cell_flags，要读字块，慢）")
    ap.add_argument("--out", default="seg_screen_out")
    a = ap.parse_args(argv)
    pages = {int(x) for x in a.pages.split(",")} if a.pages else None
    rows: dict[str, list] = {}
    counts: dict = {}
    for b in a.books:
        screen_book(b, pages, a.seal_blank, rows, counts, cell_checks=not a.no_cell)
    print(write_report(rows, counts, a.out, a.seal_blank))
    return 0


if __name__ == "__main__":
    sys.exit(main())
