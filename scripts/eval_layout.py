"""行列识别（列型判别）评测：当前管线 vs 金标。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_guji_cv.clustering.layout_eval import evaluate, format_report
from open_guji_cv.clustering.layout_spec import PageLayout, from_char_grid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", help="金标样本目录")
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    args = ap.parse_args()

    pairs = []
    missing = []
    for d in sorted(Path(args.samples).iterdir()):
        exp = d / "expected.json"
        if not exp.exists():
            continue
        gold = PageLayout.load(exp)
        grid_p = (Path("output") / gold.book / "phase3_char_grid"
                  / f"{gold.page}_char_grid.json")
        if not grid_p.exists():
            missing.append(d.name)
            continue
        grid = json.loads(grid_p.read_text(encoding="utf-8"))
        pairs.append((gold, from_char_grid(grid, gold.book, gold.page)))

    if missing:
        print(f"缺少切分结果，跳过 {len(missing)} 页: {missing[:5]}")
    report = evaluate(pairs)
    print(format_report(report))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
