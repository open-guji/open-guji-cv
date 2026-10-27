"""自由版式 Step1：原图 → 版框、长线、文字块（`layout_blocks`）。

坊刻本（yxat 起）没有固定格网、多半没有界行、一页可能分上下栏或好几格。这一步只回答
「页上有哪几块文字、按什么顺序读」，块内分列交给 Step2 `column_trace`。
人标的 `layout_hints` 优先：整页 skip、人圈的块、每块列数提示都在这里落进产物。
算法在 `utils/free_blocks.py`，提示的写法在 `utils/layout_hints.py`。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr, x_tl_to_tr
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import BlockRec, LayoutBlocks, RuleRec
from ..utils.free_blocks import Block, block_vrules, find_frame, find_rules, ink_mask, page_blocks
from ..utils.layout_hints import parse_layout_hints


class BlockDetectParams(BaseModel):
    bg_win: int = 51               # 背景中值窗（px）
    ink_ratio: float = 0.72        # 比背景暗过这个比例算墨
    n_strips: int = 8              # 找长线的条带数
    fill: float = 0.8              # 条带里一行墨占比 ≥ 此值、
    run: float = 0.65              # 且最长连续墨段 ≥ 此 × 条带宽，算「这一行是线」
    min_votes: int = 3             # 成线最少条带票数
    frame_votes: int = 4           # 当版框的线最少条带票数
    div_span: float = 0.6          # 分栏横线至少跨版框宽的比例


@register_step
class BlockDetectStep(Step):
    spec = StepSpec(
        id="block_detect", title="Step1 分块（自由版式）", version="1.0", unit="page",
        consumes=("raw_page",), produces=("layout_blocks",), params=BlockDetectParams,
        code_deps=("open_guji_cv.utils.free_blocks", "open_guji_cv.utils.layout_hints"),
        book_deps=("layout_hints",),
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BlockDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        hint = parse_layout_hints(getattr(ctx.book, "layout_hints", None)).get(page)
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        out = LayoutBlocks(page=page, width=W, height=H, hinted=hint is not None)
        if hint is not None and hint.type == "skip":
            out.page_type = "skip"
            return {"layout_blocks": out}

        ink = ink_mask(gray, p.bg_win, p.ink_ratio)
        hs, vs = find_rules(ink, p.n_strips, p.fill, p.run, min_votes=p.min_votes)
        frame = find_frame(ink, hs, vs, min_votes=p.frame_votes)
        if hint is not None and hint.manual_blocks:
            blocks = [Block(*b.box, vrules=block_vrules(vs, *b.box), source="hint")  # type: ignore[misc]
                      for b in hint.blocks]
        else:
            blocks = page_blocks(ink, frame, hs, vs, div_span=p.div_span)

        def rule_rec(r) -> RuleRec:
            if r.orient == "h":      # y = a + s·x_tl → x_tl = W−1−x_tr
                return RuleRec(orient="h", a=r.a + r.slope * (W - 1), slope=-r.slope,
                               lo=x_tl_to_tr(r.hi, W), hi=x_tl_to_tr(r.lo, W), n_strips=r.n_strips)
            return RuleRec(orient="v", a=x_tl_to_tr(r.a, W), slope=-r.slope,
                           lo=float(r.lo), hi=float(r.hi), n_strips=r.n_strips)

        out.frame = bbox_tl_to_tr((frame.left, frame.top, frame.right, frame.bottom), W)
        out.frame_found = frame.found
        out.rules = [rule_rec(r) for r in (*hs, *vs)]
        out.blocks = [BlockRec(index=i + 1, box=bbox_tl_to_tr((b.x0, b.y0, b.x1, b.y1), W),
                               kind=hint.kind_for(i) if hint else "text", source=b.source,
                               cols_hint=hint.cols_for(i) if hint else None,
                               vrules=sorted(x_tl_to_tr(x, W) for x in b.vrules))
                      for i, b in enumerate(blocks)]
        return {"layout_blocks": out}
