"""自由版式 Step1：原图 → 版框、长线、文字块（`layout_blocks`）。

坊刻本（yxat 起）没有固定格网、多半没有界行、一页可能分上下栏或好几格。这一步只回答
「页上有哪几块文字、按什么顺序读」，块内分列交给 Step2 `column_trace`。
人标的 `layout_hints` 优先：整页 skip、人圈的块、每块列数／列距提示都在这里落进产物。
自动分出的块再按版心裁一刀（`banxin` 参数说版心在哪侧；yxat 是奇数页在左）。
算法在 `utils/free_blocks.py`，提示的写法在 `utils/layout_hints.py`。
"""

from __future__ import annotations

import cv2
import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr, x_tl_to_tr
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import BlockRec, LayoutBlocks, RuleRec
from ..utils.free_blocks import (SPINE_MODES, Block, SplitParams, block_vrules, cut_pieces, find_banxin, find_banxin_gap,
                                 find_frame, find_rules, ink_mask, line_maps, snap_cut, spine_sides,
                                 split_region, thin_vlines, tree_blocks)
from ..utils.layout_hints import parse_layout_hints


class BlockDetectParams(BaseModel):
    bg_win: int = 51               # 背景中值窗（px）
    ink_ratio: float = 0.72        # 比背景暗过这个比例算墨
    n_strips: int = 8              # 找长线的条带数
    fill: float = 0.8              # 条带里一行墨占比 ≥ 此值、
    run: float = 0.65              # 且最长连续墨段 ≥ 此 × 条带宽，算「这一行是线」
    min_votes: int = 3             # 成线最少条带票数
    frame_votes: int = 4           # 当版框的线最少条带票数
    div_reach: float = 0.95        # 分栏线要首尾贯穿当前区（版心以内）的比例（1.3 起；原 div_span 0.6 会把混排页的半截线当分栏）
    div_cov: float = 0.4           # 细线像素至少盖住区宽的比例，才当一条线
    div_gap: int = 150             # 量贯穿时容许的断口（px；木版磨损、字贴线）
    auto_vsplit: bool = False      # 没人标时也试左右切（混排页）；缺省关：混排页由人标 tree
    split_depth: int = 3           # auto_vsplit 时递归切的层数（上下 → 左右 → 上下）
    banxin: str = "auto"           # 版心在哪侧：auto | left | right | odd_left | odd_right | none
    banxin_min: int = 20           # 版心线离框边的距离范围（px）
    banxin_max: int = 120
    banxin_line: float = 0.04      # 细竖线强度（框内列均值）够这个才算版心线
    banxin_pad: int = 4            # 块裁到版心线里面再让几 px
    banxin_gap: float = 0.35       # 线探不到时，书脊侧最空竖缝的墨 ≤ 此 × 框内中位才算版心分界
    banxin_gap_max: int = 100      # 退路只在框边往里这么远内找缝（再远就是正文列缝了）
    split_snap: int = 80           # 人标 splits 吸附的范围（px）：范围内有线（不论贯穿与否）吸到盖得最满的线，没有吸到最空的行


@register_step
class BlockDetectStep(Step):
    spec = StepSpec(
        id="block_detect", title="Step1 分块（自由版式）", version="1.3", unit="page",
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
        # 先认版心：分栏线「贯穿」是对版心以内的版面说的（版心线把栏线截在那里）
        if p.banxin not in SPINE_MODES:
            raise ValueError(f"block_detect.banxin 只能是 {SPINE_MODES}，写的是 {p.banxin!r}")
        sides = spine_sides(p.banxin, page)
        spine, bx = None, None
        if sides:
            prof = thin_vlines(gray, p.bg_win)[int(frame.top):int(frame.bottom)].mean(0)
            spine, bx = find_banxin(prof, frame.left, frame.right, sides, lo=p.banxin_min,
                                    hi=p.banxin_max, min_line=p.banxin_line)
            if spine is not None and bx is None:     # 线太浅：退到书脊一侧最空的竖缝
                band = ink[int(frame.top):int(frame.bottom)].mean(0).astype(np.float32)
                band = cv2.GaussianBlur(band.reshape(1, -1), (9, 1), 2).ravel()
                bx = find_banxin_gap(band, frame.left, frame.right, spine, lo=p.banxin_min,
                                     hi=p.banxin_gap_max, max_frac=p.banxin_gap)
        pad = 12
        x0, x1 = int(frame.left + pad), int(frame.right - pad)
        if bx is not None:
            if spine == "left":
                x0 = max(x0, int(bx) + p.banxin_pad)
            else:
                x1 = min(x1, int(bx) - p.banxin_pad)
        y0, y1 = int(frame.top + pad), int(frame.bottom - pad)

        leaves: list[dict] | None = None             # 版面树的叶子提示（与 blocks 一一对应）
        if hint is not None and hint.manual_blocks:
            blocks = [Block(*b.box, vrules=block_vrules(vs, *b.box), source="hint")  # type: ignore[misc]
                      for b in hint.blocks]
        else:
            hl, vl = line_maps(gray, ink, p.bg_win)
            prm = SplitParams(reach=p.div_reach, min_cov=p.div_cov, gap=p.div_gap, auto_v=p.auto_vsplit,
                              max_depth=p.split_depth, pad=pad)
            if hint is not None and hint.tree:
                pairs = tree_blocks(hint.tree, hl, vl, ink, x0, y0, x1, y1, prm)
                blocks, leaves = [b for b, _ in pairs], [n for _, n in pairs]
            elif hint is not None and hint.splits:
                # 人标说了切几刀就切几刀：每刀吸到附近盖得最满的线，没线吸到最空的行；不再自动加线
                ys = [snap_cut("h", y, p.split_snap, hl, vl, ink, x0, y0, x1, y1, prm) for y in hint.splits]
                blocks = [Block(x0, a, x1, b, source="hint") for a, b in cut_pieces(y0, y1, ys, prm)]
            else:
                blocks = split_region(hl, vl, x0, y0, x1, y1, prm=prm)
            for b in blocks:
                b.vrules = block_vrules(vs, b.x0, b.y0, b.x1, b.y1)

        def rule_rec(r) -> RuleRec:
            if r.orient == "h":      # y = a + s·x_tl → x_tl = W−1−x_tr
                return RuleRec(orient="h", a=r.a + r.slope * (W - 1), slope=-r.slope,
                               lo=x_tl_to_tr(r.hi, W), hi=x_tl_to_tr(r.lo, W), n_strips=r.n_strips)
            return RuleRec(orient="v", a=x_tl_to_tr(r.a, W), slope=-r.slope,
                           lo=float(r.lo), hi=float(r.hi), n_strips=r.n_strips)

        out.frame = bbox_tl_to_tr((frame.left, frame.top, frame.right, frame.bottom), W)
        out.frame_found = frame.found
        out.spine = spine
        out.banxin = None if bx is None else x_tl_to_tr(bx, W)
        out.rules = [rule_rec(r) for r in (*hs, *vs)]
        def leaf(i: int, k: str, fallback):
            v = leaves[i].get(k) if leaves else None
            return v if v is not None else fallback(i) if hint else None

        out.blocks = [BlockRec(index=i + 1, box=bbox_tl_to_tr((b.x0, b.y0, b.x1, b.y1), W),
                               kind=leaf(i, "kind", hint.kind_for) if hint else "text", source=b.source,
                               cols_hint=leaf(i, "cols", hint.cols_for) if hint else None,
                               pitch_hint=leaf(i, "pitch", hint.pitch_for) if hint else None,
                               vrules=sorted(x_tl_to_tr(x, W) for x in b.vrules))
                      for i, b in enumerate(blocks)]
        return {"layout_blocks": out}
