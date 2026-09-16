# -*- coding: utf-8 -*-
"""在冻结的 68 页下版框金标（绝对页面坐标）上直接测 `find_horizontal_border`
（`side="bottom"`）的像素误差——不经过 Step2/3 产物，只跑原图 + 算法。

读 `border-detection/bottom-offset/frozen_absolute.jsonl`（由
`freeze_bottom_offset_gold.py` 生成，不要再动态转换金标坐标——参照系必须
锁死，否则改完算法再读金标，误差对比就是假的）。

误差定义：算法给出的水平线在金标线两端点 x 位置上的 y 值，跟金标两端点的
y 值分别做差，取绝对值——`per-endpoint`，跟 `01-下版框根修先造金标.md`
里报告的口径一致（不是单一位置/单一偏移量，两端点各自算一次）。

用法：
    PYTHONIOENCODING=utf-8 python scripts/eval_bottom_offset_gold.py
    PYTHONIOENCODING=utf-8 python scripts/eval_bottom_offset_gold.py --hard-only
        # 只跑 books/{book}.yaml 里 sets.bottom_border_hard 登记的困难页子集
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.utils.peak_line_search import find_horizontal_border  # noqa: E402

GOLD = ROOT.parent / "open-guji-dataset" / "border-detection" / "bottom-offset" / "frozen_absolute.jsonl"
INK_THRESHOLD = 128


def hard_set(book: str) -> set[int]:
    b = load_book(book)
    sets = getattr(b, "sets", None) or {}
    return set(sets.get("bottom_border_hard", []))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hard-only", action="store_true", help="只跑 bottom_border_hard 子集")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    items = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.hard_only:
        hard_cache: dict[str, set[int]] = {}
        for book in {it["book"] for it in items}:
            hard_cache[book] = hard_set(book)
        items = [it for it in items if it["page"] in hard_cache[it["book"]]]

    errs = []
    rows = []
    for it in items:
        book, page = it["book"], it["page"]
        b = load_book(book)
        gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            print(f"跳过 {book}/{page}：原图缺失")
            continue
        h, w = gray.shape
        mask = (gray < INK_THRESHOLD).astype(np.float64)
        res = find_horizontal_border(mask, "bottom")
        # LineMatch.position/slope 在旧坐标系（左上角原点，x 向右）：
        # y_algo(x_old) = position + slope * (x_old - h/2)  —— 参见
        # peak_line_search.joint_search_coarse_to_fine 的调用方式（axis="h"
        # 时 position 是 y、slope 是"随 x_old 变化的斜率"，采样时 t 是 x_old，
        # center 是 w/2；但 sample_line_curve 内部对 axis="h" 用 n_perp=w，
        # center=w/2，因此 y(x) = position + slope*(x - w/2)）。
        y_at_left_old = res.position + res.slope * (0 - w / 2.0)      # 旧坐标 x=0（页左）
        y_at_right_old = res.position + res.slope * ((w - 1) - w / 2.0)  # 旧坐标 x=w-1（页右）

        e_left = abs(y_at_left_old - it["y_left_abs"])
        e_right = abs(y_at_right_old - it["y_right_abs"])
        errs.append(e_left)
        errs.append(e_right)
        rows.append(dict(book=book, page=page, e_left=round(e_left, 1), e_right=round(e_right, 1),
                         algo_pos=round(res.position, 1), algo_score=round(res.score, 2)))

    errs = np.array(errs)
    rows.sort(key=lambda r: -(r["e_left"] + r["e_right"]))
    print(f"{'页面':<14}{'e_left':>8}{'e_right':>9}{'score':>9}")
    for r in rows[:15]:
        print(f"{r['book']}/{r['page']:<10}{r['e_left']:>8}{r['e_right']:>9}{r['algo_score']:>9}")
    print(f"\nn={len(errs)} endpoints ({len(rows)} pages)")
    print(f"mean={errs.mean():.1f}px  p90={np.percentile(errs, 90):.1f}px  max={errs.max():.1f}px")
    print(f">20px endpoints: {(errs > 20).sum()}/{len(errs)}")

    if a.json_out:
        Path(a.json_out).write_text(
            json.dumps(dict(rows=rows, mean=float(errs.mean()), p90=float(np.percentile(errs, 90)),
                            max=float(errs.max())), ensure_ascii=False, indent=1),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
