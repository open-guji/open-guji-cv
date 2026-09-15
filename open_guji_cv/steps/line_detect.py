"""Step1（现代印刷链）行探测：无版框界行的页 → 正文列的虚拟界行 + 全部列的类型。

顶替刻本链的 `border_detect`（三模式方案 §四.1，overview `图片初步数字化/进度/总览/
05-三模式管线方案.md`）。产出**同一种** `borders`——下游 Step2 拿它算列窗口一行不改；
另产 `line_index` 记页上每一列（含脚注、书口小字）的类型。算法在 `utils/line_layout.py`。

只处理竖排；横排按方案 §三在原图入口旋转后也走这里，尚未接入。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.borders import Borders, HLineRec
from ..products.kinds.line_index import LineIndex, LineRec
from ..utils.line_layout import detect_lines, layout_to_borders


class LineDetectParams(BaseModel):
    ink_threshold: int = 128
    col_ink_min: float = 0.008      # 列方向投影里算「有墨」的墨占比下限
    min_width_frac: float = 0.15    # 窄于 em × 此值的墨段当噪点丢掉
    body_lo: float = 0.75           # 正文列宽下限（× em）
    body_hi: float = 1.35           # 正文列宽上限（× em），更宽标 wide
    margin_gap_frac: float = 1.5    # 小字列离正文块超过 × 列距 → 书口小字
    pad_frac: float = 0.6           # 上下框在正文块外的余量（× em）。要 > Step4
    # extractor 找框线行的窗口 FRAME_HINT_TOL=40px，否则首末字的横笔会被当框线


@register_step
class LineDetectStep(Step):
    spec = StepSpec(
        id="line_detect", title="Step1 行探测（现代印刷）", version="1.0", unit="page",
        consumes=("raw_page",), produces=("borders", "line_index"), params=LineDetectParams,
        code_deps=("open_guji_cv.utils.line_layout",),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: LineDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        lay = detect_lines(gray, ink_threshold=p.ink_threshold, col_ink_min=p.col_ink_min,
                           min_width_frac=p.min_width_frac, body_lo=p.body_lo, body_hi=p.body_hi,
                           margin_gap_frac=p.margin_gap_frac)
        res = layout_to_borders(lay, pad_frac=p.pad_frac)
        n_body = len(lay.body)
        if res is None:
            borders = Borders(width=W, height=H, expected_cols=0,
                              top=HLineRec(y_at_right=0.0, slope=0.0, kind="top"),
                              bottom=HLineRec(y_at_right=float(H - 1), slope=0.0, kind="bottom"),
                              verticals=[])
        else:
            # expected_cols 记列位数（含 empty 空列位）——verticals 是 N+1 条，与它对应
            borders = Borders.from_result(res, len(lay.columns))

        def tr(x0: int, y0: int, x1: int, y1: int) -> tuple[float, float, float, float]:
            return bbox_tl_to_tr((float(x0), float(y0), float(x1), float(y1)), W)

        lines = [LineRec(col=r.col, kind=r.kind, width=float(r.width), flags=list(r.flags),
                         **dict(zip(("x0", "y0", "x1", "y1"), tr(r.x0, r.y0, r.x1 - 1, r.y1))))
                 for r in lay.runs]
        block = None if lay.block is None else tr(lay.block[0], lay.block[1], lay.block[2] - 1, lay.block[3] - 1)
        rules_v = [(float((W - 1) - (b - 1)), float((W - 1) - a)) for a, b in lay.rules_v]
        rules_h = [(float(a), float(b - 1)) for a, b in lay.rules_h]
        return {"borders": borders,
                "line_index": LineIndex(page=page, width=W, height=H, em=lay.em, pitch=lay.pitch,
                                        n_body=n_body, block=block, rules_v=rules_v, rules_h=rules_h,
                                        lines=lines)}
