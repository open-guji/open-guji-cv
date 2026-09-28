"""把 cells.jsonl 里某通道的格拼成编号拼图（目检用，不给用户审）。

  GUJI_WORKSPACE=<ws> GUJI_PRODUCTS_DIR=… GUJI_CACHE_DIR=… python sheet.py <cells.jsonl> <channel> <out 前缀> [--per 48]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qtw_booklib"))
from qb_common import cell_index, ctx_for  # noqa: E402

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def main():
    src, chan, out = sys.argv[1], sys.argv[2], sys.argv[3]
    per = int(sys.argv[sys.argv.index("--per") + 1]) if "--per" in sys.argv else 48
    recs = [json.loads(l) for l in open(src, encoding="utf-8")]
    recs = [r for r in recs if r["channel"] == chan]
    ctxs, idx = {}, {}
    tiles = []
    try:
        font = ImageFont.truetype(FONT, 22)
    except OSError:
        font = ImageFont.load_default()
    for n, r in enumerate(recs):
        book = r["id"].split(":")[0]
        if book not in ctxs:
            ctxs[book] = ctx_for(book)
            idx[book] = cell_index(book, Path(__import__("os").environ["GUJI_WORKSPACE"]))
        key = idx[book][r["id"]]["patch_key"]
        img = ctxs[book].image("char_patch", key)
        h, w = img.shape
        s = 110 / max(h, w)
        img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))))
        tile = Image.new("L", (130, 170), 255)
        tile.paste(Image.fromarray(img), ((130 - img.shape[1]) // 2, 4))
        d = ImageDraw.Draw(tile)
        tr = r.get("human", {}) and (r.get("human") or {}).get("shape")
        label = f"{n} {r['char']}|{r['lib_top']}"
        d.text((2, 118), label, font=font, fill=0)
        d.text((2, 142), (r.get("wiki") or r.get("col_anchor") or tr or "-"), font=font, fill=0)
        tiles.append(tile)
    cols = 8
    for s in range(0, len(tiles), per):
        chunk = tiles[s:s + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("L", (cols * 132, rows * 172), 128)
        for i, t in enumerate(chunk):
            sheet.paste(t, ((i % cols) * 132, (i // cols) * 172))
        sheet.save(f"{out}_{s // per:02d}.png")
        print(f"{out}_{s // per:02d}.png", len(chunk))


if __name__ == "__main__":
    main()
