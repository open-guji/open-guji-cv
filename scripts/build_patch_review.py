"""生成「切分朱批 V2」数据：按列排布的**最终图块流**。

用户定版的审查形态：直接看切好的一个个文字图块（下游看到什么就审什么），
上下残余/切错一眼可见。每页=各列（从右到左）、每列=图块自上而下按格序
排列；判空格给灰色占位（真字被判空=漏切，在流里立刻现形）。

用法：PYTHONPATH=. python scripts/build_patch_review.py \
        --pages vol01:20-32 vol02:1-12 --quality 74 --out review_patches.json
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import cv2


def parse_pages(specs: list[str]) -> list[tuple[str, str]]:
    out = []
    for spec in specs:
        book, rng = spec.split(":")
        for part in rng.split(","):
            if "-" in part:
                a, b = part.split("-")
                out.extend((book, str(n)) for n in range(int(a), int(b) + 1))
            else:
                out.append((book, part))
    return out


def build_page(book: str, page: str, quality: int, index: dict):
    gp = Path("output") / book / "phase3_char_grid" / f"{page}_char_grid.json"
    if not gp.exists():
        return None
    grid = json.loads(gp.read_text(encoding="utf-8"))
    cols_out = []
    for col in sorted(grid.get("columns", []),
                      key=lambda c: c.get("index", 0)):
        if col.get("skipped") or not col.get("cells"):
            continue
        cno = int(col["index"])
        cells_out = []
        for i, cell in enumerate(
                c for c in col["cells"] if c.get("type") != "margin"):
            cid = f"{book}/{page}:{cno}:{i}"
            rec = index.get((book, page, cno, i))
            if cell.get("type") == "char" and rec is not None:
                p = Path("output") / book / "phase4_chars" / rec["patch_path"]
                img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                ok, buf = cv2.imencode(
                    ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
                cells_out.append({
                    "id": cid, "w": img.shape[1], "h": img.shape[0],
                    "f": rec.get("flags") or [],
                    "src": "data:image/jpeg;base64," +
                           base64.b64encode(buf.tobytes()).decode()})
            else:
                cells_out.append({"id": cid, "empty": True})
        if cells_out:
            cols_out.append({"col": cno, "cells": cells_out})
    # 阅读顺序：右列在前
    cols_out.sort(key=lambda c: c["col"])
    return {"book": book, "page": page, "cols": cols_out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--quality", type=int, default=74)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    index: dict[tuple, dict] = {}
    for book in {b for b, _ in parse_pages(args.pages)}:
        p = Path("output") / book / "phase4_chars" / "index.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            index[(r["book"], r["page"], r["col"], r["idx"])] = r

    pages = []
    for book, page in parse_pages(args.pages):
        d = build_page(book, page, args.quality, index)
        if d:
            pages.append(d)
            n = sum(len(c["cells"]) for c in d["cols"])
            kb = sum(len(c.get("src", "")) for col in d["cols"]
                     for c in col["cells"]) // 1024
            print(f"{book}/{page}: {n} 格 {kb}KB")
    Path(args.out).write_text(json.dumps(pages, ensure_ascii=False),
                              encoding="utf-8")
    total = sum(len(c.get("src", "")) for p in pages
                for col in p["cols"] for c in col["cells"])
    print(f"共 {len(pages)} 页 ≈{total // 1024 // 1024}MB → {args.out}")


if __name__ == "__main__":
    main()
