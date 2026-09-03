"""Step1 边框探测：原图 → 版框（上下内外）+ 界行（含三段折线）+ 抬头框。

包的是 `utils/border_geometry.detect_borders`，输入直接是**原始扫描**（不经 s1..s6），
输出坐标天然是右上原点规范空间。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.borders import Borders
from ..utils.border_geometry import detect_borders


class BorderDetectParams(BaseModel):
    expected_cols: int | None = Field(default=None, description="列数先验；None = 用 Book 的 expected_cols")
    ink_threshold: int = 128


@register_step
class BorderDetectStep(Step):
    spec = StepSpec(
        id="border_detect", title="Step1 边框探测", version="1.0", unit="page",
        consumes=("raw_page",), produces=("borders",), params=BorderDetectParams,
        code_deps=("open_guji_cv.utils.border_geometry", "open_guji_cv.utils.peak_line_search"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        cols = p.expected_cols or ctx.book.expected_cols
        gray = ctx.raw_page(page)
        res = detect_borders(gray, expected_cols=cols, ink_threshold=p.ink_threshold)
        return {"borders": Borders.from_result(res, cols)}
