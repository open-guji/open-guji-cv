"""第四步 4c「格况」`cell_state`（2026-11-28，CV4 P3b）：这一格有没有字、被印章／墨点／切坏占了没有。

**只出证据、不判放行**（子步纪律）。下面六个探测器**不读放行状态**（`r.admit`／通道／`provenance`），原来夹在 `seed_admit`
的各 pass 里边判边改格，现在先算成本步产物，收尾 `seed_admit` 读它、再按放行状态决定升降：

| 探测器 | 读什么 | 收尾里用它的 pass |
|---|---|---|
| `occluded` | Step3 字格、印章定位、原图、对位、库判决 | `occluded_gate` 遮挡闸 |
| `seal_blank` | 同上（盖章空栏候选） | `_seal_blank_flip` |
| `seg_box` | char_index、gate_manifest、cells | `_seg_box_pass` |
| `ink` | char_index 格旗 ink_seal／ink_speck | `_ink_mark_pass` |
| `jiazhu_uneven` | Step3 列旗 | `_jiazhu_uneven_pass` |
| `header_formula` | Step3 列旗＋套语正则 | `_header_formula_pass` |

读放行状态的 `symbol_review`／`symbol_ref_blank`／`blank_ink` 三个 pass 不搬（见 ai-team P3b 依赖清单）。
各探测器只在收尾对应的开关开着时才算，开关关了就不进 `ran`、收尾也不读。**缺省关（`enabled`）**：关着时收尾照旧现算，产物逐格不变。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.decide_names import ADMIT_STEP_ACTIVE
from ..core.spec import StepSpec
from ..core.step import STEPS, RunContext, Step, register_step
from ..products.kinds.cell_state import CellStateRec, PageCellState
from .decide import _opt, coord_refs, text_refs
from .seed_admit_cell_state import (_occluded, header_formula_lines, ink_mark_facts, jiazhu_uneven_spans, seg_box_bad)
from .seed_admit_page_params import accuracy_page_params, no_ref_page_params
from .seed_admit_pick import _consensus_fallback

#: 探测器读的 `SeedAdmitParams` **字段**（进本步指纹；`tests/test_cell_state.py` 静态扫探测器源码守着，漏一个就红）。
#: 门槛类常量（`seed_admit_params._CONSTANTS`：occluded_min_*、seal_blank_*、occluded_seal_keep_cov 等）不是字段，值在代码里，
#: 靠 code_deps 的 seed_admit_params 进指纹。
SEED_FIELDS = (
    "occluded_gate", "occluded_ref_empty_blank", "occluded_manual_seal_blank", "occluded_seal_align_yield",
    "seal_blank_page", "lane_seal",
    "seg_box_check", "ink_marks", "lane_header_formula", "lane_header_formula_re", "consensus_fallback",
    "no_ref_params", "no_ref_pages", "ref_accuracy",
)


class CellStateParams(BaseModel):
    enabled: bool = False
    """开不开 4c（书级）。缺省关：收尾照旧在自己里面现算。"""
    seed: dict = Field(default_factory=dict)
    """探测器读的 seed_admit 参数摘要，**自动填**（`SEED_FIELDS`），进参数指纹。"""


def classify(*, occ, seal_blank: bool, seg: list[str], ink: set[str], half: bool, ref_blank: bool) -> tuple[str, dict]:
    """一格的格况与证据。优先级 seal > occluded > seg_bad > non_char > char。

    - 印：格旗 ink_seal、盖章空栏候选、遮挡默认字来源 coord_blank（整理本说此处没字）→ seal；其余遮挡 → occluded；
    - 字框几何判据命中（含 sliver）→ seg_bad；
    - 墨点 ink_speck：贴着同列别字（`speck_half`）或对位有字 → seg_bad；对位无字且不贴字 → non_char。"""
    ev: dict = {}
    if occ is not None:
        ev["occluded"] = {"density": round(float(occ[0]), 4), "default": occ[1], "src": occ[2]}
    if seal_blank:
        ev["seal_blank"] = True
    if seg:
        ev["seg_box"] = list(seg)
    if ink:
        ev["ink"] = sorted(ink)
    if half:
        ev["speck_half"] = True
    if ref_blank:
        ev["ref_blank"] = True
    if "ink_seal" in ink or seal_blank or (occ is not None and occ[2] == "coord_blank"):
        return "seal", ev
    if occ is not None:
        return "occluded", ev
    if seg:
        return "seg_bad", ev
    if "ink_speck" in ink:
        return ("non_char" if (ref_blank and not half) else "seg_bad"), ev
    return "char", ev


def page_params(ctx: RunContext, page: int):
    """本页收尾用的 seed_admit 参数（含按页叠加：无参照页、准确度档），探测器必须与收尾同一份。"""
    p = ctx.params_for(STEPS[ADMIT_STEP_ACTIVE])
    p = no_ref_page_params(p, page, ctx.book)
    return accuracy_page_params(p, page, ctx.book)


def detect_page(ctx: RunContext, page: int, p) -> PageCellState:
    """按收尾各开关算各探测器、合成逐格格况。读不到上游的探测器给空结果。"""
    from .occlusion import page_seal_blank
    match = ctx.product("glyph_match", page)
    ref = _opt(ctx, "align_ref", page)
    amap = text_refs(ref)
    if p.consensus_fallback:
        match = _consensus_fallback(match, amap)
    ran: list[str] = []
    occ: dict = {}
    if p.occluded_gate:
        occ = _occluded(ctx, page, match, p, amap)
        ran.append("occluded")
    sb: dict = {}
    if p.seal_blank_page and p.lane_seal:
        sb = page_seal_blank(ctx, page, p)
        ran.append("seal_blank")
    seg: dict = {}
    if p.seg_box_check:
        seg = seg_box_bad(ctx, page, p.seg_box_check)
        ran.append("seg_box")
    facts = None
    if p.ink_marks:
        facts = ink_mark_facts(ctx, page)
        ran.append("ink")
    spans = jiazhu_uneven_spans(ctx, page)
    ran.append("jiazhu_uneven")
    lines = {}
    if p.lane_header_formula:
        lines = header_formula_lines(ctx, page, p)
        ran.append("header_formula")
    flags, half = facts if facts is not None else ({}, set())
    coord = coord_refs(ref)
    cells: list[CellStateRec] = []
    for cc in match.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            key = (cc.col, r.slot, r.sub or "")
            fl = {f for f in flags.get(r.id, set()) if f in ("ink_seal", "ink_speck")}
            ref_blank = not (amap.get(r.id) or (None,))[0]
            st, ev = classify(occ=occ.get(r.id), seal_blank=key in sb, seg=seg.get(r.id, []), ink=fl,
                              half=r.id in half, ref_blank=ref_blank and (coord.get(r.id) in ("", None)))
            cells.append(CellStateRec(id=r.id, col=cc.col, slot=r.slot, sub=r.sub, state=st, evidence=ev))
    return PageCellState(
        page=page, cells=cells, ran=ran,
        occluded={k: [v[0], v[1], v[2]] for k, v in occ.items()},
        seal_blank=[{"col": k[0], "slot": k[1], "sub": k[2], "seal_score": v["seal_score"], "overlap": v["overlap"]}
                    for k, v in sb.items()],
        seg_box=seg,
        ink_flags={k: sorted(v) for k, v in flags.items() if v & {"ink_seal", "ink_speck"}},
        speck_half=sorted(half),
        jiazhu_uneven={str(c): [[a, b] for a, b in v] for c, v in spans.items()},
        header_lines={str(c): v for c, v in lines.items()},
    )


@register_step
class CellStateStep(Step):
    spec = StepSpec(
        id="cell_state", title="4c 格况（印章／遮挡／切坏／墨点）", version="0.1", unit="cell",
        consumes=("glyph_match", "align_ref", "char_index"),
        optional_consumes=("seals",),
        produces=("cell_state",),
        params=CellStateParams,
        code_deps=(  # 探测器住在 seed_admit_cell_state，它与 seed_admit 同属 code_equiv.SPLITS 的一组，守卫要求整组都列（test_seg_move）
                   "open_guji_cv.steps.seed_admit", "open_guji_cv.steps.seed_admit_cell_state", "open_guji_cv.steps.seed_admit_groups",
                   "open_guji_cv.steps.seed_admit_pick", "open_guji_cv.steps.seed_admit_veto", "open_guji_cv.steps.seed_admit_altcut",
                   "open_guji_cv.steps.seed_admit_reasons", "open_guji_cv.steps.seed_admit_page_params", "open_guji_cv.steps.decide",
                   "open_guji_cv.steps.occlusion", "open_guji_cv.steps.seal_detect", "open_guji_cv.steps.seed_admit_common",
                   "open_guji_cv.steps.seed_admit_params", "open_guji_cv.steps.seed_admit_vis3", "open_guji_cv.steps.align_ref_coord", "open_guji_cv.utils.gap",
                   "open_guji_cv.products.kinds.cell_state"),
        enabled_by="enabled",
    )

    def book_params(self, p: CellStateParams, ctx: RunContext) -> CellStateParams:
        if not p.enabled:
            return p
        sp = ctx.params_for(STEPS[ADMIT_STEP_ACTIVE])
        seed = {k: getattr(sp, k) for k in SEED_FIELDS}
        return p if p.seed == seed else type(p)(enabled=p.enabled, seed=seed)

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        return {"cell_state": detect_page(ctx, page, page_params(ctx, page))}
