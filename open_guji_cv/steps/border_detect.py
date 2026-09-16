"""Step1 边框探测：原图 → 版框（上下内外）+ 界行（含三段折线）+ 抬头框 + 列类型。

包的是 `utils/border_geometry.detect_borders`，输入直接是**原始扫描**（不经 s1..s6），
输出坐标天然是右上原点规范空间。

另产 `line_index`（与现代链 `line_detect` **同一种产物**）：逐列位记类型
`body | margin | edge`，下游据此把非正文列排除在外。筒子页（`leaf_layout: folio`）
的版心就是靠它标成 `margin` 的——判据与两条负结果见 `utils/column_types.py`。
一页一个半叶的书（`leaf_layout: single`，即默认）只会标出 `edge`，其余全是 `body`，
与加这套东西之前的行为等价。
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
        id="border_detect", title="Step1 边框探测", version="1.1", unit="page",
        consumes=("raw_page",), produces=("borders", "line_index"), params=BorderDetectParams,
        code_deps=("open_guji_cv.utils.border_geometry", "open_guji_cv.utils.peak_line_search",
                   "open_guji_cv.utils.column_types"),
        # `leaf_layout` 决定要不要标版心（`margin`），改册配置必须让产物过期
        book_deps=("leaf_layout", "expected_cols", "bottom_gap"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        cols = p.expected_cols or ctx.book.expected_cols
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        # `bottom_gap` 给了才启用下版框跨页先验救援；没给就是加这套机制之前的
        # 行为（缺省参数逐位不变）。标定方法见 BookSpec.bottom_gap 的注释。
        res = detect_borders(gray, expected_cols=cols, ink_threshold=p.ink_threshold,
                             book_bottom_gap=ctx.book.bottom_gap)
        borders = Borders.from_result(res, cols)

        # 列类型：`borders.verticals` 已是右上原点空间、x 升序（右→左），与
        # `line_index` 同一坐标空间，不需要翻转。y 取版框上下沿（列位是整列的，
        # 不逐列量墨——那是 Step2/3 的事）。
        xs = [float(v.x_at_top) for v in borders.verticals]
        top_y = float(res.top.y_at(0.0)) if res.top is not None else 0.0
        bot_y = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(H - 1)
        lines = [
            LineRec(col=c.col, kind=c.kind, x0=c.x0, x1=c.x1, y0=top_y, y1=bot_y,
                    width=c.width, flags=([c.reason] if c.reason else []))
            for c in classify_columns(xs, leaf_layout=ctx.book.leaf_layout)
        ]
        n_body = sum(1 for ln in lines if ln.kind == "body")
        return {
            "borders": borders,
            "line_index": LineIndex(page=page, width=W, height=H, em=None,
                                    pitch=None, n_body=n_body, lines=lines),
        }
