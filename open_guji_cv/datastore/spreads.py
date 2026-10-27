"""对开页（一张图是书打开后的一开：右半叶在前、左半叶在后）按书脊拆成两个半叶，出拆页表给 `guji source … --splits`。

哈佛燕京等馆的 IIIF 扫描常是一开一张图（书衣是单页）。管线只认一页一个半叶，拆页又是给读者看的修正，
所以拆在页表里（`ops: crop`，可复现），不在管线里。

**书脊怎么找**（2026-10-26，《增廣幼學須知鰲頭雜字大全》哈佛本 62 张对开逐张目测全对）：
书脊折痕是一条贯通上下的细暗线。版框以内到处是墨和栏线，没法和它分开；但版框上方的天头、下方的地脚里，
除了折痕没有别的墨。所以先按行找本开版框的上、下边（中间 40% 宽里有墨的行），再在天头地脚的行里，
取中线 ±8% 宽内列均灰度最暗的那一列。

试过、不用的判据（留给后来人）：
- 版框内「每列墨点数最少」「每列 0.5 分位灰度最亮」：两版框几乎贴着时（这部书多数只隔几十像素）找不到空白带，
  或落进别的空白列；
- 「最亮的连续纸带」：插图页、雜字页的空白格比书脊纸带还亮；
- 「两条最粗的竖线中点」：版框粗细、深浅各页不一，常配错对。

只出表、不改图；表的形状同 kaiyuanguji-web `ops/iiif/siku-zongmu-splits.json`
（`[{vol, ia_leaf, canvas_seq, xywh}]`），`ia_leaf` 在这里是源件里的叶序（PDF 页号）。
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path


def gutter(im, red: int = 2) -> tuple[int, dict]:
    """一开图 → (书脊 x，源图坐标)，附诊断（版框上下边、天头地脚行数、折痕对比度）。"""
    import numpy as np
    g = np.asarray(im.convert("L").reduce(red), dtype=np.float32)
    h, w = g.shape
    rows = g[:, int(w * 0.30):int(w * 0.70)].mean(1)
    paper = float(np.median(rows))
    dark = np.where(rows < paper - 25)[0]
    body = dark[(dark > h * 0.02) & (dark < h * 0.98)]
    top, bot = (int(body.min()), int(body.max())) if len(body) else (int(h * 0.1), int(h * 0.9))
    band = np.concatenate([g[int(h * 0.01):max(int(h * 0.01) + 2, top - 6)],
                           g[min(bot + 6, int(h * 0.99) - 2):int(h * 0.99)]])
    lo, hi = int(w * 0.42), int(w * 0.58)
    prof = band[:, lo:hi].mean(0)
    x = int(prof.argmin())
    return (x + lo) * red, {"frame_top": top * red, "frame_bottom": bot * red, "margin_rows": int(band.shape[0] * red),
                            "contrast": round(float(np.median(prof) - prof[x]), 1)}


def detect(zip_path: Path, vol: str, *, min_ratio: float = 0.9, weak: float = 15.0) -> tuple[list[dict], list[dict]]:
    """叶 zip 里宽大于高（宽高比 ≥ `min_ratio`）的叶当对开，逐张找书脊。

    返回 (拆页表, 诊断)。拆页表每开两行：`a`＝右半叶（先读），`b`＝左半叶。折痕对比度低于 `weak`
    的记 `weak: true`，要人看。"""
    from PIL import Image

    from .sources import _leaf_no, leaf_seq, zip_leaves
    rows, diag = [], []
    with zipfile.ZipFile(zip_path) as z:
        for i, name in enumerate(zip_leaves(zip_path), 1):
            leaf = _leaf_no(name, i)
            im = Image.open(io.BytesIO(z.read(name)))
            w, h = im.size
            if w / h < min_ratio:
                continue
            x, info = gutter(im)
            rows.append({"vol": vol, "ia_leaf": leaf, "canvas_seq": leaf_seq(leaf, "a"), "xywh": [x, 0, w - x, h]})
            rows.append({"vol": vol, "ia_leaf": leaf, "canvas_seq": leaf_seq(leaf, "b"), "xywh": [0, 0, x, h]})
            diag.append({"leaf": leaf, "name": name, "w": w, "h": h, "x": x, "ratio": round(x / w, 3),
                         "weak": info["contrast"] < weak, **info})
    return rows, diag


def sheet(zip_path: Path, diag: list[dict], out: Path, cols: int = 8) -> None:
    """核对图：每开截切线附近一段（宽 320 px、高 12%），切线上下各画一道红标。逐张看红标是否落在折痕上。"""
    from PIL import Image, ImageDraw

    from .sources import zip_leaves
    names = {d["name"]: d for d in diag}
    tiles = []
    with zipfile.ZipFile(zip_path) as z:
        for name in zip_leaves(zip_path):
            d = names.get(name)
            if not d:
                continue
            im = Image.open(io.BytesIO(z.read(name)))
            x, h = d["x"], d["h"]
            t = im.crop((x - 160, int(h * 0.40), x + 160, int(h * 0.52))).convert("RGB")
            dr = ImageDraw.Draw(t)
            dr.line([(160, 0), (160, 12)], fill=(255, 0, 0), width=3)
            dr.line([(160, t.height - 12), (160, t.height)], fill=(255, 0, 0), width=3)
            dr.text((4, 4), f"{d['leaf']}{' !' if d['weak'] else ''}", fill=(0, 0, 255))
            tiles.append(t)
    if not tiles:
        return
    W, H = tiles[0].width + 4, max(t.height for t in tiles) + 4
    S = Image.new("RGB", (cols * W, ((len(tiles) + cols - 1) // cols) * H), "white")
    for j, t in enumerate(tiles):
        S.paste(t, ((j % cols) * W, (j // cols) * H))
    S.save(out)
