"""C1 进库准入（`seed_admit`）的否决：影子模型否决 `shadow_veto`、follow_ref 否决、witness3 近邻否决（收尾 `char_decide` 的否决一段）。

CV4 整理 P1a（2026-11-28）从 seed_admit.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from . import seed_admit_common as _C
from ..core.step import RunContext
from .decide import _opt
from .seed_admit_common import PatchUnavailable
from .seed_admit_common import _demote
from .seed_admit_groups import _group_members
from .seed_admit_groups import _group_variant
from .seed_admit_groups import _provisional_forms
from .seed_admit_params import SeedAdmitParams
from .seed_admit_reasons import _doubts
from .seed_admit_reasons import _rare_cp



_SHADOW_GATES: dict = {}


def _shadow_model_path(p: "SeedAdmitParams"):
    """缺省模型：只开 veto 用 v1（老口径，行为不变）；开了 promote 用 v2（要名次类特征）。"""
    from ..shadow.model import DEFAULT_MODEL
    return p.shadow_model or DEFAULT_MODEL


def _shadow_gate(p: "SeedAdmitParams"):
    """进程内缓存：同一 (模型指纹, db, 门槛) 只建一次（字形库人裁表要扫 sqlite）。"""
    key = (p.shadow_model_fingerprint, str(_shadow_model_path(p)), p.db_path, p.variants, p.shadow_conf)
    g = _SHADOW_GATES.get(key)
    if g is None:
        from ..shadow.gate import ShadowGate
        from ..shadow.model import load_model
        from ..shadow.signals import load_context
        g = ShadowGate(load_model(_shadow_model_path(p)), load_context(p.db_path, p.variants or None),
                       p.shadow_conf)
        _SHADOW_GATES.clear()
        _SHADOW_GATES[key] = g
    return g


def _follow_ref_veto(rec, pick, ref, g: dict) -> bool:
    """影子闸挑的字＝整理本字、放行字与它同属一个「兜底归整理本」同义组（`Provisional.follow_ref`：can 參㕘叅、ba 䟦跋、dian 點㸃𭶑）：
    sheldon 11-03 定「拆不开的格兜底放成整理本字」，而放行字是库首位（ref_lib 通道，不经字组补放，组流程复核只回 keep），
    影子一否决就降审。这里直接改成整理本字、不降审，证据记 `group.decision=provisional`、`follow_ref_veto`。
    整理本须是现役对位（缺位的坐标对位不算）；有分族的组（can 參／叅㕘）放行字与整理本须同族。→ 改了字 True。"""
    from ..groups.registry import PROVISIONAL
    gid = g.get("id") if g else None
    pv = PROVISIONAL.get(gid) if gid else None
    if pv is None or not pv.follow_ref or not pick or not ref or pick != ref or rec.char == ref:
        return False
    if rec.char not in pv.forms or ref not in (pv.forms | pv.ref_forms):
        return False
    if pv.fams and not any(rec.char in f and ref in f for f in pv.fams):
        return False
    old = rec.char
    rec.char = ref
    ev = dict(rec.evidence or {})
    ev["group"] = {**g, "decision": "provisional", "pick": ref, "why": "follow_ref_veto"}
    ev["follow_ref_veto"] = {"from": old, "to": ref}
    rec.evidence = ev
    return True


def _shadow_veto_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict, amap: dict) -> int:
    """影子放行闸（只降级）：把现行规则已放行、影子有把握说不对的格降回待审。→ 降级格数。

    放在所有通道与 `group_flow` 之后：只会把 admit 从 True 改 False，不改字、不升级。
    字组按文意定的字（通道 `group_flow`、provenance `context`）影子要改成同组另一个字时不降：形近字的库形本就分不开，
    影子挑的只是同一个难点的另一边（sheldon 10-22「文意置信度特别高可以改掉整理本」，vol09:251 改成曰后被影子降、
    又被 coord_fallback 按坐标放回日）。同义（异体）字组的流程已给字且与放行字相同（补放、复核同意或改字）时，影子挑同组
    另一个码位也不降：同义组里只差码位，由字组按刻形定（A24 10-25：參㕘叅 整理本作叅、刻形是㕘，影子照整理本降审 15 格）。字组补放时整字 HOG（`ids`）过门槛给了放行字的，影子挑同组另一个字也不降（形近组同理，vol16:42:4:3 傳）。
    `provenance=="human"`（人裁）一票定案，不经这里。模型文件缺／口径不符 → 抛错（开了开关却没有模型
    是配置错误，不静默当没开）；单格信号异常 → 该格弃权。"""
    from ..shadow.signals import CellEvidence
    gate = _shadow_gate(p)
    vmap = None
    if p.shadow_veto_variant_abstain:
        from ..clustering.variants import VariantMap
        vmap = VariantMap.load(p.variants or None)
    rare = _opt(ctx, "rare_candidates", page)
    rmap = {r.id: r for cc in (rare.columns if rare else []) for r in cc.chars}
    book = getattr(ctx, "book", None)
    cbook = book if getattr(book, "codepoints", None) else None
    n = 0
    for col in out:
        for rec in col.chars or []:
            if not rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            if m is None:
                continue
            rr = rmap.get(rec.id)
            ev = CellEvidence(
                id=rec.id, lib=[(c, v) for c, v in (m.candidates or [])],
                rare=[(x.char, x.score) for x in ((rr.candidates if rr else None) or [])],
                ref=(amap.get(rec.id) or (None, None))[0], cur=rec.char)
            v = gate.judge(ev)
            if not v.veto:
                continue
            g = (rec.evidence or {}).get("group") or {}
            if (rec.channel == "group_flow" and rec.provenance == "context" and v.pick
                    and v.pick in _group_members(g.get("id"))):
                continue                      # 字组按文意定的字，影子只是挑了同组另一个字：形近本就分不开（vol09:251 曰）
            if (rec.channel == "group_flow" and v.pick and v.pick in _group_members(g.get("id"))
                    and any(t.get("solver") == "ids" and t.get("char") == rec.char and t.get("margin") for t in g.get("solvers") or [])):
                # 字组补放时整字 HOG 过了门槛给的字（按册留出 0 错），影子挑同组另一个字：不降。vol07–18 这样被降的形近组 8 格
                # 看图全是组对（傳傅 二一 會曾 子于 出山 山由 宋朱 間問），降审后 6 格又被坐标兜底按整理本放错（A24 10-25）
                continue
            if (v.pick and _group_variant(g.get("id")) and g.get("why") == "agree" and g.get("pick") == rec.char
                    and g.get("decision") in ("admit", "keep", "fix") and v.pick in _group_members(g.get("id"))):
                continue                      # 同义字组按刻形定了码位，影子挑同组另一个码位只是码位口径差（vol13–20 參㕘叅 15 格，A24 10-25）
            if (v.pick and g.get("decision") == "provisional" and g.get("pick") == rec.char
                    and v.pick in _provisional_forms(g.get("id"))):
                continue                      # 暂归一兜底定的字，影子挑同字的另一写法：写法本来就没拆（A24 10-27）
            if _follow_ref_veto(rec, v.pick, (amap.get(rec.id) or (None, None))[0], g):
                # 兜底归整理本字（sheldon 11-03，參㕘叅、䟦跋、點㸃𭶑）：影子挑的正是整理本字，改成它，不降审（第 4 轮）
                continue
            if (cbook is not None and v.pick and rec.char and v.pick != rec.char
                    and cbook.canonical_char(v.pick) == cbook.canonical_char(rec.char)):
                continue                      # 册 `codepoints:` 归一后同字（別别、晚晩、出岀）：影子比字没按册归一，不是认错
            if (vmap is not None and v.pick and rec.char and v.pick != rec.char
                    and not _rare_cp(rec.char)    # 放行字是罕用码位不弃权（#431：𠮓→變、𣼣→漏）
                    and vmap.semantic(v.pick) == vmap.semantic(rec.char)):
                continue                      # 异体同字：标签口径差，不是认错字（#431）
            fold_ruled = (getattr(p, "ruling_anchor_loose", False) and rec.channel == "fold"
                          and ((rec.evidence or {}).get("fold") or {}).get("via") == "ruling")
            _demote(rec, "shadow_veto")
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = _doubts(m, None) + list(rec.doubts) + ["shadow_veto"] + (["fold_ruling_vetoed"] if fold_ruled else [])
            rec.evidence = {**rec.evidence, "shadow_veto": v.evidence(gate.model, gate.conf, gate.low_conf)}
            n += 1
    return n


def _witness3_knn_veto_fn(p, ctx, page: int):
    """`witness3_knn_veto` 的判官：(栏, 格, 库首位, 整理本字) → 否决证据 dict 或 None（不否决）。见该参数说明。"""
    from ..groups import near_knn
    from ..groups.registry import FLOW_GROUPS
    model = near_knn.load(p.group_flow_near_knn)
    skip_sets = [frozenset(FLOW_GROUPS[g].members) for g in model["skip_groups"] if g in FLOW_GROUPS]

    def veto(col, rec, lib, ref):
        if not lib or not ref or lib == ref or {lib, ref} & model["skip_chars"]:
            return None
        if any(lib in m and ref in m for m in skip_sets):
            return None
        try:
            img = _C._page_patch(ctx, page, col, rec.slot, rec.sub)
        except PatchUnavailable:
            return None
        v = near_knn.judge(img, model, [lib, ref])
        if (v.get("pick") == lib and v["votes"] >= model["votes_min"] - 1 and v["full"] == lib
                and v["full_votes"] >= model["full_votes_min"] and v["nn"] <= model["guard"]):
            return {k: v[k] for k in ("pick", "votes", "ratio", "full", "full_votes", "nn")}
        return None
    return veto
