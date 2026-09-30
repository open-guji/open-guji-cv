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

【2026-09-30 M1 C 组：默认改读现行 v2 链，基线重冻为 `char-drop/expected_v2.json`】
旧读法吃 v1 `output/<册>/phase3_char_grid` + 页图（已退役，云端没有 → 静默扫到 0 页，原来「回归门通过」是假的）。
v2 口径（指标名与判据常数 RUN_INK/RUN_MIN_H/RUN_GAP/SEG_LO/SEG_HI/COVER 一字不动）：
  - 「单字墨段」取自 Step2 **列图**（已去噪、清过界行与上下版框）内容窗 [content_x+4, content_x-4] 的行墨投影，
    格高用 Step3 的 `period`；
  - 「被字格接住」= 该段的行落在 **Step4 判为 cell_type=="char" 的格**对应的 Step3 格 [y0,y1] 里
    （夹注 a/b 在 Step4 合成一格，按位置并集）——墨被**取出来**才算，不是墨在网格里就行；
  - 列号从右往左 1 起、y 是列图坐标。
  因列图已清掉列尾版框横条，v1 基线里「并非真字」的列尾墨疙瘩多半不再出现：**新旧数字不同口径**，
  旧值（16，另有 29 一说）只作趋势对照，见 artifacts/m1_gold/char_drop/MIGRATION.md。
`--v1` 保留旧读法。
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


def scan_v2(body: set, books=("vol01", "vol02")):
    """读 v2 产物，返回 (n_seg, dropped)。缺 Step4 产物的正文页现补（只补缺）。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _v2_step4 import V2Book

    n_seg = 0
    dropped: list[tuple] = []
    n_pages = 0
    skipped: list = []
    for book in books:
        pages = sorted(int(p) for b, p in body if b == book)
        if not pages:
            continue
        v = V2Book(book)
        miss = v.ensure(pages)
        for pg in pages:
            pc, cells = v.chars(pg), v.cells(pg)
            if pc is None or cells is None:
                skipped.append((book, pg))
                continue
            n_pages += 1
            for cc in cells.columns:
                ch = pc.column(cc.col)
                if not cc.ok or ch is None or not ch.ok or not cc.content_x:
                    continue
                img = v.col_img(pg, cc.col)
                x0 = int(max(0, cc.content_x[0])) + 4
                x1 = int(min(img.shape[1], cc.content_x[1])) - 4
                if x1 - x0 < 8:
                    continue
                proj = (img[:, x0:x1] < 160).sum(axis=1).astype(float)
                runs = col_runs(proj, float(x1 - x0), float(cc.period or 110.0))
                if not runs:
                    continue
                char_pos = {r.pos for r in ch.chars if r.cell_type == "char"}
                cov = np.zeros(img.shape[0], dtype=bool)
                for c in cc.cells:
                    if c.pos in char_pos:
                        y0 = int(max(0, c.y0)); y1_ = int(min(img.shape[0], c.y1))
                        if y1_ > y0:
                            cov[y0:y1_] = True
                for r in runs:
                    n_seg += 1
                    hit = cov[r[0]:r[1]].mean() if r[1] > r[0] else 0.0
                    if hit < COVER:
                        dropped.append((book, str(pg), cc.col, r[0], r[1], round(float(hit), 3)))
    return n_seg, dropped, n_pages, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="列出全部丢字条目（默认只列前 25 条）")
    ap.add_argument("--v1", action="store_true", help="旧读法（v1 phase3_char_grid，已退役）")
    a = ap.parse_args()

    ds = Path(a.dataset)
    gold = json.loads((ds.parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    rows = gold if isinstance(gold, list) else gold.get("pages", [])
    body = {(e["book"], str(e["page"])) for e in rows
            if e.get("page_type") == "body"}

    n_seg = 0
    dropped: list[tuple] = []
    v2_extra = ""
    if not a.v1:
        n_seg, dropped, n_pages, skipped = scan_v2(body)
        v2_extra = f"（v2，扫 {n_pages} 页" + (f"，{len(skipped)} 页无 v2 产物：{skipped[:6]}" if skipped else "") + "）"
    for book in (("vol01", "vol02") if a.v1 else ()):
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

    exp_p = ds / "char-drop" / ("expected.json" if a.v1 else "expected_v2.json")
    base = json.loads(exp_p.read_text(encoding="utf-8")) \
        if exp_p.exists() else {}
    print(v2_extra)
    print(f"单字段 {base.get('n_segs', n_seg)} → {n_seg}")
    print(f"没被字格接住 {base.get('n_dropped', len(dropped))} → {len(dropped)}")
    print(f"丢字率（单字段里没被字格接住）  {len(dropped)}/{n_seg} ({100.0 * len(dropped) / max(n_seg, 1):.3f}%)")
    for row in (dropped if a.all else dropped[:25]):
        # 注意不写「盖住 0%」：评测层 parse_metrics 会把「名字 数%」整行当指标，把逐条明细当成总体指标
        print(f"   ✗ {row[0]}/{row[1]} c{row[2]} y{row[3]}~{row[4]} "
              f"盖住比例={row[5]:.2f}")
    if len(dropped) > 25 and not a.all:
        print(f"   …另有 {len(dropped) - 25} 条")

    if a.update:
        exp_p.parent.mkdir(parents=True, exist_ok=True)
        exp_p.write_text(json.dumps(
            {"cover": COVER, "n_segs": n_seg, "n_dropped": len(dropped),
             **({} if a.v1 else {"chain": "v2 (column_warp 列图 + row_segment 1.12 + cell_shrink)",
                                 "note": "2026-09-30 M1 C 组：新口径首个基线；旧 v1 值(n_dropped 16)仅作趋势，不可直接比",
                                 "coords": "col 1 起自右；y0/y1 为列图坐标"}),
             "dropped": [list(r) for r in dropped]},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"写入金标：丢字 {len(dropped)} → {exp_p}")
        return
    if base:
        ok = len(dropped) <= base.get("n_dropped", 0)
        print("回归门：" + ("通过" if ok else "**失败**"))
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
