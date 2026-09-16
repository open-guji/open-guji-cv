"""Step1 边框探测：原图 → 版框（上下内外）+ 界行（含三段折线）+ 抬头框 + 列类型。

包的是 `utils/border_geometry.detect_borders`，输入直接是**原始扫描**（不经 s1..s6），
输出坐标天然是右上原点规范空间。

另产 `line_index`（与现代链 `line_detect` **同一种产物**）：逐列位记类型
`body | margin | edge`，下游据此把非正文列排除在外。筒子页（`leaf_layout: folio`）
的版心就是靠它标成 `margin` 的——判据与两条负结果见 `utils/column_types.py`。
一页一个半叶的书（`leaf_layout: single`，即默认）只会标出 `edge`，其余全是 `body`，
与加这套东西之前的行为等价。

`BookSpec.column_grid` 开了走网格模式（界行没印全的书，见
`peak_line_search.find_vertical_lines_grid`）：`borders.vline_filled` 标出插值的线，
`line_index` 里两侧至少一条界行是插值的列位加 `rule_interpolated` 旗标。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.borders import Borders
from ..products.kinds.line_index import LineIndex, LineRec
from ..utils.border_geometry import detect_borders
from ..utils.column_types import classify_columns


class BorderDetectParams(BaseModel):
    expected_cols: int | None = Field(default=None, description="列数先验；None = 用 Book 的 expected_cols")
    ink_threshold: int = 128


@register_step
class BorderDetectStep(Step):
    spec = StepSpec(
        id="border_detect", title="Step1 边框探测", version="1.2", unit="page",
        consumes=("raw_page",), produces=("borders", "line_index"), params=BorderDetectParams,
        code_deps=("open_guji_cv.utils.border_geometry", "open_guji_cv.utils.peak_line_search",
                   "open_guji_cv.utils.column_types"),
        # `leaf_layout` 决定要不要标版心（`margin`），改册配置必须让产物过期；
        # `column_grid` / `col_pitch` / `vline_polyline` 决定竖线走哪条路，同理
        book_deps=("leaf_layout", "expected_cols", "bottom_gap",
                   "top_band_frac", "bottom_band_frac", "column_grid", "col_pitch",
                   "vline_polyline"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        cols = p.expected_cols or ctx.book.expected_cols
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        # `bottom_gap` 给了才启用下版框跨页先验救援；没给就是加这套机制之前的
        # 行为（缺省参数逐位不变）。标定方法见 BookSpec.bottom_gap 的注释。
        res = detect_borders(gray, expected_cols=cols, ink_threshold=p.ink_threshold,
                             book_bottom_gap=ctx.book.bottom_gap,
                             top_band_frac=ctx.book.top_band_frac,
                             bottom_band_frac=ctx.book.bottom_band_frac,
                             column_grid=ctx.book.column_grid,
                             col_pitch=ctx.book.col_pitch,
                             vline_polyline=ctx.book.vline_polyline)
        borders = Borders.from_result(res, cols)

        # 列类型：`borders.verticals` 已是右上原点空间、x 升序（右→左），与
        # `line_index` 同一坐标空间，不需要翻转。y 取版框上下沿（列位是整列的，
        # 不逐列量墨——那是 Step2/3 的事）。
        xs = [float(v.x_at_top) for v in borders.verticals]
        filled = list(res.vline_filled) or [False] * len(xs)
        top_y = float(res.top.y_at(0.0)) if res.top is not None else 0.0
        bot_y = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(H - 1)
        lines = []
        for c in classify_columns(xs, leaf_layout=ctx.book.leaf_layout):
            flags = [c.reason] if c.reason else []
            # 列位 col（1 起）夹在 xs[col-1] 与 xs[col] 之间；任一侧是插值线就标出来
            if filled[c.col - 1] or filled[c.col]:
                flags.append("rule_interpolated")
            lines.append(LineRec(col=c.col, kind=c.kind, x0=c.x0, x1=c.x1, y0=top_y, y1=bot_y,
                                 width=c.width, flags=flags))
        n_body = sum(1 for ln in lines if ln.kind == "body")
        return {
            "borders": borders,
            "line_index": LineIndex(page=page, width=W, height=H, em=None,
                                    pitch=None, n_body=n_body, lines=lines),
        }
