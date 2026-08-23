"""归一化 golden 回归门（open-guji-dataset/char-normalization）。

    python scripts/eval_normalize.py ../open-guji-dataset/char-normalization

退出码非 0 = 回归门失败（verified 层有样本超出容差）。已知缺陷层不影响
退出码，但会把「行为变了」的样本列出来——那通常是缺陷修好了，
该去更新对应的 golden 与 `VERDICTS`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

from open_guji_cv.clustering.normalize import normalize_patch, skeletonize
from open_guji_cv.clustering.normalize_eval import (check_sample, format_report,
                                                    summarize)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="char-normalization 数据集目录")
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    args = ap.parse_args()

    samples = sorted(d for d in (Path(args.dataset) / "samples").iterdir()
                     if d.is_dir() and (d / "expected.json").exists()
                     and not (d / "PLACEHOLDER.md").exists())
    results = []
    for d in samples:
        spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        gray = cv2.imread(str(d / spec["input"]), cv2.IMREAD_GRAYSCALE)
        produced = normalize_patch(gray)
        results.append(check_sample(d, produced, skeletonize(produced)))

    report = summarize(results)
    report["samples"] = [r.to_dict() for r in results]
    print(format_report(report))

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"→ {args.out}")
    sys.exit(0 if report["gate"]["ok"] else 1)


if __name__ == "__main__":
    main()
