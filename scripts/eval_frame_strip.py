"""评测列端格「去框后」的干净度（char-segmentation/frame-strip）。

口径（2026-08-25 用户 r4 定）：版框离列端字太近，格框一裁必然带进框线
——这不算错误截取，只要**后处理能消掉**。所以本测试集量的是产物图块
（已经过 strip_frame_debris）里还剩多少框渣，而不是切分时有没有碰到框。

三个指标：
  残余率   带框样本里，图块边缘带内仍有「与字身分离的块」的比例 → 目标 0
  误剥率   干净样本里，出现残余判定或字身墨低于基线的比例      → 红线 0
  字保全   全体样本里，字身（最大连通体）墨量 ≥ 金标基线的比例  → 红线 100%
           （基线取自去框前的产物；剥框只动独立连通体，字身不该少一个像素）

用法：PYTHONPATH=. python scripts/eval_frame_strip.py <数据集目录>
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="数据集目录（含 frame-strip/expected.json）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    p = Path(args.dataset)
    if p.name != "frame-strip":
        p = p / "frame-strip"
    gold = json.loads((p / "expected.json").read_text(encoding="utf-8"))

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
