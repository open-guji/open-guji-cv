# -*- coding: utf-8 -*-
"""M1 道 C 组共用件：评测读**现行 v2 链**（Step1→Step4 cell_shrink）的产物。

背景（2026-09-30）：recrop / instance_quality / char_drop / left_cut / right_cut / jiazhu_tail
这批评测原先读的是已退役 v1 链的 `./output/<册>/phase3_char_grid`、`phase4_chars`，
云端没有那棵树，静默扫到 0 页 → 假通过 / 格位消失。现在改读
`$GUJI_PRODUCTS_DIR/<册>/{row_segment,cell_shrink}/pNNNN.json`（只有数值）+ 缓存里的列图/字块。

本模块只做「把 v2 产物读出来、缺了就用现有引擎补」，不含任何评测口径。

坐标约定（与 `core/anchor.py` 一致）：
  - `CharRec.bbox_page` 是 `raw_page_px@top-right`（原点右上角，x 向左量）——
    要在 cv2/numpy 读出来的（左上原点）原图上裁，先 `tr2tl`；
  - `CharRec.bbox_col` 是列图坐标（左上原点，射影矫正后的列图）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def tr2tl(bbox, width: int):
    """raw_page_px@top-right 的 [x0,y0,x1,y1] → 左上原点（对合变换，正反同式）。"""
    x0, y0, x1, y1 = bbox
    a, b = (width - 1) - x1, (width - 1) - x0
    return (min(a, b), float(y0), max(a, b), float(y1))


tl2tr = tr2tl


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def dataset_root() -> Path:
    return (REPO.parent / "open-guji-dataset").resolve()


def workspace_output_dir() -> Path | None:
    """v1 链留在工作区里的 `output/`（只有整页 png，**没有** phase3/phase4）。

    迁移脚本要它（金标坐标系的页图）；评测本身不要——评测只读 v2 产物。
    """
    ws = os.environ.get("GUJI_WORKSPACE")
    if ws and (Path(ws) / "output").exists():
        return Path(ws) / "output"
    # overlay 工作区只有软链；退一步直接找同级 guji-workspace 里的四庫
    g = REPO.parent / "guji-workspace"
    for d in g.glob("96mid*"):
        if (d / "output").exists():
            return d / "output"
    return None


class V2Book:
    """一本书的 v2 产物读取器（懒加载、缺页可补）。"""

    def __init__(self, book: str, log=None):
        from open_guji_cv.core.book import load_book
        from open_guji_cv.core.step import RunContext
        from open_guji_cv.products import kinds as _k  # noqa: F401  注册产物种类
        from open_guji_cv.products.cache import ImageCache
        from open_guji_cv.products.store import ProductStore
        self.id = book
        self.bk = load_book(book)
        self.store = ProductStore()
        self.cache = ImageCache()
        self.log = log or (lambda s: None)
        self.ctx = RunContext(self.bk, self.store, self.cache, log=self.log)
        self._chars: dict = {}
        self._cells: dict = {}
        self._wins: dict = {}

    # ── 产物 ───────────────────────────────────────────────────────
    def has_step4(self, page: int) -> bool:
        from open_guji_cv.core.spec import page_key
        return self.store.exists(self.id, "cell_shrink", page_key(page))

    def ensure(self, pages, quiet: bool = True) -> list[int]:
        """缺 Step4 产物的页，用现有引擎从原图补跑到 cell_shrink（只补缺、不 force）。

        返回仍然没有产物的页（多半是整页 DP 无解的职名页）。
        """
        from open_guji_cv.core.engine import Engine
        from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline
        pages = sorted({int(p) for p in pages})
        miss = [p for p in pages if not self.has_step4(p)]
        if not miss:
            return []
        pl = load_pipeline(default_pipeline_id(self.bk))
        steps = list(pl.steps) if hasattr(pl, "steps") else list(pl.step_ids)
        steps = [s if isinstance(s, str) else getattr(s, "id", str(s)) for s in steps]
        steps = steps[: steps.index("cell_shrink") + 1]
        eng = Engine(self.bk, pl, store=self.store, cache=self.cache,
                     log=(lambda s: None) if quiet else print)
        eng.run(steps=steps, pages=miss)
        return [p for p in miss if not self.has_step4(p)]

    def chars(self, page: int):
        if page not in self._chars:
            from open_guji_cv.core.spec import page_key
            self._chars[page] = self.store.read(self.id, "cell_shrink", page_key(page), "char_index")
        return self._chars[page]

    def cells(self, page: int):
        if page not in self._cells:
            from open_guji_cv.core.spec import page_key
            self._cells[page] = self.store.read(self.id, "row_segment", page_key(page), "cells")
        return self._cells[page]

    def windows(self, page: int):
        if page not in self._wins:
            from open_guji_cv.core.spec import page_key
            self._wins[page] = self.store.read(self.id, "column_warp", page_key(page), "column_windows")
        return self._wins[page]

    # ── 图像 ───────────────────────────────────────────────────────
    def scan(self, page: int) -> np.ndarray:
        """原图灰度（左上原点，1 字节）。"""
        return self.ctx.raw_page(page)

    def col_img(self, page: int, col: int) -> np.ndarray:
        from open_guji_cv.core.spec import column_key
        return self.ctx.image("column_image", column_key(page, col))

    def patch(self, patch_key: str) -> np.ndarray:
        return self.ctx.image("char_patch", patch_key)
