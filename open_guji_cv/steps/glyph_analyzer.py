"""第三步识字的收尾 `glyph_analyzer`（2026-11-27，第三步重构；设计见 ai-team《第三步识字重构设计》第四节）。

在本大步各小步（3a `glyph_match`、3b `glyph_near`、3c `glyph_candidate`、3d `cell_traits`）都跑完之后跑，把它们汇总成每格一条：

    cands: [{char, p, evidence: {a: {...}, b: {...}}}, …]     按 p（再按 3a 分）降序
    p_map: {cut: …, border: …, residue: …, …}                 其他特征的概率；只放有校准来源的键
    p_src: "near:cnn_small:gong"                               p 从哪来
    traits: {cut: 0.12, border: 0.8, …}                        3d 原始分（未校准；3d 没跑不落盘）

**第三步不判断放不放行**，第四步只读这里的 p 定放行（Sheldon 11-26）。

## 现在（glyph-analyzer/0）能给出 p 的范围

- 3b 触发了、方法带校准表（`calib.json`）的格：组内各字的 p＝方法分按校准表映射（宫官小 CNN 用 5 折留出概率标定）。
  组外的 3a 候选 p 为 None。
- 其余格：候选照 3a 列出，p 全为 None（`p_src` 空）。通用打分器（3a 相似度＋刻例数＋形近等特征 → p，
  字形库留一法标定）是设计里的第 5 期，还没做。
- `p_map` 暂空：3d `cell_traits`（2026-11-28）只出原始分，没有校准来源；3d 跑了时原始分原样放进每格 `traits`
  （{cut, border, residue, stain, merged, blank: 分}，不是概率），等人裁标注标定成 p 再写进 `p_map`。

`enabled: false`（缺省）＝不跑（`StepSpec.enabled_by`）。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import STEPS, RunContext, Step, register_step
from ..products.kinds.read import ColumnFinal, FinalCand, FinalRec, PageFinal

MODEL = "glyph-analyzer/0"


class GlyphAnalyzerParams(BaseModel):
    enabled: bool = False
    """开不开收尾（书级）。缺省关。"""
    topk: int = 5
    """3a 候选列几个进 cands。"""


def match_algo(gp) -> str:
    """3a 用的相似度算法名：覆盖分（elastic）或 CNN（＋融合方式、权重 sha 前 12 位）。"""
    sm = getattr(gp, "sim_model", None)
    if not sm:
        return "elastic"
    from ..clustering.sim_cnn import SimModelConfig
    c = SimModelConfig.from_any(sm)
    sha = str(getattr(gp, "sim_model_sha", "") or "")[:12]
    return f"cnn:{c.path}" + (f"+cov/{c.fuse}" if c.fuse else "") + (f"@{sha}" if sha else "")


def merge_cell(match_rec, near_rec, calibrators: dict, topk: int, algo: str, cand_rec=None, cand_k: int = 10,
               traits_rec=None) -> FinalRec:
    """一格：3a 记录 ＋（可选）3b、3c、3d 记录 → FinalRec。`calibrators`：{方法全名: 方法对象}（有 `calibrate`）。
    3d `traits_rec` 的原始分原样放进 `traits`（未校准，不进 `p_map`）。"""
    cands: dict[str, FinalCand] = {}
    order: list[str] = []
    for c, s in (match_rec.candidates or [])[:topk]:
        c = str(c)
        if c not in cands:
            cands[c] = FinalCand(char=c, evidence={"a": {"sim": round(float(s), 4), "algo": algo}})
            order.append(c)
    if not cands and match_rec.char:
        cands[match_rec.char] = FinalCand(char=match_rec.char,
                                          evidence={"a": {"sim": round(float(match_rec.cov or 0), 4), "algo": algo}})
        order.append(match_rec.char)
    p_src = ""
    if cand_rec is not None and cand_rec.ran:
        # 3c 按图候选：前 cand_k 个并进来（3a 已有的补上证据 c，没有的新增、排在 3a 候选之后）
        for c, s in cand_rec.cands[:cand_k]:
            fc = cands.get(c)
            if fc is None:
                fc = cands[c] = FinalCand(char=c)
                order.append(c)
            ev = {"sim": round(float(s), 4)}
            if c in (cand_rec.fam_of or {}):
                ev["fam_of"] = cand_rec.fam_of[c]
            fc.evidence["c"] = ev
    if near_rec is not None:
        for mo in near_rec.methods:
            for c, s in mo.sims.items():
                fc = cands.get(c)
                if fc is None:
                    fc = cands[c] = FinalCand(char=c)
                    order.append(c)
                fc.evidence.setdefault("b", {"group": near_rec.group})[mo.method] = s
            m = calibrators.get(mo.method)
            ps = m.calibrate(mo.sims) if m is not None else None
            if ps and not p_src:
                p_src = f"near:{mo.method}"
                for c, pv in ps.items():
                    if c in cands:
                        cands[c].p = pv
                # 异体不分（方法的 merge）：异体跟它归的字同 p，但只当证据看，不另算概率
                for a, b in (getattr(m, "merge", None) or {}).items():
                    if a in cands and b in ps:
                        cands[a].evidence.setdefault("b", {})["same_as"] = b
    rank = {c: i for i, c in enumerate(order)}
    # 异体不分的字（same_as）p 记 None：概率只算在它归的字上一次，各候选 p 之和不超过 1
    for fc in cands.values():
        if (fc.evidence.get("b") or {}).get("same_as"):
            fc.p = None
    out = sorted(cands.values(), key=lambda fc: (-(fc.p if fc.p is not None else -1.0), rank[fc.char]))
    traits = dict(traits_rec.scores) if traits_rec is not None else {}
    return FinalRec(id=match_rec.id, slot=match_rec.slot, sub=match_rec.sub, cands=out, p_src=p_src, traits=traits)


@register_step
class GlyphAnalyzerStep(Step):
    spec = StepSpec(
        id="glyph_analyzer", title="3 识字收尾（汇总）", version="0.1", unit="cell",
        consumes=("glyph_match",), produces=("glyph_analyzer",),
        optional_consumes=("glyph_near", "glyph_candidate", "cell_traits"),
        params=GlyphAnalyzerParams,
        code_deps=("open_guji_cv.groups.near_methods", "open_guji_cv.clustering.sim_cnn"),
        enabled_by="enabled",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GlyphAnalyzerParams = ctx.params_for(self)  # type: ignore[assignment]
        match = ctx.product("glyph_match", page)
        try:
            near = ctx.product("glyph_near", page)
        except Exception:  # noqa: BLE001 —— 可选上游：3b 没开或没跑就当没有这一路
            near = None
        near_by = near.by_id() if near is not None else {}
        try:
            cand = ctx.product("glyph_candidate", page)
        except Exception:  # noqa: BLE001 —— 可选上游：3c 没开或没跑就当没有这一路
            cand = None
        cand_by = cand.by_id() if cand is not None else {}
        try:
            traits = ctx.product("cell_traits", page)
        except Exception:  # noqa: BLE001 —— 可选上游：3d 没开或没跑就当没有这一路
            traits = None
        traits_by = traits.by_id() if traits is not None else {}

        calibrators: dict[str, object] = {}
        if near_by:
            from ..groups.near_methods import load_method
            np_ = ctx.params_for(STEPS["glyph_near"])
            for gid, spec in (getattr(np_, "groups", None) or {}).items():
                for name, mdir in ((spec or {}).get("methods") or {}).items():
                    calibrators[f"{name}:{gid}"] = load_method(name, mdir)
        algo = match_algo(ctx.params_for(STEPS["glyph_match"]))

        cols = [ColumnFinal(col=cm.col, chars=[merge_cell(r, near_by.get(r.id), calibrators, p.topk, algo, cand_by.get(r.id),
                                                          traits_rec=traits_by.get(r.id))
                                               for r in cm.chars])
                for cm in match.columns]
        return {"glyph_analyzer": PageFinal(page=page, model=MODEL, columns=cols)}
