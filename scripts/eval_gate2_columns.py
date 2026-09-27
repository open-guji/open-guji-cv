# -*- coding: utf-8 -*-
"""闸2 可用列：`column_gate` 交接闸放行了多少列（char-segmentation 相关，Step2→3）。

    python scripts/eval_gate2_columns.py --book vol02 [--pages all] [--json out.json]

这把尺子此前只在诊断会话里现场读过 `guji status`/一次性脚本的输出（如
S-vol02正式重跑-云端 done 单："已跑 column_gate：188/188 页 gate 全通过、0 阻塞"），
没有固化。`gate_manifest`（`column_gate` 步产出）本身就是现成的**页级 + 列级**判据，
不需要另写像素判据——这里只是把它汇总成一个数字、按页给出未放行的列表。

页级 `admitted=False` 时该页贡献 0 个可用列（`GateManifest.admitted_columns()`
就是这个语义）；列级 `reject` 非空的列即使页级过了也不算可用列。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402


def _expand_pages(spec: str | None, cap: int) -> list[int]:
    if spec is None or spec == "all":
        return list(range(1, cap + 1))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", default="all")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    store = ProductStore()
    pages = _expand_pages(a.pages, 300)

    n_pages_scanned = 0
    n_pages_admitted = 0
    n_cols_total = 0
    n_cols_admitted = 0
    rejected_pages: list[int] = []
    rejected_cols: list[tuple[int, int, list[str]]] = []
    for pg in pages:
        gm = store.read(a.book, "column_gate", page_key(pg), "gate_manifest")
        if gm is None:
            continue
        n_pages_scanned += 1
        if gm.admitted:
            n_pages_admitted += 1
        else:
            rejected_pages.append(pg)
        for c in gm.columns:
            n_cols_total += 1
            ok = gm.admitted and c.admitted
            if ok:
                n_cols_admitted += 1
            else:
                rejected_cols.append((pg, c.col, list(c.reject) or (["page_rejected"] if not gm.admitted else [])))

    rate = round(100.0 * n_cols_admitted / n_cols_total, 2) if n_cols_total else float("nan")
    print(f"{a.book}：扫了 {n_pages_scanned} 页（页级放行 {n_pages_admitted}，"
          f"拒收 {len(rejected_pages)}：{rejected_pages[:20]}{'...' if len(rejected_pages) > 20 else ''}）")
    print(f"  闸2 可用列：{n_cols_admitted}/{n_cols_total} = {rate}%")
    if rejected_cols:
        print(f"  列级被拒 {len(rejected_cols)} 条，前 20 条：")
        for pg, col, reasons in rejected_cols[:20]:
            print(f"    p{pg}c{col}: {reasons}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"book": a.book, "pages_scanned": n_pages_scanned,
                       "pages_admitted": n_pages_admitted, "pages_rejected": rejected_pages,
                       "cols_total": n_cols_total, "cols_admitted": n_cols_admitted,
                       "rate_pct": rate, "cols_rejected": rejected_cols}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
