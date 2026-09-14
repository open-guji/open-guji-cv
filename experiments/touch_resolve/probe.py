# -*- coding: utf-8 -*-
"""探针：金标 → 当下产物 对得上多少；出几张双格窗口图肉眼核对坐标口径。

    python experiments/touch_resolve/probe.py [--n 8] [--out DIR]

图上：蓝 = 现役直线格线；绿 = 现役实际切法（缝）；红 = 人工金标（折线或直线）。
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from common import (Loader, OUT_ROOT, seam_chosen, seam_gold, seam_straight, seams_candidates,
                    window, half_patch, side_masks, ink_agreement)


def draw_case(case, img, scale: int = 2) -> np.ndarray:
    win, y0, x0 = window(case, img, pad=6)
    vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
    vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    def poly(seam, color, thick=1):
        pts = [(int(x * scale), int((seam[x] - y0) * scale)) for x in range(len(seam))]
        for a, b in zip(pts[:-1], pts[1:]):
            cv2.line(vis, a, b, color, thick)

    poly(seam_straight(case), (255, 0, 0))
    poly(seam_chosen(case), (0, 180, 0))
    poly(seam_gold(case), (0, 0, 255))
    # 两半（按金标）
    win0, y00, _ = window(case, img, pad=0)
    above, below = side_masks(win0.shape, seam_gold(case), y00)
    parts = [vis]
    for m in (above, below):
        hp = half_patch(win0, m)
        if hp is None:
            hp = np.full((20, 20), 255, np.uint8)
        hp = cv2.resize(hp, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        canvas = np.full((vis.shape[0], hp.shape[1] + 8, 3), 200, np.uint8)
        canvas[: hp.shape[0], 4: 4 + hp.shape[1]] = cv2.cvtColor(hp, cv2.COLOR_GRAY2BGR)
        parts.append(canvas)
    sheet = np.concatenate(parts, axis=1)
    label = f"{case.id} {case.verdict} {case.char_above}/{case.char_below}"
    cv2.putText(sheet, label.encode("ascii", "ignore").decode(), (4, 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (0, 0, 0), 1)
    return sheet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default=str(OUT_ROOT / "probe"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    L = Loader()
    items = L.gold_items()
    reasons = Counter()
    cases = []
    for it in items:
        c, why = L.resolve(it)
        reasons[why if c is None else "ok"] += 1
        if c is not None:
            cases.append(c)
    print(f"金标 {len(items)} 条 → 对上当下产物 {len(cases)} 条")
    for k, v in reasons.most_common():
        print(f"  {k:40s} {v}")
    n_img = sum(1 for c in cases if L.image_of(c) is not None)
    print(f"列图可取 {n_img}/{len(cases)}")

    # 各口径的分布
    vc = Counter(c.verdict for c in cases)
    print("verdict:", dict(vc))
    n_poly = sum(1 for c in cases if c.gold_poly and len(c.gold_poly) >= 2)
    n_chars = sum(1 for c in cases if c.has_chars())
    n_multi = sum(1 for c in cases if c.cp is not None and len(c.cp.candidates) >= 2)
    print(f"带折线 {n_poly}  带上下字 {n_chars}  当下有多候选 {n_multi}")

    # 现役切法 vs 金标：像素级墨归属一致率（只看窗口内墨像素）
    agree = []
    agree_straight = []
    for c in cases:
        img = L.image_of(c)
        if img is None:
            continue
        win, y0, _ = window(c, img)
        agree.append(ink_agreement(win, seam_chosen(c), seam_gold(c), y0))
        agree_straight.append(ink_agreement(win, seam_straight(c), seam_gold(c), y0))
    agree = np.array(agree); agree_straight = np.array(agree_straight)
    print(f"墨归属一致率（现役缝 vs 金标）: mean {agree.mean():.4f}  <0.99: {(agree < 0.99).mean():.1%}  "
          f"<0.95: {(agree < 0.95).mean():.1%}")
    print(f"墨归属一致率（直线 vs 金标）  : mean {agree_straight.mean():.4f}  <0.99: {(agree_straight < 0.99).mean():.1%}")

    # 出图：优先 overlap/moved 带折线的，再补 ok
    pick = [c for c in cases if c.gold_poly and c.verdict in ("overlap", "moved")][: a.n // 2]
    pick += [c for c in cases if c.verdict == "moved" and not c.gold_poly][: a.n // 4]
    pick += [c for c in cases if c.verdict == "ok"][: a.n - len(pick)]
    for c in pick:
        img = L.image_of(c)
        if img is None:
            continue
        sheet = draw_case(c, img)
        fn = out / (c.id.replace(":", "_") + ".png")
        cv2.imwrite(str(fn), sheet)
        cands = [(k, int(np.abs(s - c.straight_y).max())) for k, s in seams_candidates(c)]
        print(f"  {c.id:18s} {c.verdict:8s} {c.char_above}/{c.char_below} gold_y={c.gold_y:.0f} "
              f"straight={c.straight_y:.0f} period={c.period:.0f} cands={cands} → {fn.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
