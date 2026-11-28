"""3d 字块图的其他特征 `cell_traits`（2026-11-28，CV3 第三步重构 W3；Sheldon 11-27 定的方向）。

切的动作留在第二步，「这格图有没有毛病」的判断都收到这里：每格每个键出一个**原始分**（不是概率）——
`cut`（字被切断）、`border`（混入边框）、`residue`（混入上下字残留）、`stain`（背景污染／印章遮挡）、
`merged`（两字并一格）、`blank`（空格有墨／非字），可加键。**不定字、不判放行、不改上游产物**；
收尾 `glyph_analyzer` 把分原样放进每格 `traits`，以后有人裁标注标定成 p 再进 `p_map`。

判法与各子判据的来源（cell_shrink 的 flags、guji-manager `review/seg_defect` 的同字对照／端区框线／并格低谷、
`steps/occlusion` 的背景墨点与印章重叠、seed_admit `_blank_ink_pass` 的图像部分）见 `clustering/cell_traits.py` 模块头。
那几处现役代码一行没动，这里是另算一份。

## 读什么

- `char_index`（每格字框、flags）＋ `char_patch`（最终字块，形状量都在它上面量，与 seg_defect、extractor 同口径）；
- 原图 `ctx.raw_page`：格四周的中等墨点密度、列端字块框边上的压墨（要看字块框以外）。`bbox_page` 原点在右上角，
  一律经 `core.anchor`（`to_cv`／`crop_patch`）换算，不自己镜像；
- 可选 `glyph_match`：3a 首位字做本页同字对照、3a 置信给 `blank`；没跑就没有这两路；
- 可选 `cells`（Step3）：格高 `period`、版框位置（判列首／列尾格）、选中切线的 `seam_ink`；
- 可选 `seals`：大印（stain）／小印（crisp）外框重叠。

## 同字参照只取本页

一页一页跑，参照取本页 3a 判 same、离本列首末各 `same_margin` 格以外的格，同字（整字、夹注分开）≥ `same_min_ref` 个才比；
跨页取参照会让一页的产物依赖别的页，指纹管不住。

`enabled: false`（缺省）＝不跑（`StepSpec.enabled_by`），各书产物不受影响。
"""
from __future__ import annotations

import statistics

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.read import ColumnTraits, PageTraits, TraitRec

MODEL = "cell-traits/0"


class CellTraitsParams(BaseModel):
    enabled: bool = False
    """开不开 3d（书级）。缺省关。"""
    same_min_ref: int = 3
    """本页同字参照至少几个才做同字对照（seg_defect 全册取 5；本页取 3）。"""
    same_margin: int = 2
    """同字参照只取离本列首末各这么多格以外的格（列中格，seg_defect 同）。"""


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：没跑、没开就当没有这一路。"""
    try:
        return ctx.product(kind, page)
    except Exception:  # noqa: BLE001
        return None


def _conf3a(m) -> float | None:
    if m is None:
        return None
    if m.verdict == "same":
        return 1.0
    if m.candidates:
        return max(0.0, min(1.0, float(m.candidates[0][1])))
    return max(0.0, min(1.0, float(m.cov or 0.0)))


def _top_char(m) -> str | None:
    if m is None:
        return None
    if m.verdict == "same" and m.char:
        return m.char
    return str(m.candidates[0][0]) if m.candidates else m.char


def _seam_by_slot(cc_cells) -> dict[int, int]:
    """Step3 选中切线的穿墨，按格号（切线上下两格都记，取大）。"""
    out: dict[int, int] = {}
    for cut in (getattr(cc_cells, "cut_candidates", None) or []):
        if cut.chosen is None or not cut.candidates or cut.chosen >= len(cut.candidates):
            continue
        si = int(cut.candidates[cut.chosen].seam_ink or 0)
        for s in (cut.slot_above, cut.slot_below):
            if s is not None:
                out[int(s)] = max(out.get(int(s), 0), si)
    return out


def column_end(r, lo: int, hi: int, cc_cells, period: float) -> str | None:
    """列首格（本列第一个字格、贴上版框一格高以内）给 "top"，列尾格给 "bottom"（seg_defect `_at_frame_end`）。
    没有 Step3 版框位置时只按本列首末格认。"""
    top_b = getattr(cc_cells, "border_top", None) if cc_cells is not None else None
    bot_b = getattr(cc_cells, "border_bottom", None) if cc_cells is not None else None
    if r.slot == lo and (top_b is None or not period or r.bbox_col[1] <= top_b + period):
        return "top"
    if r.slot == hi and (bot_b is None or not period or r.bbox_col[3] >= bot_b - period):
        return "bottom"
    return None


@register_step
class CellTraitsStep(Step):
    spec = StepSpec(
        id="cell_traits", title="3d 字块图其他特征", version="0.1", unit="cell",
        consumes=("char_index", "char_patch", "raw_page"),
        optional_consumes=("glyph_match", "cells", "seals"),
        produces=("cell_traits",),
        params=CellTraitsParams,
        code_deps=("open_guji_cv.clustering.cell_traits", "open_guji_cv.clustering.extractor"),
        enabled_by="enabled",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering import cell_traits as T

        p: CellTraitsParams = ctx.params_for(self)  # type: ignore[assignment]
        chars = ctx.product("char_index", page)
        match = _opt(ctx, "glyph_match", page)
        cells = _opt(ctx, "cells", page)
        seals = _opt(ctx, "seals", page)
        mrec = {r.id: r for c in (match.columns if match else []) for r in c.chars}
        ccells = {c.col: c for c in (cells.columns if cells else [])}
        seal_list = list(seals.seals) if seals is not None else []
        stain_page = any(s.kind == "stain" for s in seal_list)
        gray = ctx.raw_page(page)
        dots = T.medium_dots(gray)

        # 第一遍：读字块、量形状
        body: dict[int, list] = {}
        patches: dict[str, object] = {}
        shapes: dict[str, dict] = {}
        errs: dict[str, str] = {}
        for cc in chars.columns:
            rs = [r for r in cc.chars if r.patch_key and r.cell_type != "empty"]
            if not rs:
                continue
            body[cc.col] = rs
            for r in rs:
                try:
                    patches[r.id] = ctx.image("char_patch", r.patch_key)
                except Exception as e:  # noqa: BLE001 —— 一格读不出不拖累整页，记进证据
                    patches[r.id] = None
                    errs[r.id] = f"{type(e).__name__}: {str(e)[:80]}"
                shapes[r.id] = T.patch_shape(patches[r.id])

        # 本页同字参照（列中格、3a 判 same）与本页字块墨量中位（整字、夹注分开）
        items = []
        for col, rs in body.items():
            lo, hi = min(r.slot for r in rs), max(r.slot for r in rs)
            for r in rs:
                m = mrec.get(r.id)
                if m is not None and m.verdict == "same" and m.char and lo + p.same_margin <= r.slot <= hi - p.same_margin:
                    pt = patches.get(r.id)
                    sh = shapes[r.id]
                    items.append((m.char, bool(r.sub), sh["h"], int(pt.shape[1]) if pt is not None else 0, sh["w"]))
        refs = T.same_char_refs(items, p.same_min_ref)
        ink_med: dict[bool, float] = {}
        for sub in (False, True):
            v = [shapes[r.id]["ink"] for rs in body.values() for r in rs if bool(r.sub) == sub and shapes[r.id]["ink"]]
            ink_med[sub] = float(statistics.median(v)) if v else 0.0

        cols = []
        for cc in chars.columns:
            rs = body.get(cc.col)
            if not rs:
                continue
            c_cells = ccells.get(cc.col)
            period = float((c_cells.period if c_cells is not None else None) or (cells.period if cells else None)
                           or T.slot_period(rs))
            jz = [r.height for r in rs if r.sub and r.height]
            jz_med = float(statistics.median(jz)) if jz else 0.0
            seam = _seam_by_slot(c_cells) if c_cells is not None else {}
            lo, hi = min(r.slot for r in rs), max(r.slot for r in rs)
            out = []
            for r in rs:
                m = mrec.get(r.id)
                end = column_end(r, lo, hi, c_cells, period)
                tc = _top_char(m)
                ref = refs.get((tc, bool(r.sub))) if tc else None
                bp = r.bbox_page
                scores, ev = T.score_cell(
                    patches.get(r.id), shapes[r.id], flags=r.flags, end=end, height=float(r.height or 0.0),
                    sub=bool(r.sub), period=period, merge_base=(jz_med if r.sub else period), ref=ref,
                    seam_ink=(seam.get(r.slot) if c_cells is not None else None), stain_page=stain_page,
                    edge=(T.edge_ink(gray, bp, end == "bottom") if end and bp is not None else None),
                    density=(T.dot_density(dots, bp, gray.shape[:2]) if bp is not None else None),
                    seal_ov=(T.seal_overlap(bp, seal_list) if bp is not None and seal_list else None),
                    page_ink_med=ink_med[bool(r.sub)], conf3a=_conf3a(m))
                ev["cut"]["ref_char"] = tc if ref is not None else None
                if r.id in errs:
                    ev["patch_err"] = errs[r.id]
                out.append(TraitRec(id=r.id, slot=r.slot, sub=r.sub, scores=scores, evidence=ev))
            cols.append(ColumnTraits(col=cc.col, chars=out))
        return {"cell_traits": PageTraits(page=page, model=MODEL, columns=cols)}
