"""第三步识字的收尾 `glyph_analyzer`（2026-11-27，第三步重构；设计见 ai-team《第三步识字重构设计》第四节）。

在本大步各小步（3a `glyph_match`、3b `glyph_near`、3c `glyph_candidate`、3d `cell_traits`、3e `glyph_vis`）都跑完之后跑，把它们汇总成每格一条：

    cands: [{char, p, evidence: {a: {...}, b: {...}, c: {...}, v: {...}}}, …]     按 p（再按 3a 分）降序
    p_map: {cut: …, border: …, residue: …, …}                 其他特征的概率；只放有校准来源的键
    p_src: "near:cnn_small:gong"                               p 从哪来
    traits: {cut: 0.12, border: 0.8, …}                        3d 原始分（未校准；3d 没跑不落盘）
    near: {组: {trigger, methods: {方法名: {method, …, model}}, [p, p_src]}}
                                                               3b 各组各方法这一格的证据原样＋模型版本（3b 没触发不落盘；
                                                               rr_shape 是 {char, why, nn, score, geo}，同第四步 rr_shape.judge）；
                                                               这组出了校准 p 才有 p／p_src。读旧文件用 `FinalRec.near_groups()`
    vis: {group, trigger, status, char, other, conf, why, model, prompt_sha, cache_hit, legacy, img_sha}
                                                               3e 看图大模型（只看图）这一格的结论（3e 没触发不落盘）；
                                                               答出字时那个候选另有 evidence.v = {conf, model, prompt_sha, cache_hit, legacy}

**第三步不判断放不放行**，第四步只读这里的 p 定放行（Sheldon 11-26）。

## 现在（glyph-analyzer/0）能给出 p 的范围

- 3b 触发了、方法带校准表（`calib.json`）的格：组内各字的 p＝方法分按校准表映射（宫官小 CNN 用 5 折留出概率标定）。
  组外的 3a 候选 p 为 None。
- 其余格：候选照 3a 列出，p 全为 None（`p_src` 空）。通用打分器（3a 相似度＋刻例数＋形近等特征 → p，
  字形库留一法标定）是设计里的第 5 期，还没做。
- `p_map` 暂空：3d `cell_traits`（2026-11-28）只出原始分，没有校准来源；3d 跑了时原始分原样放进每格 `traits`
  （{cut, border, residue, stain, merged, blank: 分}，不是概率），等人裁标注标定成 p 再写进 `p_map`。

## 一格多组（2026-11-28，3b 一格可触发几个组）

- `cands[].evidence.b`：各组各方法给这个字的分，键「方法:组」（键本身带组，不撞）。B3 定稿（11-28）起不再另记 `b.group`／`b.groups`
  （从键的冒号后读得出）；`same_as` 照旧（异体不分的字跟它归的字）。字段定稿见 `doc/3-识字/收尾产物.md`。
- **p 的合并规则（保守）**：每组取第一个出校准 p 的方法（同之前）。**只有一个组出了 p** → 照旧落到候选上，`p_src`＝`near:方法:组`；
  **两个以上组都出了 p** → 候选 p 全为 None、`p_src` 空（各组的 p 各自在组内归一，拼不成这一格的一个分布；谁也不挑，
  第四步按「没有 p」走，既不按 p 放行也不按 p 降审），各组的 p 只留在 `near[组].p`／`near[组].p_src` 里当证据。
- `near`：按组 `{组: {trigger, methods, [p, p_src]}}`（之前是一格一组的 `{group, trigger, methods}`）。

## 3e 看图大模型（2026-11-28，CV3／CV4）

- 3e 这格有 `VisRec` 才写 `vis`（空不落盘）；答出字（hit／asked 且不是「其他」）时那个候选写 `evidence.v`，字不在 cands 里就补一条
  `FinalCand(char, p=None)` 排在最后（同 3c 补候选）。「其他」、弃权、pending、skipped 只在 `vis` 里。
- **不出 p**：大模型的 high／mid／low 没校准；`p`、`p_src`、候选排序一概不因 `vis` 改变。
- 没开 3e 的书：`vis_rec` 为 None，收尾产物与加 3e 之前逐字节相同（`core/code_equiv.py` 登记，测试 `test_glyph_vis` 守着）。

`enabled: false`（缺省）＝不跑（`StepSpec.enabled_by`）。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import STEPS, RunContext, Step, register_step
from ..products.kinds.read import ColumnFinal, FinalCand, FinalRec, PageFinal

MODEL = "glyph-analyzer/1"


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


def _near_list(near_rec) -> list:
    """`merge_cell` 的 3b 输入：None、一条 NearRec、或这格各组的 [NearRec…] → 按组 id 排的列表。"""
    if near_rec is None:
        return []
    if isinstance(near_rec, (list, tuple)):
        return sorted(near_rec, key=lambda r: r.group)
    return [near_rec]


def merge_cell(match_rec, near_rec, calibrators: dict, topk: int, algo: str, cand_rec=None, cand_k: int = 10,
               traits_rec=None, near_models: dict | None = None, vis_rec=None) -> FinalRec:
    """一格：3a 记录 ＋（可选）3b、3c、3d 记录 → FinalRec。`calibrators`：{方法全名: 方法对象}（有 `calibrate`）。
    `near_rec`：这格 3b 各组的 [NearRec…]（`PageNear.by_id_all()` 的一项；单条 NearRec 也认）。
    3d `traits_rec` 的原始分原样放进 `traits`（未校准，不进 `p_map`）。3b 各方法的证据原样放进 `near[组].methods[方法名]`，
    `near_models`（3b 产物的 `PageNear.models`）给了就带上 `model`。多组时 p 怎么合见模块头「一格多组」。
    `vis_rec`：这格 3e 的 `VisRec`（没有为 None），见模块头「3e 看图大模型」。"""
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
    nrs = _near_list(near_rec)
    group_p: list[tuple[str, str, object, dict]] = []      # 出了校准 p 的组：(组, 方法全名, 方法对象, {字: p})
    for nr in nrs:
        got = None
        for mo in nr.methods:
            for c, s in mo.sims.items():
                fc = cands.get(c)
                if fc is None:
                    fc = cands[c] = FinalCand(char=c)
                    order.append(c)
                fc.evidence.setdefault("b", {})[mo.method] = s      # 键「方法:组」本身带组（B3：不另记 group／groups）
            if got is None:
                m = calibrators.get(mo.method)
                ps = m.calibrate(mo.sims) if m is not None else None
                if ps:
                    got = (nr.group, mo.method, m, ps)          # 一组内取第一个出 p 的方法（同之前一格一组时）
        if got is not None:
            group_p.append(got)
    # 多组时 p 的合并（保守）：只有一个组出了校准 p 才把 p 落到候选上；两个以上组都出 p（各组 p 各自归一，拼不成一格的分布）
    # → 候选 p 全不给、`p_src` 空，各组的 p 只留在 `near[组].p` 里当证据，第四步按「没有 p」走（不按 p 放行也不按 p 降审）
    if len(group_p) == 1:
        _gid, meth, m, ps = group_p[0]
        p_src = f"near:{meth}"
        for c, pv in ps.items():
            if c in cands:
                cands[c].p = pv
        # 异体不分（方法的 merge）：异体跟它归的字同 p，但只当证据看，不另算概率
        for a, b in (getattr(m, "merge", None) or {}).items():
            if a in cands and b in ps:
                cands[a].evidence.setdefault("b", {})["same_as"] = b
    vis = _vis_of(vis_rec, cands, order) if vis_rec is not None else {}
    rank = {c: i for i, c in enumerate(order)}
    # 异体不分的字（same_as）p 记 None：概率只算在它归的字上一次，各候选 p 之和不超过 1
    for fc in cands.values():
        if (fc.evidence.get("b") or {}).get("same_as"):
            fc.p = None
    out = sorted(cands.values(), key=lambda fc: (-(fc.p if fc.p is not None else -1.0), rank[fc.char]))
    traits = dict(traits_rec.scores) if traits_rec is not None else {}
    near: dict = {}
    gp = {g: (meth, ps) for g, meth, _m, ps in group_p}
    for nr in nrs:
        meth = {}
        for mo in nr.methods:
            name = mo.method.split(":", 1)[0]
            rec = {"method": name, **mo.evidence}
            if near_models and mo.method in near_models:
                rec["model"] = near_models[mo.method]
            meth[name] = rec
        near[nr.group] = {"trigger": nr.trigger, "methods": meth}
        if nr.group in gp:
            near[nr.group]["p"] = dict(gp[nr.group][1])
            near[nr.group]["p_src"] = f"near:{gp[nr.group][0]}"
    return FinalRec(id=match_rec.id, slot=match_rec.slot, sub=match_rec.sub, cands=out, p_src=p_src, traits=traits,
                    near=near, vis=vis)


def _vis_of(v, cands: dict, order: list) -> dict:
    """3e 一格 → `FinalRec.vis`；答出字时给那个候选写 `evidence.v`（不在 cands 里就补一条，p 为 None）。"""
    out = {"group": v.group, "trigger": list(v.trigger), "status": v.status, "char": v.char, "other": v.other,
           "conf": v.conf, "why": v.why, "model": v.model, "prompt_sha": v.prompt_sha, "cache_hit": v.cache_hit,
           "legacy": v.legacy, "img_sha": v.img_sha}
    if v.groups:
        out["groups"] = list(v.groups)
    if v.char and v.status in ("hit", "asked"):
        fc = cands.get(v.char)
        if fc is None:
            fc = cands[v.char] = FinalCand(char=v.char)
            order.append(v.char)
        fc.evidence["v"] = {"conf": v.conf, "model": v.model, "prompt_sha": v.prompt_sha, "cache_hit": v.cache_hit,
                            "legacy": v.legacy}
    return out


@register_step
class GlyphAnalyzerStep(Step):
    spec = StepSpec(
        id="glyph_analyzer", title="3 识字收尾（汇总）", version="0.3", unit="cell",
        consumes=("glyph_match",), produces=("glyph_analyzer",),
        optional_consumes=("glyph_near", "glyph_candidate", "cell_traits", "glyph_vis"),
        params=GlyphAnalyzerParams,
        code_deps=("open_guji_cv.groups.near_methods", "open_guji_cv.groups.near_methods._base", "open_guji_cv.groups.near_methods.cnn_small", "open_guji_cv.groups.near_methods.rr_shape", "open_guji_cv.groups.near_methods.wu_shape", "open_guji_cv.groups.near_methods.hou_shape", "open_guji_cv.groups.near_methods.part_shape", "open_guji_cv.groups.near_methods.pair_shape", "open_guji_cv.groups.near_methods.book_knn", "open_guji_cv.groups.near_methods.near_knn", "open_guji_cv.groups.near_methods.stroke_veto", "open_guji_cv.groups.near_methods.flow_shape", "open_guji_cv.groups.near_methods.pair_clf", "open_guji_cv.clustering.sim_cnn"),
        enabled_by="enabled",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GlyphAnalyzerParams = ctx.params_for(self)  # type: ignore[assignment]
        match = ctx.product("glyph_match", page)
        try:
            near = ctx.product("glyph_near", page)
        except Exception:  # noqa: BLE001 —— 可选上游：3b 没开或没跑就当没有这一路
            near = None
        near_by = near.by_id_all() if near is not None else {}
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
        try:
            vis = ctx.product("glyph_vis", page)
        except Exception:  # noqa: BLE001 —— 可选上游：3e 没开或没跑就当没有这一路
            vis = None
        vis_by = vis.by_id() if vis is not None else {}

        calibrators: dict[str, object] = {}
        if near_by:
            from ..groups.near_methods import load_method
            np_ = ctx.params_for(STEPS["glyph_near"])
            for gid, spec in (getattr(np_, "groups", None) or {}).items():
                for name, mdir in ((spec or {}).get("methods") or {}).items():
                    calibrators[f"{name}:{gid}"] = load_method(name, mdir)
        algo = match_algo(ctx.params_for(STEPS["glyph_match"]))

        cols = [ColumnFinal(col=cm.col, chars=[merge_cell(r, near_by.get(r.id), calibrators, p.topk, algo, cand_by.get(r.id),
                                                          traits_rec=traits_by.get(r.id),
                                                          near_models=near.models if near is not None else None,
                                                          vis_rec=vis_by.get(r.id))
                                               for r in cm.chars])
                for cm in match.columns]
        return {"glyph_analyzer": PageFinal(page=page, model=MODEL, columns=cols)}
