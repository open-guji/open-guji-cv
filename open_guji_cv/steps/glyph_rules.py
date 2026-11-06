"""Step5-a 判决规则表：5a 一格从「查库」到「落判决」要过的每一条规则，按执行顺序登记在 `RULES`。

2026-11-06（Sheldon：「把几条规则是个什么顺序、都有哪些参数抽象出来，做成一个框架，方便后面加规则、改参数」）。

## 两层

- **匹配器层**（`Stage.MATCHER`）：`clustering.match.GlyphMatcher` 与它外面包的几层
  （`_FontTier`、`_with_same_gate`、近形决胜）。这层规则在算法里，表里只登记**顺序、参数、实现在哪**，
  不搬代码——匹配器另有金标与负结果记录，一行没动。
- **判决层**（`Stage.STEP`）：匹配器给出 `MatchResult` 之后，Step5-a 在格上再改判的几条
  （借库降档、共识升档、近形升档）。这层规则就是本模块的函数，`decide()` 按 `RULES` 的顺序逐条执行，
  `steps.glyph_match` 只调 `decide()`，不再内联判决逻辑。

## 每条规则登记什么（`RuleSpec`）

| 字段 | 意思 |
|---|---|
| `id` | 规则枚举 `Rule`（值＝规则 id，`.label`＝一两个英文词的短名，见 `RULE_LABELS`）；产物 `MatchRec.via` 的前缀与它对应（`borrowed:` / `consensus:` / `near_shape:`） |
| `stage`、`order` | 哪一层、第几步（同层按 order 执行） |
| `params` | 管这条规则的 `GlyphMatchParams` 字段（册 yaml `params: {glyph_match: {...}}` 改） |
| `constants` | 写死在代码里的常数（改它＝改算法，产物过期） |
| `impl` | 实现在哪（匹配器层）；判决层是 `apply` 函数本身 |
| `apply` | 判决层的规则函数 `(m, d, state) -> Decision`；不适用就原样返回 `d` |

## 加一条判决层规则

1. 写函数 `rule_xxx(m, d, state) -> Decision`：`m` 是匹配器结果（只读），`d` 是前面规则改过的判决，
   `state` 是本页共用的东西（参数、人裁例数、借库 id、近形配置）。不适用就 `return d`。
2. 在 `GlyphMatchParams` 加开关（缺省关），并在它的 `_drop_unset_near_shape` 里让缺省值不进 dump——
   否则参数哈希变，全部现役产物判过期。
3. 在 `Rule` 加一个成员、在 `RULE_LABELS` 配一两个英文词的短名（改判有新通道的再在 `Via` 加前缀），
   在 `RULES` 里按位置插一条 `RuleSpec`（写清 params / via / summary）。
4. `tests/test_glyph_rules.py` 守着：判决层 `apply` 的 order 单调、登记的参数都在 `GlyphMatchParams` 里。
   文档表格用 `python -m open_guji_cv.steps.glyph_rules` 生成（`rules_markdown()`），贴进
   `doc/design/5a规则框架.md`。

## 判决层的不变式（现行三条都守）

- 只改 `unsure` 档；匹配器判了护栏（`m.guard` 非空：never_match / conflict）的格不动（超时格不进判决层）；
- 借库降档降下来的格（`d.lent`）后面的升档一律不碰——它们看的 cov 正是借来的条目给的；
- 每次改判都写 `via`，出了错能按通道归因。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Callable


# ───────────────────────── 判决层用到的判据（原在 steps.glyph_match，逻辑未动） ─────────────────────────

_FAMILY: list = []


def _family_chars() -> frozenset[str]:
    """`font_tier.family` 拦的字：字组成员 ∪ 形近护栏表里有对手的字。"""
    if not _FAMILY:
        from ..clustering.match import _PARTNER
        from ..groups.registry import GROUPS
        _FAMILY.append(frozenset().union(*(g.members for g in GROUPS.values()))
                       | frozenset(c for c, v in _PARTNER.items() if v))
    return _FAMILY[0]


def demote_borrowed(m, borrowed: frozenset[str]):
    """借来的条目判的 same 降一档（见 `steps.glyph_match` 模块头）。返回 (verdict, char, matched_id, cov, wmax, borrowed_id)：
    `borrowed_id` 非空＝降了档。不是 same、没借库、命中的是本书条目时原样返回。"""
    if m.verdict != "same" or not borrowed or m.matched_id not in borrowed:
        return m.verdict, m.char, m.matched_id, m.cov, m.wmax, None
    for iid, cov, wmax in getattr(m, "same_hits", ()) or ():
        if iid not in borrowed:                     # 本书也有条目判 same：本书优先
            return "same", m.char, iid, cov, wmax, None
    return "unsure", None, None, m.cov, m.wmax, m.matched_id


def consensus_same(candidates, n_confirmed_of, cov_min: float, margin_min: float,
                   min_confirmed: int, blocked=None) -> tuple[str, int] | None:
    """unsure 档能不能按「共识」升成 same：返回 (字, 该字人裁例数) 或 None。

    三条件缺一不可（标定见 `steps.glyph_match` 模块头）：top 候选 cov ≥ cov_min；比次优**异字**高 ≥ margin_min
    （次优同字不算——同一字的多个刻例挨着很正常）；top 字已有 ≥ min_confirmed 例人裁。
    没有异字候选时，差距按 0.85（unsure 档下界）算。
    `blocked(首位字, 异字) -> bool`（可选，`consensus_family_guard`）：候选里任一异字与首位字被它判为形近
    （同字组或互为形近对手）就不升；先以 `blocked(首位字, None)` 问一次首位字本身挡不挡（`top` 档用）。
    """
    if min_confirmed <= 0 or not candidates:
        return None
    top, cov = candidates[0]
    if cov < cov_min:
        return None
    nxt = next((v for c, v in candidates[1:] if c != top), None)
    if cov - (nxt if nxt is not None else 0.85) < margin_min:
        return None
    n = int(n_confirmed_of(top) or 0)
    if n < min_confirmed:
        return None
    if blocked is not None and (blocked(top, None)
                                or any(c != top and blocked(top, c) for c, _ in candidates[1:])):
        return None
    return top, n


def family_blocked(a: str, b: str | None) -> bool:
    """`consensus_family_guard: rival` 用：两字同在一个字组，或在形近护栏表里互为对手。"""
    if b is None:
        return False
    from ..clustering.match import _PARTNER
    if b in _PARTNER.get(a, ()) or a in _PARTNER.get(b, ()):
        return True
    from ..groups.registry import GROUPS
    return any(a in g.members and b in g.members for g in GROUPS.values())


def family_top_blocked(a: str, b: str | None) -> bool:
    """`consensus_family_guard: top`：首位字本身在字组或形近护栏表里就挡（`b` 不看）。"""
    return a in _family_chars()


CONSENSUS_GUARDS: dict[str, Callable] = {"rival": family_blocked, "top": family_top_blocked}


# ───────────────────────── 规则、层、通道的枚举（Sheldon 11-06：规则都定义成 enum，各配一两个英文词的短名，方便引用） ─────────────────────────

class Stage(StrEnum):
    MATCHER = "matcher"     # 匹配器层（clustering.match 及外面几层包装）
    STEP = "step"           # 判决层（本模块，decide() 执行）


class Rule(StrEnum):
    """5a 的每一条规则。值是规则 id（文档、日志里引用用它），`label` 是一两个英文词的短名。"""
    NORMALIZE = "normalize"
    FONT_TIER = "font_tier"
    KNN = "knn"
    EXCLUDE_SELF = "exclude_self"
    ELASTIC_VERIFY = "elastic_verify"
    GUARD_CONFLICT = "guard_conflict"
    GUARD_NEVER_MATCH = "guard_never_match"
    SHAPE_PAIR_RERANK = "shape_pair_rerank"
    NEAR_SHAPE_DECIDE = "near_shape_decide"
    BORROWED_DEMOTE = "borrowed_demote"
    CONSENSUS = "consensus"
    NEAR_SHAPE_PROMOTE = "near_shape_promote"

    @property
    def label(self) -> str:
        return RULE_LABELS[self]


RULE_LABELS: dict[Rule, str] = {
    Rule.NORMALIZE: "Normalize",
    Rule.FONT_TIER: "Font tier",
    Rule.KNN: "kNN",
    Rule.EXCLUDE_SELF: "Exclude self",
    Rule.ELASTIC_VERIFY: "Elastic verify",
    Rule.GUARD_CONFLICT: "Conflict guard",
    Rule.GUARD_NEVER_MATCH: "Never-match guard",
    Rule.SHAPE_PAIR_RERANK: "Pair rerank",
    Rule.NEAR_SHAPE_DECIDE: "Near-shape",
    Rule.BORROWED_DEMOTE: "Borrow demote",
    Rule.CONSENSUS: "Consensus",
    Rule.NEAR_SHAPE_PROMOTE: "Near-shape promote",
}


class Via(StrEnum):
    """产物 `MatchRec.via` 的前缀（判决层改判的通道）。值是落盘的字符串，不能改。"""
    BORROWED = "borrowed"
    CONSENSUS = "consensus"
    NEAR_SHAPE = "near_shape"


# ───────────────────────── 框架 ─────────────────────────

@dataclass(frozen=True)
class Decision:
    """一格的判决（判决层逐条改写它）。`lent` 非空＝借库降档降下来的（后面的升档不碰）。"""
    verdict: str
    char: str | None
    matched_id: str | None
    cov: float
    wmax: float
    via: str | None = None
    lent: str | None = None


@dataclass
class StepState:
    """判决层规则一页里共用的东西（`GlyphMatchStep.run_page` 建一次）。"""
    params: object                      # GlyphMatchParams
    confirmed: dict = field(default_factory=dict)   # 字 → 人裁例数（consensus_count 口径）
    borrowed: frozenset = frozenset()   # 借来的库条目 id
    near_shape_cfg: object = None       # NearShapeConfig | None


def _promotable(m, d: Decision) -> bool:
    """升档类规则的共同前提：unsure、匹配器没判护栏、不是借库降下来的。"""
    return d.verdict == "unsure" and m.guard is None and not d.lent


def rule_borrowed_demote(m, d: Decision, s: StepState) -> Decision:
    verdict, char, matched_id, cov, wmax, lent = demote_borrowed(m, s.borrowed)
    return replace(d, verdict=verdict, char=char, matched_id=matched_id, cov=cov, wmax=wmax,
                   via=(f"{Via.BORROWED.value}:{lent}" if lent else d.via), lent=lent)


def rule_consensus(m, d: Decision, s: StepState) -> Decision:
    if not _promotable(m, d):
        return d
    p = s.params
    hit = consensus_same(list(m.candidates), s.confirmed.get, p.consensus_cov, p.consensus_margin,
                         p.consensus_min_confirmed, blocked=CONSENSUS_GUARDS.get(p.consensus_family_guard))
    return replace(d, verdict="same", char=hit[0], via=f"{Via.CONSENSUS.value}:{hit[1]}") if hit else d


def rule_near_shape(m, d: Decision, s: StepState) -> Decision:
    ns = m.near_shape
    if s.near_shape_cfg is None or not _promotable(m, d) or not ns or not ns.get("winner"):
        return d
    return replace(d, verdict="same", char=ns["winner"], via=f"{Via.NEAR_SHAPE.value}:{ns['score']:+.2f}")


@dataclass(frozen=True)
class RuleSpec:
    id: Rule
    stage: Stage
    order: int
    summary: str
    params: tuple[str, ...] = ()
    constants: tuple[str, ...] = ()
    impl: str = ""
    via: str = ""
    apply: Callable | None = None
    cand_variants: bool = False     # 候选试切（cand_variants）也走这一条


_M = "clustering.match.GlyphMatcher"
_V = "clustering.verify"

RULES: tuple[RuleSpec, ...] = (
    # ── 匹配器层：GlyphMatcher.match 及外面几层包装 ──
    RuleSpec(Rule.NORMALIZE, Stage.MATCHER, 10, "图块归一到 64×64（标点等比）；现代印刷链可骨架化后统一笔宽",
             params=("norm_stroke",), impl="clustering.normalize.normalize_patch"),
    RuleSpec(Rule.FONT_TIER, Stage.MATCHER, 20,
             "先只查刻本库；命中弱（非 same 且首选 cov/分差不够、首选字少于 min_n 例、或首选字在形近字表）再查整库（含字体域）",
             params=("font_tier",), impl="steps.glyph_match._FontTier"),
    RuleSpec(Rule.KNN, Stage.MATCHER, 30, "HOG 特征与库矩阵相似度取前 k 名（整页合批算）",
             params=("knn_k", "batch_knn", "edition"), impl=f"{_M}._match"),
    RuleSpec(Rule.EXCLUDE_SELF, Stage.MATCHER, 40, "按同一物理格把字位自己摘出库，防自证 cov 1.0",
             params=("exclude_self",), impl=f"{_M}._same_cell_rows"),
    RuleSpec(Rule.ELASTIC_VERIFY, Stage.MATCHER, 50,
             "前 k 名逐个弹性验证：cov ≥ same_cov 且 wmax ≤ same_wmax → same；cov ≥ 0.85 → unsure；否则 diff",
             params=("same_cov", "same_wmax", "cell_budget_s"),
             constants=("ELASTIC_COV_HIGH=0.996", "MISS_WMAX=12", "COV_LOW=0.85", "MAX_SHIFT=3",
                        "SCALES=(0.95,1.0,1.05)", "ELASTIC_TAU=1.5", "ELASTIC_BLOCK=16", "ELASTIC_LOCAL=1"),
             impl=f"{_V}.verify_pair_elastic；超时 → guard=timeout（steps.glyph_match._timeout_rec）"),
    RuleSpec(Rule.GUARD_CONFLICT, Stage.MATCHER, 60, "判 same 的刻例不止一个字 → 降 unsure，guard=conflict",
             impl=f"{_M}._match（护栏 2）"),
    RuleSpec(Rule.GUARD_NEVER_MATCH, Stage.MATCHER, 70,
             "same 字在形近护栏表里有对手（库里也有）→ 降 unsure，对手补进候选，guard=never_match",
             constants=("clustering.confusable.NEVER_MATCH_FAMILIES / _PARTNER",), impl=f"{_M}._match（护栏 1）"),
    RuleSpec(Rule.SHAPE_PAIR_RERANK, Stage.MATCHER, 80, "强/強、却/卻、回/囘、并/幷 首位落在这 8 字时按部件局部决胜重排候选",
             params=("shape_pair_rerank",), impl=f"{_M}._apply_shape_rerank"),
    RuleSpec(Rule.NEAR_SHAPE_DECIDE, Stage.MATCHER, 90, "首选与次优异字 cov 差 < 0.03 时用两字人裁刻例求差异区局部决胜，胜者挪首位",
             params=("near_shape",), impl=f"{_M}._apply_near_shape（clustering.near_shape）"),
    # ── 判决层：本模块，decide() 按此顺序执行 ──
    RuleSpec(Rule.BORROWED_DEMOTE, Stage.STEP, 110,
             "只有借来的条目判 same → 降 unsure（本书也有 same 条目就用本书那条）",
             params=("borrow_fingerprint",), via="borrowed:<条目 id>", apply=rule_borrowed_demote,
             cand_variants=True),
    RuleSpec(Rule.CONSENSUS, Stage.STEP, 120,
             "unsure 且无护栏：首位 cov ≥ consensus_cov、比次优异字高 ≥ consensus_margin、该字已有 ≥ consensus_min_confirmed 例 → same",
             params=("consensus_cov", "consensus_margin", "consensus_min_confirmed", "consensus_count",
                     "consensus_family_guard"),
             constants=("无异字候选时分差按 0.85 算",), via="consensus:<例数>", apply=rule_consensus),
    RuleSpec(Rule.NEAR_SHAPE_PROMOTE, Stage.STEP, 130, "unsure 且无护栏、近形决胜决出了胜者 → same",
             params=("near_shape",), via="near_shape:<分>", apply=rule_near_shape),
)

STEP_RULES: tuple[RuleSpec, ...] = tuple(sorted((r for r in RULES if r.stage is Stage.STEP), key=lambda r: r.order))


def decide(m, state: StepState, rules: tuple[RuleSpec, ...] = STEP_RULES) -> Decision:
    """匹配器结果 → 本格判决：从匹配器的判决出发，按 `rules` 顺序逐条改写。"""
    d = Decision(m.verdict, m.char, m.matched_id, m.cov, m.wmax)
    for r in rules:
        d = r.apply(m, d, state)
    return d


def decide_variant(m, state: StepState) -> Decision:
    """候选试切只走 `cand_variants=True` 的规则（现行只有借库降档）。"""
    return decide(m, state, tuple(r for r in STEP_RULES if r.cand_variants))


def rules_markdown() -> str:
    """规则表（贴文档用）。"""
    out = ["| # | 层 | 规则 | 短名 | 做什么 | 参数（册 yaml 可调） | 写死的常数 | via | 实现 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(RULES, key=lambda r: r.order):
        impl = r.impl or (f"steps.glyph_rules.{r.apply.__name__}" if r.apply else "")
        out.append(f"| {r.order} | {'匹配器' if r.stage is Stage.MATCHER else '判决'} | `{r.id.value}` | {r.id.label} | {r.summary} | "
                   f"{'、'.join(f'`{p}`' for p in r.params) or '—'} | {'；'.join(r.constants) or '—'} | "
                   f"{f'`{r.via}`' if r.via else '—'} | {impl} |")
    return "\n".join(out)


if __name__ == "__main__":
    print(rules_markdown())
