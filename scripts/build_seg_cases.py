"""生成「格内净化」benchmark 样本（label_origin=synth）。

思路：**不造假墨**。从真实页面里挑出「结构上确定干净」的格位——
其墨迹连通体全部落在格线之内、不碰列边——把它们按书级格高重新码成
一列，每格加入 ±jitter 的纵向偏移（真实刻本里字有大有小、位置略偏，
正是溢出到邻格的成因），再画上界行竖线与版框横线。

于是每个像素属于哪一格是**构造时就知道的**，得到逐像素金标；而算法
面对的输入与真实页面同源同分布。关键正例（顶部部件与主体不连通的
「高/卞/示」类）按**结构**挑选——组件数 ≥2 且有纵向间隙——不依赖 OCR
标签，避开了「用 OCR 标签挑正例反而挑进一堆脏样本」的坑。

用法：
    python scripts/build_seg_cases.py output/book9 \
        --out ../open-guji-dataset/char-segmentation/cells --cases 40
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.extractor import (MIN_COMP_AREA_RATIO,
                                               RULE_H_RATIO, RULE_W_RATIO,
                                               _column_binary)
from open_guji_cv.utils.image_io import imread

SOURCE_DIR_CANDIDATES = ("s5_split", "s4_deskew", "s3_crop", "s6_binarize")
DETACH_MIN_GAP = 4        # 顶部部件与主体的纵向间隙下限（px）
EDGE_BAND = 3             # 碰到列边这么近就算不干净


def _source_dir(book_out: Path) -> Path:
    for name in SOURCE_DIR_CANDIDATES:
        d = book_out / name
        if d.is_dir() and any(d.iterdir()):
            return d
    raise SystemExit(f"找不到页面图目录于 {book_out}")


def harvest_clean_cells(book_out: Path) -> list[dict]:
    """扫全书，收集「结构上干净」的格位墨迹crop。"""
    src = _source_dir(book_out)
    grids = sorted((book_out / "phase3_char_grid").glob("*_char_grid.json"))
    pool: list[dict] = []
    for gp in grids:
        grid = json.loads(gp.read_text(encoding="utf-8"))
        stem = gp.name.replace("_char_grid.json", "")
        img_path = next((p for p in src.iterdir() if p.stem == stem), None)
        if img_path is None:
            continue
        page = imread(img_path)
        if page.ndim == 3:
            page = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
        ih, iw = page.shape[:2]
        for col in grid.get("columns", []):
            cells = [c for c in col.get("cells", []) if c.get("type") == "char"]
            if not cells:
                continue
            lx, rx = float(col["left_x"]), float(col["right_x"])
            col_w = rx - lx
            sx0, sx1 = int(round(max(0, lx))), int(round(min(iw, rx)))
            sy0 = int(round(max(0, min(float(c["y_top"]) for c in cells) - 20)))
            sy1 = int(round(min(ih, max(float(c["y_bottom"])
                                        for c in cells) + 20)))
            if sx1 - sx0 < 10 or sy1 - sy0 < 10:
                continue
            strip = page[sy0:sy1, sx0:sx1]
            binary = _column_binary(strip)
            n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
            w = strip.shape[1]
            for c in cells:
                top = float(c["y_top"]) - sy0
                bot = float(c["y_bottom"]) - sy0
                cell_h = bot - top
                min_area = MIN_COMP_AREA_RATIO * cell_h * col_w
                keep, ok = [], True
                for k in range(1, n):
                    x, y, cw, ch, area = stats[k]
                    if y >= bot or y + ch <= top:
                        continue                    # 与本格无交集
                    if ch > RULE_H_RATIO * cell_h and cw <= RULE_W_RATIO * col_w:
                        continue                    # 界行竖线：无歧义，忽略
                    if cw >= 0.9 * w and ch <= 0.06 * cell_h:
                        continue                    # 版框横线：同上
                    if area < min_area:
                        continue                    # 噪点：两种算法都会丢
                    if y < top - 1 or y + ch > bot + 1:
                        ok = False                  # 跨格线：归属有歧义，弃用
                        break
                    if x <= EDGE_BAND or x + cw >= w - EDGE_BAND:
                        ok = False                  # 贴列边：可能粘着界行
                        break
                    keep.append((k, y, y + ch))
                if not ok or not keep:
                    continue
                y0 = min(t for _k, t, _b in keep)
                y1 = max(b for _k, _t, b in keep)
                mask = np.zeros(labels.shape, bool)
                for k, _t, _b in keep:
                    mask |= labels == k
                sub_mask = mask[y0:y1]
                if sub_mask.sum() < 0.02 * cell_h * col_w:
                    continue
                xs = np.flatnonzero(sub_mask.any(axis=0))
                x0, x1 = int(xs.min()), int(xs.max()) + 1
                # 顶部部件与主体不连通？（结构判定，不看 OCR 标签）
                spans = sorted((t, b) for _k, t, b in keep)
                gap = max((spans[i + 1][0] - spans[i][1]
                           for i in range(len(spans) - 1)), default=0)
                pool.append({
                    "gray": strip[y0:y1, x0:x1].copy(),
                    "mask": sub_mask[:, x0:x1].copy(),
                    "cell_h": cell_h, "col_w": col_w,
                    "detached_top": len(keep) >= 2 and gap >= DETACH_MIN_GAP,
                    "text": c.get("text") or "",
                    "src": f"{stem}:{col['index']}:{c['index']}",
                })
    return pool


def compose_case(pool: list[dict], rng: random.Random, n_cells: int = 8,
                 jitter: float = 0.10, detach_ratio: float = 0.35) -> dict:
    """码一列合成样本。jitter 为格高比例的纵向抖动（溢出邻格的来源）。"""
    detached = [c for c in pool if c["detached_top"]]
    plain = [c for c in pool if not c["detached_top"]]
    picks = []
    for _ in range(n_cells):
        bag = detached if (detached and rng.random() < detach_ratio) else plain
        picks.append(rng.choice(bag or pool))

    cell_h = float(np.median([c["cell_h"] for c in pool]))
    col_w = int(round(float(np.median([c["col_w"] for c in pool]))))
    margin = int(round(cell_h * 0.5))
    h = int(round(n_cells * cell_h)) + 2 * margin
    canvas = np.full((h, col_w), 245, np.uint8)
    owner = np.zeros((h, col_w), np.int32)
    cells, tags = [], {}

    for i, ch in enumerate(picks):
        top = margin + i * cell_h
        cells.append({"index": i, "y_top": round(top, 2),
                      "y_bottom": round(top + cell_h, 2)})
        g, m = ch["gray"], ch["mask"]
        # 按目标格高缩放（各格字大小本就有出入，这里保留其原始比例再抖动）
        scale = cell_h / max(ch["cell_h"], 1e-6)
        if abs(scale - 1) > 0.01:
            g = cv2.resize(g, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
            m = cv2.resize(m.astype(np.uint8), (g.shape[1], g.shape[0]),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
        gh, gw = g.shape
        dy = int(round(rng.uniform(-jitter, jitter) * cell_h))
        y = int(round(top + (cell_h - gh) / 2)) + dy
        x = int(round((col_w - gw) / 2 + rng.uniform(-0.02, 0.02) * col_w))
        y0, x0 = max(0, y), max(0, x)
        y1, x1 = min(h, y + gh), min(col_w, x + gw)
        if y1 <= y0 or x1 <= x0:
            continue
        gs = g[y0 - y:y1 - y, x0 - x:x1 - x]
        ms = m[y0 - y:y1 - y, x0 - x:x1 - x]
        region = canvas[y0:y1, x0:x1]
        canvas[y0:y1, x0:x1] = np.where(ms, np.minimum(region, gs), region)
        owner[y0:y1, x0:x1][ms] = i + 1
        tags[i] = (["detached_top"] if ch["detached_top"] else []) + \
                  (["overflow"] if abs(dy) > 0.06 * cell_h else [])

    # 界行竖线（左右）+ 版框横线（上下），都是真实污染源
    lw = max(2, int(round(col_w * 0.025)))
    for side in ("l", "r"):
        if rng.random() < 0.85:
            xs = slice(0, lw) if side == "l" else slice(col_w - lw, col_w)
            canvas[:, xs] = np.minimum(canvas[:, xs], rng.randint(40, 110))
    if rng.random() < 0.5:
        t = max(2, int(round(cell_h * 0.03)))
        canvas[:t, :] = np.minimum(canvas[:t, :], rng.randint(40, 110))
    if rng.random() < 0.5:
        t = max(2, int(round(cell_h * 0.03)))
        canvas[-t:, :] = np.minimum(canvas[-t:, :], rng.randint(40, 110))

    noise = rng.gauss
    canvas = np.clip(canvas.astype(np.int16) +
                     np.array([[noise(0, 4) for _ in range(col_w)]
                               for _ in range(h)], np.int16), 0, 255).astype(np.uint8)

    # 污染标记：本格金标之外还有别的墨压进[格线±padding]范围
    ink = _column_binary(canvas).astype(bool)
    for c in cells:
        i = c["index"]
        pad = cell_h * 0.08
        band = slice(max(0, int(c["y_top"] - pad)),
                     min(h, int(c["y_bottom"] + pad)))
        foreign = ink[band] & (owner[band] != i + 1)
        if foreign.sum() > 0.004 * cell_h * col_w:
            tags.setdefault(i, []).append("contaminated")
        c["tags"] = sorted(set(tags.get(i, [])))
    return {"strip": canvas, "owner": owner, "cells": cells,
            "cell_h": round(cell_h, 2), "col_w": float(col_w),
            "sources": [c["src"] for c in picks]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out", help="output/bookX（需已跑过 segment）")
    ap.add_argument("--out", required=True, help="样本输出目录")
    ap.add_argument("--cases", type=int, default=40)
    ap.add_argument("--cells", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260821)
    ap.add_argument("--pipeline-version", default="")
    args = ap.parse_args()

    book_out = Path(args.book_out)
    pool = harvest_clean_cells(book_out)
    n_det = sum(c["detached_top"] for c in pool)
    print(f"干净格位池 {len(pool)} 个（其中顶部分离 {n_det} 个）")
    if len(pool) < 20:
        raise SystemExit("干净样本太少，换更大的书或放宽筛选")

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for n in range(args.cases):
        case = compose_case(pool, rng, n_cells=args.cells)
        d = out / f"{n + 1:03d}"
        d.mkdir(exist_ok=True)
        cv2.imwrite(str(d / "strip.png"), case["strip"])
        cv2.imwrite(str(d / "gold.png"), case["owner"].astype(np.uint8))
        (d / "case.json").write_text(json.dumps({
            "case_id": d.name,
            "label_origin": "synth",
            "source_item": book_out.name,
            "pipeline_version": args.pipeline_version,
            "cell_h": case["cell_h"], "col_w": case["col_w"],
            "cells": case["cells"],
            "composed_from": case["sources"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {args.cases} 个样本 → {out}")


if __name__ == "__main__":
    main()
