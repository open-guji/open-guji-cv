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


def crop_patch(img, bbox: BBox, space: str = RAW_TR):
    """按任一页面空间的 bbox（默认 `char_index.bbox_page` 用的 `raw_page_px@top-right`）
    从一张左上原点的图（`cv2`/`numpy` 读出来的原图、二值副本都是这个原点）裁出对应的
    图块。任务卡 #54 第12条：`bbox_page` 原点在页面**右上角**、x 从右往左量，直接拿它
    当左上原点 bbox 去裁**会静默裁到另一个字**（`console/routers/products.py` 那次
    实审就是这么栽的：p3c11s11「鳳」按 x=1467 裁，真身在 x=1243，两者正好差
    `(W-1) - 1557`——y 完全没错，看着像"没对齐"，其实是坐标系搞错了）。

    这个函数把 `to_cv()`（坐标换算）与切片一起包掉，调用方不用记那条镜像公式：

    ```python
    g = cv_imread(str(page_png), cv2.IMREAD_GRAYSCALE)
    patch = crop_patch(g, ch.bbox_page)   # ch: products.kinds.chars.CharRec
    ```

    `img.shape[1]` 当宽度；越界会先夹到图内，框退化（x1<=x0 或 y1<=y0）时返回
    `None`（不抛，调用方按"这一格没裁出来"处理，同 `console/routers/products.py`
    原有的失败语义）。"""
    h, w = img.shape[0], img.shape[1]
    x0, y0, x1, y1 = to_cv(bbox, w, space)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return img[y0:y1, x0:x1]
