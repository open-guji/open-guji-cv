"""Step4 字框收缩：Step3 粗格 → 贴合字身墨迹的紧框 + 自检 flags + 字块（缓存）。

沿用生产 `clustering/extractor.CharExtractor.extract_page`（用户裁定可直接复用）。它吃的是
「整页图 + phase3 网格字典」，这里用**一列当一页**喂它：列图已经射影矫正、逐列去斜
（文档要求「逐列单独去斜」），网格字典只有一列，格子来自 Step3。

P0 的已知简化：Step3 已拆好的夹注 a/b 半格在这里合成一个满宽格交给 extract_page，
由它内部的夹注逻辑再拆一次（网格字典表达不了半宽格）。两套判据一致时结果相同；
不一致的列会在 flags 里露出来，留待接口打通后改成直接喂半宽框。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, cell_key, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import ColumnCells, PageCells
from ..products.kinds.chars import CharRec, ColumnChars, PageChars
from ..products.kinds.columns import PageWindows
from ._warpmap import ColumnMapper


class CellShrinkParams(BaseModel):
    strategy: str = "component_owner"     # | padding_box
    padding_ratio: float = 0.08
    min_ink_ratio: float = 0.01


@register_step
class CellShrinkStep(Step):
    spec = StepSpec(
        id="cell_shrink", title="Step4 字框收缩", version="1.0", unit="cell",
        consumes=("cells", "column_windows", "column_image"), produces=("char_index", "char_patch"),
        params=CellShrinkParams,
        code_deps=("open_guji_cv.clustering.extractor", "open_guji_cv.clustering.crop_quality"),
    )

    # ── 一列 ──────────────────────────────────────────────────────────
    def _extract_column(self, ctx: RunContext, page: int, cc: ColumnCells,
                        img: np.ndarray) -> list[tuple[object, np.ndarray | None]]:
        from ..clustering.extractor import CharExtractor
        p: CellShrinkParams = ctx.params_for(self)  # type: ignore[assignment]
        h, w = img.shape[:2]
        # Step3 每个物理位置一格；夹注 a/b 合成一格（满宽），空白格给 empty
        by_pos: dict[int, dict] = {}
        for c in cc.cells:
            d = by_pos.setdefault(c.pos, {"index": c.pos - 1, "y_top": c.y0, "y_bottom": c.y1,
                                          "type": "empty", "kinds": set()})
            d["kinds"].add(c.kind)
            d["y_top"], d["y_bottom"] = min(d["y_top"], c.y0), max(d["y_bottom"], c.y1)
            if c.kind != "blank":
                d["type"] = "char"
        cells = [{"type": d["type"], "index": d["index"], "y_top": float(d["y_top"]),
                  "y_bottom": float(d["y_bottom"])}
                 for _, d in sorted(by_pos.items())]
        x0, x1 = cc.content_x or (0.0, float(w))
        grid = {
            "image_size": [int(w), int(h)],
            "chars_per_line": cc.n_body_slots,
            "grid": {"shear": 0.0, "period": cc.ref_w or float(x1 - x0),
                     "cell_h": cc.period, "head_raise_rows": 0},
            "columns": [{"index": cc.col, "left_x": float(x0), "right_x": float(x1),
                         "cell_left_x": float(x0), "cell_right_x": float(x1), "cells": cells}],
        }
        ex = CharExtractor(padding_ratio=p.padding_ratio, min_ink_ratio=p.min_ink_ratio,
                           strategy=p.strategy)
        return ex.extract_page(img, grid, ctx.book.id, str(page))

    # ── Step 接口 ─────────────────────────────────────────────────────
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        cells: PageCells = ctx.product("cells", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        out: list[ColumnChars] = []
        for cc in cells.columns:
            if not cc.ok:
                out.append(ColumnChars(col=cc.col, ok=False, error=cc.error))
                continue
            img = ctx.image("column_image", column_key(page, cc.col))
            wrec = wins.column(cc.col)
            mapper = (ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                   wrec.top_y, wrec.bottom_y) if wrec else None)
            step3_kind = {c.pos: ("jiazhu" if c.kind.startswith("jiazhu") else c.kind) for c in cc.cells}
            pos_to_slot = {c.pos: c.slot for c in cc.cells}
            recs: list[CharRec] = []
            for inst, patch in self._extract_column(ctx, page, cc, img):
                pos = int(inst.idx) + 1
                slot = pos_to_slot.get(pos, pos)
                key = cell_key(page, cc.col, slot) + (inst.sub or "")
                patch_key = None
                if patch is not None and getattr(patch, "size", 0) > 0 and inst.cell_type == "char":
                    ctx.cache.put(ctx.book.id, "char_patch", key, patch)
                    patch_key = key
                bbox = tuple(float(v) for v in inst.bbox)
                recs.append(CharRec(
                    id=f"{ctx.book.id}:{page}:{cc.col}:{slot}{inst.sub or ''}",
                    slot=slot, pos=pos, idx=int(inst.idx), sub=inst.sub,
                    cell_type=inst.cell_type, step3_kind=step3_kind.get(pos, "char"),
                    bbox_col=bbox,
                    bbox_page=(None if mapper is None else
                               tuple(round(v, 2) for v in mapper.bbox_tr(*bbox))),
                    ink_ratio=float(inst.ink_ratio), height=float(inst.height), width=float(inst.width),
                    flags=list(inst.flags), patch_key=patch_key,
                ))
            out.append(ColumnChars(col=cc.col, ok=True, n_instances=len(recs), chars=recs))
        return {"char_index": PageChars(page=page, columns=out)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        sub = ""
        if key[-1] in "ab":
            key, sub = key[:-1], key[-1]
        page, col, slot = parse_key(key)
        if col is None or slot is None:
            raise ValueError(f"char_patch 的键必须带列号与 slot: {key}")
        cells: PageCells = ctx.product("cells", page)
        cc = cells.column(col)
        if cc is None or not cc.ok:
            raise KeyError(f"第 {page} 页第 {col} 列没有可用的字格")
        img = ctx.image("column_image", column_key(page, col))
        pos_to_slot = {c.pos: c.slot for c in cc.cells}
        for inst, patch in self._extract_column(ctx, page, cc, img):
            if pos_to_slot.get(int(inst.idx) + 1) == slot and (inst.sub or "") == sub and patch is not None:
                return patch
        raise KeyError(f"再生不出字块: {key}{sub}")
