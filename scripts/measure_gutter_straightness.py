# -*- coding: utf-8 -*-
"""界行「直不直」的指标：把整条界行往 x 轴投影，看峰有多高、多窄。

**用户给的判据（2026-09-02）**：一条界行整条投到 x 轴上——线越直，墨全落在同
一个 x 上，峰就越高、越窄；**最直的只有 3~4px 宽**。线越弯，墨被摊到更多 x 上，
峰变矮变胖。这比「拟直线再看残差」直观得多，而且不用先假设线是直的。

三个量（都在 `detect_borders()` 找到的界行附近 ±SEARCH px 的窗口里算）：

    peak   投影峰值 ÷ 采样行数——「有多少行的墨恰好落在这一个 x 上」，1.0 = 完美
    w50    峰的**半高宽**（px）——用户说的那个宽度，直线 3~4px
    w80    装下 80% 墨的最窄 x 跨度（px）——比半高宽更能反映"整条摊了多宽"

判据用 `w80`：它对"大部分墨在哪"敏感，而 `w50` 在双峰（线弯成两段）时会误判成窄。

⚠️ **投影必须只在版框内的 y 范围做**，且要把撞上字的行剔掉，否则量的是字不是线。
本脚本用「该行在窗口里的墨宽 <= INK_W_MAX」来剔——界行本身只有 3~6px 宽，
一行里超过这个宽度说明这一行的窗口被笔画占了。

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

SEARCH = 34        # 投影窗口半宽（px）——要盖得住弯幅，又别宽到吃进邻列的字
Y_STEP = 2         # 沿 y 每隔几行取一次
INK_W_MAX = 9      # 一行墨宽超过这个就当被笔画占了，不计入投影
MIN_ROWS = 200     # 有效行数少于这个就不给结论


def _one_line(binm, V, w, h, y0, y1):
    """返回 (peak, w50, w80, n_rows)。投影只统计"这一行的墨确实像界行"的行。"""
    ys = np.arange(y0, y1, Y_STEP)
    proj = np.zeros(SEARCH * 2 + 1, np.float64)
    n = 0
    for y in ys:
        c = int(round((w - 1) - V.x_at(y)))
        lo, hi = c - SEARCH, c + SEARCH + 1
        if lo < 0 or hi > w:
            continue
        row = binm[y, lo:hi]
        k = int(row.sum())
        if k == 0 or k > INK_W_MAX:
            continue                    # 空行 / 被笔画占了的行，都不算
        proj += row
        n += 1
    if n < MIN_ROWS:
        return None
    p = proj / n                        # 每个 x 上"有多少比例的行落了墨"
    pk = float(p.max())
    if pk <= 0:
        return None
    half = pk / 2.0
    w50 = int((p >= half).sum())
    # w80：装下 80% 墨的最窄连续跨度
    total = p.sum()
    need = total * 0.80
    best = len(p)
    s = 0.0
    a = 0
    for b in range(len(p)):
        s += p[b]
        while s - p[a] >= need:
            s -= p[a]
            a += 1
        if s >= need:
            best = min(best, b - a + 1)
    return pk, w50, int(best), n


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
    for i, V in enumerate(sorted(res.verticals, key=lambda v: (w - 1) - v.x_at(h / 2.0)), 1):
        r = _one_line(binm, V, w, h, y0, y1)
        if r is None:
            continue
        pk, w50, w80, n = r
        lines.append(dict(col=i, peak=round(pk, 3), w50=w50, w80=w80, rows=n))
    if not lines:
        return None
    return dict(book=book, page=page, n_lines=len(lines), lines=lines,
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
    print(f"{'页':>12}{'线数':>5}{'w80中位':>9}{'w80最大':>9}{'峰值中位':>10}")
    for r in recs[:a.top]:
        print(f"{r['book'] + '/' + r['page']:>12}{r['n_lines']:>5}"
              f"{r['w80_med']:9.1f}{r['w80_max']:9d}{r['peak_med']:10.3f}")
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
