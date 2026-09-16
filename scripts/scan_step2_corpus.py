# -*- coding: utf-8 -*-
"""全语料跑一遍 Step2，把每一列的诊断量收成一张表——扩金标和改算法都要先有这个。

    python scripts/scan_step2_corpus.py -o output/step2_corpus_scan.json [--jobs 4]

对 `output/<book>/step2_columns/` 里已有的每一页每一列跑 `clean_column`，记：

  * `band` / `band_w`     —— `column_text_band` 定出来的文字带和带宽
  * `side_floor`          —— 原始投影两侧外 25% 的最低墨（L2 那条判据的量）
  * `edge_resid`          —— 清理后带内靠边 12px 的残墨（**循环论证量，只做参考**）
  * `top_case`/`bot_case` —— `column_border_trim` 的四档（a/b/c/d）
  * `top_px`/`bot_px`     —— 上下各削掉几行
  * `band_dev`            —— 带宽偏离本页中位数的比例
  * `w_dev`               —— 列宽偏离本页中位数的比例（L1 用的量，页级判据的列级分解）
  * `ink`                 —— 整列墨占比，用来分辨空列/半空列

**为什么要全语料而不是抽样**：金标只有 54 列、且是按难例挑的，量不出"某种失败
形态在全书占多少"。要决定「改哪条判据收益最大」必须有分母。这张表就是分母。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.column_projection import (  # noqa: E402
    clean_column, column_profile, denoise_column,
)

LOOK = 0.25


def scan_page(args) -> list[dict]:
    book, page = args
    wf = ROOT / "output" / book / "step2_columns" / page / "windows.json"
    d = json.loads(wf.read_text(encoding="utf-8"))
    widths = [c["warped_size"]["width"] for c in d["columns"]]
    med_w = statistics.median(widths)
    out, bands = [], []
    for c in d["columns"]:
        img = denoise_column(cv2.imread(str(wf.parent / c["file"]), cv2.IMREAD_GRAYSCALE))
        prof = column_profile(img)
        k = max(1, int(round(LOOK * len(prof))))
        floor = max(float(prof[:k].min()), float(prof[-k:].min()))
        cleaned, diag = clean_column(img)
        b0, b1 = diag["band"]
        cprof = column_profile(cleaned)
        out.append(dict(
            book=book, page=page, col=c["col"], w=c["warped_size"]["width"],
            h=c["warped_size"]["height"], band=[int(b0), int(b1)], band_w=int(b1 - b0),
            side_floor=round(floor, 5),
            edge_resid=round(max(float(cprof[b0:b0 + 12].max()),
                                  float(cprof[b1 - 12:b1].max())), 5),
            top_case=diag["top"]["case"], bot_case=diag["bottom"]["case"],
            top_px=int(diag["top"]["px"]), bot_px=int(diag["bottom"]["px"]),
            ink=round(float((img < 128).mean()), 5),
            raised=bool(c["raised"]),
            segments=(c["left_line"].get("segments") or 1),
            w_dev=round((c["warped_size"]["width"] - med_w) / med_w, 4)))
        bands.append(b1 - b0)
    med_b = statistics.median(bands)
    for r in out:
        r["band_dev"] = round((r["band_w"] - med_b) / med_b, 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="output/step2_corpus_scan.json")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--books", default="vol01,vol02")
    args = ap.parse_args()

    pages = []
    for book in args.books.split(","):
        root = ROOT / "output" / book / "step2_columns"
        if not root.exists():
            continue
        pages += [(book, p.name) for p in sorted(root.iterdir(), key=lambda q: int(q.name))
                   if (p / "windows.json").exists()]
    print(f"扫 {len(pages)} 页，{args.jobs} 并行…", flush=True)

    rows = []
    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for i, part in enumerate(pool.map(scan_page, pages, chunksize=4), 1):
                rows += part
                if i % 50 == 0:
                    print(f"  {i}/{len(pages)}", flush=True)
    else:
        for pg in pages:
            rows += scan_page(pg)

    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(rows)} 列 -> {args.out}")


if __name__ == "__main__":
    main()
