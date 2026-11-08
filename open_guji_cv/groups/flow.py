"""字组统一流程（新 variant-tie，2026-10-18 sheldon 定；方案见 doc/design/M7-字组统一流程-variant-tie改造方案.md）。

只被 `seed_admit` 在开关 `group_flow`（点名组 id）非空时调用，放在所有通道与后处理遍之后；缺省关，关着时本模块不执行。

**进入**（一个字只属一组，`registry` 有不重叠测试）：
- 补放：格没放行、不是人裁、没撞硬护栏；库 top1 cov ≥ `min_cov`，top1 所在组 G 在点名里；与 top1 分差 < `delta` 的
  候选全在 G 里（或在 G 的 `FlowSpec.tolerate` 里）；有整理本对位字时它（或按书级 `codepoints` 归一后）也在 G 里。
  组声明了 `ref_enter` 时，top1 是 G 的陪衬字、整理本字在 G 里也算进入（字形库里没有这一形）。
  组声明了 `tolerate_ref_agree` 时，分差内（含 top1）有组外陪衬字的格补放须与整理本字同字（陪衬字挡门，A24 10-26）。
  组声明了 `ref_top_enter` 时，top1 在 G 里、整理本字（缺位时坐标对位字）也在 G 里，分差内的组外候选不拦
  （码位归一组：两码位归同一字，整理本×库首位一致就是放行的字）。
- 复核：组声明了 `review`，格已被别的通道放行、放行字在 G 里（人裁位不碰）。

**判**：按组的方法数组（`FlowSpec.methods`，方法见 `groups/methods.py`）依次跑，`combine=first` 遇到第一个放行的就停，
`agree` 全跑、给字的须全一致（下文「解法」即方法）。
- 补放：有字 → 放行（通道 `group_flow`）；无字或冲突 → 留人审，疑问码 `group_flow_abstain`／`group_flow_conflict`；
  组声明了 `lift_needs` 而给字的解法里没有它们 → 留人审（`group_flow_weak`）。
  与整理本互证（`lift_ref_guard`）：只有文意给字、整理本对位字是组里另一个字 → `group_flow_ref_dissent`；没有现役对位时
  坐标对位字是组外的字，或是组里另一个字而给字的只有单遍文意表（不是 strong、L1 规则，别的方法也没同字）→ `group_flow_coord_dissent`。
  留人审的格若文意（本组或共字组）给了与整理本（缺时坐标对位）不同的字，另记 `group_flow_ctx_contra`，后面的补放遍不碰。
- 复核（组声明了 `review_methods` 就改跑它，依次试）：给了与放行字不同的字、或解法之间不一致 → 降为人审（`group_flow_disagree`，不改字）；组声明了
  `review_fix` 时前者改成解法的字（通道 `group_flow`，`evidence.fixed_from` 记原通道与原字）；声明了
  `review_abstain` 时解法全弃权也降（`group_flow_abstain`）；其余不动。组声明了 `review_weak` 时，这些方法单独反对、
  别的方法给的都是放行字 → 不降（留痕 `review_weak: overruled`）。

- 复核时组声明了 `review_fix_margin`：给了别的字的方法 margin 够这个门槛 → 照 `review_fix` 改字，不够照常降审（徵徴）。
- 复核时组声明了 `review_fix_strong`：文意答案 strong（L2 表多遍都 high 同字）且方法之间一致 → 照 `review_fix` 改字，否则照常降审。
  组声明了 `rule_strong` 时 L1 规则命中够条数也算 strong；声明了 `review_fix_ref_rule` 时 L1 规则的字与整理本（现役对位缺格时用坐标对位字）同字也改字（木本）。
- 组声明了 `lift_ref_agree`（部首族）：补放的字须与整理本字（缺位时用坐标对位字）同字，否则留人审
  （`group_flow_ref_dissent`／`group_flow_ref_missing`）。
- 组声明了 `solo_margin`（彝）：整理本没有证人（现役对位缺，坐标对位也缺或是 〓）时只凭字形补放，给字方法每段 margin 都要够，
  否则留人审（`group_flow_solo_weak`）；坐标对位 〓 不当组外字拦。
- 组声明了 `lift_ref_veto`（一二）：整理本字是组里另一个字就不补放（`group_flow_ref_dissent`），不论哪个方法给的字。
- 组声明了 `pair`（己已巳：干支「己巳」）：读序紧挨的两格都进了本组 → 前一格给 `pair[0]`、后一格给 `pair[1]`，不跑方法
  （留痕 `ctx:pair`）；三格以上连着照常跑方法。

**暂归一兜底**（同义组，`registry.PROVISIONAL`，sheldon 2026-10-27）：上面补放留人审、复核要降审的格，若「是这个字」两路都认（`_provisional`：
库首位与分差内候选、整理本字都在这组的同字写法里；复核时放行字在里面），就放成这组最常见的字形，`evidence.group.decision`
记 `provisional`、留痕末尾记原来没放的原因与证人，将来按这个标记筛出来再拆（`is_provisional`）。意思不同的形近字组不兜底。

每个进了流程的格都写 `evidence.group`：组、入口、每个解法的给字与理由、最终结论。

判格在前、改格在后：先用遍前状态给所有格算好结论，再逐格执行，前一格改字不污染后一格的窗口。
分层同 `groups` 包：只 import L0／L1。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from . import freq as _freq
from .methods import KINDS, Method, MethodInput
from .protocol import GroupVerdict
from .registry import FLOW_GROUPS as GROUPS   # 含码位归一组（`registry.CODEPOINT_GROUPS`）
from .registry import PROVISIONAL

CHANNEL = "group_flow"
GAP = "〓"           # 逐列本（整理本）的生僻字占位：知道有字、不知道是哪个


@dataclass
class FlowConfig:
    groups: tuple
    delta: float = 0.03
    min_cov: float = 0.85
    top1_cov: float = 0.97
    form_margin: float = 0.02                          # 两段判的形选择：族内库形第一名领先族内第二名的最小分差
    freq_table: dict = field(default_factory=dict)     # 组 id → {成员: 人裁刻形数}（`freq.load`）
    freq_major: int = _freq.MAJOR
    freq_vols: dict = field(default_factory=dict)      # 组 id → {成员: 人裁册数}（`freq.load_vols`）
    freq_min_vols: int = _freq.MIN_VOLS
    l2_tables: dict = field(default_factory=dict)      # 组 id → 文意 L3 大模型答案表路径（字段名沿用旧名）
    l2_models: dict = field(default_factory=dict)      # 组 id → 文意 L2 模型小头路径（`ctx_l2`）
    l3_online: dict = field(default_factory=dict)      # 组 id → {system 提示词, ver, cache 路径}：文意 L3 在线（`ctx_llm`）；空＝不问
    l3_model: str = "claude-opus-5-5"
    l3_effort: str = "low"
    l3_need_l2_agree: bool = False                     # L3 在线给的字须与 L2 模型弃权时的首选字相同
    l3_skip_half: bool = False                         # 夹注 a/b 半格不走 L3（答案表、在线、二审小组都不碰；SJ 史記 06:12:5:12a 错放，A31 11-04 定半格归 S）
    l3_panel: tuple = ()                               # L3 二审小组 ("模型:effort", …)：首问不稳时全部同字才给字，记 strong（`ctx_llm.panel_verdict`）；空＝不开
    l3_panel_groups: tuple = ()                        # 哪些组用二审小组（其余组不问）
    canon: Callable[[str], str] | None = None          # 书级码位归一（L2 表键按它归一再比；None＝逐字比）
    l2_drift: int = 0                                  # L2 表键容许远处差几个字位（`ctx_l3.ctx_drift`；0＝逐字比）
    joint: bool = False                                # 共字组联合补放（`entry` 的 "joint"，见 `decide_joint`）
    lift_ref_veto: frozenset = frozenset()    # 书级：这几组补放（lift）时，整理本（或坐标对位）字是组里另一个字、与给的字不同 → 不放，留人审（只降不放；史記 sy 山→出 2026-11-03）
    ref_free_groups: frozenset = frozenset()  # 书级：这几组也按 `ref_free` 走（完全不看整理本字：入口、判法、补放、复核都不用；sheldon 2026-11-06 日曰同己已巳）
    lift_shape_ref: frozenset = frozenset()   # 书级：这几组 lift_needs 没满足时，字形路给的字＝整理本（或坐标对位）字、无解法异议也补放
    lift_shape_ratio: dict = field(default_factory=dict)       # 组 id → {字: (下限, 上限)}：`lift_shape_ref` 的宽高门，字形路 ratio 在区间内才放（seed_admit `group_flow_lift_shape_ratio`）
    lift_shape_ratio_half: dict | None = None                  # 夹注 a/b 半格单用的宽高门；None＝同正文
    abstain_ref_ok: frozenset = frozenset()  # 书级「按整理本走」：复核时解法全弃权、已放行字＝整理本字 → 不降审；补放时族内刻形拆不开、整理本是同族一形 → 取整理本形
    shape_ref_ok: frozenset = frozenset()    # 书级「按整理本走」：复核时只有字形路（ids）给出别的字、已放行字＝整理本字 → 不降审（史記 2026-11-01，廣賔、還遺 等）
    tolerate_extra: dict = field(default_factory=dict)  # 组 id → 书级追加的陪衬字（叠在 `FlowSpec.tolerate` 上；seed_admit `group_flow_tolerate_extra`）
    rr_model: str | None = None
    rr_p: float = 0.5
    coord_outside_skip: bool = False                   # 现役对位缺这一格、坐标对位字是组外字（非组员、非陪衬、非〓）时不补放入组（A24 Z01 深挖 2026-11-06；seed_admit `group_flow_coord_outside_skip`）
    lift_ref_guard: bool = True                        # 补放与整理本互证（`group_flow_pass`，seed_admit `group_flow_lift_ref_guard`）
    codepoint_min_cov: float = 0.91                    # 码位法（`methods.Codepoint`）给字要库首位 cov 到这个数：更低的多是褪墨页（vol44:213:9:12 郞 0.90 看不清）
    provisional: bool = True                           # 同义组暂归一兜底（`registry.PROVISIONAL`，seed_admit `group_flow_provisional`）
    vis_model: str | None = None                       # 字块图像＋文意 L4（`vis_llm`）用的模型；None＝不问（A24 2026-11-01）
    vis_cache: object = None                           # 裁定库缓存（lookup／store）
    provisional_gap_cov: float = 0.95                  # 兜底时整理本缺字（〓）算一路证人，库首位 cov 要到这个数
    provisional_to: dict = field(default_factory=dict) # 组 id → 书级暂归一字形（压过 `registry.PROVISIONAL` 的 `to`；须在该组 forms 里；seed_admit `group_flow_provisional_to`）
    dissent_keep: frozenset = frozenset()              # 书级：这几组复核时「整理本＝放行字、只有弱图像票反对」不降审（`_dissent_keep`；seed_admit `group_flow_dissent_keep`，A24 Z02 深挖 2026-11-06）
    dissent_keep_form: bool = True                     # 书级：`dissent_keep` 里「至少一路给了放行字」也认 ids 弃权票（margin<`dissent_margin`）的刻形＝放行字（A24 Z03 11-08，r7 殿本一二 27 格里 19 格 ids 低 margin 弃权但刻形＝放行字＝整理本，只有 yr_bars 数横反对）
    same_writing_keep: frozenset = frozenset()         # 书级：这几组（缺省见 seed_admit `group_flow_same_writing_keep`）复核时给别字的解法给的全是「同一个字的另一写法」（`registry.PROVISIONAL` 暂归一表）→ 不降审（A24 Z03 深挖 2026-11-07，殿本／史記 21 格宮宫、賓賔、敘叙、敎教 等）
    review_fix_agree: frozenset = frozenset()          # 书级：这几组复核时 ≥2 路不同的图像解法（`IMG_SOLVERS`，如 yr_bars＋ids）给了同一个别的字、没人反对 → 照 `review_fix` 改字（A24 Z03 深挖 2026-11-07，一二 35 格目视 24 格全对）
    dissent_margin: float = 1.0                        # `dissent_keep` 里 ids 反对票算弱票的 margin 上限（seed_admit `group_flow_dissent_margin`）
    dissent_l1: frozenset = frozenset()                # 书级：`dissent_keep` 的组里，文意 L1 规则（`ctx:ctx_l1`）孤证反对也算弱票，但要有本组非文意解法（ids 等）同意放行字（A24 Z02 11-07）
    ctx_agree: frozenset = frozenset()                 # 书级：`dissent_keep`／`ref_pair` 里列入此名单的组，还要本组文意（ctx）同意放行字／整理本字才生效（A24 Z02 11-07；入人八 rr）
    ref_pair: frozenset = frozenset()                  # 书级：这几组补放／联合判卡住时「整理本字＝本组解法给的字、反对的只有图像路」取整理本字（`_ref_pair_pick`；seed_admit `group_flow_ref_pair`）
    ref_pair_margin: float = 1.5                       # `ref_pair` 里图像路反对票的 margin 上限（seed_admit `group_flow_ref_pair_margin`）
    ref_pair_coord: bool = False                       # 书级：`ref_pair` 的组联合判卡住、现役对位缺时，坐标对位字＝本组给的字且没有任何解法（含搭档）给别字 → 取它（`_ref_pair_coord_pick`；seed_admit `group_flow_ref_pair_coord`，A24 Z07 11-07）


@dataclass
class FlowResult:
    lifted: int = 0
    demoted: int = 0
    entered: int = 0



def _shape_ratio_ok(g: str, cid: str, ch: str, trail: list, cfg) -> bool:
    """`lift_shape_ref` 的宽高门：组 `g` 没设门 → 放；设了门，字 `ch` 须在表里、字形路给 `ch` 的 ratio 落在区间内。"""
    tab = cfg.lift_shape_ratio
    if cid[-1:] in ("a", "b") and cfg.lift_shape_ratio_half is not None:
        tab = cfg.lift_shape_ratio_half
    if g not in tab:
        return True
    lim = tab[g].get(ch)
    if not lim:
        return False
    lo, hi = lim
    rs = [t.get("ratio") for t in trail if t.get("char") == ch and t.get("ratio") is not None]
    return bool(rs) and all(lo <= float(x) <= hi for x in rs)


def _rf(g: str, cfg) -> bool:
    """组 `g` 在这次流程里是否完全不看整理本字：注册表的 `ref_free`，或书级 `FlowConfig.ref_free_groups`。"""
    return GROUPS[g].ref_free or g in cfg.ref_free_groups

def check_groups(groups) -> None:
    """点名的组必须已登记且声明了 `flow`，方法须是 `groups.methods` 认得的类、名字不重复。"""
    for g in groups:
        if g not in GROUPS:
            raise ValueError(f"group_flow：未登记的字组 {g!r}")
        f = GROUPS[g].flow
        if f is None:
            raise ValueError(f"group_flow：字组 {g!r} 没有声明 flow（registry.GroupSpec.flow）")
        bad = [m for m in (*f.methods, *f.form_methods, *f.review_methods) if not isinstance(m, Method) or m.kind not in (*KINDS, "chain")]
        if bad:
            raise ValueError(f"group_flow：字组 {g!r} 的方法 {bad} 不认得（须是 groups.methods 的方法）")
        if len(set(f.solvers)) != len(f.solvers):
            raise ValueError(f"group_flow：字组 {g!r} 的方法名重复 {f.solvers}")
        if set(f.lift_needs) - set(f.solvers):
            raise ValueError(f"group_flow：字组 {g!r} 的 lift_needs {f.lift_needs} 不在它的解法里")
        if f.families and set("".join(f.families)) - GROUPS[g].members:
            raise ValueError(f"group_flow：字组 {g!r} 的 families {f.families} 含非成员字")
        if len(set(f.form_solvers)) != len(f.form_solvers):
            raise ValueError(f"group_flow：字组 {g!r} 的 form_methods 名重复 {f.form_solvers}")
        if len(set(f.review_solvers)) != len(f.review_solvers):
            raise ValueError(f"group_flow：字组 {g!r} 的 review_methods 名重复 {f.review_solvers}")
        if f.review_methods and not f.review:
            raise ValueError(f"group_flow：字组 {g!r} 声明了 review_methods 却没开 review")
        if f.combine not in ("first", "agree"):
            raise ValueError(f"group_flow：字组 {g!r} 的 combine={f.combine!r} 只能是 first/agree")


def group_of(ch: str | None, groups) -> str | None:
    gs = groups_in(ch, groups)
    return gs[0] if gs else None


def groups_in(ch: str | None, groups) -> list[str]:
    """点名的组里含 `ch` 的全部组（按点名顺序）。成员原则上不重叠，只有登记表里互相声明了 `overlaps` 的组可以共字（如日曰／日目）。"""
    if not ch:
        return []
    return [g for g in groups if ch in GROUPS[g].members]


def _member(g: str, ch: str | None, canon: Callable[[str], str]) -> bool:
    """`ch` 算不算组 `g` 的字：是组员，或按书级码位归一后是组员；组声明了 `ref_canon` 时，归一后与某个组员归一后同字也算。"""
    if not ch:
        return False
    mem = GROUPS[g].members
    if ch in mem or canon(ch) in mem:
        return True
    return GROUPS[g].flow.ref_canon and canon(ch) in {canon(m) for m in mem}


def _same(g: str, a: str | None, b: str | None, canon: Callable[[str], str]) -> bool:
    """复核比字：同字；或组声明了 `ref_canon`、两字不同为组员、按书级码位归一后同字（同一刻法的两个码位）。"""
    if a == b:
        return True
    mem = GROUPS[g].members
    return bool(GROUPS[g].flow.ref_canon and a and b and not (a in mem and b in mem) and canon(a) == canon(b))


def _tol(g: str, cfg: FlowConfig) -> frozenset:
    """组 g 的陪衬字：注册表 `FlowSpec.tolerate` ＋ 书级追加（`FlowConfig.tolerate_extra`）。"""
    extra = cfg.tolerate_extra.get(g)
    return GROUPS[g].flow.tolerate | frozenset(extra) if extra else GROUPS[g].flow.tolerate


def entry(r, cands, ref, cfg: FlowConfig, canon: Callable[[str], str] = lambda c: c,
          coord_ref: str | None = None) -> tuple[str, str] | None:
    """→ (组 id, "lift"|"review") 或 None。`r` 是放行记录（id/char/admit/channel/provenance）；硬护栏由调用方先筛。

    一个字属于多个组（`overlaps`）时：补放选第一个能把「分差内全部候选＋整理本字」都装下的组，复核选第一个
    声明了 `review` 且装得下整理本字的组。哪一组都装不下、但装得下「组＋它的共字组」（日曰目紧咬：ry＋rm）时，
    `cfg.joint` 开着 → (组, "joint")，由 `decide_joint` 判。
    `coord_ref`：现役对位缺这一格时的坐标对位字，只给 `ref_enter`／`ref_top_enter` 用（vol49 算學諸書整页对位缺，坐标对位作 𮅕）。"""
    if r.provenance == "human" or r.channel in ("human", CHANNEL):
        return None
    if r.admit:
        gs = [g for g in cfg.groups if GROUPS[g].flow.review and (r.char in GROUPS[g].members
                                                                 or (GROUPS[g].flow.ref_canon and _member(g, r.char, canon)))]
        for g in gs:
            if _rf(g, cfg) or not ref or _member(g, ref, canon):
                return g, "review"
        return None
    if not cands:
        return None
    top, c1 = cands[0]
    if c1 < cfg.min_cov:
        return None
    rr = ref or coord_ref
    # 现役对位缺这一格、坐标对位说是另一个字（`coord_outside_skip`）：组只会在组员里挑字，这格进组必弃权（Z01），
    # 原因该落回 L01／P02（殿本 Z01 527 格里 394 格是这样，A24 2026-11-06）。〓／空格位不算（彝 solo_margin 要进）。
    co = coord_ref if (cfg.coord_outside_skip and not ref and coord_ref and coord_ref != GAP) else None

    def _coord_out(g: str, mem) -> bool:
        pv = PROVISIONAL.get(g)                    # 暂归一的另一写法／整理本写法（點㸃 的 𭶑）算组内
        return (bool(co) and not _rf(g, cfg) and co not in mem and canon(co) not in mem and co not in _tol(g, cfg)
                and not (pv and (co in pv.forms or co in pv.ref_forms)))

    def _pv_ref(g: str, w: str) -> bool:
        # 整理本字是本组暂归一兜底的另一写法（li 的 𨽻、sui 的 𡻕）：同字异写，不算组外字，照样进组让解法／兜底定形。
        # 第 6 轮 align_ref 把这些位对上了整理本字（第 5 轮缺位、按坐标对位进组暂归一放行），入口反倒因「整理本字不是组员」
        # 不接，殿本 V01 多出 225 格（A24 V01 按新码重统计 2026-11-07）。
        pv = PROVISIONAL.get(g)
        return bool(cfg.provisional and pv and (w in pv.forms or canon(w) in pv.forms or w in pv.ref_forms))

    for g in cfg.groups:                      # 库里没有这一形、库排成陪衬字：按整理本字进（`FlowSpec.ref_enter`），先于库首位字所在的组
        f, mem = GROUPS[g].flow, GROUPS[g].members
        tol = _tol(g, cfg)
        if not (f.ref_enter and not _rf(g, cfg) and (f.lift_ref_agree or f.tolerate_ref_agree) and rr and _member(g, rr, canon)
                and (top in tol or (f.ref_enter_member and top in mem and rr != top))):
            continue
        if all(c in mem or c in tol for c, v in cands[1:] if c1 - v < cfg.delta):
            return g, "lift"
    for g in groups_in(top, cfg.groups):
        mem = GROUPS[g].members
        if not all(c in mem or c in _tol(g, cfg) for c, v in cands[1:] if c1 - v < cfg.delta):
            continue
        if not _rf(g, cfg) and ref and not _member(g, ref, canon) and not _pv_ref(g, ref):
            continue
        if _coord_out(g, mem) and not _member(g, co, canon):
            continue
        return g, "lift"
    for g in groups_in(top, cfg.groups):      # 库首位与整理本（缺位时坐标对位）字同在本组：分差内的组外字不拦（`FlowSpec.ref_top_enter`）
        if GROUPS[g].flow.ref_top_enter and rr and (rr in GROUPS[g].members or canon(rr) in GROUPS[g].members):
            return g, "lift"
    if cfg.joint:
        for g in groups_in(top, cfg.groups):
            parts = partners(g, cfg.groups)
            if not parts:
                continue
            mem = GROUPS[g].members.union(*(GROUPS[h].members for h in parts))
            tol = _tol(g, cfg)
            if not all(c in mem or c in tol for c, v in cands[1:] if c1 - v < cfg.delta):
                continue
            if ref and ref not in mem and canon(ref) not in mem:
                continue
            if _coord_out(g, mem):
                continue
            return g, "joint"
    return None


def _ctx_strong(trail: list, ch: str | None) -> bool:
    """本组文意给了 `ch` 且 strong（L2 表多遍都 high 同字；L1 规则与这样的表一致也算）。"""
    return any(t["solver"] == "ctx" and t["char"] == ch and t.get("strong") for t in trail)


def _ctx_panel(trail: list, ch: str | None) -> bool:
    """本组文意给了 `ch`，且经 L3 二审小组确认（两个强模型高 effort 同字，至少一家 high）。"""
    return any(t["solver"] == "ctx" and t["char"] == ch and t.get("strong") and str(t.get("panel") or "").startswith("char") for t in trail)


def partners(g: str, groups) -> tuple:
    """组 `g` 在点名里的共字组（登记表 `overlaps`）。"""
    return tuple(h for h in GROUPS[g].overlaps if h in groups)


def _method(g: str, name: str, form: bool = False, review: bool = False):
    f = GROUPS[g].flow
    for m in (f.form_methods if form else (f.review_methods or f.methods) if review else f.methods):
        if m.name == name:
            return m
    raise ValueError(f"group_flow：字组 {g!r} 没有方法 {name!r}")


def _solve(name: str, g: str, r, cands, ref, cfg: FlowConfig, left: str | None, right: str | None,
           patch_fn, members=None, form: bool = False, review: bool = False, force_panel: bool = False,
           coord: str | None = None) -> GroupVerdict:
    """跑组 `g` 方法数组里名叫 `name` 的方法（`groups.methods`）。`members` 给了就只在这些字里选（两段判第二段＝族）。"""
    inp = MethodInput(group=g, members=frozenset(members if members is not None else GROUPS[g].members),
                      cell_id=r.id, cands=cands, ref=ref, cfg=cfg, left=left, right=right, patch_fn=patch_fn,
                      cur=r.char if review else None, force_panel=force_panel, coord=coord)
    return _method(g, name, form, review).run(inp)


#: 清晰几何量先于其他字形路与整理本：组 → (方法名, |比值−1| 门槛)。土士：量横比 ≥1.12 判土、≤0.88 判士（A24 2026-11-03）。
CLEAR_OVER = {"ts": ("bars", 0.12)}


def decide(g: str, r, cands, ref, cfg: FlowConfig, left=None, right=None, patch_fn=None,
           review: bool = False, coord: str | None = None) -> tuple[str | None, str, list]:
    """依次跑组的方法数组 → (字或 None, 原因 "agree"|"abstain"|"conflict", 每个方法的留痕)。
    `review` 且组声明了 `review_methods`：改跑复核数组，第一个给字的说了算。"""
    f = GROUPS[g].flow
    alt = review and bool(f.review_methods)
    trail: list[dict] = []
    picks: list[str] = []
    for name in (f.review_solvers if alt else f.solvers):
        v = _solve(name, g, r, cands, ref, cfg, left, right, patch_fn, review=alt, coord=coord)
        trail.append({"solver": name, "char": v.char, "why": v.why, **({"via": v.via} if v.via != name else {}),
                      **v.extra})
        if v.char is not None:
            picks.append(v.char)
            if f.combine == "first" or alt:
                break
    if len(set(picks)) > 1 and f.ctx_over_panel and not alt:
        # 文意与字形冲突：字形（ry_shape）在 ctx_over_panel 里，且文意字还没经二审小组确认 → 让小组确认一次，确认了字形只当弱票（`_ctx_over`）
        ci = next((i for i, t in enumerate(trail) if t["solver"] == "ctx" and t["char"] and not t.get("panel")), None)
        if ci is not None:
            v = _solve("ctx", g, r, cands, ref, cfg, left, right, patch_fn, force_panel=True)
            if v.extra.get("panel"):
                trail[ci] = {"solver": "ctx", "char": v.char, "why": v.why, **({"via": v.via} if v.via != "ctx" else {}), **v.extra}
                picks = [t["char"] for t in trail if t["char"] is not None]
    if not alt and g in CLEAR_OVER and len(set(picks)) != 1:
        # 量横清晰：几何量够清楚（|比值−1| ≥ 门槛）时先于 ids、整理本；文意给了另一个字则照旧（A24 11-03，sheldon 定：
        # 「量横首先越过整理本，但必须是清晰横线，不确定的按文意」；土士 admitted 5 格里 士 其实刻作 土，比值 1.06–1.22）
        sol, gap = CLEAR_OVER[g]
        t = next((t for t in trail if t["solver"] == sol and t["char"] and t.get("ratio") is not None
                  and abs(t["ratio"] - 1) >= gap), None)
        if t is not None and not any(x["solver"] == "ctx" and x["char"] and x["char"] != t["char"] for x in trail):
            trail.append({"solver": "clear_over", "char": t["char"], "why": "agree", "ratio": t["ratio"]})
            return t["char"], "agree", trail
    if not picks:
        return None, "abstain", trail
    if len(set(picks)) > 1:
        return None, "conflict", trail
    if f.families:
        return _pick_form(g, picks[0], r, cands, cfg, patch_fn, trail)
    return picks[0], "agree", trail


def _ctx_firm(t: dict) -> bool:
    """文意这一路的字够硬：L1 规则，或 L2 表 strong（多遍同字、至少两遍 high）。"""
    return t["solver"] == "ctx" and t["char"] is not None and (t.get("via") == "ctx:ctx_l1" or bool(t.get("strong")))


def _panel_firm(t: dict) -> bool:
    """文意这一路的字是 L3 二审小组（两个强模型高 effort 同字）确认过的。"""
    return t["solver"] == "ctx" and t["char"] is not None and str(t.get("panel") or "").startswith("char")


def _ctx_over(g: str, ch, why: str, trail: list) -> tuple:
    """`FlowSpec.ctx_over`：文意够硬（`_ctx_firm`）时，`ctx_over` 里的字形方法给了别的字只当弱票——别的方法都同文意就照文意给字，
    留痕 `ctx_over: overruled`。入人八（A24 10-26）：殿本 入 多刻成两笔分开、像 八，整字 HOG 常把 入 判成 八。
    `FlowSpec.ctx_over_panel`：同理，但只有文意字经 L3 二审小组确认（`_panel_firm`）才算硬（日曰，A24 11-01：字形宽高比在
    「爲日月星辰之用數」「高日化」上把日判成曰，二审小组读对）。"""
    f = GROUPS[g].flow
    names = tuple(f.ctx_over) + tuple(f.ctx_over_panel)
    firm = {t["char"] for t in trail if (_ctx_firm(t) if f.ctx_over else _panel_firm(t))}
    if f.ctx_over and f.ctx_over_panel:
        firm = {t["char"] for t in trail if _ctx_firm(t) or _panel_firm(t)}
    rest = {t["char"] for t in trail if t["char"] is not None and t["solver"] != "ctx" and t["solver"] not in names}
    if len(firm) != 1 or not rest <= firm:
        return ch, why, trail
    c = next(iter(firm))
    return c, "agree", trail + [{"solver": "ctx_over", "char": None, "why": "overruled",
                                 "weak": [t["solver"] for t in trail if t["solver"] in names and t["char"] not in (None, c)]}]


def decide_joint(g: str, r, cands, ref, cfg: FlowConfig, left=None, right=None, patch_fn=None) -> tuple[str | None, str, list]:
    """共字组联合判（日曰目三字紧咬，哪一组都装不下；sheldon 10-22「目是真竞争者，不能当陪衬」）：
    先由组 `g` 定字 X，再问每个共字组 h——X 是 h 的成员：h 也须给 X；X 不是 h 的成员：h 须明确说「其他」
    （文意 L2 表 `abstain:other` 且各遍都是 high，即「h 的字放进去都不通」）。任一共字组弃权、给了别的字 → 待定（"joint"）。
    例：ry 说曰、rm 说其他 → 曰；ry 说日、rm 说日 → 日；rm 没表态 → 留人审。共字组的留痕名前加「组 id:」。"""
    ch, why, trail = decide(g, r, cands, None if _rf(g, cfg) else ref, cfg, left, right, patch_fn)
    if ch is None:
        return None, why, trail
    for h in partners(g, cfg.groups):
        if ch not in GROUPS[h].members and _ctx_panel(trail, ch):
            # 本组文意字经 L3 二审小组确认、且不是共字组 h 的成员：小组读的就是「这几个字都放进去」，h 不用再表态
            # （日曰 ry 说曰、日目 rm 的小组常各说各的「其他／目」而联判卡住，A24 11-01）
            trail = trail + [{"solver": f"{h}:skip", "char": None, "why": "panel_confirmed"}]
            continue
        hc, _, ht = decide(h, r, cands, None if _rf(h, cfg) else ref, cfg, left, right, patch_fn)
        trail = trail + [{**t, "solver": f"{h}:{t['solver']}"} for t in ht]
        ok = hc == ch if ch in GROUPS[h].members else (
            hc is None and any(t.get("why") == "abstain:other" and t.get("other_conf") == "high" for t in ht))
        if not ok:
            return None, "joint", trail
    return ch, "agree", trail


def _pick_form(g: str, ch: str, r, cands, cfg: FlowConfig, patch_fn, trail: list) -> tuple[str | None, str, list]:
    """两段判的第二段：`ch` 是第一段（文意）定的字；它所在的族不止一形时，按刻形在族内依次试 `form_methods`，都待定就待定。"""
    f = GROUPS[g].flow
    fam = next((x for x in f.families if ch in x), None)
    if fam is None or len(fam) < 2:
        return ch, "agree", trail
    # 族内各形按书级码位归一后是同一个字（宮宫 sheldon 10-25 暂归一到 宫）：刻形不用再分，直接给归一后的字
    if cfg.canon is not None and len({cfg.canon(c) for c in fam}) == 1:
        return cfg.canon(ch), "agree", trail + [{"solver": "form:canon", "char": cfg.canon(ch), "why": "agree"}]
    fam_set = frozenset(fam)
    for name in f.form_solvers:
        v = _solve(name, g, r, cands, None, cfg, None, None, patch_fn, members=fam_set, form=True)
        if v.char is not None and v.char not in fam_set:
            v = GroupVerdict(None, why="abstain:out_of_family", via=v.via)
        trail.append({"solver": f"form:{name}", "char": v.char, "why": v.why, **v.extra})
        if v.char is not None:
            return v.char, "agree", trail
    return None, "abstain", trail


def _pair_pos(entries: dict, i: int, g: str) -> int | None:
    """组声明了 `pair` 时，第 i 格与读序紧挨的一格都进了本组、且不是三格以上连着 → 0（前一格）或 1（后一格）；否则 None。"""
    if not GROUPS[g].flow.pair:
        return None
    same = lambda j: j in entries and entries[j][2][0] == g
    run = [j for j in (i - 1, i + 1) if same(j)]
    if len(run) != 1:
        return None
    j = run[0]
    lo = min(i, j)
    if same(lo - 1) or same(lo + 2):
        return None
    return 0 if i == lo else 1


def _slot_family(pv, trail: list | None, w, canon: Callable[[str], str]) -> str | None:
    """暂归一按 IDS 取块分族（`Provisional.slot_to`，參㕘叅）：返回兜底该放的字；族对不上、没有 IDS 取块 → None（不兜底）。
    整理本字（`w`）在 forms 里就必须与 IDS 取块同族；整理本缺字（或没有）时取块分差要 ≥ `slot_min`。"""
    sl = dict(pv.slot_to)
    its = [t for t in (trail or []) if t.get("solver") == "ids" and t.get("scores")]
    if not its:
        return pv.to                      # 没有 IDS 取块分（复核只跑别的方法时）：照旧放最常见字形
    sc = its[0]["scores"]
    best = max(sc, key=sc.get)
    t = sl.get(best)
    if t is None:
        return None
    fam = lambda c: next((i for i, f in enumerate(pv.fams) if c in f or canon(c) in f), -1)  # noqa: E731
    if w and w != GAP and (w in pv.forms or canon(w) in pv.forms):
        return t if fam(w) == fam(t) else None
    v = sorted(sc.values(), reverse=True)
    return t if len(v) > 1 and v[0] - v[1] >= pv.slot_min else None


def _provisional(g: str, mode: str, r, cands, ref, coord: str | None, cfg: FlowConfig,
                 canon: Callable[[str], str], trail: list | None = None) -> tuple[str, str | None] | None:
    out = _provisional_base(g, mode, r, cands, ref, coord, cfg, canon, trail)
    pv = PROVISIONAL.get(g)
    if out is not None or pv is None or not pv.follow_ref or not cfg.provisional or mode != "lift" or not cands:
        return out
    # 兜底归成整理本（A24 11-03，sheldon 定 參㕘叅、䟦跋、點㸃𭶑）：库首位与整理本（缺位用坐标对位字）都认是这一族、cov 够，
    # 分差内别的候选不管（叅 常紧咬 恭未）；有分族的组（參／叅㕘）两者须同族。
    inn = lambda c: bool(c) and (c in pv.forms or canon(c) in pv.forms)  # noqa: E731
    top, c1 = cands[0]
    w0 = ref or coord
    if (inn(top) and c1 >= cfg.min_cov and w0 and w0 != GAP and (inn(w0) or w0 in pv.ref_forms)
            and (ref or r.id[-1:] not in ("a", "b"))):
        if not pv.fams or any((top in f_ or canon(top) in f_) and (w0 in f_ or canon(w0) in f_) for f_ in pv.fams):
            return w0, w0
    return None


def _provisional_base(g: str, mode: str, r, cands, ref, coord: str | None, cfg: FlowConfig,
                      canon: Callable[[str], str], trail: list | None = None) -> tuple[str, str | None] | None:
    """同义组暂归一兜底（`registry.PROVISIONAL`，sheldon 2026-10-27「先 IDS 拆分，拆不开或置信度不够就暂归一到一个字形，
    记下是暂归一定的」）：方法没定下来（弃权、冲突、被整理本拦、复核要降）的格，「是这个字」两路都认 → (暂归一的字, 证人)，否则 None。
    - 复核：放行字在 `forms` 里（别的通道已认了字），整理本没有字、是 〓 或也在 `forms` 里；
    - 补放：库首位在 `forms` 里、cov ≥ `min_cov`，分差内的候选全在 `forms` 里（陪衬、形近的别的字都不许在）；
      整理本字（现役对位缺时坐标对位字，夹注半格不认坐标对位）也在 `forms` 里；表里声明了 `gap` 的组，整理本缺字（〓）且库首位 cov ≥ `provisional_gap_cov` 也算。
    整理本说是组外的字、没有整理本字、库里分差内有别的字 → 字认不准，照旧留人审。"""
    pv = PROVISIONAL.get(g)
    if pv is None or not cfg.provisional or mode == "joint":
        return None
    if cfg.provisional_to.get(g) in pv.forms:
        pv = replace(pv, to=cfg.provisional_to[g])     # 书级暂归一字形（全唐文 彝组 刻的是 彝，不归殿本的 𢑱；11-05）
    inn = lambda c: bool(c) and (c in pv.forms or canon(c) in pv.forms)  # noqa: E731
    if mode == "review":
        if not (inn(r.char) and (not ref or ref == GAP or inn(ref))):
            return None
        if pv.slot_to:
            to = _slot_family(pv, trail, ref or coord, canon)
            return (to, ref) if to else None
        return pv.to, ref
    fam = GROUPS[g].flow.families
    if fam and trail is not None:
        # 混合组（文意定族、族内是同义异体：象彖𧰼、冠寇冦宼㓂，A24 11-01 sheldon「族内识别不了的暂归一到 象／寇」）：
        # 文意给的字在 forms 里（族外的字——彖、冠——文意给了就不兜底），整理本（缺位用坐标对位）也在 forms 里，
        # 就不看库候选里有没有形近的别的字（冠 与 寇 的库分差常在 delta 内），按文意认定族、写法拆不开暂归一到 `to`。
        cc = {t["char"] for t in trail if t["solver"] == "ctx" and t["char"]}
        if cc and not all(inn(c) for c in cc):
            return None                                        # 文意给了族外的字（彖、冠）：不兜底
        if cc:
            w = ref or coord
            if not ref and r.id[-1:] in ("a", "b"):
                return None
            return (pv.to, w) if inn(w) else None
    if not cands:
        return None
    top, c1 = cands[0]
    if not inn(top) or c1 < cfg.min_cov or not all(inn(c) for c, v in cands[1:] if c1 - v < cfg.delta):
        return None
    w = ref or coord
    if not ref and r.id[-1:] in ("a", "b"):
        return None    # 夹注半格只有坐标对位：列尾切残的半格会把上一格的字对过来（vol20:175:7:21a 坐标对位 𨽻、刻的不是 隸）
    if inn(w) or (w == GAP and pv.gap and c1 >= cfg.provisional_gap_cov):
        if pv.slot_to:
            to = _slot_family(pv, trail, w, canon)
            return (to, w) if to else None
        return pv.to, w
    return None


def is_provisional(rec) -> bool:
    """产物里的一格（dict 或放行记录）是不是暂归一兜底放的（建模板、统计时要剔除或单列）。"""
    ev = rec.get("evidence") if isinstance(rec, dict) else getattr(rec, "evidence", None)
    return ((ev or {}).get("group") or {}).get("decision") == "provisional"


def _margin(t: dict) -> float | None:
    """方法留痕的把握：整字方法记 `margin`；三段 IDS 记每段的 `margins`，取最小的一段。"""
    if t.get("margin") is not None:
        return float(t["margin"])
    ms = t.get("margins")
    return min(float(x) for x in ms) if ms else None


def _ref_lowmargin(g: str, ch, why: str, trail: list, ref: str, canon: Callable[[str], str]):
    """整理本互证降门槛（`FlowSpec.ref_margin`，A24 2026-11-01）：整字 HOG 弃权只因 margin 不够（`abstain:low_margin`），第一名是
    少见形（`ref_margin_forms`）、与整理本字（现役对位，缺位时坐标对位）同字、margin ≥ `ref_margin` → 放第一名。"""
    f = GROUPS[g].flow
    for t in trail:
        form, m = t.get("form"), _margin(t)
        if (t.get("solver") == "ids" and t.get("why") == "abstain:low_margin" and form and m is not None and m >= f.ref_margin
                and form in (f.ref_margin_forms or "".join(GROUPS[g].members)) and canon(form) == canon(ref)):
            return form, "agree", trail + [{"solver": "ref_lowmargin", "char": form, "why": "agree:ref_lowmargin",
                                            "margin": m, "ref_margin": f.ref_margin, "witness": ref}]
    return ch, why, trail


#: 只看图像的解法名（`ref_pair`、`dissent_keep` 里算「图像路」；文意 `ctx`、码位 `codepoint`、整理本类都不在内）。
IMG_SOLVERS = frozenset({"ids", "rr_img", "yr_bars", "bars", "ss_bars", "ry_shape", "zy_strokes"})


_EXTRA_SAME_WRITING = (frozenset("宫宮"), frozenset("賓賔"))


def _same_writing(a: str | None, b: str | None) -> bool:
    """同一个字的不同写法（`registry.PROVISIONAL[*].forms` 的并集判等，外加 宫宮；与 guji-manager `reasons._default_same_writing` 同口径）。"""
    if not a or not b:
        return False
    return a == b or any(a in f and b in f for f in (*(frozenset(p.forms) for p in PROVISIONAL.values()), *_EXTRA_SAME_WRITING))


def _agree_fix(trail: list, ch: str | None, members) -> bool:
    """`review_fix_agree`：≥2 路不同的图像解法给了同一个组员字 `ch`。"""
    if not ch or ch not in members:
        return False
    return len({_sname(t) for t in trail if t.get("char") == ch and _sname(t) in IMG_SOLVERS}) >= 2


def _sname(t: dict) -> str:
    return t["solver"].split(":")[-1]


def _ref_pair_coord_pick(g: str, r, trail: list, coord: str | None, canon: Callable[[str], str]) -> str | None:
    """联合判卡在「共字组搭档没表态」（`joint`）、现役对位缺这一格时，用坐标对位字作整理本证人（`FlowConfig.ref_pair_coord`，
    A24 Z07 差一路确认 11-07）：坐标对位字是组员、本组至少一路给了它，**没有任何解法（含搭档）给出别的字**（比 `ref_pair`
    更严：图像路反对也不取）；夹注半格、〓 不认。殿本＋全唐文 Z07 里这样的 41 格看图全对。"""
    if not coord or coord == GAP or r.id[-1:] in ("a", "b") or not _member(g, coord, canon):
        return None
    x = canon(coord)
    given = [t for t in trail if t.get("char")]
    if not given or any(canon(t["char"]) != x for t in given):
        return None
    sup = [t for t in given if ":" not in t["solver"]]
    if not sup:
        return None
    return next((t["char"] for t in sup if _sname(t) == "ctx"), sup[0]["char"])


def _ref_pair_pick(g: str, trail: list, ref: str | None, canon: Callable[[str], str], img_margin: float) -> str | None:
    """整理本＋本组解法两路互证（`FlowConfig.ref_pair`，A24 Z02 深挖 2026-11-06）：补放卡在「字形与文意冲突」（`conflict`）
    或「共字组搭档没裁定」（`joint`）时，若整理本对位字（现役对位，不用坐标对位）是组员 X，且 ①本组至少一路解法给了 X；
    ②所有给了别字的解法（含共字组搭档，名字带「组:」前缀）都是图像路（`IMG_SOLVERS`）、margin < `img_margin`——
    文意、码位、搭档的文意给了别字就不取；③没有文意支持 X 时，反对的图像路须比支持 X 的 ids 弱（margin 更小）。
    取支持它的解法给的字形。看图核对见 ai-team 待审原因深挖/Z02-判法打架.md（殿本 112 格目视：整理本×文意一致的 13 格全对）。"""
    if not ref or ref == GAP or not _member(g, ref, canon):
        return None
    x = canon(ref)
    sup = [t for t in trail if ":" not in t["solver"] and t.get("char") and canon(t["char"]) == x]
    if not sup:
        return None
    ctx_sup = any(_sname(t) == "ctx" for t in sup)
    sup_m = max((_margin(t) or 0.0 for t in sup if _sname(t) == "ids"), default=0.0)
    for t in trail:
        c = t.get("char")
        if not c or canon(c) == x:
            continue
        if _sname(t) not in IMG_SOLVERS:
            return None
        m = _margin(t)
        if m is not None and m >= img_margin:
            return None
        if not ctx_sup and (m is None or m >= sup_m):
            return None
    return next((t["char"] for t in sup if _sname(t) == "ctx"), sup[0]["char"])   # 取支持它的解法给的字形（与整理本字只差码位归一时不改写法）


def _ctx_agrees(trail: list, char: str | None, canon: Callable[[str], str]) -> bool:
    """本组（不含共字组搭档）的文意解法给了 ``char``（`FlowConfig.ctx_agree`）。"""
    return bool(char) and any(":" not in t["solver"] and _sname(t) == "ctx" and t.get("char") and canon(t["char"]) == canon(char) for t in trail)


def _dissent_keep(g: str, trail: list, char: str | None, ref: str | None, canon: Callable[[str], str],
                  weak_margin: float, l1_weak: bool = False, form_support: bool = False) -> bool:
    """复核弱票不降审（`FlowConfig.dissent_keep`，A24 Z02 深挖 2026-11-06）：已放行字＝整理本字（现役对位，不用坐标对位），
    ①至少一路解法给了放行字；②给了别字的解法全是图像路、且是弱票（`ids` 等记了 margin 的 < `weak_margin`；`yr_bars`、`bars`
    这类量笔画的不记 margin 也算弱票——数一二的横在切残的格上必错）。有文意、码位给了别字就照旧降审。
    殿本目视 36 格（遺還、圓圖、面而、傳傅、諭論、甲申、間問、曾會、一二）放行字全对。"""
    if not char or not ref or ref == GAP or canon(ref) != canon(char):
        return False
    x = canon(char)
    if not any(t.get("char") and canon(t["char"]) == x for t in trail) and not (
            form_support and any(_sname(t) == "ids" and not t.get("char") and t.get("form") and canon(t["form"]) == x
                                 and (_margin(t) or 0) < weak_margin for t in trail)):
        return False
    for t in trail:
        c = t.get("char")
        if not c or canon(c) == x:
            continue
        if l1_weak and _sname(t) == "ctx" and t.get("via") == "ctx:ctx_l1" and ":" not in t["solver"]:
            # L1 规则孤证（二字组合规则，全册审计冲突率约 1–2%）：整理本×本组非文意解法已同意放行字时不推翻（A24 Z02 11-07）
            if any(t2.get("char") and canon(t2["char"]) == x and _sname(t2) != "ctx" and ":" not in t2["solver"] for t2 in trail):
                continue
            return False
        if _sname(t) not in IMG_SOLVERS:
            return False
        m = _margin(t)
        if m is not None and m >= weak_margin:
            return False
    return True


def _vis_try(g: str, r, trail: list, cr: str | None, cfg: FlowConfig, canon, patch_fn, left, right):
    """字块图像＋文意 L4（`groups.vis_llm`）：一格 → (字｜None, trail 项)。高置信、是（本组＋共字组）组员，
    且有别的证人（整理本字／坐标对位字、文意 L3 或 L1、字形 ids）同字才给字。`None` 项不留痕。"""
    f = GROUPS[g].flow
    if not (f.vis and cfg.vis_model and patch_fn is not None and left is not None):
        return None, None
    mem = set(GROUPS[g].members)
    for h in partners(g, cfg.groups):
        mem |= set(GROUPS[h].members)
    patch = patch_fn(r.id)
    if patch is None:
        return None, None
    from . import vis_llm
    ans = vis_llm.judge(g, mem, patch, left, right, model=cfg.vis_model, cache=cfg.vis_cache, cell=r.id)
    if ans is None:
        return None, None
    if ans.get("ask"):                       # 管线不在线问：留痕记下这一问，导出待裁清单见 feedback/llm_queue
        return None, {"solver": "vis", "char": None, "why": ans["why"], "ask": ans["ask"]}
    ch, conf = ans["char"], ans["conf"]
    item = {"solver": "vis", "char": None, "why": f"{conf}:{ch}", "vis_conf": conf, "vis_why": ans.get("why"), "cached": ans["cached"]}
    if conf != "high" or ch not in mem:
        return None, item
    if cr and cr != GAP and canon(cr) != canon(ch) and canon(cr) in {canon(m) for m in mem}:
        # 整理本（含坐标对位）说是组里另一个字：不越过它改字。留出看图：图像＋文意 L3 都说「于」而整理本、刻形是「干」
        # （vol35:152:2:4 干文傳），两个大模型共用一套先验会一起错；整理本是组外字（悶 之类）才让图像＋证人改
        item["why"] = f"ref_dissent:{ch}"
        return None, item
    sup = []
    if cr and cr != GAP and canon(cr) == canon(ch):
        sup.append("ref")
    for t in trail:
        if t.get("char") == ch and t["solver"].split(":")[-1] in ("ctx", "ids"):
            sup.append(t["solver"])
    if not sup:
        item["why"] = f"nosupport:{ch}"
        return None, item
    return ch, {**item, "char": ch, "why": "agree", "support": sup}


def group_flow_pass(seq: list, amap: dict, cands_of: Callable[[str], list], blocked: Callable[[object], bool],
                    cfg: FlowConfig, ctx_fn: Callable[[list, int, int], str] | None = None,
                    patch_fn: Callable[[str], object] | None = None,
                    canon: Callable[[str], str] = lambda c: c,
                    veto_refs: dict[str, str] | None = None) -> FlowResult:
    """`seq`：本页读序展平的放行记录；`amap`：{id: (整理本字, op)}；`cands_of(id)`：库候选 [(字, cov)]；
    `blocked(r)`：硬护栏（遮挡、超时、排除、非字…），True 的格不进流程。就地改 `seq` 里的记录。
    `veto_refs`：{id: 坐标对位字}，只在现役对位缺这一格时用来拦补放（`cfg.lift_ref_guard`），不参与判字。"""
    entries = {}
    tol_hit = set()                          # 分差内（含 top1）有组外陪衬字的补放格（`FlowSpec.tolerate_ref_agree`）
    for i, r in enumerate(seq):
        if blocked(r):
            continue
        cands = cands_of(r.id) or []
        ref = (amap.get(r.id) or (None, None))[0]
        e = entry(r, cands, ref, cfg, canon, coord_ref=(veto_refs or {}).get(r.id))
        if e is not None:
            entries[i] = (cands, ref, e)
            f = GROUPS[e[0]].flow
            if e[1] in ("lift", "joint") and f.tolerate_ref_agree and not _rf(e[0], cfg) and cands and any(
                    c in _tol(e[0], cfg) and c not in GROUPS[e[0]].members for c, v in cands if cands[0][1] - v < cfg.delta):
                tol_hit.add(r.id)
    plans = []
    lr = {}                                      # 格 id → (cands, left, right)：文意窗口留着，coord_dissent 时请二审小组确认用

    def panel_ok(g: str, r, ch, trail: list, need_strong: bool = True) -> bool:
        """补放被坐标对位拦（coord_dissent）时：文意字已是二审小组确认的，或是组里 strong 的表答案且小组也确认 → 放行。
        只对声明了 `strong_over_ref` 的组；小组只问这一次（重判结果带 `panel` 留痕，缓存按窗口）。"""
        if not GROUPS[g].flow.strong_over_ref or ch is None:
            return False
        if _ctx_panel(trail, ch):
            return True
        if r.id not in lr or not any(t["solver"] == "ctx" and t["char"] == ch and (t.get("strong") or not need_strong) for t in trail):
            return False
        cands_, left_, right_ = lr[r.id]
        v = _solve("ctx", g, r, cands_, None, cfg, left_, right_, None, force_panel=True)
        if v.char == ch and v.extra.get("strong") and str(v.extra.get("panel") or "").startswith("char"):
            trail.append({"solver": "ctx_panel", "char": ch, "why": "confirmed", "panel": v.extra["panel"]})
            return True
        return False

    wins = {}
    for i, (cands, ref, (g, mode)) in entries.items():
        r = seq[i]
        pos = _pair_pos(entries, i, g)
        if pos is not None:
            ch = GROUPS[g].flow.pair[pos]
            plans.append((r, g, mode, ch, "agree", [{"solver": "ctx", "char": ch, "why": "agree:pair", "via": "ctx:pair"}], ref))
            continue
        need_ctx = ctx_fn is not None and any("ctx" in GROUPS[x].flow.solvers
                                              for x in (g, *(partners(g, cfg.groups) if mode == "joint" else ())))
        need_ctx = need_ctx or bool(ctx_fn is not None and cfg.vis_model and GROUPS[g].flow.vis)
        left, right = (ctx_fn(seq, i, -1), ctx_fn(seq, i, 1)) if need_ctx else (None, None)
        if need_ctx:
            lr[r.id] = (cands, left, right)
        wins[r.id] = (left, right)
        if mode == "joint":
            ch, why, trail = decide_joint(g, r, cands, ref, cfg, left, right, patch_fn)
        else:
            ch, why, trail = decide(g, r, cands, None if _rf(g, cfg) else ref, cfg, left, right, patch_fn,
                                    review=mode == "review",
                                    coord=None if r.id[-1:] in ("a", "b") else (veto_refs or {}).get(r.id))
        if mode == "lift" and ch is None and cfg.joint and any(
                t.get("why") == "abstain:other" and t.get("other_conf") == "high" for t in trail):
            # 本组文意明说「其他」（各遍都 high）：库里分差内没有共字组的字（曰 cov 0、只剩日目），格才进了 rm；
            # 交共字组联合判，给的须是本组外的字（vol13 99:8:18「子女子曰」、vol16 118:5:21「改題曰」，A24 10-26）
            for h in partners(g, cfg.groups):
                hc, hwhy, ht = decide_joint(h, r, cands, ref, cfg, left, right, patch_fn)
                if hc is not None and hc not in GROUPS[g].members:
                    trail = trail + [{"solver": "handoff", "char": None, "why": f"other:{h}"}] + ht
                    g, ch, why = h, hc, hwhy
                    break
        if mode == "lift" and ch is None and why == "abstain" and GROUPS[g].flow.ref_margin:
            # 整理本字：现役对位，缺位时用坐标对位字（vol49 整页对位缺）；夹注半格只有坐标对位不认（列尾切残会对到上一格的字）
            wit = ref or ("" if r.id[-1:] in ("a", "b") else (veto_refs or {}).get(r.id))
            if wit and wit != GAP:
                ch, why, trail = _ref_lowmargin(g, ch, why, trail, wit, cfg.canon or canon)
        if why == "conflict" and (GROUPS[g].flow.ctx_over or GROUPS[g].flow.ctx_over_panel):
            ch, why, trail = _ctx_over(g, ch, why, trail)
        if ch is None and why in ("conflict", "joint") and mode in ("lift", "joint") and g in cfg.ref_pair and not _rf(g, cfg):
            xp = _ref_pair_pick(g, trail, ref, cfg.canon or canon, cfg.ref_pair_margin)
            if xp is not None and g in cfg.ctx_agree and not _ctx_agrees(trail, xp, cfg.canon or canon):
                xp = None
            if xp is not None:
                # 整理本字＝本组解法给的字、反对的只有图像路：取整理本字（留痕 `ref_pair`，A24 Z02）
                ch, why, trail = xp, "agree", trail + [{"solver": "ref_pair", "char": xp, "why": "agree:ref_pair", "witness": ref}]
            elif cfg.ref_pair_coord and why == "joint" and not ref:
                cw = (veto_refs or {}).get(r.id)
                xp = _ref_pair_coord_pick(g, r, trail, cw, cfg.canon or canon)
                if xp is not None:
                    # 现役对位缺、坐标对位字＝本组给的字、搭档只是没表态：取它（留痕 `ref_pair_coord`，A24 Z07）
                    ch, why, trail = xp, "agree", trail + [{"solver": "ref_pair", "char": xp, "why": "agree:ref_pair_coord", "witness": cw}]
        plans.append((r, g, mode, ch, why, trail, ref))
    res = FlowResult(entered=len(plans))
    norm = cfg.canon or canon
    for r, g, mode, ch, why, trail, ref in plans:
        if mode in ("lift", "joint"):
            if (ch is None and why == "abstain" and mode == "lift" and g in cfg.abstain_ref_ok and not _rf(g, cfg)
                    and (fr := ref or (veto_refs or {}).get(r.id))):
                fam = next((x for x in GROUPS[g].flow.families if fr in x), None)
                given = {t["char"] for t in trail if t["char"]}
                if fam and given and given <= set(fam) and any(t["solver"].startswith("form:") for t in trail):
                    # 文意（或字形）定了族、族内刻形拆不开（如 會㑹），整理本是族里一形、没人给族外的字：取整理本形（史記 2026-11-01）
                    ch, why = fr, "agree"
                    trail = trail + [{"solver": "form:ref", "char": fr, "why": "abstain_ref_agree"}]
            needs = GROUPS[g].flow.lift_needs
            if ch is not None and needs and not any(t["solver"] in needs and t["char"] == ch for t in trail) and not (
                    g in cfg.lift_shape_ref and not _rf(g, cfg) and (sr := ref or (veto_refs or {}).get(r.id))
                    and norm(sr) == norm(ch) and all(not t["char"] or t["char"] == ch for t in trail)
                    and _shape_ratio_ok(g, r.id, ch, trail, cfg)):
                ch, why = None, "weak"          # 给字的只有不许单独补放的解法（如入人八字形分类器）
            elif (ch is not None and mode == "lift" and cfg.lift_ref_guard and ref and not _rf(g, cfg)
                  and norm(ref) != norm(ch) and norm(ref) in {norm(m) for m in GROUPS[g].members}
                  and not any(t["solver"] != "ctx" and t["char"] == ch for t in trail)
                  and not (GROUPS[g].flow.strong_over_ref and _ctx_strong(trail, ch))):
                # 只有文意给字、整理本说是组里另一个字：不补放（vol15 118:4:15 面→而）；`strong_over_ref` 的组文意 strong
                # 时照放（日曰：sheldon 10-22「文意置信度特别高可以改掉整理本」，vol22:9:5:19「日者列傳」整理本作曰，A24 10-26）
                ch, why = None, "ref_dissent"
            elif (ch is not None and mode == "lift" and (GROUPS[g].flow.lift_ref_veto or g in cfg.lift_ref_veto)
                  and (vr := (ref or ((veto_refs or {}).get(r.id) if g in cfg.lift_ref_veto else None)))
                  and norm(vr) != norm(ch) and norm(vr) in {norm(m) for m in GROUPS[g].members}):
                ch, why = None, "ref_dissent"   # 一二：整理本说是组里另一个字，字形怎么判都不补放（vol19:116:9:8）
            elif (ch is not None and mode == "lift" and GROUPS[g].flow.lift_img_ref_veto
                  and (ir := ref or (veto_refs or {}).get(r.id)) and norm(ir) != norm(ch)
                  and norm(ir) in {norm(m) for m in GROUPS[g].members}
                  and not any(t["solver"] == "ctx" and t["char"] == ch for t in trail)):
                # 入人八：文意没给字、只有字形给了整理本（现役对位缺格时用坐标对位字）以外的组员，不补放
                # （vol12:147:2:17 入→八、vol28:20:5:4「國家八旗」八→入，A24 10-26）
                ch, why = None, "ref_dissent"
            elif ch is not None and not _rf(g, cfg) and ((mode == "lift" and GROUPS[g].flow.lift_ref_agree) or r.id in tol_hit) and norm(
                    rr := ref or (veto_refs or {}).get(r.id) or "") != norm(ch) and not (
                    not rr and mode == "lift" and GROUPS[g].flow.lift_ref_missing_ctx and r.id not in tol_hit
                    and any(t["solver"] == "ctx" and t["char"] == ch for t in trail)):
                ch, why = None, "ref_dissent" if rr else "ref_missing"   # 部首族／陪衬字挡门：字形与整理本两路一致才补放
                # `lift_ref_missing_ctx`：整理本完全缺位时文意给的字照放（门族辶族，A24 10-28）
            elif (ch is not None and mode == "lift" and cfg.lift_ref_guard and not ref and veto_refs
                  and not _rf(g, cfg) and (cr := veto_refs.get(r.id))
                  and not (cr == GAP and GROUPS[g].flow.solo_margin > 0)
                  and not (g in PROVISIONAL and cr in PROVISIONAL[g].forms)    # 坐标对位是同字的另一写法（蒙𫎇 的 䝉），不算组外字（A24 11-01）
                  and norm(cr) != norm(ch) and norm(cr) not in {norm(m) for m in GROUPS[g].members}
                  and not panel_ok(g, r, ch, trail)):
                ch, why = None, "coord_dissent"   # 坐标对位说是组外另一个字：不补放（vol18 107:6:7 叔→叙）；L3 二审小组确认的文意字照放（A24 11-01）
            elif (ch is not None and mode == "lift" and GROUPS[g].flow.solo_margin > 0 and not ref
                  and (veto_refs or {}).get(r.id) in (None, "", GAP)
                  and not any(t["char"] == ch and (m := _margin(t)) is not None and m >= GROUPS[g].flow.solo_margin
                              for t in trail)):
                # 整理本缺字（〓）或无对位：只凭字形，给字方法每段 margin 都够才补放（彝，A24 10-26）
                ch, why = None, "solo_weak"
            elif (ch is not None and mode == "lift" and cfg.lift_ref_guard and not ref and veto_refs
                  and not _rf(g, cfg) and (cr := veto_refs.get(r.id))
                  and norm(cr) != norm(ch) and norm(cr) in {norm(m) for m in GROUPS[g].members}
                  and not any(t["char"] == ch and (t["solver"] != "ctx" or t.get("strong") or t.get("via") == "ctx:ctx_l1"
                                                   or t.get("runs", 1) >= 2)
                              for t in trail)
                  and not panel_ok(g, r, ch, trail, need_strong=False)):
                # 坐标对位说是组里另一个字、给字的只有单遍文意表：不补放（vol13 63:5:18、vol17 161:8:8、vol19 27:7:9
                # 单遍 haiku 读反，A24 10-24）；文意 strong、两遍以上同字、L1 规则或别的方法同字时照放
                ch, why = None, "coord_dissent"
            if (ch is None and why in ("ref_dissent", "abstain") and mode == "lift" and g in cfg.abstain_ref_ok
                    and GROUPS[g].kind == "variant" and (fr := ref or (veto_refs or {}).get(r.id))
                    and fr in GROUPS[g].members):
                given = {t["char"] for t in trail if t["char"]}
                if given <= set(GROUPS[g].members) and (given or not any(
                        str(t.get("why") or "").startswith("abstain:other") for t in trail)):
                    # 同义异体组：写法本就拆不开（別别 隠隱 之类），书级「按整理本走」→ 取整理本形，留痕方便回查（史記 2026-11-02）。
                    # ref_dissent：方法给了组里另一种写法、与整理本不一；abstain：没有方法给字、整理本字在组内（库首位可以不是它）。
                    # 不同义的形近组不适用；文意明说「其他」的弃权不取。
                    ch, why = fr, "agree"
                    trail = trail + [{"solver": "form:ref", "char": fr,
                                      "why": "ref_dissent_follow" if given else "abstain_ref_follow"}]
            if ch is None and why not in ("weak",):
                vch, vitem = _vis_try(g, r, trail, ref or (veto_refs or {}).get(r.id), cfg, norm, patch_fn, *wins.get(r.id, (None, None)))
                if vitem is not None:
                    trail = trail + [vitem]
                if vch is not None:
                    ch, why = vch, "vis"
            pv = None if ch is not None else _provisional(g, mode, r, cands_of(r.id) or [], ref, (veto_refs or {}).get(r.id), cfg, norm, trail)
            if pv is not None:
                # 暂归一兜底：字认得准、写法拆不开 → 放成这组最常见的字形，留痕记原来没放的原因与证人
                decision, ch = "provisional", pv[0]
                trail = trail + [{"solver": "provisional", "char": ch, "why": f"fallback:{why}", "witness": pv[1]}]
                why = "provisional"
                r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, CHANNEL, "match", []
                res.lifted += 1
            elif ch is not None:
                decision = "admit"
                prov = "context" if any(t["solver"] == "ctx" and t["char"] == ch for t in trail) else "match"
                r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, CHANNEL, prov, []
                res.lifted += 1
            else:
                decision = "review"
                codes = [f"group_flow_{why}"]
                cr = ref or (veto_refs or {}).get(r.id)
                if cr and any(t["solver"].split(":")[-1] == "ctx" and t["char"] and norm(t["char"]) != norm(cr)
                              for t in trail):
                    # 文意（本组或共字组）给了与整理本不同的字却没放成：后面的补放遍不许按整理本字放回
                    # （vol11 18:5:11 顧炎武日知錄、vol15 136:4:14 子曰 被 witness3 按整理本放成曰、目，A24 10-24）
                    codes.append("group_flow_ctx_contra")
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + codes))
        else:
            f = GROUPS[g].flow
            if f.review_weak and (ch != r.char or why == "conflict"):
                strong = {t["char"] for t in trail if t["char"] and t["solver"] not in f.review_weak}
                if strong == {r.char}:
                    # 弱票（入人八随机森林）单独反对、别的方法都支持放行字：不降（A24 10-25）
                    ch, why = r.char, "agree"
                    trail = trail + [{"solver": "review_weak", "char": None, "why": "overruled",
                                      "weak": [t["solver"] for t in trail if t["solver"] in f.review_weak and t["char"]]}]
            fix = f.review_fix or (f.review_fix_strong and why == "agree" and _ctx_strong(trail, ch)) or (
                f.review_fix_ref_rule and why == "agree" and ch is not None
                and (rr := ref or (veto_refs or {}).get(r.id)) and norm(rr) == norm(ch)
                and any(t["solver"] == "ctx" and t["char"] == ch and t.get("via") == "ctx:ctx_l1" for t in trail)) or (
                f.review_fix_margin > 0 and why == "agree" and any(
                    t["char"] == ch and (_margin(t) or 0) >= f.review_fix_margin for t in trail)) or (
                g in cfg.review_fix_agree and why == "agree" and _agree_fix(trail, ch, GROUPS[g].members))
            other = ch is not None and not _same(g, ch, r.char, norm)
            code = ("group_flow_disagree" if (other and not fix) or why == "conflict"
                    else "group_flow_abstain" if why == "abstain" and f.review_abstain else None)
            if (code == "group_flow_abstain" and g in cfg.abstain_ref_ok and not _rf(g, cfg) and r.char
                    and (rr := ref or (veto_refs or {}).get(r.id)) and norm(rr) == norm(r.char)
                    and not any(t["char"] and norm(t["char"]) != norm(r.char) for t in trail)):
                # 解法只是弃权、没人反对，已放行字与整理本同字：照整理本留放（史記 2026-11-01，用户定「按整理本走」）
                code = None
                trail = trail + [{"solver": "ref_ok", "char": r.char, "why": "abstain_ref_agree"}]
            if (code == "group_flow_disagree" and g in cfg.shape_ref_ok and r.char
                    and (rr := ref or (veto_refs or {}).get(r.id)) and norm(rr) == norm(r.char)
                    and (dis := [t for t in trail if t["char"] and norm(t["char"]) != norm(r.char)])
                    and all(t["solver"] == "ids" for t in dis)):
                # 只有字形路 ids 给了别的字（文意没有异议）、已放行字与整理本同字：照整理本留放（史記 2026-11-01，
                # 廣→賔、還→遺 等看图全是整理本对，ids 模板库对写本形不准）
                code, other = None, False
                trail = trail + [{"solver": "ref_ok", "char": r.char, "why": "shape_dissent_ref_agree"}]
            if (code == "group_flow_disagree" and g in cfg.same_writing_keep and r.char and why != "conflict"
                    and (dis := [t["char"] for t in trail if t.get("char") and t["char"] != r.char])
                    and all(_same_writing(c, r.char) for c in dis)):
                # 给别字的解法给的全是放行字的另一写法（暂归一表同组）：同一个字，不降审（A24 Z03 深挖 2026-11-07）
                code, other = None, False
                trail = trail + [{"solver": "same_writing", "char": r.char, "why": "dissent_same_writing"}]
            if (code == "group_flow_disagree" and g in cfg.dissent_keep and not _rf(g, cfg)
                    and _dissent_keep(g, trail, r.char, ref, norm, cfg.dissent_margin, g in cfg.dissent_l1, cfg.dissent_keep_form)
                    and (g not in cfg.ctx_agree or _ctx_agrees(trail, r.char, norm))):
                # 整理本＝放行字、只有弱图像票反对：不降（A24 Z02 深挖 2026-11-06）
                code, other = None, False
                trail = trail + [{"solver": "dissent_keep", "char": r.char, "why": "weak_dissent_ref_agree"}]
            if (f.review_ref_agree and not _rf(g, cfg) and not code and ref and _member(g, ref, norm) and not _same(g, ref, r.char, norm)
                    and not (ch is not None and _same(g, ch, ref, norm))):
                other, code = False, "group_flow_ref_dissent"   # 整理本说是组里另一形、方法没跟上：降审（隸𨽾）
            if code and not (other and fix) and code != "group_flow_ref_dissent":
                vch, vitem = _vis_try(g, r, trail, ref or (veto_refs or {}).get(r.id), cfg, norm, patch_fn, *wins.get(r.id, (None, None)))
                if vitem is not None:
                    trail = trail + [vitem]
                if vch is not None and _same(g, vch, r.char, norm):
                    code, other = None, False            # 图像＋文意 L4 高置信、与放行字同字且有证人：不降审
                elif vch is not None:
                    fix, other, code = True, True, None  # 同上、给了别的字：改字
                    ch = vch
            pv = _provisional(g, mode, r, [], ref, None, cfg, norm, trail) if code and not (other and fix) else None
            if pv is not None:
                # 暂归一兜底：别的通道认了字、组里拆不开写法（判出另一形、弃权、与整理本不一） → 不降审，放成这组最常见的字形
                decision = "provisional"
                trail = trail + [{"solver": "provisional", "char": pv[0], "why": f"fallback:{code[len('group_flow_'):]}",
                                  "witness": pv[1]}]
                if r.char != pv[0]:
                    r.evidence = {**(r.evidence or {}), "fixed_from": {"channel": r.channel, "char": r.char}}
                ch, why = pv[0], "provisional"
                r.char, r.channel, r.provenance = ch, CHANNEL, "match"
            elif other and fix:
                decision = "fix"
                r.evidence = {**(r.evidence or {}), "fixed_from": {"channel": r.channel, "char": r.char}}
                r.char, r.channel, r.provenance = ch, CHANNEL, "context"
                r.doubts = [d for d in (r.doubts or []) if d != "always_review"]
            elif code:
                decision = "demote"
                r.evidence = {**(r.evidence or {}), "demoted_from": {"channel": r.channel, "by": CHANNEL}}
                r.admit, r.channel, r.provenance = False, None, ""
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + [code]))
                res.demoted += 1
            else:
                decision = "keep"
        r.evidence = {**(r.evidence or {}), "group": {"id": g, "mode": mode, "pick": ch, "why": why,
                                                       "decision": decision, "solvers": trail}}
    return res


# —— 文意（离线建表与评测用；管线里走 `methods.CTX` 子数组，两者同一口径）：L1 规则先行，弃权再查 L2 答案表 ——
#    窗口由调用方给（`seed_admit._clf_ctx`，宽 `context.WIDTH`），建表（`research/m7/ctx/l2_make_book.py`）须用同一取法。

_REPO = Path(__file__).resolve().parents[2]
_L1: dict = {}
_L2: dict = {}


def rules_path(group: str) -> Path:
    return _REPO / GROUPS[group].config_dir / "rules.yaml"


def ctx_fingerprint(groups, tables: dict) -> str:
    """规则文件与答案表的内容哈希；换了任何一个，seed_admit 产物判过期。"""
    h = hashlib.sha256()
    for g in sorted(groups):
        p = rules_path(g)
        h.update(g.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest() if p.exists() else b"missing")
        t = tables.get(g)
        h.update(hashlib.sha256(Path(t).read_bytes()).digest() if t and Path(t).exists() else b"-")
    return h.hexdigest()[:16]


def ctx_judge(g: str, cid: str, ref, left: str, right: str, table: str | None,
              canon: Callable[[str], str] | None = None) -> GroupVerdict:
    from .ctx_l1 import CtxL1Backend
    from .ctx_l3 import CtxL3Backend
    from .protocol import JudgeInput, window_from_text
    spec = GROUPS[g]
    cell = JudgeInput(id=cid, ref=ref, window=window_from_text(left, right))
    if g not in _L1:
        _L1[g] = CtxL1Backend(rules_path(g), spec.members)
    v = _L1[g].judge(spec, cell)
    if v.char is not None or not table:
        return v
    if table not in _L2:
        _L2[table] = CtxL3Backend(table)
    v2 = _L2[table].judge(spec, cell, canon)
    v2.extra = {**v2.extra, "l1_why": v.why}
    return v2
