#!/usr/bin/env python3
"""预裁雪碧图原型（GUJI-557 / P1-4，字段表见 ai-team team/CV/guji-proof-0.2-字段表-GUJI-557.md §二）。

来源：ai-team `team/整理/GUJI-557/sprite_build.py`，2026-10-20 迁入 cv `scripts/zhengli/`（GUJI-652）。
迁入适配：只给 main() 加了可选 argv 参数（便于测试），不依赖 cv 包与 ai-team 路径；同目录 alt_build.py／ex_build.py 从这里 import TILE／COLS／tile_of。
用途：按 cord 格框从原图裁出每个待审格，按页拼成雪碧图，写桶清单 assets.json，并在 pending 每格标 img 坐标。

只读：册 NNN.cord.json（格框，canvas 坐标）＋NNN.pending.json（待审格）＋原图 PNG 目录。
不读不写 cv，不进 book-text git。产出到 --out：
  pNNNN.webp                    每页一张，96×96 网格，行优先，宽 ≤2048（每行 21 格），WebP q80
  assets.json                   桶清单 guji-proof-assets/0.1：book／volume／rev／files[name,bytes,sha256,w,h]
  pending.with-img.json         pending.json 每格加 img={s,x,y,w,h}（s＝相对文件名）
坐标换算：只在「cord 页图尺寸 == 原图尺寸」时直接用 box；不等的页跳过并列入 manifest.skipped（不瞎裁）。

用法：
    python3 scripts/zhengli/sprite_build.py --cord 001.cord.json --pending 001.pending.json \
        --raw-dir <workspace>/data_full/zongmu/vol01 --book 96mid1ogzk --vol 01 \
        --out <dir> [--pad 0.08]
    （--raw-dir 示例是四库总目 vol01 在 guji-workspace 里的原图目录；别的书换成该书原图目录。）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

TILE, MAXW = 96, 2048
COLS = MAXW // TILE  # 21


def tile_of(im: Image.Image, box: list[int], pad: float) -> Image.Image:
    x, y, w, h = box
    px, py = int(w * pad), int(h * pad)
    im = im.crop((max(0, x - px), max(0, y - py), min(im.width, x + w + px), min(im.height, y + h + py))).convert("L")
    s = min(TILE / im.width, TILE / im.height)
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    t = Image.new("L", (TILE, TILE), 255)
    t.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    return t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cord", required=True, type=Path)
    ap.add_argument("--pending", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--book", required=True)
    ap.add_argument("--vol", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pad", type=float, default=0.08)
    a = ap.parse_args(argv)

    cord = json.loads(a.cord.read_text(encoding="utf-8"))
    pend = json.loads(a.pending.read_text(encoding="utf-8"))
    boxes = {}
    for pg in cord["pages"]:
        for c in pg.get("cells", []):
            boxes[c["a"]] = (pg["page"], c["box"], pg["image"])
    by_page: dict[int, list[dict]] = {}
    skipped = []
    for c in pend["cells"]:
        b = boxes.get(c["cell"])
        if not b or not b[1]:
            skipped.append({"cell": c["cell"], "why": "cord 无框"})
            continue
        by_page.setdefault(b[0], []).append(c)

    sdir = a.out  # 扁平：webp 与 manifest 同目录，资产同名上传 Release（Eliot 定）
    sdir.mkdir(parents=True, exist_ok=True)
    files, imgs = [], {}
    for page, cells in sorted(by_page.items()):
        src = a.raw_dir / f"{page}.png"
        im = Image.open(src)
        cw, ch = boxes[cells[0]["cell"]][2]["width"], boxes[cells[0]["cell"]][2]["height"]
        if im.size != (cw, ch):
            for c in cells:
                skipped.append({"cell": c["cell"], "why": f"原图 {im.size} 与 cord 页图 {(cw, ch)} 尺寸不同"})
            continue
        n = len(cells)
        cols = min(COLS, n)
        rows = -(-n // cols)
        sheet = Image.new("L", (cols * TILE, rows * TILE), 255)
        name = f"p{page:04d}.webp"
        for i, c in enumerate(cells):
            x, y = (i % cols) * TILE, (i // cols) * TILE
            sheet.paste(tile_of(im, boxes[c["cell"]][1], a.pad), (x, y))
            imgs[c["cell"]] = {"s": name, "x": x, "y": y, "w": TILE, "h": TILE}
        p = sdir / name
        sheet.save(p, "WEBP", quality=80)
        raw = p.read_bytes()
        files.append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                      "w": sheet.width, "h": sheet.height})
    # 桶清单 assets.json（guji-proof-assets/0.1，book-text F-OV-09/10/11：s 在 files[].name、x+w≤w、y+h≤h、rev＝pending.rev）
    man = {"schema": "guji-proof-assets/0.1", "book": a.book, "volume": int(a.vol), "rev": pend["rev"], "files": files}
    (a.out / "assets.json").write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if skipped:
        print("跳过：", json.dumps(skipped, ensure_ascii=False), file=sys.stderr)
    out = dict(pend, cells=[dict(c, img=imgs[c["cell"]]) if c["cell"] in imgs else c for c in pend["cells"]])
    (a.out / "pending.with-img.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"页 {len(files)}，格 {len(imgs)}/{len(pend['cells'])}，字节 {sum(f['bytes'] for f in files)}，跳过 {len(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
