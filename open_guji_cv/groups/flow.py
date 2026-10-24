"""字组统一流程（新 variant-tie，2026-10-18 sheldon 定；方案见 doc/design/M7-字组统一流程-variant-tie改造方案.md）。

只被 `seed_admit` 在开关 `group_flow`（点名组 id）非空时调用，放在所有通道与后处理遍之后；缺省关，关着时本模块不执行。

**进入**（一个字只属一组，`registry` 有不重叠测试）：
- 补放：格没放行、不是人裁、没撞硬护栏；库 top1 cov ≥ `min_cov`，top1 所在组 G 在点名里；与 top1 分差 < `delta` 的
  候选全在 G 里（或在 G 的 `FlowSpec.tolerate` 里）；有整理本对位字时它（或按书级 `codepoints` 归一后）也在 G 里。
- 复核：组声明了 `review`，格已被别的通道放行、放行字在 G 里（人裁位不碰）。

**判**：按组的方法数组（`FlowSpec.methods`，方法见 `groups/methods.py`）依次跑，`combine=first` 遇到第一个放行的就停，
`agree` 全跑、给字的须全一致（下文「解法」即方法）。
- 补放：有字 → 放行（通道 `group_flow`）；无字或冲突 → 留人审，疑问码 `group_flow_abstain`／`group_flow_conflict`；
  组声明了 `lift_needs` 而给字的解法里没有它们 → 留人审（`group_flow_weak`）。
- 复核（组声明了 `review_methods` 就改跑它，依次试）：给了与放行字不同的字、或解法之间不一致 → 降为人审（`group_flow_disagree`，不改字）；组声明了
  `review_fix` 时前者改成解法的字（通道 `group_flow`，`evidence.fixed_from` 记原通道与原字）；声明了
  `review_abstain` 时解法全弃权也降（`group_flow_abstain`）；其余不动。

- 复核时组声明了 `review_fix_strong`：文意答案 strong（L2 表多遍都 high 同字）且方法之间一致 → 照 `review_fix` 改字，否则照常降审。
- 组声明了 `pair`（己已巳：干支「己巳」）：读序紧挨的两格都进了本组 → 前一格给 `pair[0]`、后一格给 `pair[1]`，不跑方法
  （留痕 `ctx:pair`）；三格以上连着照常跑方法。

每个进了流程的格都写 `evidence.group`：组、入口、每个解法的给字与理由、最终结论。

判格在前、改格在后：先用遍前状态给所有格算好结论，再逐格执行，前一格改字不污染后一格的窗口。
分层同 `groups` 包：只 import L0／L1。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import freq as _freq
from .methods import KINDS, Method, MethodInput
from .protocol import GroupVerdict
from .registry import FLOW_GROUPS as GROUPS   # 含码位归一组（`registry.CODEPOINT_GROUPS`）

CHANNEL = "group_flow"


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
    l2_tables: dict = field(default_factory=dict)      # 组 id → 上下文 L2 答案表路径
    canon: Callable[[str], str] | None = None          # 书级码位归一（L2 表键按它归一再比；None＝逐字比）
    l2_drift: int = 0                                  # L2 表键容许远处差几个字位（`ctx_l2.ctx_drift`；0＝逐字比）
    joint: bool = False                                # 共字组联合补放（`entry` 的 "joint"，见 `decide_joint`）
    rr_model: str | None = None
    rr_p: float = 0.5
    lift_ref_guard: bool = True                        # 补放与整理本互证（`group_flow_pass`，seed_admit `group_flow_lift_ref_guard`）


@dataclass
class FlowResult:
    lifted: int = 0
    demoted: int = 0
    entered: int = 0


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


def entry(r, cands, ref, cfg: FlowConfig, canon: Callable[[str], str] = lambda c: c) -> tuple[str, str] | None:
    """→ (组 id, "lift"|"review") 或 None。`r` 是放行记录（id/char/admit/channel/provenance）；硬护栏由调用方先筛。

    一个字属于多个组（`overlaps`）时：补放选第一个能把「分差内全部候选＋整理本字」都装下的组，复核选第一个
    声明了 `review` 且装得下整理本字的组。哪一组都装不下、但装得下「组＋它的共字组」（日曰目紧咬：ry＋rm）时，
    `cfg.joint` 开着 → (组, "joint")，由 `decide_joint` 判。"""
    if r.provenance == "human" or r.channel in ("human", CHANNEL):
        return None
    if r.admit:
        gs = [g for g in groups_in(r.char, cfg.groups) if GROUPS[g].flow.review]
        for g in gs:
            mem = GROUPS[g].members
            if GROUPS[g].ref_free or not ref or ref in mem or canon(ref) in mem:
                return g, "review"
        return None
    if not cands:
        return None
    top, c1 = cands[0]
    if c1 < cfg.min_cov:
        return None
    for g in groups_in(top, cfg.groups):
        mem = GROUPS[g].members
        if not all(c in mem or c in GROUPS[g].flow.tolerate for c, v in cands[1:] if c1 - v < cfg.delta):
            continue
        if not GROUPS[g].ref_free and ref and ref not in mem and canon(ref) not in mem:
            continue
        return g, "lift"
    if cfg.joint:
        for g in groups_in(top, cfg.groups):
            parts = partners(g, cfg.groups)
            if not parts:
                continue
            mem = GROUPS[g].members.union(*(GROUPS[h].members for h in parts))
            tol = GROUPS[g].flow.tolerate
            if not all(c in mem or c in tol for c, v in cands[1:] if c1 - v < cfg.delta):
                continue
            if ref and ref not in mem and canon(ref) not in mem:
                continue
            return g, "joint"
    return None


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
           patch_fn, members=None, form: bool = False, review: bool = False) -> GroupVerdict:
    """跑组 `g` 方法数组里名叫 `name` 的方法（`groups.methods`）。`members` 给了就只在这些字里选（两段判第二段＝族）。"""
    inp = MethodInput(group=g, members=frozenset(members if members is not None else GROUPS[g].members),
                      cell_id=r.id, cands=cands, ref=ref, cfg=cfg, left=left, right=right, patch_fn=patch_fn)
    return _method(g, name, form, review).run(inp)


def decide(g: str, r, cands, ref, cfg: FlowConfig, left=None, right=None, patch_fn=None,
           review: bool = False) -> tuple[str | None, str, list]:
    """依次跑组的方法数组 → (字或 None, 原因 "agree"|"abstain"|"conflict", 每个方法的留痕)。
    `review` 且组声明了 `review_methods`：改跑复核数组，第一个给字的说了算。"""
    f = GROUPS[g].flow
    alt = review and bool(f.review_methods)
    trail: list[dict] = []
    picks: list[str] = []
    for name in (f.review_solvers if alt else f.solvers):
        v = _solve(name, g, r, cands, ref, cfg, left, right, patch_fn, review=alt)
        trail.append({"solver": name, "char": v.char, "why": v.why, **({"via": v.via} if v.via != name else {}),
                      **v.extra})
        if v.char is not None:
            picks.append(v.char)
            if f.combine == "first" or alt:
                break
    if not picks:
        return None, "abstain", trail
    if len(set(picks)) > 1:
        return None, "conflict", trail
    if f.families:
        return _pick_form(g, picks[0], r, cands, cfg, patch_fn, trail)
    return picks[0], "agree", trail


def decide_joint(g: str, r, cands, ref, cfg: FlowConfig, left=None, right=None, patch_fn=None) -> tuple[str | None, str, list]:
    """共字组联合判（日曰目三字紧咬，哪一组都装不下；sheldon 10-22「目是真竞争者，不能当陪衬」）：
    先由组 `g` 定字 X，再问每个共字组 h——X 是 h 的成员：h 也须给 X；X 不是 h 的成员：h 须明确说「其他」
    （文意 L2 表 `abstain:other` 且各遍都是 high，即「h 的字放进去都不通」）。任一共字组弃权、给了别的字 → 待定（"joint"）。
    例：ry 说曰、rm 说其他 → 曰；ry 说日、rm 说日 → 日；rm 没表态 → 留人审。共字组的留痕名前加「组 id:」。"""
    ch, why, trail = decide(g, r, cands, None if GROUPS[g].ref_free else ref, cfg, left, right, patch_fn)
    if ch is None:
        return None, why, trail
    for h in partners(g, cfg.groups):
        hc, _, ht = decide(h, r, cands, None if GROUPS[h].ref_free else ref, cfg, left, right, patch_fn)
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


def group_flow_pass(seq: list, amap: dict, cands_of: Callable[[str], list], blocked: Callable[[object], bool],
                    cfg: FlowConfig, ctx_fn: Callable[[list, int, int], str] | None = None,
                    patch_fn: Callable[[str], object] | None = None,
                    canon: Callable[[str], str] = lambda c: c,
                    veto_refs: dict[str, str] | None = None) -> FlowResult:
    """`seq`：本页读序展平的放行记录；`amap`：{id: (整理本字, op)}；`cands_of(id)`：库候选 [(字, cov)]；
    `blocked(r)`：硬护栏（遮挡、超时、排除、非字…），True 的格不进流程。就地改 `seq` 里的记录。
    `veto_refs`：{id: 坐标对位字}，只在现役对位缺这一格时用来拦补放（`cfg.lift_ref_guard`），不参与判字。"""
    entries = {}
    for i, r in enumerate(seq):
        if blocked(r):
            continue
        cands = cands_of(r.id) or []
        ref = (amap.get(r.id) or (None, None))[0]
        e = entry(r, cands, ref, cfg, canon)
        if e is not None:
            entries[i] = (cands, ref, e)
    plans = []
    for i, (cands, ref, (g, mode)) in entries.items():
        r = seq[i]
        pos = _pair_pos(entries, i, g)
        if pos is not None:
            ch = GROUPS[g].flow.pair[pos]
            plans.append((r, g, mode, ch, "agree", [{"solver": "ctx", "char": ch, "why": "agree:pair", "via": "ctx:pair"}], ref))
            continue
        need_ctx = ctx_fn is not None and any("ctx" in GROUPS[x].flow.solvers
                                              for x in (g, *(partners(g, cfg.groups) if mode == "joint" else ())))
        left, right = (ctx_fn(seq, i, -1), ctx_fn(seq, i, 1)) if need_ctx else (None, None)
        if mode == "joint":
            ch, why, trail = decide_joint(g, r, cands, ref, cfg, left, right, patch_fn)
        else:
            ch, why, trail = decide(g, r, cands, None if GROUPS[g].ref_free else ref, cfg, left, right, patch_fn,
                                    review=mode == "review")
        plans.append((r, g, mode, ch, why, trail, ref))
    res = FlowResult(entered=len(plans))
    norm = cfg.canon or canon
    for r, g, mode, ch, why, trail, ref in plans:
        if mode in ("lift", "joint"):
            needs = GROUPS[g].flow.lift_needs
            if ch is not None and needs and not any(t["solver"] in needs and t["char"] == ch for t in trail):
                ch, why = None, "weak"          # 给字的只有不许单独补放的解法（如入人八字形分类器）
            elif (ch is not None and mode == "lift" and cfg.lift_ref_guard and ref and not GROUPS[g].ref_free
                  and norm(ref) != norm(ch) and norm(ref) in {norm(m) for m in GROUPS[g].members}
                  and not any(t["solver"] != "ctx" and t["char"] == ch for t in trail)):
                ch, why = None, "ref_dissent"   # 只有文意给字、整理本说是组里另一个字：不补放（vol15 118:4:15 面→而）
            elif (ch is not None and mode == "lift" and cfg.lift_ref_guard and not ref and veto_refs
                  and not GROUPS[g].ref_free and (cr := veto_refs.get(r.id))
                  and norm(cr) != norm(ch) and norm(cr) not in {norm(m) for m in GROUPS[g].members}):
                ch, why = None, "coord_dissent"   # 坐标对位说是组外另一个字：不补放（vol18 107:6:7 叔→叙）
            if ch is not None:
                decision = "admit"
                prov = "context" if any(t["solver"] == "ctx" and t["char"] == ch for t in trail) else "match"
                r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, CHANNEL, prov, []
                res.lifted += 1
            else:
                decision = "review"
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + [f"group_flow_{why}"]))
        else:
            f = GROUPS[g].flow
            fix = f.review_fix or (f.review_fix_strong and why == "agree" and any(
                t["solver"] == "ctx" and t["char"] == ch and t.get("strong") for t in trail))
            code = ("group_flow_disagree" if (ch is not None and ch != r.char and not fix) or why == "conflict"
                    else "group_flow_abstain" if why == "abstain" and f.review_abstain else None)
            if ch is not None and ch != r.char and fix:
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
    from .ctx_l2 import CtxL2Backend
    from .protocol import JudgeInput, window_from_text
    spec = GROUPS[g]
    cell = JudgeInput(id=cid, ref=ref, window=window_from_text(left, right))
    if g not in _L1:
        _L1[g] = CtxL1Backend(rules_path(g), spec.members)
    v = _L1[g].judge(spec, cell)
    if v.char is not None or not table:
        return v
    if table not in _L2:
        _L2[table] = CtxL2Backend(table)
    v2 = _L2[table].judge(spec, cell, canon)
    v2.extra = {**v2.extra, "l1_why": v.why}
    return v2
