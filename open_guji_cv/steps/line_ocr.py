"""自由版式 Step2-b：逐列送识别软件读文本行（`free_ocr_lines`，可选）。

列按 Step2 的左右缝外接框裁出（拉正后的灰度图），送 PaddleOCR（books/zengguang_youxue/free_ocr.py`）。
出的行框换回页面坐标，Step3 `cell_cut` 拿它定区（大字行／并排小注行）和每行字数；
没跑这一步、或没装 paddleocr，Step3 照旧只用规则。Sheldon 10-28：「考虑用识别软件作为辅助」。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import FreeColumns, FreeOcrLines, OcrLineRec
from ..books.zengguang_youxue import free_ocr
from ..books.zengguang_youxue.free_cells import column_span
from ..books.zengguang_youxue.free_rectify import rectify_gray


class LineOcrParams(BaseModel):
    device: str = "cpu"


_READERS: dict[str, free_ocr.LineReader] = {}


@register_step
class LineOcrStep(Step):
    spec = StepSpec(
        id="line_ocr", title="Step2-b 列内识别行（自由版式，可选）", version="1.0", unit="page",
        consumes=("raw_page", "layout_blocks", "free_columns"), produces=("free_ocr_lines",), params=LineOcrParams,
        code_deps=("open_guji_cv.books.zengguang_youxue.free_ocr", "open_guji_cv.books.zengguang_youxue.free_cells", "open_guji_cv.books.zengguang_youxue.free_rectify"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: LineOcrParams = ctx.params_for(self)  # type: ignore[assignment]
        fc: FreeColumns = ctx.product("free_columns", page)
        if not free_ocr.available():
            raise RuntimeError("没装 paddleocr：line_ocr 跑不了（装 `.[cpu]`）；Step3 没有这一路照旧只用规则")
        out = FreeOcrLines(page=page, width=fc.width, height=fc.height, engine=free_ocr.engine_name())
        if not fc.columns:
            return {"free_ocr_lines": out}
        reader = _READERS.setdefault(p.device, free_ocr.LineReader(p.device))
        gray = rectify_gray(ctx.raw_page(page), ctx.product("layout_blocks", page).warp)
        for col in fc.columns:
            xa, xb = column_span(col, fc.width)
            y0, y1 = int(col.y0), int(col.y1)
            for x0, ya, x1, yb, text, score in reader.read(gray[y0:y1, xa:xb]):
                box = (float(xa + x0), float(y0 + ya), float(xa + x1 - 1), float(y0 + yb - 1))
                out.lines.append(OcrLineRec(col=col.col, box=bbox_tl_to_tr(box, fc.width), text=text, score=round(score, 4)))
        return {"free_ocr_lines": out}
