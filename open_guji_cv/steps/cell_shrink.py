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
from pydantic import BaseModel, model_serializer

from ..core.spec import StepSpec, cell_key, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import ColumnCells, CutPointCandidates, PageCells
from ..products.kinds.chars import CandidatePatch, CharRec, ColumnChars, PageChars
from ..products.kinds.columns import PageWindows
from ._warpmap import ColumnMapper


class CellShrinkParams(BaseModel):
    strategy: str = "component_owner"     # | padding_box
    padding_ratio: float = 0.08
    min_ink_ratio: float = 0.01
    seal_flag: bool = True
    """印章／大片污损遮挡格打 `seal_region` 旗（2026-09-30 L2，overview#318）：判据就是
    `steps/occlusion.page_occluded`（与 seed_admit 入库闸同一入口、同一组默认阈值），**只打标不改几何**——
    框、char/blank、字块一概不动，非遮挡格产物逐字节不变。此前切分完全不知道印章：字块裁得过宽、
    吞进半幅印泥，下游（定字裁决、人审卡）拿不到任何标记。"""
    yolo_gate: bool = False
    """YOLO 收框复核闸（Y1，overview#373，缺省关）。同一格里 yolo_tool 单字模型（**原生喂法**：整页版面
    模型出列条 → 裁条 → 单字模型，跑在原图上）的框比 CV 紧框
    **多包进来**的墨占比 > `yolo_extra_ink` → 给这格打 `yolo_box` 旗，`seed_admit.yolo_box_review`
    开着时它不放行、落人审。专抓「首字只框到最上一笔」「把下版框线当末字」「整列切成半宽框」。
    **只打标，不改框**（YOLO 框兜底没做：YOLO 框在页坐标，字块要在列图坐标重裁，ColumnMapper 只有
    列→页的正向映射，见 HANDOFF_Y1.md）。缺 onnxruntime／权重、推理失败、印章多的页
    （`yolo_max_seal`）一律弃权。关着时 `yolo_*` 都不进 dump，产物与参数哈希逐字节不变。"""
    yolo_weights: str = ""
    """yolo_tool 的 `model/slide/best.onnx` 路径（空 = 取环境变量 `GUJI_YOLO_WEIGHTS`）。路径不进指纹
    （`path_params`），权重**内容**指纹在 `yolo_weights_fp`。"""
    yolo_layout_weights: str = ""
    """版面模型 `model/type/best.onnx` 路径（空 = 与 `yolo_weights` 并排的 `../type/best.onnx`）。同样不进指纹。"""
    yolo_weights_fp: str = ""
    """自动填（`RunContext.params_for`）：两份权重内容的联合指纹（sha256 前 16 位）。读不到权重 = ""。"""
    yolo_extra_ink: float = 0.05
    """多出墨占比门槛（见 `utils/yolo_boxes.extra_ink_ratio`）。**0.05 是 vol02/vol03 共 294 页、4.6 万格上标的**
    （不是 yolo_tool 评测里的 0.25：贴版框那一侧的墨已按首/末格跳过，剩下的真错最多 0.14，0.25 一格都不命中；
    0.05 命中 38 格＝每页 0.13 格，目视约 1/4–1/3 是 CV 真错——言／益只框到一半、藏內两字合一格）。
    见 HANDOFF_Y1.md。"""
    yolo_max_seal: int = 2
    """一页里 `seal_region` 格数 > 这个数 = 印章页，闸整页弃权（YOLO 在印泥散点上成片出假字）。
    依赖 `seal_flag`；`seal_flag` 关着这条不起作用。"""
    frame_guard: bool = True
    """首/末格端区抹「版框横条行」（extractor.mask_frame_bars_outside）。刻本开；现代排印本
    （modern_body.yaml）关——没有版框，列末字的底横会被当框线抹掉（2026-09-15 北行日錄）。"""

    @model_serializer(mode="wrap")
    def _drop_yolo_when_off(self, handler):
        """`yolo_gate` 关着时 `yolo_*` 不进 dump：没开的书参数哈希与加字段前逐位相同。
        闸开着时 `yolo_weights`（路径）仍进 dump，由 `path_params` 剔出指纹。"""
        d = handler(self)
        if isinstance(d, dict):
            if not self.yolo_gate:
                for k in ("yolo_gate", "yolo_weights", "yolo_weights_fp", "yolo_extra_ink",
                          "yolo_max_seal", "yolo_layout_weights"):
                    d.pop(k, None)
        return d


def _yolo_weights(p: CellShrinkParams, seal: dict) -> tuple[str, str] | None:
    """闸这一页要不要跑：开着、两份权重都可读、不是印章页 → (单字, 版面) 权重路径；否则 None（弃权，不报错）。"""
    if not p.yolo_gate or len(seal) > p.yolo_max_seal:
        return None
    from pathlib import Path

    from ..utils.yolo_boxes import resolve_weights, sibling_layout
    slide = resolve_weights(p.yolo_weights)
    layout = p.yolo_layout_weights or sibling_layout(slide)
    return (slide, layout) if slide and Path(slide).is_file() and Path(layout).is_file() else None


class _YoloPage:
    """一页原图上的 YOLO 单字框 + 墨图（页坐标，左上原点），供逐格复核（`utils/yolo_boxes`）。"""

    def __init__(self, boxes, ink):
        self.boxes, self.ink = boxes, ink

    @classmethod
    def of(cls, weights: tuple[str, str], raw: np.ndarray) -> "_YoloPage | None":
        from ..utils import yolo_boxes as yb
        try:
            det = yb.detect_page(weights[0], weights[1], raw)
        except yb.YoloUnavailable:
            return None
        return cls([(x0, y0, x1, y1) for x0, y0, x1, y1, _, _ in det], (raw < 128).astype(np.uint8))


def _page_box(mapper: ColumnMapper, box) -> tuple[float, float, float, float]:
    """列图矩形 → 原图（左上原点）外包框。"""
    x0, y0, x1, y1 = (float(v) for v in box)
    pts = [mapper.to_page_tl(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _yolo_ratio(yp: _YoloPage, mapper: ColumnMapper, bbox, cell_rect,
                skip_top: bool = False, skip_bottom: bool = False):
    """这一格 YOLO 框比 CV 紧框多出的墨占比。返回 `(占比, 页坐标 YOLO 框)`；这格 YOLO 没出字、
    坐标映射失败 = `(None, None)`（弃权）。"""
    from ..utils import yolo_boxes as yb
    try:
        cv = _page_box(mapper, bbox)
        cell = _page_box(mapper, cell_rect)
    except Exception:                                     # noqa: BLE001 —— 映射不了就弃权
        return None, None
    y = yb.match_yolo(cv, (cell[1], cell[3]), yp.boxes, (cell[0], cell[2]))
    if y is None:
        return None, None
    return yb.extra_ink_ratio(yp.ink, cv, y, (cell[1], cell[3]), skip_top, skip_bottom), y


def _yolo_check(yp: _YoloPage, mapper: ColumnMapper, bbox, cell_rect, thr: float,
                skip_top: bool = False, skip_bottom: bool = False):
    """占比 > thr → 命中的 YOLO 框（页坐标），否则 None。"""
    r, y = _yolo_ratio(yp, mapper, bbox, cell_rect, skip_top, skip_bottom)
    return y if r is not None and r > thr else None


def _upright(ctx: RunContext, patch):
    """字块转回正。

    横排书在 `RunContext.raw_page` 入口整页顺时针转了 90°（三模式方案 §三），
    列图与格坐标都在读序空间——**但字块必须是正的**：Step5 之后（库匹配、
    OCR、字形库、人裁审查页）全都假设 `char_patch` 是端正的字。
    方案 §三 的落地表第三行写的就是这件事，2026-09-15 补上。

    没有它的后果不是难看：OCR 把躺着的「曹」读成「量」「聯」「海」，
    字形库存进去的也是躺着的字，跨书永远配不上。
    """
    if patch is None or getattr(patch, "size", 0) == 0:
        return patch
    if getattr(ctx.book, "writing_mode", "vertical-rl") != "horizontal-tb":
        return patch
    return np.rot90(patch, 1).copy()      # 入口转了 -1（顺时针），这里转回来


#: 抬头位（slot < 1）里「矮而满宽」的紧框是版框线，不是字（2026-09-25）。
#: 雙邊版框的外框线落在列窗里，Step3 给它开了一个抬头格，Step4 就把那条线当字框收了进来，
#: 一路送进识别。vol02 全书 29 个抬头位字框里 12 个是这种线（高 12–35px、宽 0.6 列以上），
#: 真抬头字（御/聖/易/厚…）高全在 97px 以上。门槛取 0.4 格高：抬头位出现「一」这类扁字
#: 在这套书里不存在（抬头是给御/聖/皇/天这些字的）。
FRAME_BAR_MAX_H = 0.4
FRAME_BAR_MIN_W = 0.6


FRAME_BAR_TOP = 0.15
"""首格（slot 1）也收框线（2026-09-26，用户定）：上边框线落在列首第一格里（vol02 p58c4、p113c9），
同样是矮而满宽，但首格可能真有扁字，所以多一条——紧框贴着格顶（≤ 这么多格高）。「一」作首字时
居中，不贴顶。四册全书按这三条筛只中 vol02 这 2 格，全是框线。"""


def _is_raised_frame_bar(slot, cell_type: str, bbox, cc) -> bool:
    if cell_type != "char" or slot is None or slot > 1 or not cc.period or not cc.content_x:
        return False
    h, w = bbox[3] - bbox[1], bbox[2] - bbox[0]
    col_w = cc.content_x[1] - cc.content_x[0]
    if not (h < FRAME_BAR_MAX_H * cc.period and w >= FRAME_BAR_MIN_W * col_w):
        return False
    if slot < 1:
        return True
    cell = next((c for c in cc.cells if c.slot == 1 and not c.sub), None)
    return cell is not None and bbox[1] - cell.y0 <= FRAME_BAR_TOP * cc.period


@register_step
class CellShrinkStep(Step):
    spec = StepSpec(
        id="cell_shrink", title="Step4 字框收缩", version="1.6", unit="cell",
        consumes=("cells", "column_windows", "column_image"), produces=("char_index", "char_patch"),
        params=CellShrinkParams,
        path_params=("yolo_weights", "yolo_layout_weights"),     # 权重路径是机器属性；内容指纹走 yolo_weights_fp
        # ⚠️ 读了 `ctx.book.frame_bar_strategy` 就必须在这里声明，否则换了策略
        # 产物还报「新鲜、跳过」，改了等于没改（feedback_fingerprint_book_deps）。
        book_deps=("frame_bar_strategy",),
        code_deps=("open_guji_cv.clustering.extractor", "open_guji_cv.clustering.crop_quality",
                   "open_guji_cv.clustering.frame_bar_strategy", "open_guji_cv.utils.seam",
                   "open_guji_cv.steps.occlusion", "open_guji_cv.utils.yolo_boxes"),
    )

    # ── 一列 ──────────────────────────────────────────────────────────
    def _extract_column(self, ctx: RunContext, page: int, cc: ColumnCells,
                        img: np.ndarray) -> list[tuple[object, np.ndarray | None]]:
        from ..clustering.extractor import CharExtractor
        p: CellShrinkParams = ctx.params_for(self)  # type: ignore[assignment]
        h, w = img.shape[:2]
        # Step3 每个物理位置一格；夹注 a/b 合成一格（满宽），空白格给 empty
        pos_count: dict[int, int] = {}
        for c in cc.cells:
            pos_count[c.pos] = pos_count.get(c.pos, 0) + 1
        by_pos: dict[int, dict] = {}
        for c in cc.cells:
            d = by_pos.setdefault(c.pos, {"index": c.pos - 1, "y_top": c.y0, "y_bottom": c.y1,
                                          "type": "empty", "kinds": set(), "is_punct": False,
                                          "seam_top": None, "seam_bottom": None})
            d["kinds"].add(c.kind)
            if c.kind == "punct":
                d["is_punct"] = True
            d["y_top"], d["y_bottom"] = min(d["y_top"], c.y0), max(d["y_bottom"], c.y1)
            if c.kind != "blank":
                d["type"] = "char"
            # 夹注 a/b 合成一格时不传折线——折线是给单一整格算的，半宽格各自
            # 的 seam 语义对不上合成后的满宽格，宁可退回矩形边界也不要凑错。
            if pos_count[c.pos] == 1:
                d["seam_top"] = c.seam_top
                d["seam_bottom"] = c.seam_bottom
            if c.kind in ("jiazhu_a", "jiazhu_b") and c.gap_center is not None:
                d["jiazhu_cx"] = float(c.gap_center)
        # `is_punct` 透传给 extractor：格框高宽比（bad_seg）对标点格不成立，见下。
        # 类型仍记 "char"——extractor 只认这一种，标点也要出图块。
        # Step3 认下的雙行夹注：缝中心（列图坐标）+ 是否只有 a 半（段尾单字）。extractor 自己那套
        # 旧判据漏掉的格按它补拆（overview#266，见 extractor「Step3 补拆」一段）
        cells = [{"type": d["type"], "index": d["index"], "y_top": float(d["y_top"]),
                  "y_bottom": float(d["y_bottom"]), "is_punct": d["is_punct"],
                  "seam_top": d["seam_top"], "seam_bottom": d["seam_bottom"],
                  **({"jiazhu_cx": d["jiazhu_cx"], "jiazhu_tail_a": "jiazhu_b" not in d["kinds"]}
                     if "jiazhu_cx" in d else {})}
                 for _, d in sorted(by_pos.items())]
        x0, x1 = cc.content_x or (0.0, float(w))
        grid = {
            "image_size": [int(w), int(h)],
            "chars_per_line": cc.n_body_slots,
            "grid": {"shear": 0.0, "period": cc.ref_w or float(x1 - x0),
                     "cell_h": cc.period, "head_raise_rows": 0,
                     # Step 2 量好的版框 y（列图坐标）：extractor 只在它附近认框线行，
                     # 并把条带开到下框（见 extractor.frame_band_inner 的 hint 说明）
                     "frame_top": cc.border_top, "frame_bottom": cc.border_bottom,
                     # 册级判据（见 BookSpec.frame_bar_strategy）。`border_line`
                     # 用下面这两条线定位版框，它们是**列图坐标**：border_top=0 表示
                     # 「列图顶端就是版框内缘」（列裁切已把框排除），所以真正的框残留
                     # 落在 y≈0 与 y≈border_bottom 附近。
                     "frame_bar_strategy": getattr(ctx.book, "frame_bar_strategy", "side_gap")},
            "columns": [{"index": cc.col, "left_x": float(x0), "right_x": float(x1),
                         "cell_left_x": float(x0), "cell_right_x": float(x1), "cells": cells}],
        }
        ex = CharExtractor(padding_ratio=p.padding_ratio, min_ink_ratio=p.min_ink_ratio,
                           strategy=p.strategy, frame_guard=p.frame_guard)
        return ex.extract_page(img, grid, ctx.book.id, str(page))

    # ── 多候选试切（Step7「切分裁决」板块要看的数据）────────────────────
    def _cand_variants(self, ctx: RunContext, page: int, cc: ColumnCells,
                       img: np.ndarray, inst, slot: int, chosen_seam: tuple | None,
                       cp_above: CutPointCandidates | None,
                       cp_below: CutPointCandidates | None) -> list["CandidatePatch"]:
        """本格邻接的多候选切点，每个候选各切一次字块（对侧固定用 chosen）。

        `chosen_seam` = `seams.get(pos)`，即 `(seam_top, seam_bottom, x0)`
        用 chosen 候选组装出来的三元组（`row_segment.py` 里 `up[0].seam_bottom
        = dn[0].seam_top = cands[chosen].y` 那条赋值，本函数换成别的候选重放
        同一条路径）；本格不邻接任何 seam 时为 None（两侧都是 straight）。
        `straight` 候选的 `y` 恒为 None，与 chosen 恰好是 straight 时的
        `seam_top`/`seam_bottom` 同义，交给 `_apply_seam` 原样处理即可。
        """
        variants: list[CandidatePatch] = []
        bbox0 = tuple(float(v) for v in inst.bbox)
        chosen_top, chosen_bottom, cell_x0 = chosen_seam or (None, None, bbox0[0])
        # cp_above：本格与上一格之间那条切点——它的候选决定本格的**上边界**
        # （seam_top）；cp_below：本格与下一格之间那条——决定**下边界**
        # （seam_bottom）。见 row_segment.py `up[0].seam_bottom = dn[0].seam_top
        # = cands[chosen].y`：本格若是那条切点的"上格"（up），被写的是它的
        # seam_bottom；若是"下格"（dn），被写的是它的 seam_top——因此
        # `cp_above`（本格是下格）→ seam_top，`cp_below`（本格是上格）→
        # seam_bottom，与切点名字直觉相反的地方就在这里，别写反。
        for cp, side, which in ((cp_above, "above", "top"), (cp_below, "below", "bottom")):
            if cp is None:
                continue
            for i, cand in enumerate(cp.candidates):
                if i == cp.chosen:
                    continue    # chosen 已经是主 patch，不重复切一遍
                x0, y0, x1, y1 = (int(round(v)) for v in bbox0)
                patch = img[y0:y1, x0:x1]
                if patch.size == 0:
                    continue
                seam_top = cand.y if which == "top" else chosen_top
                seam_bottom = cand.y if which == "bottom" else chosen_bottom
                masked_patch, masked_bbox = _apply_seam(
                    img, patch, bbox0, seam_top, seam_bottom, cell_x0)
                if masked_patch is None or masked_patch.size == 0:
                    continue
                # 下划线不是 `_KEY_RE` 认得的分隔符——这批候选字块是给 Step7
                # 人工裁决的临时试算，不必能被 `parse_key`/`render()` 反解重
                # 生成（不像 chosen 那份要长期支撑训练/进库），缓存被 LRU
                # 清掉就重算一遍即可，成本是一次 kNN 匹配，不值得为它们扩
                # `_KEY_RE` 的语法。side 入 key：同一格两侧可能各有一个
                # cand_idx=0（都是 straight），不带 side 会互相覆盖缓存文件。
                key = cell_key(page, cc.col, slot) + f"_{side}{i}"
                ctx.cache.put(ctx.book.id, "char_patch", key, _upright(ctx, masked_patch))
                variants.append(CandidatePatch(
                    side=side, cand_idx=i, kind=cand.kind, patch_key=key,
                    bbox_col=tuple(float(v) for v in masked_bbox)))
        return variants

    # ── Step 接口 ─────────────────────────────────────────────────────
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        cells: PageCells = ctx.product("cells", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        seal: dict = {}
        if ctx.params_for(self).seal_flag:  # type: ignore[attr-defined]
            from .occlusion import page_occluded
            from .seed_admit import SeedAdmitParams
            seal = page_occluded(ctx, page, SeedAdmitParams())
        out: list[ColumnChars] = []
        p: CellShrinkParams = ctx.params_for(self)  # type: ignore[assignment]
        yolo_w = _yolo_weights(p, seal)
        yolo = None
        if yolo_w:
            try:
                yolo = _YoloPage.of(yolo_w, ctx.raw_page(page))
            except FileNotFoundError:
                yolo = None
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
            slot_to_pos = {c.slot: c.pos for c in cc.cells}
            x_lo, x_hi = cc.content_x or (0.0, float(img.shape[1]))
            cell_rect = {c.pos: (float(x_lo), float(c.y0), float(x_hi), float(c.y1)) for c in cc.cells}
            first_pos, last_pos = min(c.pos for c in cc.cells), max(c.pos for c in cc.cells)
            seams = {c.pos: (c.seam_top, c.seam_bottom, c.x0) for c in cc.cells
                     if c.kind == "char" and (c.seam_top or c.seam_bottom)}
            # 多候选切点，只收 candidates ≥2 的（单一候选＝算法有把握，见
            # review/cards.py::blocking_cutline_cases 同一判据，两处必须
            # 一致，否则 Step7 展示的候选跟这里切出来的对不上）。
            # 命名是**格位视角**：`multi_above[pos]` = pos 这一格**往上方向**
            # 的那条切点——它就是 `cp.slot_below == pos` 的那条切点（这一格
            # 是切点的"下格"，切点在它上面）；`multi_below[pos]` 反之，是
            # `cp.slot_above == pos` 的切点。别与切点自身的 slot_above/
            # slot_below（**切点视角**：那一格是这个切点的上/下格）弄混——
            # 两套命名视角相反，是这块代码唯一容易踩的坑。
            multi_above: dict[int, CutPointCandidates] = {}   # 这一格往上那条切点
            multi_below: dict[int, CutPointCandidates] = {}   # 这一格往下那条切点
            for cp in cc.cut_candidates:
                if len(cp.candidates) < 2:
                    continue
                pa, pb = slot_to_pos.get(cp.slot_above), slot_to_pos.get(cp.slot_below)
                if pa is not None:
                    multi_below[pa] = cp    # pa 是切点的上格 → 切点在 pa 下方
                if pb is not None:
                    multi_above[pb] = cp    # pb 是切点的下格 → 切点在 pb 上方
            recs: list[CharRec] = []
            for inst, patch in self._extract_column(ctx, page, cc, img):
                pos = int(inst.idx) + 1
                slot = pos_to_slot.get(pos, pos)
                key = cell_key(page, cc.col, slot) + (inst.sub or "")
                patch_key = None
                bbox = tuple(float(v) for v in inst.bbox)
                has_patch = patch is not None and getattr(patch, "size", 0) > 0
                if pos in seams and not inst.sub and has_patch:
                    patch, bbox = _apply_seam(img, patch, bbox, *seams[pos])
                cell_type = inst.cell_type
                frame_bar = _is_raised_frame_bar(slot, cell_type, bbox, cc)
                if frame_bar:
                    cell_type, has_patch = "empty", False
                yolo_flags: list[str] = []
                if (yolo is not None and mapper is not None and not inst.sub and has_patch
                        and cell_type == "char" and pos in cell_rect and (cc.col, slot, "") not in seal):
                    hit = _yolo_check(yolo, mapper, bbox, cell_rect[pos], p.yolo_extra_ink,
                                      skip_top=pos == first_pos, skip_bottom=pos == last_pos)
                    if hit is not None:
                        yolo_flags.append("yolo_box")
                cand_variants: list[CandidatePatch] = []
                if not inst.sub and has_patch and cell_type == "char":
                    cand_variants = self._cand_variants(
                        ctx, page, cc, img, inst, slot, seams.get(pos),
                        multi_above.get(pos), multi_below.get(pos))
                if has_patch and cell_type == "char":
                    ctx.cache.put(ctx.book.id, "char_patch", key, _upright(ctx, patch))
                    patch_key = key
                flags = list(inst.flags) + (["frame_bar"] if frame_bar else []) + yolo_flags
                if (cc.col, slot, inst.sub or "") in seal:
                    flags.append("seal_region")
                s3_kind = step3_kind.get(pos, "char")
                # 静默丢字兜底（2026-09-16）：Step3 判定这一格有内容（char /
                # jiazhu，不是 blank），但走到这里 patch_key 仍是 None——
                # 无论是列端渣格闸误杀（tail_junk）、`patch.size == 0`
                # 的极端情况，还是以后任何新引入的路径——下游（Step5-c
                # OCR、glyph_match、人裁审查页）一律按 pos 遍历 char_index，
                # patch_key=None 会被默默跳过，字就凭空消失在产物里、
                # 不报错也不留痕（旧行为——本卡起点的那 63 个丢字就是
                # 这样被发现的）。这里补一个确定性 flag：只要满足
                # 「Step3 说有字」+「Step4 没给出可用图块」，就打
                # `lost_patch`，下游/人审能靠这个 flag 筛出「Step4 认为
                # 这里没有可交付的图块，但 Step3 认为这里应该有字」的
                # 格位，而不是永远无声无息。
                if (patch_key is None and s3_kind in ("char", "jiazhu") and "lost_patch" not in flags
                        and not frame_bar):
                    flags.append("lost_patch")
                recs.append(CharRec(
                    id=f"{ctx.book.id}:{page}:{cc.col}:{slot}{inst.sub or ''}",
                    slot=slot, pos=pos, idx=int(inst.idx), sub=inst.sub,
                    cell_type=cell_type, step3_kind=s3_kind,
                    bbox_col=bbox,
                    bbox_page=(None if mapper is None else
                               tuple(round(v, 2) for v in mapper.bbox_tr(*bbox))),
                    ink_ratio=float(inst.ink_ratio), height=float(bbox[3] - bbox[1]), width=float(bbox[2] - bbox[0]),
                    flags=flags, patch_key=patch_key,
                    cand_variants=cand_variants,
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
        seams = {c.pos: (c.seam_top, c.seam_bottom, c.x0) for c in cc.cells
                 if c.kind == "char" and (c.seam_top or c.seam_bottom)}
        for inst, patch in self._extract_column(ctx, page, cc, img):
            pos = int(inst.idx) + 1
            if pos_to_slot.get(pos) == slot and (inst.sub or "") == sub and patch is not None:
                if pos in seams and not sub:
                    patch, _ = _apply_seam(img, patch, tuple(float(v) for v in inst.bbox), *seams[pos])
                return patch
        raise KeyError(f"再生不出字块: {key}{sub}")


def _apply_seam(img: np.ndarray, patch: np.ndarray, bbox: tuple, seam_top, seam_bottom, cell_x0: float):
    """按折线缝把紧框裁片里属于邻格的像素抹白，再把紧框收到剩余墨迹上。

    缝在列图坐标（每 x 一个 y，x 从格的内容窗口 x0 起）；紧框 bbox = (x0, y0, x1, y1) 也是列图
    坐标。抹白后若有整行/整列空了，紧框相应收缩——邻字拖过格线的那截笔画正是要去掉的。
    """
    from ..utils.seam import mask_outside
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    if patch.shape[0] != y1 - y0 or patch.shape[1] != x1 - x0:
        # 裁片与 bbox 不对应（extractor 可能加了 padding），直接从列图重裁
        patch = img[y0:y1, x0:x1]
    masked = mask_outside(patch, seam_top, seam_bottom, y0=y0, x0=x0 - int(round(cell_x0)))
    ink = masked < 128
    rows = np.nonzero(ink.any(axis=1))[0]
    cols = np.nonzero(ink.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return masked, bbox
    r0, r1, c0, c1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    return masked[r0:r1, c0:c1], (float(x0 + c0), float(y0 + r0), float(x0 + c1), float(y0 + r1))
