#!/usr/bin/env python3
"""检查人工指定格分片（M10·D5，GUJI-692）：格式不对的行以前会让整个分片静默作废、退回自动切分。

用法：
  python scripts/zhengli/check_manual_cells.py <数据目录>/feedback/verdicts/char-segmentation/manual-cells/items.jsonl
逐行报问题，没问题退出码 0，有问题退出码 3。写分片后、`guji db sync` 前跑一次。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from open_guji_cv.feedback.lookup import check_manual_cells  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    problems = check_manual_cells(Path(argv[0]))
    for p in problems:
        print(p)
    print(f"{len(problems)} 个问题" if problems else "没问题")
    return 3 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
