"""Step2 单列射影变换 + 去噪 + 界行 / 版框清除。

包的是 `utils/column_projection` 的 page_column_windows → warp_column → denoise_column →
clean_column。numeric 产物存复现所需的全部量；两种列图（矫正去噪 / 清理后）只进缓存，
`render` 用同一条路径现算——射影与清理都是 (原图, Step1 线, 参数, 代码版本) 的确定性函数。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.borders import Borders, VLineRec
from ..products.kinds.columns import BorderTrim, ColumnWindowRec, PageWindows
from ..utils.column_projection import (ColumnWindow, clean_column, column_profile,
                                       denoise_column, page_column_windows, warp_column)


class ColumnWarpParams(BaseModel):
    body_pad: float = 0.0
    bottom_pad: float = 40.0          # 下界额外开的余量，见 column_projection.BOTTOM_PAD
    ink_threshold: int = 128
    min_blob_area: int = 6            # denoise_column
    side_floor_look: float = 0.25     # 交接闸 L2 用：两侧各看进去多少比例的宽度


def side_floor(raw: np.ndarray, look: float = 0.25, ink_threshold: int = 128) -> float:
    """两侧各外 look 里的最低墨占比，取两侧较大者。在**原始矫正图**上量，不是清理后。"""
    prof = column_profile(raw, ink_threshold=ink_threshold)
    k = max(1, int(round(look * len(prof))))
    return max(float(prof[:k].min()), float(prof[-k:].min()))


@register_step
class ColumnWarpStep(Step):
    spec = StepSpec(
        id="column_warp", title="Step2 单列射影 + 去噪 + 清理", version="1.1", unit="column",
        consumes=("raw_page", "borders"), produces=("column_windows", "column_raw", "column_image"),
        params=ColumnWarpParams,
        code_deps=("open_guji_cv.utils.column_projection", "open_guji_cv.utils.border_geometry"),
    )

    # ── 共用的一列计算 ─────────────────────────────────────────────────
    def _windows(self, ctx: RunContext, page: int) -> tuple[np.ndarray, Borders, list[ColumnWindow]]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        borders: Borders = ctx.product("borders", page)
        wins = page_column_windows(borders.to_result(), body_pad=p.body_pad,
                                   bottom_pad=p.bottom_pad)
        return gray, borders, wins

    def _images(self, ctx: RunContext, gray: np.ndarray, win: ColumnWindow
                ) -> tuple[np.ndarray, np.ndarray, dict]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        warped = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y)
        raw = denoise_column(warped, ink_threshold=p.ink_threshold, min_blob_area=p.min_blob_area)
        cleaned, diag = clean_column(raw, ink_threshold=p.ink_threshold)
        return raw, cleaned, diag

    # ── Step 接口 ─────────────────────────────────────────────────────
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gray, borders, wins = self._windows(ctx, page)
        recs: list[ColumnWindowRec] = []
        for win in wins:
            raw, cleaned, diag = self._images(ctx, gray, win)
            key = column_key(page, win.col)
            ctx.cache.put(ctx.book.id, "column_raw", key, raw)
            ctx.cache.put(ctx.book.id, "column_image", key, cleaned)
            b0, b1 = diag["band"]
            recs.append(ColumnWindowRec(
                col=win.col,
                left_line=VLineRec.of(win.left), right_line=VLineRec.of(win.right),
                top_y=float(win.top_y), bottom_y=float(win.bottom_y),
                border_top_y=float(win.border_top_y), border_bottom_y=float(win.border_bottom_y),
                border_top_in_column=float(win.border_top_in_column),
                border_bottom_in_column=float(win.border_bottom_in_column),
                raised=bool(win.raised),
                head_raise_inner_y=None if win.head_raise_inner_y is None else float(win.head_raise_inner_y),
                warped_size=(int(cleaned.shape[1]), int(cleaned.shape[0])),
                band=(int(b0), int(b1)),
                trim_top=BorderTrim(px=int(diag["top"]["px"]), case=str(diag["top"]["case"])),
                trim_bottom=BorderTrim(px=int(diag["bottom"]["px"]), case=str(diag["bottom"]["case"])),
                side_floor=round(side_floor(raw, p.side_floor_look, p.ink_threshold), 4),
            ))
        h, w = gray.shape[:2]
        return {"column_windows": PageWindows(
            page=page, page_size=(int(w), int(h)), vline_segments=int(borders.vline_segments),
            denoised=True, columns=recs)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        gray, _, wins = self._windows(ctx, page)
        win = next((w for w in wins if w.col == col), None)
        if win is None:
            raise KeyError(f"第 {page} 页没有第 {col} 列")
        raw, cleaned, _ = self._images(ctx, gray, win)
        return raw if kind_id == "column_raw" else cleaned
