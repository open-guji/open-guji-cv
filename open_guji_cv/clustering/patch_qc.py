"""单字图块的裁切质检：只看图块本身，判「切分有没有切进框线」。

## 为什么要单独一个函数

`extractor.strip_frame_line` / `strip_frame_debris` 在 Step4 裁格时剥框线，但它们要整页／
整列上下文（格界、内容窗、全页线位），而且只对列首／列尾格调用。剥漏了的格进了快审，人就得一格格点掉。

史記文淵閣本第 1 轮参校字快审（2026-10-31，3120 格，Sheldon 拦下 323）里，被拦格最显眼的一类是
**图块顶上（或底下）横着一道版框／界栏细线**，字本身是对的。PaddleOCR 照样读对，所以 OCR 票拦不住；
但这道线只看图块就分得出来：

- 从图块边往里第一段墨行自成一带，后面隔着一段空白才是字身；
- 这一带又扁又宽：宽 ≥ 0.35 图块宽、宽高比 ≥ 3.3、厚 ≤ 0.13 图块高；
- 与字身的空白 ≥ 0.09 图块高——字自己的上横（三、王、元、玉、西）紧贴字身，空白都 < 0.08；
  或者这一带比字身还宽（≥ 1.15 倍）且很薄（≤ 0.08 图块高）——「帝」「初」框线贴得近，但比字宽。

第 1 轮实测：命中被拦格 47 个，人放行的 2797 格里只误中 1 个（「年」，列首格，图上确有一道线）。

只做判别不改像素：拿来给放行／送审打疑点，以后也可用来查切分是否切到边框。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

BINARY_THRESHOLD = 128      # 同 extractor.BINARY_THRESHOLD_PATCH

EDGE_ZONE = 0.3             # 墨带须起止在图块外侧这么多（× 图块高）以内
EDGE_MIN_GAP_PX = 2         # 墨带与字身之间至少这么多空白行，才算「自成一带」
LINE_MIN_ASPECT = 3.3       # 墨带外接框宽/高
LINE_MIN_SPAN = 0.35        # 墨带宽 ≥ 此 × 图块宽
LINE_MAX_THICK = 0.13       # 墨带厚 ≤ 此 × 图块高
LINE_MIN_GAP = 0.09         # 与字身空白 ≥ 此 × 图块高（字的上横紧贴字身，< 0.08）
LINE_WIDE_BODY = 1.15       # 或：墨带宽 ≥ 此 × 字身宽……
LINE_WIDE_THICK = 0.08      # ……且厚 ≤ 此 × 图块高（框线贴得近但比字宽：「帝」「初」）


@dataclass(frozen=True)
class EdgeBand:
    """图块上/下边与字身分离的一条墨带（坐标按从该边往里量）。"""
    side: str          # "top" | "bottom"
    offset: int        # 墨带离图块边的行数
    thick: int         # 墨带厚（行）
    gap: int           # 墨带与字身之间的空白行数
    span: float        # 墨带宽 / 图块宽
    aspect: float      # 墨带外接框宽 / 厚
    body_ratio: float  # 墨带宽 / 字身宽
    ink_frac: float    # 墨带墨量 / 图块总墨量
    patch_h: int

    @property
    def is_frame_line(self) -> bool:
        h = max(1, self.patch_h)
        thick, gap = self.thick / h, self.gap / h
        if not (self.aspect >= LINE_MIN_ASPECT and self.span >= LINE_MIN_SPAN
                and thick <= LINE_MAX_THICK):
            return False
        return gap >= LINE_MIN_GAP or (self.body_ratio >= LINE_WIDE_BODY and thick <= LINE_WIDE_THICK)


def _gray(patch: np.ndarray) -> np.ndarray:
    return patch if patch.ndim == 2 else cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)


def edge_bands(patch: np.ndarray, zone: float = EDGE_ZONE,
               min_gap: int = EDGE_MIN_GAP_PX) -> dict[str, EdgeBand | None]:
    """找图块上、下边各自「与字身隔开」的第一条墨带；没有就是 None。"""
    ink = _gray(patch) < BINARY_THRESHOLD
    h, w = ink.shape
    total = int(ink.sum())
    out: dict[str, EdgeBand | None] = {"top": None, "bottom": None}
    if total == 0:
        return out
    for side in ("top", "bottom"):
        b = ink if side == "top" else ink[::-1]
        occ = b.any(axis=1)
        y0 = int(np.argmax(occ))
        y = y0
        while y < h and occ[y]:
            y += 1
        y1 = y
        while y < h and not occ[y]:
            y += 1
        gap = y - y1
        if y >= h or gap < min_gap or y1 > zone * h:
            continue
        band = b[y0:y1]
        cols = np.flatnonzero(band.any(axis=0))
        bw, bh = int(cols[-1] - cols[0] + 1), y1 - y0
        bcols = np.flatnonzero(b[y:].any(axis=0))
        body_w = int(bcols[-1] - bcols[0] + 1)
        out[side] = EdgeBand(side=side, offset=y0, thick=bh, gap=gap, span=bw / w,
                             aspect=bw / bh, body_ratio=bw / body_w,
                             ink_frac=float(band.sum()) / total, patch_h=h)
    return out


def edge_frame_lines(patch: np.ndarray) -> list[EdgeBand]:
    """图块上/下边残留的版框／界栏横线（见模块说明的判据）。空列表＝没切到框线。"""
    return [b for b in edge_bands(patch).values() if b is not None and b.is_frame_line]


def has_edge_frame_line(patch: np.ndarray) -> bool:
    return bool(edge_frame_lines(patch))
