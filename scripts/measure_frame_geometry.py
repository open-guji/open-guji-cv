# -*- coding: utf-8 -*-
"""版框几何常数实测：内框线宽 / 外框条宽 / 内外框间距，按边分开统计。

**为什么单独有这么个脚本**：这几个常数是 Step1 一堆判据的地基（外框搜索窗口、
「这条线是不是版框」的门槛、抬头框的间距先验），先前只在 14 页金标里量过、
每边 n=4~5，太薄。这个脚本**不需要人工标注**——清楚的页上内框线本身就是最强
的墨，直接从真墨量即可，所以可以在整册上跑。

口径（以**内框线心**为 0，向外为正；线心与边沿都取半高亚像素）：
    inner_w   内框线半高宽
    near/far  外框条朝内/朝外那一侧的半高交点
    bar_w     = far - near        外框条宽度
    gap_near  = near              内心 → 外条近沿
    gap_far   = far               内心 → 外条外延（**就是金标 `*_outer_offset` 的口径**）

只统计「清楚」的边：内框峰墨 >= INNER_CLEAR、外条峰墨 >= OUTER_CLEAR，且内框线
半高宽 <= INNER_W_MAX。糊页的数进来会把常数拉偏，而且糊页本来就不该用来定常数。
**线宽那道闸是必须的**——末行字那一片墨也能有 0.5 以上的行墨占比，光看墨量拦不住，
混进来会把下框的「内心→外延」从 34.3±3.7 拉成 30.3±9.8。

**已知的两条坑**（都是量出来的，别再踩）：
- **外条近沿不可用，只有远沿（外延）稳**。外条是从**内侧**磨掉的：清楚页近沿
  在 +15~+17，磨损页漂到 +28~+34，而远沿只从 +33~+38 漂到 +39~+45。拿近沿去
  反推内框位置会错十几 px。
- **版框四边不等距**。竖直的外延间距明显大于上下。所以「内外间距全页一致」这个
  判据只在**同一条边**上成立，跨边要按边校正（见 `OUTER_PRIOR_SHIFT`）。

起点用 `detect_borders()` 找到的版框线，但**量之前先把原点精修到真墨峰**，
所以算法的残余误差不进结果；而且「清楚」这道闸本身就要求那条线上有强墨，
线找歪了的页会被自动筛掉。

跑法：
    python scripts/measure_frame_geometry.py --sample 40      # 每册抽 40 页
    python scripts/measure_frame_geometry.py --books vol01 --pages 24,26,65
    python scripts/measure_frame_geometry.py --sample 40 --jobs 8 --out out.json
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

INNER_CLEAR, OUTER_CLEAR = 0.45, 0.60
INNER_W_MAX = 10.0     # 内框线半高宽上限。真版框线实测 4~8px；**这道闸是必须的**
                       # ——末行字那一片墨也能有 0.5 以上的行墨占比，混进来会把
                       # 「内心→外延」整体拉小（下框 34.3→30.3px、标准差 3.7→9.8）
LO, HI = -25, 120          # 剖面范围（相对内框线，向外为正）
ORIGIN_SNAP = 6            # 精修原点时在 ±这么多 px 里找真墨峰


def _halfwidth(pr: dict[int, float], c: int) -> tuple[float, float]:
    """峰 c 的半高亚像素交点 (近侧, 远侧)。"""
    half = pr[c] / 2.0
    a = c
    while a - 1 in pr and pr[a - 1] >= half:
        a -= 1
    b = c
    while b + 1 in pr and pr[b + 1] >= half:
        b += 1

    def cross(i, j):
        p0, p1 = pr[i], pr[j]
        return float(i) if p0 == p1 else i + (p0 - half) / (p0 - p1) * (j - i)

    lo = cross(a, a - 1) if a - 1 in pr and pr[a - 1] < half else float(a)
    hi = cross(b, b + 1) if b + 1 in pr and pr[b + 1] < half else float(b)
    return lo, hi


def _centroid(pr: dict[int, float], c: int) -> float:
    """半高以上加权质心——比 argmax 稳，量线心用。"""
    half = pr[c] / 2.0
    a = c
    while a - 1 in pr and pr[a - 1] >= half:
        a -= 1
    b = c
    while b + 1 in pr and pr[b + 1] >= half:
        b += 1
    ws = [pr[o] for o in range(a, b + 1)]
    return float(np.average(range(a, b + 1), weights=ws))


def measure_page(args) -> list[dict]:
    book, page = args
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return []
    try:
        res = detect_borders(gray, expected_cols=9)
    except Exception:
        return []
    if not res.verticals or res.top is None or res.bottom is None:
        return []
    binm = (gray < 128).astype(np.uint8)
    h, w = binm.shape
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    xs = np.arange(int((w - 1) - vx[-1] + 20), int((w - 1) - vx[0] - 20), 2)
    ys = np.arange(int(h * 0.15), int(h * 0.85), 3)
    if len(xs) < 50 or len(ys) < 50:
        return []

    out = []
    for kind in ("top", "bottom", "vert_right", "vert_left"):
        if kind.startswith("vert"):
            V = res.verticals[0] if kind == "vert_right" else res.verticals[-1]
            sgn = -1 if kind == "vert_right" else 1
            base = np.array([(w - 1) - V.x_at(y) for y in ys])
            pr = {}
            for o in range(LO, HI + 1):
                xx = (base - o * sgn).astype(int)
                ok = (xx >= 0) & (xx < w)
                pr[o] = float(binm[ys[ok], xx[ok]].mean()) if ok.any() else 0.0
        else:
            L = res.top if kind == "top" else res.bottom
            sgn = -1 if kind == "top" else 1
            base = np.array([L.y_at((w - 1) - x) for x in xs])
            pr = {}
            for o in range(LO, HI + 1):
                yy = np.rint(base + o * sgn).astype(int)
                ok = (yy >= 0) & (yy < h)
                pr[o] = float(binm[yy[ok], xs[ok]].mean()) if ok.any() else 0.0

        ic = max(range(-ORIGIN_SNAP, ORIGIN_SNAP + 1), key=lambda o: pr[o])
        oc = max(range(8, HI + 1), key=lambda o: pr[o])
        if pr[ic] < INNER_CLEAR or pr[oc] < OUTER_CLEAR:
            continue
        origin = _centroid(pr, ic)          # 原点精修到真墨线心，去掉算法残差
        ilo, ihi = _halfwidth(pr, ic)
        if ihi - ilo > INNER_W_MAX:
            continue                        # 太宽 => 那是字行不是版框线
        olo, ohi = _halfwidth(pr, oc)
        out.append(dict(book=book, page=page, kind=kind,
                        inner_peak=round(pr[ic], 3), outer_peak=round(pr[oc], 3),
                        inner_w=round(ihi - ilo, 2),
                        near=round(olo - origin, 2), far=round(ohi - origin, 2),
                        bar_w=round(ohi - olo, 2)))
    return out


def body_pages(books, sample, explicit):
    if explicit:
        return [(books[0], p.strip()) for p in explicit.split(",")]
    want = set(books)
    rows = json.loads(PAGE_TYPE.read_text(encoding="utf-8"))
    pages = [(r["book"], r["page"]) for r in rows
             if r["book"] in want and r.get("page_type") == "body"]
    if sample and len(pages) > sample * len(books):
        out = []
        for b in books:
            bp = [p for p in pages if p[0] == b]
            step = max(1, len(bp) // sample)
            out += bp[::step][:sample]
        return out
    return pages


def report(recs):
    lab = {"top": "上框", "bottom": "下框", "vert_right": "竖直·右", "vert_left": "竖直·左"}
    print(f"\n{'边':>9}{'n':>5} | {'内框线宽':>12}{'外框条宽':>12}"
          f"{'内心→外条近沿':>16}{'内心→外条外延':>16}")
    stats = {}
    for kind in ("top", "bottom", "vert_right", "vert_left"):
        v = [r for r in recs if r["kind"] == kind]
        if not v:
            continue
        a = {k: np.array([r[k] for r in v]) for k in ("inner_w", "bar_w", "near", "far")}
        stats[kind] = {k: (float(x.mean()), float(x.std())) for k, x in a.items()}
        stats[kind]["n"] = len(v)
        f = lambda k: f"{a[k].mean():6.1f} ± {a[k].std():4.1f}"   # noqa: E731
        print(f"{lab[kind]:>9}{len(v):>5} | {f('inner_w'):>12}{f('bar_w'):>12}"
              f"{f('near'):>16}{f('far'):>16}")

    # 四边不等距：只用同一页上两边都清楚的样本配对，去掉页间差异
    print("\n同页配对差（竖直外延 − 上/下外延），检验版框是不是四边等距：")
    by = {}
    for r in recs:
        by.setdefault((r["book"], r["page"]), {})[r["kind"]] = r
    for kind in ("top", "bottom"):
        d = []
        for _, v in by.items():
            vt = [v[k]["far"] for k in ("vert_right", "vert_left") if k in v]
            if vt and kind in v:
                d.append(float(np.mean(vt)) - v[kind]["far"])
        if d:
            arr = np.array(d)
            print(f"    竖直 − {lab[kind]}: 均值={arr.mean():+.1f}px 标准差={arr.std():.1f} "
                  f"中位={np.median(arr):+.1f} (n={len(arr)})")
            stats.setdefault("asym", {})[kind] = (float(arr.mean()), float(arr.std()), len(arr))
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--pages", default="", help="逗号分隔；给了就忽略 --sample")
    ap.add_argument("--sample", type=int, default=40, help="每册抽多少页正文页")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "output" / "frame_geometry.json"))
    a = ap.parse_args()
    books = [b.strip() for b in a.books.split(",")]
    jobs = body_pages(books, a.sample, a.pages)
    print(f"量 {len(jobs)} 页（{', '.join(books)}），{a.jobs} 并行…")
    recs = []
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, r in enumerate(ex.map(measure_page, jobs, chunksize=1), 1):
            recs += r
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)} 页，已收 {len(recs)} 条清楚边")
    print(f"\n共 {len(recs)} 条清楚边（内框峰墨 >= {INNER_CLEAR}、外条峰墨 >= {OUTER_CLEAR}）")
    stats = report(recs)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"stats": stats, "records": recs},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
