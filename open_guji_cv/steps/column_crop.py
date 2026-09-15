"""Step2（现代印刷链）单列裁剪 + 去噪：虚拟界行之间直接裁成列图，不剥界行、不削版框。

与刻本链 `column_warp` 产同一套种类（`column_windows` / `column_raw` / `column_image`），
出口挂同一道闸 `column_gate`（见 `gates/column_gate.py` 末尾）。不改 `column_warp`
而另起一步的原因：现代页没有界行版框，`clean_column` 那套「先定文字带、抹侧、削上下」
在没有墙的列上会啃掉首末字；而 `column_warp.py` 又是切分侧会话正在改的文件，
不往里加开关（三模式方案 §七）。

射影仍走 `warp_column`——虚拟界行是竖直直线，射影退化成裁剪，但走同一条路保证
`_warpmap.ColumnMapper` 逆映射与刻本链一致。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.borders import Borders, VLineRec
from ..products.kinds.columns import BorderTrim, ColumnWindowRec, PageWindows
from ..utils.column_projection import (ColumnWindow, denoise_column, page_column_windows,
                                       stamp_noise_density, warp_column)
from .column_warp import side_floor


class ColumnCropParams(BaseModel):
    ink_threshold: int = 128
    min_blob_area: int = 6            # denoise_column
    side_floor_look: float = 0.25


@register_step
class ColumnCropStep(Step):
    spec = StepSpec(
        id="column_crop", title="Step2 单列裁剪 + 去噪（现代印刷）", version="1.1", unit="column",
        consumes=("raw_page", "borders", "border_detect_gate_manifest", "line_index"),
        produces=("column_windows", "column_raw", "column_image"),
        params=ColumnCropParams,
        code_deps=("open_guji_cv.utils.column_projection",),
    )

    def _windows(self, ctx: RunContext, page: int) -> tuple[np.ndarray, Borders, list[ColumnWindow]]:
        """原图先抹掉 Step1 探到的**长横线**（贯穿 ≥ 半页宽的印刷线——北行日錄扫描页 4 的
        栏线印在了上栏顶上，落进裁剪框后每一列顶端都多出一条细横条，Step3 把它当成一个
        薄字，整页每列多一项）。抹的是原图副本，`raw_page` 缓存不动。竖线（书口栏线）在
        正文列之外，`line_detect` 分列时已经绕开，列图里本来就没有，不在这里处理。"""
        gray = ctx.raw_page(page).copy()
        borders: Borders = ctx.product("borders", page)
        li = ctx.product("line_index", page)
        for a, b in li.rules_h:
            y0, y1 = max(0, int(a) - 3), min(gray.shape[0], int(b) + 4)
            gray[y0:y1, :] = 255
        wins = page_column_windows(borders.to_result(), body_pad=0.0, bottom_pad=0.0, head_pad=0.0)
        return gray, borders, wins

    def _images(self, ctx: RunContext, gray: np.ndarray, win: ColumnWindow
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        p: ColumnCropParams = ctx.params_for(self)  # type: ignore[assignment]
        warped = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y)
        raw = denoise_column(warped, ink_threshold=p.ink_threshold, min_blob_area=p.min_blob_area)
        return raw, raw, warped

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnCropParams = ctx.params_for(self)  # type: ignore[assignment]
        gate: BorderDetectGateManifest = ctx.product("border_detect_gate_manifest", page)
        gray = ctx.raw_page(page)
        h, w = gray.shape[:2]
        if gate.page_type_policy == "skip":
            return {"column_windows": PageWindows(page=page, page_size=(int(w), int(h)),
                                                  vline_segments=1, denoised=True, columns=[])}
        gray, borders, wins = self._windows(ctx, page)
        recs: list[ColumnWindowRec] = []
        for win in wins:
            raw, cleaned, warped = self._images(ctx, gray, win)
            key = column_key(page, win.col)
            ctx.cache.put(ctx.book.id, "column_raw", key, raw)
            ctx.cache.put(ctx.book.id, "column_image", key, cleaned)
            recs.append(ColumnWindowRec(
                col=win.col,
                left_line=VLineRec.of(win.left), right_line=VLineRec.of(win.right),
                top_y=float(win.top_y), bottom_y=float(win.bottom_y),
                border_top_y=float(win.border_top_y), border_bottom_y=float(win.border_bottom_y),
                border_top_in_column=float(win.border_top_in_column),
                border_bottom_in_column=float(win.border_bottom_in_column),
                raised=False, head_raise_inner_y=None,
                warped_size=(int(cleaned.shape[1]), int(cleaned.shape[0])),
                band=(0, int(cleaned.shape[1])),
                trim_top=BorderTrim(px=0, case="none"), trim_bottom=BorderTrim(px=0, case="none"),
                side_floor=round(side_floor(raw, p.side_floor_look, p.ink_threshold), 4),
                stamp_noise=round(stamp_noise_density(warped, p.ink_threshold), 4),
            ))
        return {"column_windows": PageWindows(page=page, page_size=(int(w), int(h)),
                                              vline_segments=1, denoised=True, columns=recs)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        gate: BorderDetectGateManifest = ctx.product("border_detect_gate_manifest", page)
        if gate.page_type_policy == "skip":
            raise KeyError(f"第 {page} 页页型判定为「{gate.page_type}」，没有列产物")
        gray, _, wins = self._windows(ctx, page)
        win = next((w for w in wins if w.col == col), None)
        if win is None:
            raise KeyError(f"第 {page} 页没有第 {col} 列")
        raw, cleaned, _ = self._images(ctx, gray, win)
        return raw if kind_id == "column_raw" else cleaned
