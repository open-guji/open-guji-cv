"""字组统一流程（新 variant-tie，2026-10-18 sheldon 定；方案见 doc/design/M7-字组统一流程-variant-tie改造方案.md）。

只被 `seed_admit` 在开关 `group_flow`（点名组 id）非空时调用，放在所有通道与后处理遍之后；缺省关，关着时本模块不执行。

**进入**（一个字只属一组，`registry` 有不重叠测试）：
- 补放：格没放行、不是人裁、没撞硬护栏；库 top1 cov ≥ `min_cov`，top1 所在组 G 在点名里；与 top1 分差 < `delta` 的
  候选全在 G 里；有整理本对位字时它（或按书级 `codepoints` 归一后）也在 G 里。
- 复核：组声明了 `review`，格已被别的通道放行、放行字在 G 里（人裁位不碰）。

**判**：按组的 `FlowSpec.solvers` 顺序跑解法，`combine=first` 取第一个给字的，`agree` 要求给字的全一致。
- 补放：有字 → 放行（通道 `group_flow`）；无字或冲突 → 留人审，疑问码 `group_flow_abstain`／`group_flow_conflict`；
  组声明了 `lift_needs` 而给字的解法里没有它们 → 留人审（`group_flow_weak`）。
- 复核：给了与放行字不同的字、或解法之间不一致 → 降为人审（`group_flow_disagree`，不改字）；组声明了
  `review_fix` 时前者改成解法的字（通道 `group_flow`，`evidence.fixed_from` 记原通道与原字）；声明了
  `review_abstain` 时解法全弃权也降（`group_flow_abstain`）；其余不动。

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
    freq_vols: dict = field(default_factory=dict)      # 组 id → {成员: 人裁册数}（`freq.load_vols`）
    freq_min_vols: int = _freq.MIN_VOLS
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
        if set(f.lift_needs) - set(f.solvers):
            raise ValueError(f"group_flow：字组 {g!r} 的 lift_needs {f.lift_needs} 不在它的解法里")
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
        return _freq.decide(cfg.freq_table.get(g), spec.members, cfg.freq_major,
                            cfg.freq_vols.get(g), cfg.freq_min_vols)
    if name == "ids":
        # 方案 S7：有在线判法与模板库的组（`ids_online.SPECS`）才取图判；其余弃权，且不去取图
        from . import ids_online
        if not ids_online.has_bank(g):
            return GroupVerdict(None, why="abstain:no_bank", via="ids")
        return ids_online.judge(g, patch_fn(r.id) if patch_fn is not None else None)
    if name == "top1":
        if not cands:
            return GroupVerdict(None, why="abstain:no_cands", via="top1")
        top, c1 = cands[0]
        if c1 >= cfg.top1_cov and top in spec.members:
            return GroupVerdict(top, conf=c1, why="agree", via="top1", extra={"cov": c1})
        return GroupVerdict(None, conf=c1, why="abstain:low_cov", via="top1", extra={"cov": c1})
    if name == "ctx":
        v = ctx_judge(g, r.id, ref, left or "", right or "", cfg.l2_tables.get(g))
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
            needs = GROUPS[g].flow.lift_needs
            if ch is not None and needs and not any(t["solver"] in needs and t["char"] == ch for t in trail):
                ch, why = None, "weak"          # 给字的只有不许单独补放的解法（如入人八字形分类器）
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
            code = ("group_flow_disagree" if (ch is not None and ch != r.char and not f.review_fix) or why == "conflict"
                    else "group_flow_abstain" if why == "abstain" and f.review_abstain else None)
            if ch is not None and ch != r.char and f.review_fix:
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


# —— 文意解法 `ctx`：L1 规则先行，弃权再查 L2 答案表（原 `groups/m7_pass.py`，2026-10-18 S6 挪来） ——
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


def ctx_judge(g: str, cid: str, ref, left: str, right: str, table: str | None) -> GroupVerdict:
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
    v2 = _L2[table].judge(spec, cell)
    v2.extra = {**v2.extra, "l1_why": v.why}
    return v2
