"""快测台：只对指定字格重跑 extract_page，秒级看修复效果。

改一处切分逻辑就整册重建太贵（~30 分钟）。这里只跑相关页，打印每格的
cell_type / bbox / flags，配合 --baseline 可直接看「改前 → 改后」。

用法：
  PYTHONPATH=. python scripts/check_cells.py vol02/129:8:20 vol02/130:9:3
  PYTHONPATH=. python scripts/check_cells.py --file ids.txt --baseline base.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_id(s: str):
    book_page, rest = s.split(":", 1)
    book, page = book_page.split("/")
    parts = rest.split(":")
    col, idx = int(parts[0]), parts[1]
    sub = None
    if idx and idx[-1] in "ab":
        sub, idx = idx[-1], idx[:-1]
    return book, page, col, int(idx), sub


def run(ids: list[str], out: str = "output") -> dict:
    import cv2
    import numpy as np
    from open_guji_cv.clustering.extractor import (CharExtractor,
                                                   BINARY_THRESHOLD_PATCH)

    want = {}
    for s in ids:
        b, p, c, i, sub = parse_id(s)
        want.setdefault((b, p), []).append((c, i, sub, s))
    ex = CharExtractor()
    res = {}
    for (book, page), cells in sorted(want.items()):
        gp = Path(out) / book / "phase3_char_grid" / f"{page}_char_grid.json"
        img = cv2.imread(f"{out}/{book}/{page}.png")
        if img is None or not gp.exists():
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        got = {}
        for inst, patch in ex.extract_page(img, grid, book, page):
            got[(inst.col, inst.idx, inst.sub)] = (inst, patch)
        for c, i, sub, s in cells:
            hit = got.get((c, i, sub))
            if hit is None:
                res[s] = None
                continue
            inst, patch = hit
            # 墨量必须一起比：只比 bbox 会漏掉「框没变、块内墨被清掉」
            # ——横条掩蔽那类修复正是这种，2026-08-26 快测台补此项。
            ink = int((patch < BINARY_THRESHOLD_PATCH).sum())
            res[s] = {"cell_type": inst.cell_type,
                      "bbox": [round(v, 1) for v in inst.bbox],
                      "ink": ink, "flags": sorted(inst.flags)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--baseline")
    ap.add_argument("--save-baseline")
    ap.add_argument("--out", default="output")
    ap.add_argument("--changed-only", action="store_true")
    a = ap.parse_args()

    ids = list(a.ids)
    if a.file:
        ids += [x.strip() for x in Path(a.file).read_text().split() if x.strip()]
    res = run(ids, a.out)
    if a.save_baseline:
        Path(a.save_baseline).write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"基线存下 {len(res)} 格 → {a.save_baseline}")
        return
    base = json.loads(Path(a.baseline).read_text(encoding="utf-8")) \
        if a.baseline else {}
    n_same = n_diff = 0
    for k in ids:
        cur, old = res.get(k), base.get(k)
        same = (old == cur)
        n_same += same
        n_diff += (not same)
        if a.changed_only and same:
            continue
        if old is None or not a.baseline:
            print(f"{k}: {cur}")
        elif same:
            print(f"{k}: 未变 {cur['cell_type']} {cur['bbox']}")
        else:
            print(f"{k}:\n  改前 {old}\n  改后 {cur}")
    if a.baseline:
        print(f"\n共 {len(ids)} 格：未变 {n_same}，变了 {n_diff}")


if __name__ == "__main__":
    main()
