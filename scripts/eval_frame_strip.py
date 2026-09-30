"""评测列端格「去框后」的干净度（char-segmentation/frame-strip）。

口径（2026-08-25 用户 r4 定）：版框离列端字太近，格框一裁必然带进框线
——这不算错误截取，只要**后处理能消掉**。所以本测试集量的是产物图块
（已经过 strip_frame_debris）里还剩多少框渣，而不是切分时有没有碰到框。

三个指标：
  残余率   带框样本里，图块边缘带内仍有「与字身分离的块」的比例 → 目标 0
  误剥率   干净样本里，出现残余判定或字身墨低于基线的比例      → 红线 0
  字保全   全体样本里，字身（最大连通体）墨量 ≥ 金标基线的比例  → 红线 100%
           （基线取自去框前的产物；剥框只动独立连通体，字身不该少一个像素）

用法：PYTHONPATH=. python scripts/eval_frame_strip.py <数据集目录> [--source v2|v1]

## 2026-09-30（M1·A 道）：默认改读现行 v2 链

`--source v1`（旧）读 `output/<册>/phase4_chars/patches/<页>/<列>_<idx>.png`（退役链）。
金标挂的格位因切分口径换过几轮全部失效，旧脚本只印「0 个样本（65 个格位已消失）」——空跑。
`--source v2`（默认）读 `products/<册>/cell_shrink` + `cache/<册>/char_patch`，且**每条金标先过
「人当时看的图块还在不在」闸**（`patch_identity.locate`：拿 instances/patches 里存的人裁图块原图
去跟 v2 图块做二值墨 NCC 模板匹配，NCC≥0.90 且位移≤4px、尺寸差≤12px 才计分）。
没存图块的金标无从证明图还在，不计分，分原因列出；不拿算法判了什么当判据。
三个指标（残余率/误剥率/字保全）的定义与 v1 完全相同，只是只在通过闸的样本上算。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.extractor import (BINARY_THRESHOLD_PATCH,
                                               DEBRIS_GAP, DEBRIS_ZONE,
                                               STUB_MAX_H)


def _analyse(img: np.ndarray) -> tuple[int, bool]:
    """返回（字身墨量, 边缘带内是否仍有分离残块）。"""
    binary = (img < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return 0, False
    areas = st[1:, 4]
    main = int(np.argmax(areas)) + 1
    m_y0, m_y1 = int(st[main, 1]), int(st[main, 1] + st[main, 3])
    h = img.shape[0]
    zone, gap_min = DEBRIS_ZONE * h, DEBRIS_GAP * h
    residue = False
    for k in range(1, n):
        if k == main:
            continue
        y, ch = int(st[k, 1]), int(st[k, 3])
        # 框渣是**薄**的（版框线实测 1~11px）。没有这条，字自己那些与
        # 主体断开的部件会被算成残余——刻本墨色不匀，「書」的日部、
        # 「當」的上半、「諱」的言旁上横都可能与主体断开，落在边缘带里
        # 就冒充框渣（实测这三条的部件高 23~43px，而真框渣 ≤11px）。
        if ch > STUB_MAX_H:
            continue
        in_band = (y + ch >= h - zone) or (y <= zone)
        if not in_band:
            continue
        gap = (y - m_y1) if y >= m_y1 else (m_y0 - (y + ch))
        if gap >= gap_min:
            residue = True
    return int(areas.max()), residue


def main_v2(gold: list[dict], out: str | None) -> None:
    import collections
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from patch_identity import locate
    rows, reasons = [], collections.Counter()
    skipped = []
    for g in gold:
        loc = locate(g)
        if loc["status"] != "scored":
            reasons[loc["status"]] += 1
            skipped.append({**g, "status": loc["status"], "why": loc["why"]})
            continue
        ink, residue = _analyse(loc["patch"])
        rows.append({**g, "missing": False, "ink_now": ink, "residue": residue,
                     "ink_ok": ink >= g["main_ink"], "ncc": loc["ident"]["ncc"]})
    n = len(gold)
    print(f"frame-strip [v2 链]：金标 {n} 条；图像同一性通过并计分 {len(rows)}；不计分 {len(skipped)}"
          f"（{'、'.join(f'{k} {v}' for k, v in sorted(reasons.items())) or '—'}）")
    framed = [r for r in rows if r["frame"]]
    clean = [r for r in rows if not r["frame"]]

    def pct(a: int, b: int) -> str:
        return f"{a}/{b} ({a / b:.0%})" if b else "n/a"

    print(f"  frame-strip：{len(rows)} 个样本")
    print(f"  残余率（带框组仍有框渣）  {pct(sum(r['residue'] for r in framed), len(framed))}")
    print(f"  误剥率（干净组见残余）    {pct(sum(r['residue'] for r in clean), len(clean))}")
    print(f"  字保全（墨量 ≥ 基线）     {pct(sum(r['ink_ok'] for r in rows), len(rows))}")
    tol = [r for r in rows if r["ink_now"] >= 0.97 * r["main_ink"]]
    if rows:
        worst = min(r["ink_now"] / r["main_ink"] for r in rows)
        print(f"  字保全（容差 3%，附加指标）{pct(len(tol), len(rows))}，最差比值 {worst:.3f}"
              f"——v2 的矫正重采样与 v1 不逐像素相同，同一张图的 main_ink 会差零点几到几个百分点；"
              f"红线判读以逐像素看图为准（对位后旧有新无/新有旧无像素数同量级＝重采样，不是切字）")
    for r in rows:
        if not r["ink_ok"]:
            print(f"    ⚠ 字身墨低于基线 {r['book']}:{r['page']}:{r['col']}:{r['idx']} "
                  f"{r['ink_now']} < {r['main_ink']}（NCC {r['ncc']}）——先逐像素看图再定是切字还是渣清干净了")
    if out:
        Path(out).write_text(json.dumps({"scored": rows, "skipped": skipped},
                                        ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="数据集目录（含 frame-strip/expected.json）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--source", choices=("v2", "v1"), default="v2")
    args = ap.parse_args()

    p = Path(args.dataset)
    if p.name != "frame-strip":
        p = p / "frame-strip"
    gold = json.loads((p / "expected.json").read_text(encoding="utf-8"))
    if args.source == "v2":
        return main_v2(gold, args.out)

    rows = []
    for g in gold:
        patch = (Path("output") / g["book"] / "phase4_chars" / "patches"
                 / g["page"] / f"{g['col']}_{g['idx']}.png")
        if not patch.exists():
            rows.append({**g, "missing": True})
            continue
        img = cv2.imread(str(patch), cv2.IMREAD_GRAYSCALE)
        if img is None:
            rows.append({**g, "missing": True})
            continue
        ink, residue = _analyse(img)
        rows.append({**g, "missing": False, "ink_now": ink, "residue": residue,
                     "ink_ok": ink >= g["main_ink"]})

    live = [r for r in rows if not r["missing"]]
    framed = [r for r in live if r["frame"]]
    clean = [r for r in live if not r["frame"]]
    miss = len(rows) - len(live)

    def pct(a: int, b: int) -> str:
        return f"{a}/{b} ({a / b:.0%})" if b else "n/a"

    print(f"frame-strip：{len(live)} 个样本"
          + (f"（{miss} 个格位已消失）" if miss else ""))
    print(f"  残余率（带框组仍有框渣）  {pct(sum(r['residue'] for r in framed), len(framed))}")
    print(f"  误剥率（干净组见残余）    {pct(sum(r['residue'] for r in clean), len(clean))}")
    print(f"  字保全（墨量 ≥ 基线）     {pct(sum(r['ink_ok'] for r in live), len(live))}")
    bad = [r for r in live if not r["ink_ok"]]
    if bad:
        print("  ⚠ 字身墨低于基线（红线）：")
        for r in bad[:10]:
            print(f"    {r['book']}:{r['page']}:{r['col']}:{r['idx']} "
                  f"{r['ink_now']} < {r['main_ink']}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False),
                                  encoding="utf-8")


if __name__ == "__main__":
    main()
