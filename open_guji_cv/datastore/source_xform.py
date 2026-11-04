"""换图源后的坐标换算：旧页坐标 → 新页坐标（页表 `from_rev.H`）。

2026-11-04 殿本《四庫全書總目》图源切到 Commons 景印文淵閣本（A20，设计见计划文档「四庫總目图源切到
Commons 文淵閣本」）：新页表每页带

    "from_rev": {"rev": 3, "sha256": "<旧页图 sha>", "w": 1281, "h": 1920, "H": [[…], […], […]]}

`H` 是旧页（`from_rev.rev` 那一版页表里的同一页序）左上原点像素 → 新页左上原点像素的 3×3 齐次矩阵：
旧页 ×s 落到 600 dpi 大图，再按版框四边形透视摆正、加外扩。页序、页号不变，所以按「页:列:格」寻址的
东西不用改，只有带像素的字段要换。

本模块只管点和框，不碰任何 Step 产物格式；不在任何 Step 的 `code_deps` 里，改它不动指纹。

- 右上原点（`RAW_TR`，x 从页右边往左量）先转左上原点再乘 H，乘完再按新页宽转回。
- 框（轴对齐矩形）经透视后一般是略斜的四边形：`box_quad` 给四角，`box` 给外接矩形。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TL = "top-left"
TR = "top-right"


@dataclass(frozen=True)
class PageXform:
    """一页的换算：旧页尺寸、新页尺寸、H。"""
    seq: str
    page: int
    old_w: int
    old_h: int
    new_w: int
    new_h: int
    H: np.ndarray

    def points(self, pts, origin: str = TL) -> np.ndarray:
        """`pts`：N×2（旧页像素）→ N×2（新页像素），原点口径进出一致。"""
        p = np.asarray(pts, dtype=float).reshape(-1, 2).copy()
        if origin == TR:
            p[:, 0] = self.old_w - p[:, 0]
        elif origin != TL:
            raise ValueError(f"origin 只能是 {TL!r} 或 {TR!r}：{origin!r}")
        q = np.c_[p, np.ones(len(p))] @ self.H.T
        q = q[:, :2] / q[:, 2:3]
        if origin == TR:
            q[:, 0] = self.new_w - q[:, 0]
        return q

    def box_quad(self, x0: float, y0: float, x1: float, y1: float, origin: str = TL) -> np.ndarray:
        """轴对齐框（两角）→ 新页上的四角（左上、右上、右下、左下，按旧框的角序）。"""
        return self.points([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], origin)

    def box(self, x0: float, y0: float, x1: float, y1: float, origin: str = TL) -> tuple[float, float, float, float]:
        """轴对齐框 → 新页上四角的外接矩形 (x0, y0, x1, y1)。"""
        q = self.box_quad(x0, y0, x1, y1, origin)
        return float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())

    def xywh(self, x: float, y: float, w: float, h: float, origin: str = TL) -> tuple[float, float, float, float]:
        """IIIF 口径 (x, y, w, h)（左上原点）。"""
        a, b, c, d = self.box(x, y, x + w, y + h, origin)
        return a, b, c - a, d - b


def page_xforms(table: dict) -> dict[str, PageXform]:
    """页表 → {页序: PageXform}。没有 `from_rev` 的页（不是换源出来的）跳过。"""
    out: dict[str, PageXform] = {}
    for p in table.get("pages", []):
        f = p.get("from_rev")
        if not f or "H" not in f:
            continue
        H = np.asarray(f["H"], dtype=float)
        if H.shape != (3, 3):
            raise ValueError(f"{p['seq']} 的 from_rev.H 不是 3×3")
        out[p["seq"]] = PageXform(p["seq"], int(p["page"]), int(f["w"]), int(f["h"]), int(p["w"]), int(p["h"]), H)
    return out


def by_page(table: dict) -> dict[int, PageXform]:
    """同 `page_xforms`，按 cv 页号取（页号换源前后不变）。"""
    return {x.page: x for x in page_xforms(table).values()}


def from_rev(table: dict) -> int | None:
    """这版页表是从哪一版换算来的（各页应一致；不一致报错）。"""
    revs = {p["from_rev"]["rev"] for p in table.get("pages", []) if p.get("from_rev")}
    if len(revs) > 1:
        raise ValueError(f"页表里 from_rev 不止一版：{sorted(revs)}")
    return next(iter(revs), None)
