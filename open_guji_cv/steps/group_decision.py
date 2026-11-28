"""第四步 4d「字组」`group_decision`（2026-11-28，CV4 P3c）：落在已登记字组里的格，先把**不读放行状态**的原料算好。

**只出原料、不出决定**（子步纪律）。原料三样：

| 原料 | 读什么 | 收尾里用它的地方 |
|---|---|---|
| `entry` 字组入口归属（待审口径） | 3a 候选、整理本字、坐标对位、字组登记表 | 本版只出不读（收尾 `group_flow` 仍自己算；入口还读放行状态） |
| `near:<方法>` 3b 看图判法快照 | 3b `glyph_near`（rr／wu／hou／part／pair_shape、book_knn、near_knn，开关 `group_flow_near_from_3b`） | 各刻形遍的 `_near_from_3b`／`_near_by_model_from_3b` |
| `wh`＋按组 `aspect` 字框宽高比 | `char_index` | `_fold_pass(wh=…)`（`fold_aspect`） |

**不做**（读邻格放行状态，只能在收尾）：补放／改字／降审、字组文意各层（ctx L1／L2／L3、vis）、`fold`／`vis_ruling` 的裁定缓存查询。
`vis_ruling`（原 5c）及其后各遍的次序、`ask`、`evidence.vis_ctx`、`evidence.group` 的位置一律不动。
**缺省关（`enabled`）**：关着时收尾照旧现算，产物逐字节不变；开着时收尾读本产物，逐格相同（`tests/test_group_decision.py`）。
"""
from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel, Field

from ..core.spec import StepSpec
from ..core.step import STEPS, RunContext, Step, register_step
from ..products.kinds.group_decision import GroupDecisionRec, PageGroupDecision, pack_near
from .cell_state import page_params
from .decide import _opt, coord_refs, text_refs
from .seed_admit_groups import _FOLD_ASPECT_PAIRS, _entry_config
from .seed_admit_pick import _consensus_fallback

#: 3b 看图方法 → 取法（`seed_admit_shapes`）：模型路径的参数名（None＝不比单个模型，按组指纹查）、键是不是 (格, 对)。
_NEAR_SPECS = {
    "rr_shape": ("group_flow_rr_shape", False), "wu_shape": ("group_flow_wu_shape", False), "hou_shape": ("group_flow_hou_shape", False),
    "part_shape": ("group_flow_part_shape", True),
    "pair_shape": (None, False), "book_knn": (None, False), "near_knn": (None, False), "stroke_veto": (None, False),
}

#: 本步读的 `SeedAdmitParams` 字段（进本步指纹）：字组流程全部 `group_flow*`，加上面几个入口、宽高比、整理本字用到的。
_SEED_EXTRA = ("fold_groups", "fold_aspect", "consensus_fallback", "reference_trust", "no_ref_params", "no_ref_pages",
               "ref_accuracy")


def seed_fields() -> tuple[str, ...]:
    from .seed_admit_params import SeedAdmitParams
    return tuple(k for k in SeedAdmitParams.model_fields if k.startswith("group_flow")) + _SEED_EXTRA


class GroupDecisionParams(BaseModel):
    enabled: bool = False
    """开不开 4d（书级）。缺省关：收尾照旧在自己里面现算。"""
    seed: dict = Field(default_factory=dict)
    """本步读的 seed_admit 参数摘要，**自动填**（`seed_fields()`），进参数指纹。"""
    handling: dict[str, dict] = Field(default_factory=dict)
    """书级处理方式覆盖 `{组 id: {context, aspect, action, threshold}}`（书配置优先、登记表缺省；键与取值由 `near_registry.handling_of(over=)` 校验，`methods` 不许写）。"""
    resolved: dict[str, dict] = Field(default_factory=dict)
    """`handling` 叠到登记表之后的**定稿快照**，**自动填**（`resolve_handling()`），进参数指纹：登记表一改、书级覆盖一改，产物就过期。"""


def near_snapshot(ctx: RunContext, page: int, p) -> dict[str, list[dict]]:
    """按书开关 `group_flow_near_from_3b` 里的方法，读 3b 的原样结论（同收尾各遍现用的读法，模型不一致同样报错）。"""
    from .seed_admit_shapes import _near_by_model_from_3b, _near_from_3b
    out: dict[str, list[dict]] = {}
    for m in getattr(p, "group_flow_near_from_3b", None) or ():
        spec = _NEAR_SPECS.get(m)
        if spec is None:
            continue
        path, by_pair = spec
        got = (_near_from_3b(ctx, page, m, getattr(p, path), by_pair=by_pair, use_gd=False) if path
               else _near_by_model_from_3b(ctx, page, m, use_gd=False))
        out[m] = pack_near(m, got)
    return out


def resolve_handling(p) -> dict[str, dict]:
    """本书涉及的组（`group_flow`＋`fold_groups` 里登记表有的）的处理方式定稿：登记表缺省 ＋ 书级 `handling` 覆盖。
    书级覆盖里写了不在登记表的组、或键值不合规，报错（见 `near_registry.handling_of`）。"""
    from ..groups import near_registry as nr
    reg = nr.load()
    over = dict(getattr(p, "handling", None) or {})
    bad = sorted(g for g in over if g not in reg)
    if bad:
        raise ValueError(f"group_decision.handling 写了登记表里没有的组：{bad}")
    seed = getattr(p, "seed", None) or {}
    gids = set(seed.get("group_flow") or ()) | set(seed.get("fold_groups") or ()) | set(over)
    out: dict[str, dict] = {}
    for g in sorted(gids):
        if g in reg:
            h = reg.handling_of(g, over.get(g))
            out[g] = {**h, "methods": list(h["methods"])}
    return out


def detect_page(ctx: RunContext, page: int, p) -> PageGroupDecision:
    from ..groups.flow import entry
    match = ctx.product("glyph_match", page)
    ref = _opt(ctx, "align_ref", page)
    amap = text_refs(ref)
    if p.consensus_fallback:
        match = _consensus_fallback(match, amap)
    coord = coord_refs(ref)
    ran: list[str] = []
    cfg = _entry_config(p)
    canon = ctx.book.canonical_char if ctx.book.codepoints else (lambda c: c)
    al = cfg.ref_alias
    aliased = (lambda c: al.get(c, c) if c else c) if al else (lambda c: c)
    wh: dict[str, list[float]] = {}
    ci = _opt(ctx, "char_index", page)
    if ci is not None and p.fold_aspect:
        wh = {c.id: [c.width, c.height] for col in ci.columns for c in col.chars}
        ran.append("wh")
    pairs = {g: pr for g, pr in _FOLD_ASPECT_PAIRS.items() if g in (p.fold_groups or ())}
    cells: list[GroupDecisionRec] = []
    if p.group_flow:
        ran.append("entry")
    for cc in match.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            lift = None
            if p.group_flow:
                cands = list(r.candidates or [])
                rf = aliased((amap.get(r.id) or (None, None))[0])
                # 待审口径的桩：没放行、不是人裁（`entry` 对这类格只读候选、整理本字、坐标对位，不读放行状态）
                stub = SimpleNamespace(id=r.id, char=getattr(r, "char", None), admit=False, channel=None, provenance="")
                e = entry(stub, cands, rf, cfg, canon, coord_ref=aliased(coord.get(r.id)))
                lift = [e[0], e[1]] if e is not None else None
            asp: dict[str, float] = {}
            if wh and pairs and r.id in wh:
                w, h = wh[r.id]
                if h and h > 0 and w:
                    asp = {g: w / h for g in pairs}
            cells.append(GroupDecisionRec(id=r.id, col=cc.col, slot=r.slot, sub=r.sub, lift=lift, aspect=asp))
    near = near_snapshot(ctx, page, p)
    ran += [f"near:{m}" for m in near]
    return PageGroupDecision(page=page, cells=cells, ran=ran, wh=wh, near=near)


@register_step
class GroupDecisionStep(Step):
    spec = StepSpec(
        id="group_decision", title="4d 字组（入口归属／3b 看图判法／字框宽高比）", version="0.1", unit="cell",
        consumes=("glyph_match", "align_ref", "char_index"),
        optional_consumes=("glyph_near",),
        optional_consumes_when=(("glyph_near", "group_flow_near_from_3b"),),
        produces=("group_decision",),
        params=GroupDecisionParams,
        code_deps=(  # 与 cell_state 一样：入口与读 3b 的函数住在 seed_admit 各块，那一组 code_equiv.SPLITS 要整组列（test_seg_move）
                   "open_guji_cv.steps.seed_admit", "open_guji_cv.steps.seed_admit_cell_state", "open_guji_cv.steps.seed_admit_groups",
                   "open_guji_cv.steps.seed_admit_pick", "open_guji_cv.steps.seed_admit_veto", "open_guji_cv.steps.seed_admit_altcut",
                   "open_guji_cv.steps.seed_admit_reasons", "open_guji_cv.steps.seed_admit_page_params", "open_guji_cv.steps.decide",
                   "open_guji_cv.steps.seed_admit_common", "open_guji_cv.steps.seed_admit_params", "open_guji_cv.steps.cell_state",
                   "open_guji_cv.steps.seed_admit_shapes",   # 读 3b 快照的两个读口住在这里（_near_from_3b／_near_by_model_from_3b）
                   "open_guji_cv.groups.flow", "open_guji_cv.groups.registry", "open_guji_cv.groups.near_methods", "open_guji_cv.groups.near_methods._base", "open_guji_cv.groups.near_methods.cnn_small", "open_guji_cv.groups.near_methods.rr_shape", "open_guji_cv.groups.near_methods.wu_shape", "open_guji_cv.groups.near_methods.hou_shape", "open_guji_cv.groups.near_methods.part_shape", "open_guji_cv.groups.near_methods.pair_shape", "open_guji_cv.groups.near_methods.book_knn", "open_guji_cv.groups.near_methods.near_knn", "open_guji_cv.groups.near_methods.stroke_veto", "open_guji_cv.groups.near_methods.flow_shape", "open_guji_cv.groups.near_methods.pair_clf", "open_guji_cv.groups.near_registry",
                   "open_guji_cv.products.kinds.group_decision"),
        enabled_by="enabled",
    )

    def book_params(self, p: GroupDecisionParams, ctx: RunContext) -> GroupDecisionParams:
        if not p.enabled:
            return p
        sp = ctx.params_for(STEPS["seed_admit"])
        seed = {k: getattr(sp, k) for k in seed_fields()}
        q = p if p.seed == seed else p.model_copy(update={"seed": seed})
        res = resolve_handling(q)
        return q if q.resolved == res else q.model_copy(update={"resolved": res})

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        gp = ctx.params_for(STEPS["group_decision"])
        out = detect_page(ctx, page, page_params(ctx, page))
        out.handling = {g: dict(h) for g, h in gp.resolved.items()}
        return {"group_decision": out}
