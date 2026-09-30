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
    n_nosrc = 0
    books: dict = {}
    for g in gold:
        # 2026-09-30 M1：金标标的是**原图**（没变），v1 的 output/<册>/<页>.png 早已不存在
        # （云端读到 n=0 的空跑根因）。改从工作区册定义的原图读；旧路径留作回退。
        img = None
        try:
            if g.book not in books:
                from open_guji_cv.core.book import load_book
                books[g.book] = load_book(g.book)
            src = books[g.book].raw_path(int(g.page))
            if src.exists():
                img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
        except Exception:
            img = None
        if img is None:
            img = cv2.imread(f"output/{g.book}/{g.page}.png", cv2.IMREAD_GRAYSCALE)
        if img is None:
            n_nosrc += 1
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
    if n_nosrc:
        print(f"⚠ {n_nosrc} 页找不到原图（册定义不在 GUJI_WORKSPACE?），未计入")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
