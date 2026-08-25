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

from open_guji_cv.clustering.extractor import defect_flags


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


def _patch_cell(book: str, cid: str, lab: str, rec: dict, quality: int):
    p = Path("output") / book / "phase4_chars" / rec["patch_path"]
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    # 只把**缺陷** flag 送进审查页：jiazhu 一类是版式标注，画成橙边
    # 只是让人白清一遍（2026-08-25 用户 r7）
    return {"id": cid, "lab": lab, "w": img.shape[1], "h": img.shape[0],
            "f": defect_flags(rec.get("flags")),
            "src": "data:image/jpeg;base64," +
                   base64.b64encode(buf.tobytes()).decode()}


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
            # 判空要看**实例**的 cell_type，不是 grid 的 type：列端渣格闸
            # 把纯框渣/污渍的格判成 empty 时只改实例，grid 里仍写着 char
            # ——审查页照 grid 显示，就把管线已经判空的格又画成字块，
            # 看着像「管线把污渍当字圈起来」（2026-08-25 用户实审反馈）。
            if isinstance(rec, dict) and not rec.get("__subs__") \
                    and rec.get("cell_type") == "empty":
                cells_out.append({"id": cid, "empty": True,
                                  "lab": str(i + 1), "junk": 1})
            elif cell.get("type") == "char" and isinstance(rec, dict) \
                    and rec.get("__subs__"):
                # 夹注格：整格实例已被 a=右子列 / b=左子列 两个半宽实例
                # 替换。两半**并排**成一块（a 在右、b 在左，与竖排读序
                # 一致）——分成上下两块看不出它们本是同一格的左右两半
                # （2026-08-25 用户反馈）。
                pair = []
                for sub in ("a", "b"):
                    sr = rec.get(sub)
                    if sr is None:
                        continue
                    d = _patch_cell(book, f"{cid}{sub}", f"{i + 1}{sub}",
                                    sr, quality)
                    if d is not None:
                        d["jz"] = 1
                        pair.append(d)
                if pair:
                    cells_out.append({"id": cid, "lab": str(i + 1),
                                      "jz": 1, "pair": pair})
            elif cell.get("type") == "char" and rec is not None \
                    and not rec.get("__subs__"):
                d = _patch_cell(book, cid, str(i + 1), rec, quality)
                if d is not None:
                    cells_out.append(d)
            else:
                cells_out.append({"id": cid, "empty": True,
                                  "lab": str(i + 1)})
        if cells_out:
            cols_out.append({"col": cno, "cells": cells_out})
    # 阅读顺序：右列在前
    cols_out.sort(key=lambda c: c["col"])
    out = {"book": book, "page": page, "cols": cols_out}
    if not cols_out:
        # 页型闸门跳过的页（封面/牌记/空白）没有字块——给审查页一个
        # 说明，否则显示成一片空白像没处理（2026-08-25 用户反馈）
        gp = Path("output") / book / "phase3_char_grid" \
            / f"{page}_char_grid.json"
        ptype = "?"
        if gp.exists():
            g = json.loads(gp.read_text(encoding="utf-8"))
            ptype = g.get("page_type") or g.get("skipped") or "?"
        out["skipped"] = ptype
    return out


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
            k = (r["book"], r["page"], r["col"], r["idx"])
            if r.get("sub"):
                # 夹注 a/b 半宽实例：同格两条，聚成 {'__subs__':1,'a':…,'b':…}
                slot = index.get(k)
                if not (isinstance(slot, dict) and slot.get("__subs__")):
                    slot = {"__subs__": 1}
                    index[k] = slot
                slot[r["sub"]] = r
            else:
                index[k] = r

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
