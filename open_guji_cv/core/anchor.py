"""坐标空间与换算。

规范空间 `raw_page_px@top-right`（用户 2026-09-03 裁定：古籍从右上角起）：
原点在页面右上角，x 向左递增，y 向下递增，列号从右到左从 1 起。
算法内部照旧用 numpy / OpenCV 的左上原点，只在落盘与锚点处换算。
换算沿用 `utils/border_geometry.py` 的像素中心约定：

    x_tr = (width - 1) - x_tl
"""

from __future__ import annotations

from .spec import COLUMN_PX, RAW_TL, RAW_TR

SPACES = (RAW_TR, RAW_TL, COLUMN_PX)

BBox = tuple[float, float, float, float]


def x_tl_to_tr(x: float, width: int) -> float:
    return float(width - 1) - float(x)


def x_tr_to_tl(x: float, width: int) -> float:
    return float(width - 1) - float(x)


def bbox_tl_to_tr(bbox: BBox, width: int) -> BBox:
    """[x0,y0,x1,y1]（左上原点）→ 右上原点；x 翻转后重排保证 x0 <= x1。"""
    x0, y0, x1, y1 = bbox
    a, b = x_tl_to_tr(x1, width), x_tl_to_tr(x0, width)
    return (min(a, b), float(y0), max(a, b), float(y1))


def bbox_tr_to_tl(bbox: BBox, width: int) -> BBox:
    return bbox_tl_to_tr(bbox, width)   # 对合变换，正反同式


def to_cv(bbox: BBox, width: int, space: str = RAW_TR) -> tuple[int, int, int, int]:
    """任一页面空间的 bbox → 可直接切片的整数左上原点 bbox。"""
    if space == RAW_TL:
        x0, y0, x1, y1 = bbox
    elif space == RAW_TR:
        x0, y0, x1, y1 = bbox_tr_to_tl(bbox, width)
    else:
        raise ValueError(f"to_cv 不接受空间 {space!r}")
    return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
