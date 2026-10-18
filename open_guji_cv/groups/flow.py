"""字组统一流程（新 variant-tie，2026-10-18 sheldon 定；方案见 doc/design/M7-字组统一流程-variant-tie改造方案.md）。

只被 `seed_admit` 在开关 `group_flow`（点名组 id）非空时调用，放在所有通道与后处理遍之后；缺省关，关着时本模块不执行。

**进入**（一个字只属一组，`registry` 有不重叠测试）：
- 补放：格没放行、不是人裁、没撞硬护栏；库 top1 cov ≥ `min_cov`，top1 所在组 G 在点名里；与 top1 分差 < `delta` 的
  候选全在 G 里；有整理本对位字时它（或按书级 `codepoints` 归一后）也在 G 里。
- 复核：组声明了 `review`，格已被别的通道放行、放行字在 G 里（人裁位不碰）。

**判**：按组的 `FlowSpec.solvers` 顺序跑解法，`combine=first` 取第一个给字的，`agree` 要求给字的全一致。
- 补放：有字 → 放行（通道 `group_flow`）；无字或冲突 → 留人审，疑问码 `group_flow_abstain`／`group_flow_conflict`。
- 复核：给了与放行字不同的字 → 降为人审（`group_flow_disagree`，不改字）；一致或弃权 → 不动。

每个进了流程的格都写 `evidence.group`：组、入口、每个解法的给字与理由、最终结论。

判格在前、改格在后：先用遍前状态给所有格算好结论，再逐格执行，前一格改字不污染后一格的窗口。
分层同 `groups` 包：只 import L0／L1。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import freq as _freq
from .protocol import GroupVerdict
from .registry import GROUPS

SOLVERS = frozenset({"freq", "ids", "top1", "ctx", "bars", "rr_img"})
CHANNEL = "group_flow"


@dataclass
class FlowConfig:
    groups: tuple
    delta: float = 0.03
    min_cov: float = 0.85
    top1_cov: float = 0.97
    freq_table: dict = field(default_factory=dict)     # 组 id → {成员: 人裁刻形数}（`freq.load`）
    freq_major: int = _freq.MAJOR
    l2_tables: dict = field(default_factory=dict)      # 组 id → 上下文 L2 答案表路径
    rr_model: str | None = None
    rr_p: float = 0.5


@dataclass
class FlowResult:
    lifted: int = 0
    demoted: int = 0
    entered: int = 0


def check_groups(groups) -> None:
    """点名的组必须已登记且声明了 `flow`，解法名必须认得。"""
    for g in groups:
        if g not in GROUPS:
            raise ValueError(f"group_flow：未登记的字组 {g!r}")
        f = GROUPS[g].flow
        if f is None:
            raise ValueError(f"group_flow：字组 {g!r} 没有声明 flow（registry.GroupSpec.flow）")
        bad = set(f.solvers) - SOLVERS
        if bad:
            raise ValueError(f"group_flow：字组 {g!r} 的解法 {sorted(bad)} 不认得")
        if f.combine not in ("first", "agree"):
            raise ValueError(f"group_flow：字组 {g!r} 的 combine={f.combine!r} 只能是 first/agree")


def group_of(ch: str | None, groups) -> str | None:
    if not ch:
        return None
    for g in groups:
        if ch in GROUPS[g].members:
            return g
    return None


def entry(r, cands, ref, cfg: FlowConfig, canon: Callable[[str], str] = lambda c: c) -> tuple[str, str] | None:
    """→ (组 id, "lift"|"review") 或 None。`r` 是放行记录（id/char/admit/channel/provenance）；硬护栏由调用方先筛。"""
    if r.provenance == "human" or r.channel in ("human", CHANNEL):
        return None
    if r.admit:
        g = group_of(r.char, cfg.groups)
        return (g, "review") if g and GROUPS[g].flow.review else None
    if not cands:
        return None
    top, c1 = cands[0]
    if c1 < cfg.min_cov:
        return None
    g = group_of(top, cfg.groups)
    if g is None:
        return None
    mem = GROUPS[g].members
    if not all(c in mem for c, v in cands[1:] if c1 - v < cfg.delta):
        return None
    if ref and ref not in mem and canon(ref) not in mem:
        return None
    return g, "lift"


def _solve(name: str, g: str, r, cands, ref, cfg: FlowConfig, left: str | None, right: str | None,
           patch_fn) -> GroupVerdict:
    spec = GROUPS[g]
    if name == "freq":
        return _freq.decide(cfg.freq_table.get(g), spec.members, cfg.freq_major)
    if name == "ids":
        return GroupVerdict(None, why="abstain:offline_only", via="ids")   # IDS 还没有在线入口（方案 S7）
    if name == "top1":
        if not cands:
            return GroupVerdict(None, why="abstain:no_cands", via="top1")
        top, c1 = cands[0]
        if c1 >= cfg.top1_cov and top in spec.members:
            return GroupVerdict(top, conf=c1, why="agree", via="top1", extra={"cov": c1})
        return GroupVerdict(None, conf=c1, why="abstain:low_cov", via="top1", extra={"cov": c1})
    if name == "ctx":
        from .m7_pass import judge
        v = judge(g, r.id, ref, left or "", right or "", cfg.l2_tables.get(g))
        return GroupVerdict(v.char, conf=v.conf, why=v.why, via=f"ctx:{v.via}" if v.via else "ctx",
                            extra={"rules": v.extra.get("rules")} if v.extra.get("rules") else {})
    img = patch_fn(r.id) if patch_fn is not None else None
    if img is None:
        return GroupVerdict(None, why="abstain:no_patch", via=name)
    if name == "bars":
        from .bars import BarsImageBackend
        from .protocol import JudgeInput, window_from_text
        v = BarsImageBackend().judge(spec, JudgeInput(id=r.id, ref=ref, window=window_from_text("", ""),
                                                      patch=lambda: img))
        return GroupVerdict(v.char, conf=v.conf, why=v.why, via="bars", extra={"ratio": v.extra.get("ratio")})
    if name == "rr_img":
        from ..utils import rr_clf
        c = rr_clf.classify(img, cfg.rr_model or None, cfg.rr_p)
        pick = c.get("pick")
        return GroupVerdict(pick if pick in spec.members else None, conf=c.get("p"),
                            why="agree" if pick in spec.members else "abstain:rr_clf", via="rr_img",
                            extra={"probs": c.get("probs")})
    raise ValueError(f"group_flow：解法 {name!r} 不认得")


def decide(g: str, r, cands, ref, cfg: FlowConfig, left=None, right=None, patch_fn=None) -> tuple[str | None, str, list]:
    """跑组内解法 → (字或 None, 原因 "agree"|"abstain"|"conflict", 每个解法的留痕)。"""
    f = GROUPS[g].flow
    trail: list[dict] = []
    picks: list[str] = []
    for name in f.solvers:
        v = _solve(name, g, r, cands, ref, cfg, left, right, patch_fn)
        trail.append({"solver": name, "char": v.char, "why": v.why, **({"via": v.via} if v.via != name else {}),
                      **v.extra})
        if v.char is not None:
            picks.append(v.char)
            if f.combine == "first":
                break
    if not picks:
        return None, "abstain", trail
    if len(set(picks)) > 1:
        return None, "conflict", trail
    return picks[0], "agree", trail


def group_flow_pass(seq: list, amap: dict, cands_of: Callable[[str], list], blocked: Callable[[object], bool],
                    cfg: FlowConfig, ctx_fn: Callable[[list, int, int], str] | None = None,
                    patch_fn: Callable[[str], object] | None = None,
                    canon: Callable[[str], str] = lambda c: c) -> FlowResult:
    """`seq`：本页读序展平的放行记录；`amap`：{id: (整理本字, op)}；`cands_of(id)`：库候选 [(字, cov)]；
    `blocked(r)`：硬护栏（遮挡、超时、排除、非字…），True 的格不进流程。就地改 `seq` 里的记录。"""
    plans = []
    for i, r in enumerate(seq):
        if blocked(r):
            continue
        cands = cands_of(r.id) or []
        ref = (amap.get(r.id) or (None, None))[0]
        e = entry(r, cands, ref, cfg, canon)
        if e is None:
            continue
        g, mode = e
        need_ctx = "ctx" in GROUPS[g].flow.solvers and ctx_fn is not None
        left, right = (ctx_fn(seq, i, -1), ctx_fn(seq, i, 1)) if need_ctx else (None, None)
        ch, why, trail = decide(g, r, cands, ref, cfg, left, right, patch_fn)
        plans.append((r, g, mode, ch, why, trail))
    res = FlowResult(entered=len(plans))
    for r, g, mode, ch, why, trail in plans:
        if mode == "lift":
            if ch is not None:
                decision = "admit"
                prov = "context" if any(t["solver"] == "ctx" and t["char"] == ch for t in trail) else "match"
                r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, CHANNEL, prov, []
                res.lifted += 1
            else:
                decision = "review"
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + [f"group_flow_{why}"]))
        else:
            if ch is not None and ch != r.char:
                decision = "demote"
                r.evidence = {**(r.evidence or {}), "demoted_from": {"channel": r.channel, "by": CHANNEL}}
                r.admit, r.channel, r.provenance = False, None, ""
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + ["group_flow_disagree"]))
                res.demoted += 1
            else:
                decision = "keep"
        r.evidence = {**(r.evidence or {}), "group": {"id": g, "mode": mode, "pick": ch, "why": why,
                                                       "decision": decision, "solvers": trail}}
    return res
