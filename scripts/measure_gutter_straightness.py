# -*- coding: utf-8 -*-
"""界行「直不直」的指标：把整条界行往 x 轴投影，看峰有多高、多窄。

**用户给的判据（2026-09-02）**：一条界行整条投到 x 轴上——线越直，墨全落在同
一个 x 上，峰就越高、越窄；**最直的只有 3~4px 宽**。线越弯，墨被摊到更多 x 上，
峰变矮变胖。这比「拟直线再看残差」直观得多，而且不用先假设线是直的。

三个量（`gutter_projection`，窗口 ±BEND_SEARCH，行过滤见 `_rule_rows`）：

    peak   投影峰值 ÷ 采样行数——「有多少行的墨恰好落在这一个 x 上」，1.0 = 完美
    w50    峰的**半高宽**（px）——用户说的那个宽度，直线 3~4px
    w80    装下 80% 墨的最窄 x 跨度（px）——比半高宽更能反映"整条摊了多宽"

判据用 `w80`：它对"大部分墨在哪"敏感，而 `w50` 在双峰（线弯成两段）时会误判成窄。
量的是**直线拟合下**的弯度（把 `detect_borders` 给的线退化成直线再投影），所以
弯页上 `segments` 会是 3 而 w80 仍是直线的数——这正是「要不要切三段」的依据。

跑法：
    python scripts/measure_gutter_straightness.py --sample 40 --jobs 8
    python scripts/measure_gutter_straightness.py --books vol01 --pages 151,11,24
输出 `output/gutter_straightness.json`，并按页排出最弯的若干页。
原图路径用 GUJI_RAW 覆盖（默认 /home/user/rebuild_src）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.border_geometry import detect_borders  # noqa: E402

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
PAGE_TYPE = ROOT.parent / "open-guji-dataset" / "page-type" / "expected.json"

from open_guji_cv.utils.border_geometry import (  # noqa: E402
    gutter_projection, BEND_SEARCH, BEND_INK_W_MAX, BEND_MIN_ROWS)

# 投影/行过滤的实现**只在 border_geometry.gutter_projection 里有一份**——本脚本
# 曾自带一份，后来库里加了「局部一致性」闸（碎片是跳的、线是连的），两份就
# 分叉了：老实现把 vol02/3 判成最弯的页之一（w80 36），其实界行是直的。


def measure_page(args) -> dict | None:
    book, page = args
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    try:
        res = detect_borders(gray, expected_cols=9)
    except Exception:
        return None
    if not res.verticals or res.top is None or res.bottom is None:
        return None
    binm = (gray < 128).astype(np.uint8)
    h, w = binm.shape
    y0 = int(res.top.y_at(w / 2)) + 30
    y1 = int(res.bottom.y_at(w / 2)) - 30
    if y1 - y0 < 400:
        return None
    lines = []
    # 量的是**直线拟合下**的弯度——用拟合前留下的 verticals_straight，不能从
    # 三段线的 x_at_top/slope 反推（那是第一段的外推，量出来是错的）
    for i, V in enumerate(sorted(res.verticals_straight, key=lambda v: (w - 1) - v.x_at(h / 2.0)), 1):
        r = gutter_projection(binm, V.x_at, y0, y1, w)
        if r is None:
            continue
        pk, w50, w80, n = r
        lines.append(dict(col=i, peak=round(pk, 3), w50=w50, w80=w80, rows=n))
    if not lines:
        return None
    return dict(book=book, page=page, n_lines=len(lines), lines=lines,
                segments=res.vline_segments,
                w80_med=float(np.median([l["w80"] for l in lines])),
                w80_max=int(max(l["w80"] for l in lines)),
                peak_med=float(np.median([l["peak"] for l in lines])))


def body_pages(books, sample, explicit):
    if explicit:
        return [(books[0], x.strip()) for x in explicit.split(",") if x.strip()]
    rows = json.loads(PAGE_TYPE.read_text(encoding="utf-8"))
    pages = [(r["book"], r["page"]) for r in rows
             if r["book"] in set(books) and r.get("page_type") == "body"]
    out = []
    for b in books:
        bp = [p for p in pages if p[0] == b]
        step = max(1, len(bp) // sample) if sample else 1
        out += bp[::step][:sample] if sample else bp
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--pages", default="")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--top", type=int, default=12, help="列出最弯的几页")
    ap.add_argument("--out", default=str(ROOT / "output" / "gutter_straightness.json"))
    a = ap.parse_args()
    books = [b.strip() for b in a.books.split(",")]
    jobs = body_pages(books, a.sample, a.pages)
    print(f"量 {len(jobs)} 页，{a.jobs} 并行…")
    recs = []
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, r in enumerate(ex.map(measure_page, jobs, chunksize=1), 1):
            if r:
                recs.append(r)
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}")
    recs.sort(key=lambda r: -r["w80_med"])
    print(f"\n共 {len(recs)} 页有结果。w80 = 装下 80% 墨的最窄 x 跨度，越小越直\n")
    print(f"{'页':>12}{'线数':>5}{'w80中位':>9}{'w80最大':>9}{'峰值中位':>10}{'seg':>5}")
    for r in recs[:a.top]:
        print(f"{r['book'] + '/' + r['page']:>12}{r['n_lines']:>5}"
              f"{r['w80_med']:9.1f}{r['w80_max']:9d}{r['peak_med']:10.3f}{r['segments']:>5}")
    w = np.array([r["w80_med"] for r in recs])
    print(f"\n全样本 w80 中位: 中位={np.median(w):.1f}px 25分位={np.percentile(w, 25):.1f} "
          f"75分位={np.percentile(w, 75):.1f} 最大={w.max():.1f}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
