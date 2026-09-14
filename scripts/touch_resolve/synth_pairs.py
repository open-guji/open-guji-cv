# -*- coding: utf-8 -*-
"""合成粘连字对：从本书干净字格纵向叠放，产出逐像素归属真值 + 字标签（零人工标注）。

    python scripts/touch_resolve/synth_pairs.py --book vol01 --n 20000 --out D:/data/touch_synth/vol01

「干净格」= Step3 判为 char、两侧格线都不穿墨（不在 cut_candidates 里）、墨外接框完整落在格内。
两格来自同一列（保留天然的水平错位），按墨外接框对齐叠放：
    g = B 的墨顶行 − A 的墨底行 − 1     （g<0 重叠，g=0 刚好相接，g>0 有空隙）
g 从一个偏向重叠的混合分布抽；B 再加 ±3px 水平抖动。
真值 owner：0 背景 / 1 A / 2 B / 3 两者都有墨（重叠像素，评测时按「任一边算对」）。
标签来自 align_ref（只取 align_op == equal 的位），没有就留空——像素归属训练不需要标签，
成对校验 / 模板实验才需要。

产出：<out>/pairs/{i:06d}.png（灰度窗口）、{i:06d}_own.png（owner 0..3）、<out>/meta.jsonl、<out>/cells.jsonl。
"""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from common import INK_TH, Loader, ink_bbox, page_key

GAP_MIX = [((-6, -1), 0.50), ((-12, -7), 0.20), ((-18, -13), 0.05), ((0, 2), 0.20), ((3, 6), 0.05)]
# 按 gold_geometry.py 量出的真实分布加权：真实 g 中位 -3、深于 -10 的占 3%；这里刻意多留一点深交错给训练用


def sample_gap(rng: random.Random) -> int:
    r = rng.random(); acc = 0.0
    for (lo, hi), p in GAP_MIX:
        acc += p
        if r <= acc:
            return rng.randint(lo, hi)
    return 0


def harvest_clean_cells(L: Loader, book: str, pages: list[int]) -> list[dict]:
    """全书干净字格：返回 dict(page, col, pos, slot, label, y0, y1, x_lo, x_hi, bbox)。"""
    out = []
    for pg in pages:
        cells = L.cells(book, pg)
        if cells is None:
            continue
        ar = L.store.read(book, "align_ref", page_key(pg), "align_ref")
        labels = {}
        if ar is not None and ar.anchored:
            for r in ar.chars:
                if r.align_op == "equal" and r.sub is None:
                    labels[(r.col, r.slot)] = r.align_char
        for cc in cells.columns:
            if not cc.ok or len(cc.cells) != len(cc.boundaries) - 1 or not cc.content_x:
                continue
            crossing = {c.k for c in cc.cut_candidates}
            img = L.column_image(book, pg, cc.col)
            if img is None:
                continue
            x_lo, x_hi = int(round(cc.content_x[0])), int(round(cc.content_x[1]))
            period = float(cc.period or cells.period or 0) or 1.0
            for i, c in enumerate(cc.cells):
                if c.kind != "char" or c.raised or c.ink_ratio < 0.03:
                    continue
                if i in crossing or (i + 1) in crossing:      # 上边界 = boundaries[i]，下边界 = boundaries[i+1]
                    continue
                y0, y1 = int(round(c.y0)), int(round(c.y1))
                crop = img[y0:y1, x_lo:x_hi]
                bb = ink_bbox(crop < INK_TH)
                if bb is None:
                    continue
                bx0, by0, bx1, by1 = bb
                h = by1 - by0
                if not (0.45 * period <= h <= 1.05 * period):
                    continue
                if by0 < 2 or by1 > crop.shape[0] - 2:          # 墨顶到格顶/墨底到格底要有余量，否则可能被切
                    continue
                out.append(dict(page=pg, col=cc.col, pos=c.pos, slot=c.slot,
                                label=labels.get((cc.col, c.slot), ""),
                                y0=y0, y1=y1, x_lo=x_lo, x_hi=x_hi, bbox=[bx0, by0, bx1, by1]))
    return out


def compose(L: Loader, book: str, A: dict, B: dict, g: int, dx: int) -> tuple[np.ndarray, np.ndarray, dict]:
    imgA = L.column_image(book, A["page"], A["col"])[A["y0"]:A["y1"], A["x_lo"]:A["x_hi"]]
    imgB = L.column_image(book, B["page"], B["col"])[B["y0"]:B["y1"], B["x_lo"]:B["x_hi"]]
    w = min(imgA.shape[1], imgB.shape[1])
    imgA, imgB = imgA[:, :w], imgB[:, :w]
    a_bot = A["bbox"][3] - 1
    b_top = B["bbox"][1]
    yB = a_bot + 1 + g - b_top
    H = max(imgA.shape[0], yB + imgB.shape[0])
    canvas = np.full((H, w), 255, np.uint8)
    ownA = np.zeros((H, w), bool); ownB = np.zeros((H, w), bool)
    canvas[: imgA.shape[0]] = np.minimum(canvas[: imgA.shape[0]], imgA)
    ownA[: imgA.shape[0]] = imgA < INK_TH
    # B 带水平抖动
    shifted = np.full_like(imgB, 255)
    if dx >= 0:
        shifted[:, dx:] = imgB[:, : w - dx]
    else:
        shifted[:, : w + dx] = imgB[:, -dx:]
    yb0, yb1 = max(0, yB), yB + imgB.shape[0]
    src0 = yb0 - yB
    canvas[yb0:yb1] = np.minimum(canvas[yb0:yb1], shifted[src0:])
    ownB[yb0:yb1] = shifted[src0:] < INK_TH
    owner = np.zeros((H, w), np.uint8)
    owner[ownA & ~ownB] = 1
    owner[ownB & ~ownA] = 2
    owner[ownA & ownB] = 3
    # 直线基线：能达到的最高墨归属一致率（只算 owner∈{1,2} 的像素）
    ink = owner > 0
    best_line, best_agree = None, -1.0
    a_rows = np.nonzero(ownA.any(axis=1))[0]; b_rows = np.nonzero(ownB.any(axis=1))[0]
    lo = int(min(a_rows.max(), b_rows.min())) - 12; hi = int(max(a_rows.max(), b_rows.min())) + 12
    r1 = (owner == 1).sum(axis=1); r2 = (owner == 2).sum(axis=1)
    c1 = np.cumsum(r1); c2 = np.cumsum(r2); nv = int(r1.sum() + r2.sum())
    for y in range(max(1, lo), min(H - 1, hi) + 1):
        ag = float((c1[y - 1] + (c2[-1] - c2[y - 1])) / max(1, nv))   # 行 < y 判 A、其余判 B
        if ag > best_agree:
            best_agree, best_line = ag, y
    meta = dict(g=g, dx=dx, yB=int(yB), H=int(H), w=int(w), a_ink_bottom=int(a_bot), b_ink_top=int(b_top + yB),
                n_shared=int((owner == 3).sum()), n_ink=int(ink.sum()),
                straight_best_y=best_line, straight_best_agree=round(best_agree, 4))
    return canvas, owner, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--pages", default="all", help="all | dev_set | 逗号页号")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--same-col", type=float, default=0.8, help="两格取自同一列的概率（否则同页）")
    a = ap.parse_args()
    out = Path(a.out or f"D:/data/touch_synth/{a.book}")
    (out / "pairs").mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)

    L = Loader()
    bk = L.book(a.book)
    if a.pages == "all":
        pages = sorted(int(p.stem[1:]) for p in (L.store.root / a.book / "row_segment").glob("p*.json"))
    elif a.pages == "dev_set":
        pages = list(bk.resolve_pages("dev_set"))
    else:
        pages = [int(x) for x in a.pages.split(",")]
    t0 = time.time()
    cells = harvest_clean_cells(L, a.book, pages)
    n_lab = sum(1 for c in cells if c["label"])
    print(f"{a.book}: {len(pages)} 页 → 干净字格 {len(cells)}（带标签 {n_lab}），{time.time() - t0:.0f}s")
    (out / "cells.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cells), encoding="utf-8")
    by_col = defaultdict(list); by_page = defaultdict(list)
    for c in cells:
        by_col[(c["page"], c["col"])].append(c); by_page[c["page"]].append(c)
    cols = [k for k, v in by_col.items() if len(v) >= 2]

    metas = []
    gaps = Counter()
    t0 = time.time()
    i = 0
    while i < a.n:
        if rng.random() < a.same_col:
            k = rng.choice(cols); pool = by_col[k]
        else:
            pg = rng.choice(list(by_page)); pool = by_page[pg]
            if len(pool) < 2:
                continue
        A, B = rng.sample(pool, 2)
        g = sample_gap(rng); dx = rng.randint(-3, 3)
        gray, owner, m = compose(L, a.book, A, B, g, dx)
        if m["n_ink"] == 0:
            continue
        fn = f"{i:06d}"
        cv2.imwrite(str(out / "pairs" / f"{fn}.png"), gray)
        cv2.imwrite(str(out / "pairs" / f"{fn}_own.png"), owner)
        m.update(dict(i=i, book=a.book, A={k: A[k] for k in ("page", "col", "pos", "slot", "label", "bbox")},
                      B={k: B[k] for k in ("page", "col", "pos", "slot", "label", "bbox")}))
        metas.append(m)
        gaps["overlap" if g < 0 else ("touch" if g <= 2 else "gap")] += 1
        i += 1
        if i % 2000 == 0:
            print(f"  {i}/{a.n}  {time.time() - t0:.0f}s", flush=True)
    (out / "meta.jsonl").write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in metas), encoding="utf-8")
    sb = np.array([m["straight_best_agree"] for m in metas])
    print(f"合成 {len(metas)} 对：{dict(gaps)}；直线最优归属一致率 mean {sb.mean():.4f}，<0.98 的占 {(sb < 0.98).mean():.1%}，"
          f"<0.95 的占 {(sb < 0.95).mean():.1%}")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
