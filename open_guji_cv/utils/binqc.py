# -*- coding: utf-8 -*-
"""二值化体检：一页上「二值化可能出了问题、该看彩图」的区域（用户 2026-11-17：算法走二值，显示尽量彩图，
二值出问题的地方可以切彩图看）。

产物 `binarized/<书>/<页>.qc.json`，与整页二值副本放在一起，由 `guji binarize` 顺带写出。
**不是管线产物**：不进指纹、不进 R2、不进中心库，可删可重做；控制台读它决定哪些字块缺省显示彩图、
页图上把可疑区画出来。

格式（坐标是**原图左上原点**像素，与磁盘上的页图一致；管线 `bbox_page` 是右上原点，比之前先翻 x）：

```json
{"page": 11, "size": [W, H], "ink": {...} | null, "color_mode": "max",
 "flags": ["halftone"],
 "regions": [{"bbox": [x0, y0, x1, y1], "reason": "color_mark", "score": 0.31}, ...]}
```

`reason` 的取值：

| 值 | 意思 |
|---|---|
| `color_mark` | 有色记号（朱印、朱批、红圈点）：原样亮度里是墨，墨层里被压掉了。彩图上一看便知是什么 |
| `bin_diff` | 二值与「亮度图＋Otsu」差得多：淡墨、洇墨、污渍处，二值可能丢笔画或多出墨块 |
| `speckle` | 去小斑去掉了很多点：纸纹重，二值可能把纸纹当墨或把小点画抹掉 |

页级 `flags`：`halftone`（网点印刷，小连通体占多数，见 ai-team domain/CV/经验.md「半色调」条）。
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .ink import InkSpec, ink_mask, resolve_color_mode, speck_area_for, to_ink_gray

QC_SUFFIX = ".qc.json"
#: 体检网格：页高的 1/48（约一个字高的一半），最小 16 px
TILE_FRAC = 1 / 48
#: 一格里墨层与亮度差出的墨（有色记号）占格面积超过它就标 `color_mark`
COLOR_MARK_FRAC = 0.02
#: 一格里两种二值的不一致（异或 / 并）超过它、且并集占格面积 ≥ `MIN_INK_FRAC` 就标 `bin_diff`
BIN_DIFF_FRAC = 0.45
MIN_INK_FRAC = 0.03
#: 一格里被去掉的小斑个数 ≥ 它就标 `speckle`
SPECKLE_N = 12
#: 页上小连通体（面积 < 4×speck_area）占全部连通体的比例 ≥ 它就标 `halftone`
HALFTONE_FRAC = 0.5


def qc_path(binarized_png: Path) -> Path:
    return binarized_png.with_suffix(QC_SUFFIX)


def _tile_counts(mask: np.ndarray, t: int) -> np.ndarray:
    h, w = mask.shape
    gh, gw = (h + t - 1) // t, (w + t - 1) // t
    pad = np.zeros((gh * t, gw * t), np.float32)
    pad[:h, :w] = mask
    return pad.reshape(gh, t, gw, t).sum(axis=(1, 3))


def _regions(hit: np.ndarray, score: np.ndarray, t: int, size: tuple[int, int], reason: str) -> list[dict]:
    """格网上标中的格连成块 → 原图像素框。"""
    if not hit.any():
        return []
    n, lab, stats, _ = cv2.connectedComponentsWithStats(hit.astype(np.uint8), connectivity=8)
    W, H = size
    out = []
    for i in range(1, n):
        x, y, w, h = stats[i, :4]
        sc = float(score[lab == i].max())
        out.append({"bbox": [int(x * t), int(y * t), int(min(W, (x + w) * t)), int(min(H, (y + h) * t))],
                    "reason": reason, "score": round(sc, 3)})
    return out


def check_page(img: np.ndarray, spec: InkSpec) -> dict:
    """原图（BGR 或灰度）＋墨层设置 → 体检结果（见模块头格式，不含 `page`）。"""
    H, W = img.shape[:2]
    t = max(16, int(H * TILE_FRAC))
    area = float(t * t)
    luma = img if img.ndim == 2 else cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    color_mode = resolve_color_mode(img, spec.color) if img.ndim == 3 else "luma"
    ink_gray = to_ink_gray(img, spec.color)
    bspec = spec if spec.binary else InkSpec(**{**spec.__dict__, "binarize": "otsu"})
    ink = ink_mask(ink_gray, bspec)

    _, lthr = cv2.threshold(luma, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    luma_ink = lthr.astype(np.uint8)
    m = int(spec.edge_margin)
    if m > 0 and H > 2 * m and W > 2 * m:
        luma_ink[:m, :] = 0
        luma_ink[-m:, :] = 0
        luma_ink[:, :m] = 0
        luma_ink[:, -m:] = 0

    regions: list[dict] = []
    # 有色记号：亮度上是墨、墨层上不是
    if color_mode != "luma":
        removed = ((luma_ink > 0) & (ink == 0)).astype(np.float32)
        frac = _tile_counts(removed, t) / area
        regions += _regions(frac >= COLOR_MARK_FRAC, frac, t, (W, H), "color_mark")
    # 二值不一致（灰度图上才有意义：彩图的差异多半就是有色记号，已经单列）
    else:
        a, b = ink.astype(bool), luma_ink.astype(bool)
        x = _tile_counts((a ^ b).astype(np.float32), t)
        u = _tile_counts((a | b).astype(np.float32), t)
        ratio = np.where(u > 0, x / np.maximum(u, 1), 0.0)
        hit = (ratio >= BIN_DIFF_FRAC) & (u / area >= MIN_INK_FRAC)
        regions += _regions(hit, ratio, t, (W, H), "bin_diff")
    # 纸纹斑点：去小斑前后的连通体差
    flags: list[str] = []
    sa = speck_area_for(bspec, H)
    if sa > 1:
        raw_ink = ink_mask(ink_gray, InkSpec(**{**bspec.__dict__, "speck_area": 0}))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(raw_ink, connectivity=8)
        if n > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            small = areas < sa
            if small.any():
                pts = cent[1:][small]
                gh, gw = (H + t - 1) // t, (W + t - 1) // t
                cnt = np.zeros((gh, gw), np.float32)
                np.add.at(cnt, (np.clip((pts[:, 1] // t).astype(int), 0, gh - 1),
                                np.clip((pts[:, 0] // t).astype(int), 0, gw - 1)), 1)
                regions += _regions(cnt >= SPECKLE_N, cnt, t, (W, H), "speckle")
            if float((areas < 4 * sa).mean()) >= HALFTONE_FRAC and len(areas) > 200:
                flags.append("halftone")
    return {"size": [W, H], "ink": spec.token(), "color_mode": color_mode, "tile": t,
            "flags": flags, "regions": regions}


def write_qc(binarized_png: Path, page: int, img: np.ndarray, spec: InkSpec) -> Path:
    d = {"page": page, **check_page(img, spec)}
    p = qc_path(binarized_png)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def read_qc(binarized_png: Path | None) -> dict | None:
    if binarized_png is None:
        return None
    p = qc_path(binarized_png)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def canon_box_suspect(qc: dict | None, bbox_page, min_overlap: float = 0.25) -> list[str]:
    """管线坐标（右上原点规范空间）的字框落进了哪些可疑区：返回原因列表（空＝不可疑）。
    `min_overlap`：字框面积被可疑区盖住的比例下限。"""
    if not qc or not bbox_page:
        return []
    W = qc["size"][0]
    bx0, by0, bx1, by1 = (float(v) for v in bbox_page)
    x0, x1 = (W - 1) - bx1, (W - 1) - bx0
    a = max(1.0, (x1 - x0) * (by1 - by0))
    hit = []
    for r in qc.get("regions", []):
        rx0, ry0, rx1, ry1 = r["bbox"]
        ix = max(0.0, min(x1, rx1) - max(x0, rx0))
        iy = max(0.0, min(by1, ry1) - max(by0, ry0))
        if ix * iy / a >= min_overlap and r["reason"] not in hit:
            hit.append(r["reason"])
    return hit
