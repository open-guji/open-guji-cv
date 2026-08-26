"""丢字普查：单字墨段有没有被**字格**接住（char-segmentation/char-drop）。

【为什么要单独一把尺子】
截断闸量「格线切进字身多深」，红线普查量「墨有没有落在网格覆盖的区间里」。
两把都绿，字仍可能丢——2026-08-26 实测：clip_refit 把网格挪到裁窗顶之上，
`cells_from_bounds` 拿负下标切片得到空数组，整格判 `empty`，格里那个真字
就此消失（vol01/60 c6/c7/c9、vol01/50 c5 各一枚，新首格墨率 0.34~0.40）。
**「墨在网格内」和「墨被取出来」是两把尺子**：前者绿不代表后者没丢。

量法（口径与 eval_truncation.col_runs 逐字一致，不然闸会跟着修法一起瞎）：
  1. 逐列取原始行墨投影，切出「单字墨段」（高度 0.45~1.35 格）；
  2. 每段算它被 `type == "char"` 的格覆盖了多少行；
  3. 覆盖不足 COVER 判「丢」。

回归门：丢字数只许降不许升（零容忍那一类，升一个就红）。
用法：PYTHONPATH=. python scripts/eval_char_drop.py <数据集目录> [--update]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

RUN_INK = 0.06        # 行墨占列宽这么多才算「有墨」
RUN_MIN_H = 14        # 短于此的段是渣
RUN_GAP = 6           # 间隙不超过这么多就并成一段
SEG_LO, SEG_HI = 0.45, 1.35   # 「单字段」高度窗（× 格高）
COVER = 0.5           # 段内被字格盖住的行数低于此比例 → 判丢


def col_runs(proj: np.ndarray, width: float, cell_h: float):
    on = proj > width * RUN_INK
    out, s = [], None
    for y, v in enumerate(on):
        if v and s is None:
            s = y
        if not v and s is not None:
            out.append([s, y]); s = None
    if s is not None:
        out.append([s, len(on)])
    out = [r for r in out if r[1] - r[0] >= RUN_MIN_H]
    merged: list[list[int]] = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= RUN_GAP:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))
    return [tuple(r) for r in merged
            if SEG_LO * cell_h <= r[1] - r[0] <= SEG_HI * cell_h]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="列出全部丢字条目（默认只列前 25 条）")
    a = ap.parse_args()

    ds = Path(a.dataset)
    gold = json.loads((ds.parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    rows = gold if isinstance(gold, list) else gold.get("pages", [])
    body = {(e["book"], str(e["page"])) for e in rows
            if e.get("page_type") == "body"}

    n_seg = 0
    dropped: list[tuple] = []
    for book in ("vol01", "vol02"):
        d = Path(a.out) / book / "phase3_char_grid"
        for gp in sorted(d.glob("*_char_grid.json")):
            page = gp.name.split("_")[0]
            if (book, page) not in body:
                continue
            g = json.loads(gp.read_text(encoding="utf-8"))
            img = cv2.imread(f"{a.out}/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            cell_h = float(g.get("grid", {}).get("cell_h") or 0) or 110.0
            for c in g.get("columns", []):
                x0 = int(max(0, c.get("left_x", 0))) + 4
                x1 = int(min(img.shape[1], c.get("right_x", 0))) - 4
                if x1 - x0 < 8:
                    continue
                proj = (img[:, x0:x1] < 160).sum(axis=1).astype(float)
                runs = col_runs(proj, float(x1 - x0), cell_h)
                if not runs:
                    continue
                cov = np.zeros(img.shape[0], dtype=bool)
                for ce in c.get("cells", []):
                    if ce.get("type") != "char":
                        continue
                    y0 = int(max(0, ce["y_top"]))
                    y1_ = int(min(img.shape[0], ce["y_bottom"]))
                    if y1_ > y0:
                        cov[y0:y1_] = True
                for r in runs:
                    n_seg += 1
                    hit = cov[r[0]:r[1]].mean() if r[1] > r[0] else 0.0
                    if hit < COVER:
                        dropped.append((book, page, c.get("index"),
                                        r[0], r[1], round(float(hit), 3)))

    exp_p = ds / "char-drop" / "expected.json"
    base = json.loads(exp_p.read_text(encoding="utf-8")) \
        if exp_p.exists() else {}
    print(f"单字段 {base.get('n_segs', n_seg)} → {n_seg}")
    print(f"没被字格接住 {base.get('n_dropped', len(dropped))} → {len(dropped)}")
    for row in (dropped if a.all else dropped[:25]):
        print(f"   ✗ {row[0]}/{row[1]} c{row[2]} y{row[3]}~{row[4]} "
              f"盖住 {row[5]:.0%}")
    if len(dropped) > 25 and not a.all:
        print(f"   …另有 {len(dropped) - 25} 条")

    if a.update:
        exp_p.parent.mkdir(parents=True, exist_ok=True)
        exp_p.write_text(json.dumps(
            {"cover": COVER, "n_segs": n_seg, "n_dropped": len(dropped),
             "dropped": [list(r) for r in dropped]},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"写入金标：丢字 {len(dropped)} → {exp_p}")
        return
    if base:
        ok = len(dropped) <= base.get("n_dropped", 0)
        print("回归门：" + ("通过" if ok else "**失败**"))
        raise SystemExit(0 if ok else 1)


main()
