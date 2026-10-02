# -*- coding: utf-8 -*-
"""guji-page 校验图：把字框画回一张图（本页图、源叶、缩放档都行），并量一下对没对准。

    python scripts/render_guji_page_overlay.py PAGE.json IMAGE.png OUT.png \\
        [--image-desc page|canvas|source|<json 文件>] [--width 1200]

`--image-desc` 说明 IMAGE 是哪张图（坐标换算靠它，规范 §2.3）：
`page`＝就是本页图（缺省）；`source`＝`image.source` 那张原叶（按 `image.region` 平移）；
`canvas`＝meta 里给的另一版裁图（读 PAGE.json 同目录 meta.json 的 `pages.<页>.canvas_image`）；
或给一个 JSON 文件（`width/height/region/source`）。`--width` 先把图缩到这个宽度再画（IIIF `w,` 档）。

对位检验：每个字框里的墨占比，原位 vs 整体平移 ±dx/±dy；框对准时原位应是最大（字框是
收紧到墨上的，挪开就落进字间空白）。结果打印出来，也写进图的角上。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.formats import guji_page as gp  # noqa: E402

LANE_COLOR = {"main": (30, 90, 220), "jz_r": (0, 150, 70), "jz_l": (200, 120, 0), "solo": (150, 60, 170)}
MARK_COLOR = {"seal": (230, 0, 0), "blank": (170, 170, 170), "excluded": (190, 0, 190)}


def ink_score(gray: np.ndarray, boxes, dx: int = 0, dy: int = 0) -> float:
    H, W = gray.shape
    vals = []
    for x, y, w, h in boxes:
        x0, y0 = max(0, x + dx), max(0, y + dy)
        x1, y1 = min(W, x + dx + w), min(H, y + dy + h)
        if x1 > x0 and y1 > y0:
            vals.append(float((gray[y0:y1, x0:x1] < 128).mean()))
    return float(np.mean(vals)) if vals else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--image-desc", default="page")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--shift", type=float, default=0.5, help="平移量 = 字框中位宽/高 × 这个比例")
    a = ap.parse_args(argv)

    page = gp.load(a.page)
    if a.image_desc == "page":
        desc = page["image"]
    elif a.image_desc == "source":
        src = page["image"]["source"]
        desc = {"width": src["width"], "height": src["height"], "source": src}
    elif a.image_desc == "canvas":
        meta = json.loads((Path(a.page).parent / "meta.json").read_text(encoding="utf-8"))
        desc = meta["pages"][str(page["page"]["index"])]["canvas_image"]
    else:
        desc = json.loads(Path(a.image_desc).read_text(encoding="utf-8"))

    im = Image.open(a.image).convert("RGB")
    if (im.width, im.height) != (desc["width"], desc["height"]):
        print(f"✗ 图 {im.width}×{im.height} 与描述 {desc['width']}×{desc['height']} 不符", file=sys.stderr)
        return 2
    if a.width:
        desc = gp.scaled_image(desc, a.width)
        im = im.resize((desc["width"], desc["height"]), Image.LANCZOS)

    def m(box):
        return gp.map_box(box, page["image"], desc)

    gray = np.asarray(im.convert("L"))
    # 印章压着的字（occluded）框里全是印泥散点，不拿来量对位
    boxes = [m(g["box"]) for g in page["glyphs"]
             if g.get("box") and "occluded" not in g.get("flags", []) and g["text"][1] > g["text"][0]]
    sx = max(2, round(a.shift * float(np.median([b[2] for b in boxes]))))
    sy = max(2, round(a.shift * float(np.median([b[3] for b in boxes]))))
    base = ink_score(gray, boxes)
    shifted = {f"{dx:+d},{dy:+d}": ink_score(gray, boxes, dx, dy)
               for dx, dy in ((sx, 0), (-sx, 0), (0, sy), (0, -sy))}
    ok = all(base > v for v in shifted.values())

    dr = ImageDraw.Draw(im, "RGBA")
    lw = max(1, round(desc["width"] / 800))
    for _, col in gp.iter_columns(page):
        if col.get("box"):
            x, y, w, h = m(col["box"])
            dr.rectangle([x, y, x + w, y + h], outline=(120, 120, 120, 160), width=lw)
    for mk in page.get("marks", []):
        if mk.get("box") and mk["kind"] in MARK_COLOR:
            x, y, w, h = m(mk["box"])
            c = MARK_COLOR[mk["kind"]]
            if mk["kind"] == "seal":
                dr.rectangle([x, y, x + w, y + h], outline=c + (255,), width=lw * 3)
            else:
                dr.rectangle([x, y, x + w, y + h], outline=c + (200,), width=lw)
    for g in page["glyphs"]:
        if not g.get("box"):
            continue
        x, y, w, h = m(g["box"])
        c = LANE_COLOR.get(g.get("lane"), (0, 0, 0))
        fill = c + (40,) if g.get("review") in ("auto", "human") else (255, 0, 0, 40)
        dr.rectangle([x, y, x + w, y + h], outline=c + (255,), width=lw, fill=fill)
    msg = (f"{page['page_id']}  n={len(boxes)}  frame {desc['width']}x{desc['height']}  ink in boxes {base:.3f}  "
           + "  ".join(f"shift {k}: {v:.3f}" for k, v in shifted.items()) + ("  OK" if ok else "  MISALIGNED?"))
    dr.rectangle([0, 0, min(im.width, 12 + 7 * len(msg)), 22], fill=(255, 255, 255, 230))
    dr.text((6, 5), msg, fill=(0, 0, 0))
    if a.out.lower().endswith((".jpg", ".jpeg")):
        im.save(a.out, quality=82, optimize=True)
    else:
        im.save(a.out, optimize=True)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
