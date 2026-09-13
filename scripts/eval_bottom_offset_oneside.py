# -*- coding: utf-8 -*-
"""下版框金标的**单侧**评估：宁可往下留白，绝不可靠上切字。

用户 2026-09-13 定的口径，取代原来的对称像素误差：

- 算法线落在金标**下方**（更靠页边空白）≤ `TOL` px → **过**；
- 算法线落在金标**上方**（更靠正文）→ **不过**，不给任何容差；
- 超过下方 `TOL` → 不过（掉到空白里太远，同样无用）。

为什么不对称：切版框的目的是不切掉最后一行字。往下多留一点只是带进一点
空白或污点，往上一点点就会把字切掉——两种错的代价根本不对等。

`TOL=30` 的来由：金标线离粗墨条上沿实测中位 19px、p90 28px，所以 30 大致
等于"允许落到墨条上，但不许再往下跑进空白"。

用法：
    PYTHONIOENCODING=utf-8 python scripts/eval_bottom_offset_oneside.py
    PYTHONIOENCODING=utf-8 python scripts/eval_bottom_offset_oneside.py --tol 20
    PYTHONIOENCODING=utf-8 python scripts/eval_bottom_offset_oneside.py --no-rescue
        # 关掉救援跑一遍做对照
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
from open_guji_cv.utils.peak_line_search import (  # noqa: E402
    find_horizontal_border, find_vertical_lines)

GOLD = ROOT.parent / "open-guji-dataset" / "border-detection" / "bottom-offset" / "frozen_absolute.jsonl"
INK_THRESHOLD = 128
DEFAULT_TOL = 30.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="允许落在金标下方多少 px")
    ap.add_argument("--no-rescue", action="store_true", help="关掉跨页先验救援做对照")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    items = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    gaps: dict[str, float | None] = {}
    rows = []
    for it in items:
        book, page = it["book"], it["page"]
        if book not in gaps:
            gaps[book] = None if a.no_rescue else load_book(book).bottom_gap
        b = load_book(book)
        gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        h, w = gray.shape
        mask = (gray < INK_THRESHOLD).astype(np.float64)
        vl = find_vertical_lines(mask, expected_count=b.expected_cols + 1)
        m = find_horizontal_border(mask, "bottom", verticals=vl, book_gap=gaps[book])
        # 正的 = 算法线在金标下方（安全侧）；负的 = 在金标上方（切字侧）
        d_left = (m.position + m.slope * (0 - w / 2.0)) - it["y_left_abs"]
        d_right = (m.position + m.slope * ((w - 1) - w / 2.0)) - it["y_right_abs"]
        worst = min(d_left, d_right)            # 两端里最靠上的那端决定成败
        rows.append(dict(book=book, page=page, d_left=round(d_left, 1),
                         d_right=round(d_right, 1), worst=round(worst, 1),
                         ok=bool(0 <= worst <= a.tol) or bool(-0.0 <= worst <= a.tol)))

    worst = np.array([r["worst"] for r in rows])
    ok = (worst >= 0) & (worst <= a.tol)
    above = worst < 0                            # 切字侧，最严重的错
    too_low = worst > a.tol
    n = len(rows)
    print(f"金标 {n} 页  容差 TOL={a.tol:.0f}px  救援={'关' if a.no_rescue else '开'}")
    print(f"  过        : {ok.sum():3d} ({100*ok.mean():5.1f}%)")
    print(f"  高于金标  : {above.sum():3d} ({100*above.mean():5.1f}%)   ← 切字，最严重")
    print(f"  低于超容差: {too_low.sum():3d} ({100*too_low.mean():5.1f}%)")
    if above.sum():
        av = worst[above]
        print(f"  切字侧深度: median={np.median(av):.1f}px  最深={av.min():.1f}px")
    print(f"\n  安全侧距离分布(仅过的页): "
          f"median={np.median(worst[ok]) if ok.sum() else float('nan'):.1f}px")
    print(f"\n切字侧最严重的 15 页：")
    for r in sorted(rows, key=lambda r: r["worst"])[:15]:
        tag = "切字" if r["worst"] < 0 else ("过" if r["worst"] <= a.tol else "太低")
        print(f"   {r['book']}/{r['page']:<5} 左={r['d_left']:+8.1f} 右={r['d_right']:+8.1f} "
              f"最靠上={r['worst']:+8.1f}  {tag}")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            dict(tol=a.tol, rescue=not a.no_rescue, n=n, ok=int(ok.sum()),
                 above=int(above.sum()), too_low=int(too_low.sum()), rows=rows),
            ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
