# -*- coding: utf-8 -*-
"""闸3「版式未支持」判据 vs page-type 金标。

判据本身在 `gates/row_segment_gate.py`（L0u），这里只做金标复核——
**红线是 body 误判必须 0**（正文页被误标成"非异常"= 该页被静默排除在
正文指标之外，没人会去查）。

用法：
    python scripts/eval_unsupported_layout.py            # 全金标
    python scripts/eval_unsupported_layout.py --book vol01

判据只读现成的 `cells` 产物，不重跑管线。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类（cells 等）
from open_guji_cv.clustering.page_type import unsupported_layout_columns
from open_guji_cv.core.spec import page_key
from open_guji_cv.products.store import ProductStore

GOLD = Path(r"D:\workspace\open-guji-dataset\page-type\expected.json")
# 金标页型 → 本判据该不该判「版式未支持」。判据只分两档（正文 / 切不了），
# 不细分 roster/toc——两者在判据上重叠，见 row_segment_gate.py 的 L0u 一节。
SHOULD_FLAG = {"roster", "toc"}
BODY_LIKE = {"body"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None)
    ap.add_argument("--products", default=None)
    args = ap.parse_args()

    store = ProductStore(Path(args.products) if args.products else None)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    by_type: dict[str, Counter] = {}
    misfires: list[str] = []
    missed: list[str] = []

    for g in gold:
        book, pg, pt = g["book"], int(g["page"]), g["page_type"]
        if args.book and book != args.book:
            continue
        cells = store.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            by_type.setdefault(pt, Counter())["无产物"] += 1
            continue
        cols = [c.model_dump() for c in cells.columns]
        n_uns = unsupported_layout_columns(cols)
        n_ok = sum(1 for c in cols if c["ok"])
        flagged = bool(cols) and n_ok == 0 and n_uns == len(cols)
        c = by_type.setdefault(pt, Counter())
        c["判版式未支持" if flagged else "未判"] += 1
        if flagged and pt in BODY_LIKE:
            misfires.append(f"{book}/{pg}")
        if not flagged and pt in SHOULD_FLAG and n_uns:
            missed.append(f"{book}/{pg}({n_uns}/{len(cols)}列无解)")

    print(f"{'金标页型':<10}{'判版式未支持':>14}{'未判':>8}{'无产物':>8}")
    for pt, c in sorted(by_type.items()):
        print(f"{pt:<10}{c['判版式未支持']:>14}{c['未判']:>8}{c['无产物']:>8}")

    n_body = sum(by_type.get(t, Counter())["判版式未支持"] for t in BODY_LIKE)
    print(f"\n红线｜正文页误判成「版式未支持」：{n_body} 页", "✅ 通过" if n_body == 0 else "❌ 破线")
    if misfires:
        print("  误判页：", ", ".join(misfires))
    if missed:
        print(f"\n漏判（有无解列但未整页判定，归异常侧，方向安全）：{len(missed)} 页")
        print("  ", ", ".join(missed))


if __name__ == "__main__":
    main()
