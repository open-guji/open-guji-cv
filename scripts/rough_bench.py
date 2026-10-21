#!/usr/bin/env python3
"""粗校基准建库（M9 D6-5，GUJI-669）：从快照＋中心库人裁／看图结论冻结一版 `rough-bench/`。

    python scripts/rough_bench.py build --snapshot <快照产物根> [--books vol04,…,vol10] \\
        [--out ../open-guji-dataset/rough-bench] [--random 12] [--hard 16] [--seed 0]

快照＝各册 main 产物包取回的产物根（`guji products pack fetch <册> --to <根>`，每册目录里的 `.pack.json`
记着包标签，冻进 `bench.yaml`）。人裁读当前数据目录的 `feedback/events/`，看图结论读 `feedback/vision/`。
跑基准用 `scripts/eval_rough_bench.py`（`guji eval run rough_bench`）。口径见 `open_guji_cv/exp/rough_bench.py` 模块头。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.exp import rough_bench as RB  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("build")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--books", default=",".join(RB.DEFAULT_BOOKS))
    p.add_argument("--out", default=None, help="缺省 <测试集仓>/rough-bench")
    p.add_argument("--random", type=int, default=12)
    p.add_argument("--hard", type=int, default=16)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--why", default="")
    a = ap.parse_args(argv)
    from open_guji_cv.core.workspace import feedback_root
    from open_guji_cv.gold.store import default_dataset_root as dataset_root
    snap = Path(a.snapshot).resolve()
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    packs = {}
    for b in books:
        f = snap / b / ".pack.json"
        if not f.exists():
            raise SystemExit(f"快照 {b} 没有 .pack.json（要用 guji products pack fetch 取回的产物，基准才知道冻的是哪个包）")
        packs[b] = json.loads(f.read_text(encoding="utf-8"))["label"]
    out = Path(a.out) if a.out else dataset_root() / RB.SHARD
    vision = sorted((feedback_root() / "vision").glob("*.jsonl"))
    res = RB.build(snap, out, packs, books=books, vision_files=vision, n_random=a.random, n_hard=a.hard,
                   seed=a.seed, why=a.why)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
