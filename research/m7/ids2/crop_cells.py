# -*- coding: utf-8 -*-
"""M7 IDS 扩展：按 cells.json 里的格从原图灰度裁字块图（bbox_page 是右上原点，需镜像 x，同 products.py::_char_patch_binarized）。

    python research/m7/ids2/crop_cells.py <cells.json> <快照根(含 <vol>/products/<vol>/cell_shrink)> <原图根(含 volNN/<page>.png)> <out_dir> [组,组…]
只出图，不判字。文件名＝id 的 ':' 换 '_'。
"""
import json, sys
from pathlib import Path
import cv2

cells, snap, raw, out = (Path(a) for a in sys.argv[1:5])
groups = set(sys.argv[5].split(",")) if len(sys.argv) > 5 else None
out.mkdir(parents=True, exist_ok=True)
rows = [r for r in json.load(open(cells, encoding="utf-8")) if r["core"] and (groups is None or r["group"] in groups)]
cache, n_ok, bad = {}, 0, []
for r in rows:
    book, page = r["id"].split(":")[0], int(r["id"].split(":")[1])
    col, slot, sub = r["id"].split(":")[2], r["id"].split(":")[3], ""
    if slot[-1] in "ab":
        slot, sub = slot[:-1], slot[-1]
    ck = (book, page)
    if ck not in cache:
        ci = json.load(open(snap / book / "products" / book / "cell_shrink" / f"p{page:04d}.json", encoding="utf-8"))["char_index"]
        img = cv2.imread(str(raw / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
        cache = {ck: (ci, img)}
    ci, g = cache[ck]
    box = None
    for cc in ci["columns"]:
        for ch in cc["chars"]:
            if ch["id"] == r["id"] and ch.get("bbox_page"):
                box = ch["bbox_page"]
    if box is None or g is None:
        bad.append(r["id"]); continue
    W = g.shape[1]
    bx0, by0, bx1, by1 = box
    x0, x1 = int(round((W - 1) - bx1)), int(round((W - 1) - bx0))
    y0, y1 = int(round(by0)), int(round(by1))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(g.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        bad.append(r["id"]); continue
    cv2.imwrite(str(out / (r["id"].replace(":", "_") + ".png")), g[y0:y1, x0:x1]); n_ok += 1
print("ok", n_ok, "bad", len(bad), bad[:10])
