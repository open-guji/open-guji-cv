"""页型判别 benchmark。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.page_type import classify_page_type, load_labels
from open_guji_cv.clustering.pagetype_eval import evaluate, format_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    gold = load_labels(Path(args.dataset) / "expected.json")
    pred = {}
    for g in gold:
        img = cv2.imread(f"output/{g.book}/{g.page}.png", cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        pred[g.key] = classify_page_type(img)
    rep = evaluate(gold, pred)
    print(format_report(rep))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
