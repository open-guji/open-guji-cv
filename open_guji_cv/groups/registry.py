"""字组注册表：单一真源。加一组＝在 `GROUPS` 加一项（成员＋`FlowSpec` 判法），不碰 `seed_admit`。

`seed_admit` 里字组只有一条路：`group_flow`（`groups/flow.py`）。旧的各组开关（`ji_yi_si_*`、`ry_group`、`rr_clf`、
`m7_*`、`variant_tie*`）与它们的升降策略 `GroupPolicy`／`apply.py` 已于 2026-10-18 并进 `group_flow` 后删除（方案 S6）。

⚠ 现有各处还有自己的成员常量（`ji_yi_si_clf.FAMILY`、`rr_clf.CLASSES`…）；
`tests/test_groups_registry.py` 断言这里的成员与它们一致，防漂移。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowSpec:
    """字组统一流程（`seed_admit.group_flow`，新 variant-tie，2026-10-18 sheldon 定）里这一组怎么判。

    - `solvers`：有序，取值见 `groups.flow.SOLVERS`（`freq` 字频、`ids` 部件拆分、`top1` 库形最近、`ctx` 文意、
      `bars` 量横、`rr_img` 入人八字形分类器）；
    - `combine`：`first`＝按顺序第一个给字的说了算（字频成立就不再看 IDS）；`agree`＝所有给字的必须一致，不一致送审；
    - `review`：已被别的通道放行、放行字在组里的格也进流程复核——解法给了**别的字**（或解法之间不一致）就降为人审
      （只降不改字）；
    - `review_fix`：复核时解法给了别的字，**改成解法的字**（仍放行，通道 `group_flow`）而不是降审——只给「字形只定
      是这一族、哪个字全凭文意」的组用（己已巳：别的通道放的字本来就是整理本或库形的猜测）；
    - `review_abstain`：复核时解法全弃权也降为人审（「没有文意证据就不信别的通道」，己已巳用；旧 `ji_yi_si_clf`
      对规则不命中的整理本放行格就是这么做的）；
    - `lift_needs`：补放时给字的解法里必须有这几个之一（空＝不限）。入人八字形分类器只验证过「降级」，不许单独补放
      （vol04 A/B：过切的半个「爻」被它单独放成「人」）。"""
    solvers: tuple
    combine: str = "agree"
    review: bool = False
    review_fix: bool = False
    lift_needs: tuple = ()
    review_abstain: bool = False


@dataclass(frozen=True)
class GroupSpec:
    id: str                       # 与 dataset `char-groups/groups.json` 的 id 一致
    name: str
    members: frozenset            # 组内字；各处成员常量应由它派生
    backends: tuple               # 离线评测（`eval/groups.py`）用的判别后端名："rule"|"ctx_table"|"table"|"image"
    note: str = ""
    # —— M7（GUJI-563）：解法声明。旧字段不动，缺省值不改变任何现有行为 ——
    kind: str = "near_form"       # "variant"（异体，靠 IDS）| "near_form"（形近不同义，靠上下文）
    solvers: tuple = ()           # 有序："ids" | "ctx_l1" | "ctx_l2" | "image"；可多个（一组可同时挂两种）
    config_dir: str | None = None # 相对仓根，如 "config/groups/yi_560"
    flow: FlowSpec | None = None  # 字组统一流程里的判法；None＝不进 `group_flow`
    overlaps: tuple = ()          # 允许与哪些组共用成员（须互相声明）；入口按分差内候选＋整理本字选第一个装得下的组
    ref_free: bool = False        # 整理本在本组的字上没有参考价值（如己已巳，sheldon 2026-10-19 定）：入口不看整理本字，判法也拿不到它


GROUPS: dict[str, GroupSpec] = {
    "jys": GroupSpec(
        id="jys", name="己已巳", members=frozenset("己已巳"),
        backends=("rule", "ctx_table", "table"),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/jys",
        flow=FlowSpec(("ctx",), review=True, review_fix=True, review_abstain=True), ref_free=True,
        note="按文意定（L1 规则含旧 ji_yi_si_clf 规则路，弃权查 L2 表）；已放行的本族格无文意证据也降审。"),
    "ry": GroupSpec(
        id="ry", name="日曰", members=frozenset("日曰"),
        backends=("table",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/ry",
        flow=FlowSpec(("ctx",), review=True), overlaps=("rm",),
        note="按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。与日目组 rm 共用「日」。"),
    "rr": GroupSpec(
        id="rr", name="入人八", members=frozenset("人入八"),
        backends=("image",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/rr",
        flow=FlowSpec(("ctx", "rr_img"), review=True, lift_needs=("ctx",)),
        note="文意＋字形分类器；补放要文意给字且两路不冲突，复核时任一路给了别的字就降审。"),
    # —— 上下文线（cv#118）：按文意定；土士、未末另加量横（文意弃权才用量横，两路不一致送审） ——
    "wxs": GroupSpec(
        id="wxs", name="戊戌戍", members=frozenset("戊戌戍"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/wxs",
        flow=FlowSpec(("ctx",), review=True),
        note="按文意定（只有 L1 规则）。"),
    "wm": GroupSpec(
        id="wm", name="未末", members=frozenset("未末"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/wm",
        flow=FlowSpec(("ctx", "bars")),
        note="按文意定；文意弃权时按量横长短（groups/bars.py）。"),
    "ts": GroupSpec(
        id="ts", name="土士", members=frozenset("土士"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/ts",
        flow=FlowSpec(("ctx", "bars")),
        note="按文意定；文意弃权时按量横长短（groups/bars.py）。"),
    # —— 第三批形近不同义组（2026-10-19 sheldon 定）：按文意定（L1 规则＋haiku 查表）。只补放，不复核；
    #    L1 零冲突于整理本，其余格由逐册 L2 表（haiku，只收 conf=high）决定，弃权送人审。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec(("ctx",), review=True),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("ly", "論諭", "論＝議論；諭＝詔諭、上諭。"), ("dt", "大太", "太只收官名帝号类；大史／太史等两可词弃权。"),
                               ("wj", "問間", "間＝其間、間有、年間；問＝詢問、學問。"), ("zh", "曾會", "會＝會典、附會；曾＝曾經、姓氏。"),
                               ("yh", "遺還", "遺＝遺文、補遺；還＝還朝、返還。"))},
    # —— 第四批（2026-10-19）：象彖、王玉、圓圖。同前，L1 零冲突＋逐册 L2 表。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec(("ctx",), review=True),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("xz", "象彖", "彖傳＝释卦辞；象傳＝释卦象；象數、取象为象。"), ("wyu", "王玉", "王＝王弼等人名、帝王；玉＝玉器、玉海。"),
                               ("yt", "圓圖", "圖＝河圖、圖書、圖說；圓＝圓通、渾圓、方圓。"))},
    # —— 日目（2026-10-19）：与 ry 共用「日」（互相声明 overlaps），入口按分差内候选选组：日曰候选归 ry，日目候选归 rm，三者混杂留人审。
    "rm": GroupSpec(
        id="rm", name="日目", members=frozenset("日目"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/rm",
        flow=FlowSpec(("ctx",), review=True), overlaps=("ry", "mz"),
        note="按文意定；与 ry 共用「日」。目＝書目、總目、存目；日＝今日、是日、日月。"),
    # —— 第五批（2026-10-19）：目自、一二、千干、十卜、甲申、而面、傅傳、木本。同前：L1 规则（整理本奇偶册交叉验证零冲突）＋逐册 L2 表。
    #    目自与 rm 共用「目」（互相声明 overlaps）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec(("ctx",), review=True), overlaps=ov,
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, ov, note in (
           ("mz", "目自", ("rm",), "目＝總目、書目、存目；自＝自序、所自、自某代以來。"),
           ("yr", "一二", (), "数词序列：卷一、第二、一二、二十一。"),
           ("qg", "千干", (), "千＝千百、千餘、千里；干＝干支、干戈、干預。"),
           ("sb", "十卜", (), "十＝十二、十卷；卜＝占卜、卜筮、卜子。"),
           ("js", "甲申", (), "干支：甲子、甲乙；申＝申明、申屠、庚申。"),
           ("em", "而面", (), "而＝虚词；面＝東面、南面、四面。"),
           ("fc", "傅傳", (), "傳＝傳注、經傳、傳記；傅＝傅會、傅寅、傅以漸、太傅。"),
           ("mb", "木本", (), "本＝版本、原本、本草；木＝草木、木瓜、木部。"))},
    "yi_560": GroupSpec(
        id="yi_560", name="彝彛彜彞𢑱𢑴", members=frozenset("彝彛彜彞𢑱𢑴"),
        backends=(),
        kind="variant", solvers=("ids",), config_dir="config/groups/yi_560",
        note="异体字组（#560）：只登记成员。没有判别器（42 格训不出「大 vs 廾」读字器），走人裁数据路，不抬不降。"),
    # —— 异体组（字组统一流程首批，2026-10-18 sheldon 定）：即旧 `variant_tie_extra` 用户裁过的七组。
    #    判法：字频成立就定；否则 IDS（尚未在线，弃权）；再否则沿用旧 variant_tie「库形最近的码位」（top1 cov ≥ 0.97）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=cfg,
        flow=FlowSpec(("freq", "ids", "top1"), combine="first"),
        note="异体组：字频→IDS→库形最近；只在 seed_admit.group_flow 点名时生效。")
       for gid, name, cfg in (("mn", "蒙𫎇", None), ("dian", "點㸃", None), ("can", "參㕘叅", "config/groups/can"),
                              ("chen", "讖識䜟", None), ("li", "隸𨽾", None), ("shen", "慎愼", "config/groups/shen"),
                              ("zhi", "旨㫖", None))},
    # —— 第二批异体组（2026-10-18 sheldon 定）：只靠字频。人裁数不够（主形 <20 或次形不为 0）时弃权、送人审，
    #    不退到 IDS／库形最近；字频表重算后数据攒够就自动放行。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=(), config_dir=None,
        flow=FlowSpec(("freq",), combine="first"),
        note="异体组：只看字频；数据不够送人审，重算字频表后自动放行。只在 seed_admit.group_flow 点名时生效。")
       for gid, name in (("ji", "即卽"), ("qing", "卿𨜊"), ("bian", "變𠮓"), ("hui", "彙彚"))},
}


def get_group(group_id: str) -> GroupSpec:
    return GROUPS[group_id]


def groups_of(ch: str) -> list[GroupSpec]:
    """一个字属于哪些组（可多个：同字可同属两组）。"""
    return [g for g in GROUPS.values() if ch in g.members]
