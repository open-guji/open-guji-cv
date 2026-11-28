# -*- coding: utf-8 -*-
"""识字候选 benchmark 命令行壳（实现搬到 `open_guji_cv/eval/cands_bench.py`，CV3 2026-11-28）。

用法同旧：
    PYTHONPATH=. python scripts/eval_cands.py <dataset>/char-candidates [--out report.json] [--against 旧report.json]
        [--part 3c,4b,card] [--no-mlm] [--limit N] [--w 0.005]
统一接口：`guji bench run read-3c-cands --book <书>`、`guji bench run decide-4b-ctx --book <书>`。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.eval.cands_bench import main  # noqa: E402

if __name__ == "__main__":
    main()
