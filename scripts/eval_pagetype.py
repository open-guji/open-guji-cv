"""页型判别 benchmark。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.page_type import (classify_page_type,
                                               load_labels, refine_page_type)
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
        ptype, policy = classify_page_type(img)
        # 切分产物在手时做页型细化（body → roster），与管线 run_book 一致
        gp = Path("output") / g.book / "phase3_char_grid" \
            / f"{g.page}_char_grid.json"
        if ptype == "body" and gp.exists():
            r = json.loads(gp.read_text(encoding="utf-8"))
            r["page_type"] = ptype
            ptype = refine_page_type(r)
        pred[g.key] = (ptype, policy)
    rep = evaluate(gold, pred)
    print(format_report(rep))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
