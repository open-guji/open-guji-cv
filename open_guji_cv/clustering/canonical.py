"""字形图块的统一存储格式（canonical form）。

`glyph_store/patches/` 及一切外部字形来源（字体渲染、字典扫描、外部
数据集）入库前统一转成本格式，消除「每个来源一种尺寸/居中方式」：

- **画布**：200×200，8-bit 灰度 PNG，白底（255）黑字。存灰度不存二值：
  管线裁切本来就近二值，无损；扫描/渲染来源保留灰度信息给下游二值化。
- **几何**：墨迹外接框**等比、只缩不放**——超出内容区（画布 ×
  (1 - 2×0.12)，与匹配层 MARGIN_RATIO 同参）才 INTER_AREA 缩小，
  否则保持原生像素；按**墨迹质心**居中（与 normalize_patch 的居中
  规则一致，clamp 不出界）。不上采样是实测结论：放大重采样 + 下游
  再二值化会让 pairs 金标的 coverage 判定翻转 10/60，只缩不放降到
  1/60、逐实例自扰动为零。代价是画布内墨迹大小不完全统一——匹配层
  反正要做自己的缩放居中，存储层强行放大只会引入插值噪声。同理，
  存储层也不做匹配层那种 ±20% 各向异性拉伸，真源保留真实纵横比。
- **清理**：边缘残渣清理（界行/邻字残留）只在「原始裁切 → canonical」
  这一次发生；canonical 图约定为**干净的单字**，墨迹不贴边，下游
  normalize_patch 的贴边启发式在其上自然退化为 no-op，不会误咬笔画。
- **不做**二值化/骨架化/笔宽归一——那些是匹配层派生物（derived），
  由 rebuild 按当前算法重算。

原始裁切的尺寸/bbox 元数据仍在 instances 表（width/height/bbox），
canonical 化不抹掉相对字号信息。设计讨论见
.claude/doc/glyph_canonical_format.md。
"""

from __future__ import annotations

import cv2
import numpy as np

from .normalize import (
    _drop_stray_components,
    ink_bbox,
    remove_edge_specks,
    sauvola_binarize,
)

CANON_SIZE = 200
CANON_MARGIN_RATIO = 0.12   # 与 normalize.MARGIN_RATIO 保持一致


def to_canonical(gray: np.ndarray, size: int = CANON_SIZE,
                 margin_ratio: float = CANON_MARGIN_RATIO,
                 clean: bool = True) -> np.ndarray:
    """任意尺寸的字形图（灰度/彩色，白底黑字）→ canonical 灰度图。

    clean=True 时执行边缘残渣清理（管线裁切必开）；字体渲染等本就干净
    的来源可关掉，转换退化为纯几何变换。空图返回全白画布。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    gray = gray.astype(np.uint8)

    raw_mask = sauvola_binarize(gray)
    mask = raw_mask
    if clean:
        mask = remove_edge_specks(mask)
        mask = _drop_stray_components(mask)
        removed = ((raw_mask > 0) & (mask == 0)).astype(np.uint8)
        if removed.any():
            # 残渣连灰晕一起抹白，但不啃到保留笔画
            ker = np.ones((3, 3), np.uint8)
            halo = cv2.dilate(removed, ker) & (1 - cv2.dilate(mask, ker))
            gray = gray.copy()
            gray[(removed | halo).astype(bool)] = 255

    out = np.full((size, size), 255, dtype=np.uint8)
    bbox = ink_bbox(mask)
    if bbox is None:
        return out
    x0, y0, x1, y1 = bbox
    crop = gray[y0:y1, x0:x1]
    mcrop = mask[y0:y1, x0:x1]

    content = max(1, int(round(size * (1.0 - 2.0 * margin_ratio))))
    ch, cw = crop.shape
    scale = min(content / max(ch, cw), 1.0)   # 只缩不放
    nh = max(1, min(size, int(round(ch * scale))))
    nw = max(1, min(size, int(round(cw * scale))))
    if scale < 1.0:
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
        rmask = cv2.resize(mcrop.astype(np.uint8) * 255, (nw, nh),
                           interpolation=cv2.INTER_AREA) > 127
    else:
        resized, rmask = crop, mcrop > 0

    ys, xs = np.nonzero(rmask)
    if len(xs) == 0:
        return out
    cy, cx = float(ys.mean()), float(xs.mean())
    top = int(round(size / 2.0 - cy))
    left = int(round(size / 2.0 - cx))
    top = min(max(top, 0), size - nh)
    left = min(max(left, 0), size - nw)
    out[top:top + nh, left:left + nw] = resized
    return out


def is_canonical(img: np.ndarray, size: int = CANON_SIZE) -> bool:
    """形状/类型合规检查（不验证几何——几何由 to_canonical 保证）。"""
    return (img.ndim == 2 and img.shape == (size, size)
            and img.dtype == np.uint8)


def canonical_png(gray: np.ndarray, clean: bool = True) -> bytes:
    """任意字形图 → canonical PNG bytes（入库用）。"""
    ok, buf = cv2.imencode(".png", to_canonical(gray, clean=clean))
    if not ok:
        raise RuntimeError("PNG 編碼失敗")
    return buf.tobytes()
