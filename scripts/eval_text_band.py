"""文字带窗口够不够装下一整列（char-segmentation/text-band）。

列的纵向窗口来自 phase2 的 `inner_frame` 上下界。版面检测把**正文中间的
某条横线**当成上框或下框时，窗口能塌到只剩三分之一页——窗外的字全部被
判空、静默丢掉。实测两册 21 张正文页中招，最惨的 vol02/97 只切出 47 个
字格（正文页中位 168）。

这个量**不需要人工标注**：文字带高是书级刚性常量

    应有窗口高 = 每列字数 × 书级格高（全书格高中位）

窗口短过它一大截就是版面检测认错了线。金标记「当前哪些页的窗口偏短、
偏到多少」，回归看的是：不许出现新的塌陷页，已塌的不许塌得更狠，
字格总数不许掉。

用法：PYTHONPATH=. python scripts/eval_text_band.py <数据集目录> [--update]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

SHORT_T = 0.90      # 窗口高 / 应有 低于此 → 记一张「窗口偏短」页
DROP_TOL = 0.02     # 字格总数允许的下滑（比例）


def scan(dataset: str, out: str = "output") -> dict:
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    body = {(r["book"], r["page"]) for r in gold if r["page_type"] == "body"}
    short: dict[str, float] = {}
    n_cells = 0
    n_pages = 0
    for book_dir in sorted(Path(out).glob("vol*")):
        book = book_dir.name
        grids = sorted((book_dir / "phase3_char_grid").glob("*_char_grid.json"))
        hs = []
        for gp in grids:
            ch = (json.loads(gp.read_text(encoding="utf-8")).get("grid")
                  or {}).get("cell_h")
            if ch:
                hs.append(ch)
        if not hs:
            continue
        cell_h = float(np.median(hs))
        for gp in grids:
            page = gp.stem.replace("_char_grid", "")
            if (book, page) not in body:
                continue
            g = json.loads(gp.read_text(encoding="utf-8"))
            n = g.get("chars_per_line") or 21
            lp = book_dir / "phase2_layout" / f"{page}_layout.json"
            if not lp.exists():
                continue
            n_pages += 1
            n_cells += sum(1 for c in g.get("columns") or []
                           for x in c.get("cells", []) if x.get("type") == "char")
            inner = (json.loads(lp.read_text(encoding="utf-8")).get("borders")
                     or {}).get("inner_frame") or {}
            t = (inner.get("top") or {}).get("intercept")
            b = (inner.get("bottom") or {}).get("intercept")
            band = g.get("grid", {}).get("band_widened")
            if band:
                continue          # 已被 Pass 2a4 放开，不再算塌陷
            if g.get("grid", {}).get("band_checked"):
                # Pass 2a4 拿真像素比过了：整页放开并**没有**更好
                # （漏墨没减半、字格没多、丢字没少）——短窗口在这一页
                # 没有造成覆盖损失。窗口比照旧偏短（上游 inner_frame
                # 的病，归 phase2 修），但不记成切分层的「塌陷」。
                # 2026-08-26：clip_refit 把这些页的原网格修准之后，
                # 11 张页从「靠放开窗口救回来」变成「本来就不用救」，
                # 字格 1800 → 1801、文字跨度逐页几乎不变。
                continue
            if t is None or b is None:
                continue
            ratio = (b - t) / (n * cell_h)
            if ratio < SHORT_T:
                short[f"{book}/{page}"] = round(ratio, 3)
    return {"short_threshold": SHORT_T, "n_body_pages": n_pages,
            "n_char_cells": n_cells, "short_pages": short}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    a = ap.parse_args()
    shard = Path(a.dataset) / "text-band" / "expected.json"
    got = scan(a.dataset, a.out)
    if a.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标：正文 {got['n_body_pages']} 页、字格 "
              f"{got['n_char_cells']}、窗口偏短 {len(got['short_pages'])} 页 → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))
    gp, tp = gold.get("short_pages", {}), got.get("short_pages", {})
    print(f"正文页 {gold['n_body_pages']} → {got['n_body_pages']}；"
          f"字格 {gold['n_char_cells']} → {got['n_char_cells']}")
    print(f"窗口偏短页 {len(gp)} → {len(tp)}")
    new = sorted(set(tp) - set(gp))
    gone = sorted(set(gp) - set(tp))
    worse = [k for k in sorted(set(tp) & set(gp)) if tp[k] < gp[k] - 0.01]
    for k in gone:
        print(f"  ✔ 修好 {k}（金标 {gp[k]}）")
    for k in new:
        print(f"  ✗ 新塌陷 {k} {tp[k]}")
    for k in worse:
        print(f"  ✗ 塌得更狠 {k} {gp[k]} → {tp[k]}")
    lost = got["n_char_cells"] < gold["n_char_cells"] * (1 - DROP_TOL)
    if lost:
        print(f"  ✗ 字格总数掉了超过 {DROP_TOL:.0%}")
    ok = not new and not worse and not lost
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
