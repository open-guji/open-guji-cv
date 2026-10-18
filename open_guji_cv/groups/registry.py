"""字组注册表：单一真源。加一组＝在 `GROUPS` 加一项＋配后端，不碰 `seed_admit`。

每项 `GroupSpec` 包含：成员字、判别后端名、升降策略 `GroupPolicy`。策略把现有三个 `_pass` 里的差别
写成**可声明的旋钮**，由 `apply.apply_group_verdicts` 一次执行（语义对齐 `seed_admit` 现状，旧证据键／疑问码／通道名原样保留，
所以旧产物逐字节不变）。

⚠ 现有各处还有自己的成员常量（`ji_yi_si_clf.FAMILY`、`ry_group.FAMILY`、`rr_clf.CLASSES`…）；它们在 Step 的
`code_deps` 里，S0 不动。`tests/test_groups_registry.py` 断言这里的成员与它们一致，防漂移。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..utils.ji_yi_si_clf import STRONG_CHANNELS as _JYS_STRONG


@dataclass(frozen=True)
class GroupPolicy:
    # —— 选格：哪些格归本组处理 ——
    target: str = "any"                       # "pending"（只碰待审）| "admitted"（只碰已放行）| "any"
    membership: str = "char"                  # 判「属于本组」看谁："ref"（整理本对位字）| "char"（现行放行字）
    skip_channels: frozenset = frozenset({"human"})        # 人裁位任何遍都不动（B1 原则 4）
    skip_doubts: frozenset = frozenset()
    skip_doubt_substr: tuple = ()             # 疑问码含这些子串也跳过（如 ry 的 "seal"）
    # —— 抬升：待审 → 放行 ——
    lift: bool = False
    lift_needs_ref_agree: bool = False        # pick 必须等于整理本字才抬（ry）；不等则只追加 `disagree_doubt`
    lift_overwrites_admitted: bool = False    # 已放行（非强通道）的格也按 pick 改字／改通道（jys）
    lift_channel: str | None = None
    lift_provenance: str = "context"
    lift_clear_doubts: tuple = ()
    # —— 降级：放行 → 待审 ——
    demote: bool = False                      # 放行字≠pick → 退回待审（rr）
    demote_by: str = ""                       # `evidence.demoted_from.by`
    demote_clears_char: bool = False
    disagree_doubt: str | None = None         # pick 与整理本字（ry）／放行字（rr）不一致时追加的疑问码
    strong_channels: frozenset = frozenset()  # 这些通道放行的字与 pick 冲突：两边都不信，退回待审（jys）
    conflict_doubt: str | None = None         # 同时作 `demoted_from.by`
    abstain_demote_channels: frozenset = frozenset()   # pick 弃权时，这些通道放行的格退回待审（jys 退役的 split_ref）
    abstain_doubt: str | None = None          # 同时作 `demoted_from.by`
    # —— 写证据：(证据键, 取自 verdict.extra 的哪个字段) ——
    evidence: tuple = ()


@dataclass(frozen=True)
class GroupSpec:
    id: str                       # 与 dataset `char-groups/groups.json` 的 id 一致
    name: str
    members: frozenset            # 组内字；各处成员常量应由它派生
    backends: tuple               # 判别后端名，按优先级："rule"|"ctx_table"|"table"|"image"
    policy: GroupPolicy
    note: str = ""
    # —— M7（GUJI-563）：解法声明。旧字段不动，缺省值不改变任何现有行为 ——
    kind: str = "near_form"       # "variant"（异体，靠 IDS）| "near_form"（形近不同义，靠上下文）
    solvers: tuple = ()           # 有序："ids" | "ctx_l1" | "ctx_l2" | "image"；可多个（一组可同时挂两种）
    config_dir: str | None = None # 相对仓根，如 "config/groups/yi_560"


_JYS_POLICY = GroupPolicy(
    target="any", membership="char",
    skip_doubts=frozenset({"occluded", "glyph_timeout", "excluded"}),
    lift=True, lift_overwrites_admitted=True, lift_channel="ji_yi_si", lift_provenance="context",
    lift_clear_doubts=("always_review", "ji_yi_si"),
    strong_channels=_JYS_STRONG, conflict_doubt="ji_yi_si_clf_conflict",
    demote_clears_char=True,
    abstain_demote_channels=frozenset({"split_ref"}), abstain_doubt="ji_yi_si_clf_review",
)
"""新增三组沿用 jys 的升降策略（不写证据键）；后端待上下文线接好再声明，现在只登记成员与解法。"""


GROUPS: dict[str, GroupSpec] = {
    "jys": GroupSpec(
        id="jys", name="己已巳", members=frozenset("己已巳"),
        backends=("rule", "ctx_table", "table"),
        policy=GroupPolicy(
            target="any", membership="char",
            skip_doubts=frozenset({"occluded", "glyph_timeout", "excluded"}),   # excluded：旧遍先把这类格从序列里剔掉
            lift=True, lift_overwrites_admitted=True, lift_channel="ji_yi_si", lift_provenance="context",
            lift_clear_doubts=("always_review", "ji_yi_si"),
            strong_channels=_JYS_STRONG, conflict_doubt="ji_yi_si_clf_conflict",
            demote_clears_char=True,
            abstain_demote_channels=frozenset({"split_ref"}), abstain_doubt="ji_yi_si_clf_review",
            evidence=(("ji_yi_si_clf", "clf_ev"), ("ji_yi_si", "ji_yi_si")),
        ),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/jys",
        note="按文意定；现行规则路对应 seed_admit.ji_yi_si_clf。表路（suggest）与 llm 路、ctx_rule 路、review 闸 S0 不覆盖，见设计档第七节。"),
    "ry": GroupSpec(
        id="ry", name="日曰", members=frozenset("日曰"),
        backends=("table",),
        policy=GroupPolicy(
            target="pending", membership="ref",
            skip_doubts=frozenset({"occluded", "glyph_timeout", "excluded"}), skip_doubt_substr=("seal",),
            lift=True, lift_needs_ref_agree=True, lift_channel="ry_group", lift_provenance="context",
            lift_clear_doubts=("always_review",),
            disagree_doubt="ry_disagree",
            evidence=(("ry_group", "legacy"),),
        ),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/ry",
        note="离线多模型答案表，只抬待审、不改字、不降放行。"),
    "rr": GroupSpec(
        id="rr", name="入人八", members=frozenset("人入八"),
        backends=("image",),
        policy=GroupPolicy(
            target="admitted", membership="char",
            demote=True, demote_by="rr_clf", disagree_doubt="rr_clf_disagree",
            evidence=(("rr_clf", "legacy"),),
        ),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/rr",
        note="字形分类器，只降级、不改字、不放行。"),
    # —— 上下文线（cv#118）登记：解法走 ctx_l1/ctx_l2，策略同 jys（按文意定） ——
    "wxs": GroupSpec(
        id="wxs", name="戊戌戍", members=frozenset("戊戌戍"),
        backends=(),
        policy=_JYS_POLICY,
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/wxs",
        note="按文意定；只登记，后端待上下文线接入。"),
    "wm": GroupSpec(
        id="wm", name="未末", members=frozenset("未末"),
        backends=(),
        policy=_JYS_POLICY,
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/wm",
        note="按文意定；文意弃权时按量横长短（groups/bars.py，开关 seed_admit.m7_bars）。"),
    "ts": GroupSpec(
        id="ts", name="土士", members=frozenset("土士"),
        backends=(),
        policy=_JYS_POLICY,
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/ts",
        note="按文意定；文意弃权时按量横长短（groups/bars.py，开关 seed_admit.m7_bars）。"),
    "yi_560": GroupSpec(
        id="yi_560", name="彝彛彜彞𢑱𢑴", members=frozenset("彝彛彜彞𢑱𢑴"),
        backends=(),
        policy=GroupPolicy(),
        kind="variant", solvers=("ids",), config_dir="config/groups/yi_560",
        note="异体字组（#560）：只登记成员。没有判别器（42 格训不出「大 vs 廾」读字器），走人裁数据路，不抬不降。"),
}


def get_group(group_id: str) -> GroupSpec:
    return GROUPS[group_id]


def groups_of(ch: str) -> list[GroupSpec]:
    """一个字属于哪些组（可多个：同字可同属两组）。"""
    return [g for g in GROUPS.values() if ch in g.members]
