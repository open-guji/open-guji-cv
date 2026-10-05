# -*- coding: utf-8 -*-
"""pages.json 抽字核对（A2 验收，F3 overview#398）：抽 N 个格，把框画回原图，出一张对照图 + 对位量。

对位量法同 guji_page_v0.2 §十一：字框里的墨占比，原位 vs 整体平移半个框（右/左/下/上）；框对准时原位最大。
图的 sha256 与 pages.json `image.sha256` 不同就报出来（坐标所在的图换过，要经 region 换算，见 guji_page §2.3）。

    python scripts/check_pages_json_boxes.py --pages-json 002.pages.json --images vol02_4.png=4 ... --n 20 --out check.png
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def ink(arr, box):
    x, y, w, h = box
    sub = arr[max(0, y):y + h, max(0, x):x + w]
    return float((sub < 128).mean()) if sub.size else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages-json", required=True)
    ap.add_argument("--images", nargs="+", required=True, help="图路径=页号")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=398)
    ap.add_argument("--font", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    pj = json.loads(Path(a.pages_json).read_text(encoding="utf-8"))
    pages = {p["page"]["index"]: p for p in pj["pages"]}
    imgs = {}
    for spec in a.images:
        path, pg = spec.rsplit("=", 1)
        imgs[int(pg)] = Path(path)
    pool = [(pg, c) for pg in imgs for c in pages[pg]["cells"] if c.get("box")]
    rnd = random.Random(a.seed)
    pick = rnd.sample(pool, min(a.n, len(pool)))
    font = ImageFont.truetype(a.font, 28) if a.font else ImageFont.load_default()
    tiles, rows = [], []
    for pg, c in pick:
        im = Image.open(imgs[pg]).convert("L")
        sha = hashlib.sha256(imgs[pg].read_bytes()).hexdigest()
        arr = np.asarray(im)
        x, y, w, h = c["box"]
        shifts = {"原位": (0, 0), "右": (w // 2, 0), "左": (-w // 2, 0), "下": (0, h // 2), "上": (0, -h // 2)}
        r = {k: ink(arr, (x + dx, y + dy, w, h)) for k, (dx, dy) in shifts.items()}
        ok = r["原位"] >= max(v for k, v in r.items() if k != "原位")
        rows.append({"page": pg, "a": c["a"], "c": c["c"], "box": c["box"], "ink": r, "aligned": ok,
                     "sha_match": sha == (pages[pg].get("image") or {}).get("sha256")})
        pad = max(w, h) // 3
        crop = im.crop((x - pad, y - pad, x + w + pad, y + h + pad)).convert("RGB")
        d = ImageDraw.Draw(crop)
        d.rectangle((pad, pad, pad + w, pad + h), outline=(220, 30, 30), width=3)
        crop = crop.resize((160, int(160 * crop.height / crop.width)))
        tile = Image.new("RGB", (170, crop.height + 44), "white")
        tile.paste(crop, (5, 40))
        ImageDraw.Draw(tile).text((5, 4), f"{c['c']} {c['a']}", fill=(0, 0, 0), font=font)
        tiles.append(tile)
    cols = 5
    th = max(t.height for t in tiles)
    sheet = Image.new("RGB", (cols * 170, ((len(tiles) + cols - 1) // cols) * th), "white")
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % cols) * 170, (k // cols) * th))
    sheet.save(a.out)
    rep = {"n": len(rows), "aligned": sum(r["aligned"] for r in rows), "sha_match": sum(r["sha_match"] for r in rows),
           "mean_ink": {k: round(float(np.mean([r["ink"][k] for r in rows])), 3) for k in rows[0]["ink"]},
           "rows": rows}
    Path(a.out).with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"抽 {rep['n']} 字：原位墨占比最大 {rep['aligned']}，图 sha 对上 {rep['sha_match']}，均值 {rep['mean_ink']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
