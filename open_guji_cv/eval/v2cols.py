"""v2 链产物读取小工具：seam / truncation 评测改读现役 Step3（row_segment）+ Step2 列图用（2026-09-30 M1 B 道）。

原 eval_seam / eval_truncation 读 v1 链 `output/<册>/phase3_char_grid` + `output/<册>/<页>.png`（已退役）。
这里给出等价的 v2 输入：每页每个 ok 列 → (ColumnCells, 列图灰度)。坐标全在列图坐标（左上原点）。
"""
from __future__ import annotations

import json
from pathlib import Path


def body_pages(dataset: str) -> list[tuple[str, int]]:
    """page-type 金标里 page_type == body 的 (册, 页)，按册页排序。dataset = char-segmentation 目录。"""
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json").read_text(encoding="utf-8"))
    return sorted({(r["book"], int(r["page"])) for r in gold if r["page_type"] == "body"})


def iter_columns(book: str, page: int, store=None, step: str = "row_segment"):
    """yield (ColumnCells, gray ndarray)；取不到 cells / 列图的列跳过。"""
    import cv2
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from ..utils.image_io import imread as cv_imread
    store = store or ProductStore()
    cells = store.read(book, step, page_key(page), "cells")
    if cells is None:
        return
    cache = ImageCache()
    for cc in cells.columns:
        if not cc.ok or not cc.boundaries:
            continue
        path = cache.get(book, "column_image", f"p{page:04d}c{cc.col:02d}")
        if path is None:
            continue
        im = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        yield cc, im
