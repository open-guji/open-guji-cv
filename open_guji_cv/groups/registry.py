"""字组注册表：单一真源。加一组＝在 `GROUPS` 加一项（成员＋`FlowSpec` 方法数组，方法见 `groups/methods.py`），不碰 `seed_admit`。

`seed_admit` 里字组只有一条路：`group_flow`（`groups/flow.py`）。旧的各组开关（`ji_yi_si_*`、`ry_group`、`rr_clf`、
`m7_*`、`variant_tie*`）与它们的升降策略 `GroupPolicy`／`apply.py` 已于 2026-10-18 并进 `group_flow` 后删除（方案 S6）。

⚠ 现有各处还有自己的成员常量（`ji_yi_si_clf.FAMILY`、`rr_clf.CLASSES`…）；
`tests/test_groups_registry.py` 断言这里的成员与它们一致，防漂移。
"""
from __future__ import annotations

from dataclasses import dataclass

from .methods import BARS, CODEPOINT, CTX, FORM_TOP1, JYS_CTX, FREQ, IDS, RR_IMG, RY_SHAPE, TOP1, Method, describe, hog_or_crop


@dataclass(frozen=True)
class FlowSpec:
    """字组统一流程（`seed_admit.group_flow`，2026-10-18 sheldon 定）里这一组怎么判。

    - `methods`：**方法数组**（sheldon 2026-10-22 定），`groups.methods` 里八类方法的实例，有序；每个方法输出放行（组内一个字）
      或待定，带 0–1 置信度与留痕。`solvers` 是它们的名字（留痕与旧代码用）；
    - `combine`：`first`＝依次试，第一个放行的说了算（字频成立就不再看 IDS）；`agree`＝所有方法都跑，给字的必须一致，不一致送审
      （后面的方法当第二路校验）；
    - `review`：已被别的通道放行、放行字在组里的格也进流程复核——方法给了**别的字**（或方法之间不一致）就降为人审
      （只降不改字）；
    - `review_fix`：复核时方法给了别的字，**改成方法的字**（仍放行，通道 `group_flow`）而不是降审——只给「字形只定
      是这一族、哪个字全凭文意」的组用（己已巳：别的通道放的字本来就是整理本或库形的猜测）；
    - `review_fix_strong`：同 `review_fix`，但只在文意答案 strong（L2 表第二个模型也以 high 给了同一个字，`ctx_l2.add_confirm`）、
      且其余方法没有反对时才改字，否则照常降审（日曰：sheldon 10-22「文意置信度特别高可以改掉整理本」）；
    - `pair`：相邻两格（读序紧挨）都进了本组时，前一格给 `pair[0]`、后一格给 `pair[1]`，不再跑方法（己已巳：干支「己巳」；
      總目参考文本里己已巳两两相邻 37 处全是干支己巳）。三格以上连着不适用，照常跑方法；
    - `review_abstain`：复核时方法全待定也降为人审（「没有文意证据就不信别的通道」，己已巳用）；
    - `lift_needs`：补放时给字的方法里必须有这几个之一（按名字；空＝不限）。入人八字形分类器只验证过「降级」，不许单独补放
      （vol04 A/B：过切的半个「爻」被它单独放成「人」）；
    - `tolerate`：补放进入时，分差内允许出现的**组外候选字**（库形上的陪衬，不是真竞争者）。只放宽进入，给字仍全凭方法，
      方法给不出组内字照样送审。彝：库形常把 尋、舞 排在第二、三位（vol04–10 有 4 格因此没进流程）；
    - `families`：两段判。组里有同字异体时（象彖𧰼：象𧰼同字，彖另一字），先由 `methods`（文意）定「哪一族」，
      族里不止一形的，再由 `form_methods`（字频→IDS→库形最近，按刻形，只在族里选）定哪一形，定不下来待定。族是字符串，如 ("彖", "象𧰼")；
    - `review_methods`：复核时改跑这个数组（依次试，第一个给字的说了算），空＝跟补放一样跑 `methods`。异体组复核只看刻形
      （2026-10-24，A24：字频永远说主形，拿它复核会把真次形也降掉），如 旨㫖：补放 字频→IDS，复核只跑 IDS。"""
    methods: tuple
    combine: str = "agree"
    review: bool = False
    review_fix: bool = False
    review_fix_strong: bool = False
    pair: tuple = ()
    lift_needs: tuple = ()
    review_abstain: bool = False
    tolerate: frozenset = frozenset()
    families: tuple = ()
    form_methods: tuple = (FREQ, IDS, FORM_TOP1)
    review_methods: tuple = ()

    @property
    def solvers(self) -> tuple:
        return tuple(m.name for m in self.methods)

    @property
    def review_solvers(self) -> tuple:
        return tuple(m.name for m in (self.review_methods or self.methods))

    @property
    def form_solvers(self) -> tuple:
        return tuple(m.name for m in self.form_methods)

    @property
    def needs_patch(self) -> bool:
        """有方法要字块图（两段判时连第二段一起算）。"""
        return any(m.needs_patch for m in (*self.methods, *self.review_methods,
                                            *(self.form_methods if self.families else ())))

    def describe(self) -> str:
        return (" → " if self.combine == "first" else " ＋ ").join(describe(m) for m in self.methods)


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


#: 两段判的族（见 `FlowSpec.families`）：先按文意定哪一族，族内不止一形再按刻形定（sheldon 2026-10-22）。
FAMILIES: dict[str, tuple] = {"zh": ("曾", "會㑹"), "xz": ("彖", "象𧰼")}



def _img(gid: str) -> Method:
    """看字块的方法：`ids_online.SPECS` 里登记成整字判法的组 → 整字 HOG＋岭回归（登记了取框的 → 取框→HOG 复合方法）；
    其余 → IDS 部件（没登记模板库的组在线上待定）。"""
    from .ids_online import SPECS
    sp = SPECS.get(gid)
    if sp is not None and sp.whole:
        return hog_or_crop(tuple(sp.region))
    return IDS


#: 按刻形复核的异体组（2026-10-24，A24；sheldon「错放的情况也要注意修复」）：别的通道（库形替换、整理本、三证…）已放行、放行字在组里的格，
#: 复核只跑组的字形方法（`_img`，不跑字频与库形最近）；判出组里另一形就降审，只降不改字，判不出不动。
#: vol04–20 回放：旨→㫖 24 格、删→刪 约 12 格等是真错放；判法也会错（删 2 格），所以只降审。名单＝在 `ids_online.SPECS` 有判法的异体组。
SHAPE_REVIEW = frozenset({"zhi", "can", "xu", "jiao", "qik", "lih", "jue", "lv", "zheng", "weiw", "shan", "di", "yi_560"})


def _rv(gid: str) -> dict:
    return {"review": True, "review_methods": (_img(gid),)} if gid in SHAPE_REVIEW else {}


#: 文意组里加了字形第二路的组（2026-10-22；判法与门槛见 `ids_online.SPECS` 同名行）。方法数组里排在文意之后，`agree`：
#: 文意弃权时字形可单独补放，两路都给字须一致，否则送审；复核时字形给了别的字就降审。
GLYPH2 = frozenset({"rr", "ts", "ly", "wj", "zh", "yh", "yt", "js", "em", "fc", "yr"})


def _g2(gid: str) -> tuple:
    return (_img(gid),) if gid in GLYPH2 else ()


GROUPS: dict[str, GroupSpec] = {
    "jys": GroupSpec(
        id="jys", name="己已巳", members=frozenset("己已巳"),
        backends=("rule", "ctx_table", "table"),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/jys",
        flow=FlowSpec((JYS_CTX,), review=True, review_fix=True, review_abstain=True, tolerate=frozenset("巴"),
                     pair=("己", "巳")), ref_free=True,
        note="按文意定（L1 规则含旧 ji_yi_si_clf 规则路，弃权查 L2 表）；已放行的本族格无文意证据也降审。巴是库形陪衬（vol04–10 有 17 格因分差内的巴没进流程；L2 有「其他」出口，真是巴会弃权）。前一字也是族字（干支「己巳」的第二字）时不查 L2 表。"),
    "ry": GroupSpec(
        id="ry", name="日曰", members=frozenset("日曰"),
        backends=("table",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/ry",
        flow=FlowSpec((CTX, RY_SHAPE), review=True, review_fix_strong=True, lift_needs=("ctx",)), overlaps=("rm",),
        note="按文意定（L1 规则，弃权查 L2 表）＋字形宽高比（日窄曰宽，只当第二路：强烈指向另一个字就降审，不单独补放）；补放，也复核（只降审不改字）。与日目组 rm 共用「日」。"),
    "rr": GroupSpec(
        id="rr", name="入人八", members=frozenset("人入八"),
        backends=("image",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/rr",
        flow=FlowSpec((CTX, RR_IMG, *_g2("rr")), review=True, lift_needs=("ctx", "ids")),
        note="文意＋字形分类器＋整字 HOG（上半）；补放要文意或整字 HOG 给字且各路不冲突（随机森林分类器不单独补放），复核时任一路给了别的字就降审。"),
    # —— 上下文线（cv#118）：按文意定；土士、未末另加量横（文意弃权才用量横，两路不一致送审） ——
    "wxs": GroupSpec(
        id="wxs", name="戊戌戍", members=frozenset("戊戌戍"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/wxs",
        flow=FlowSpec((CTX,), review=True),
        note="按文意定（只有 L1 规则）。"),
    "wm": GroupSpec(
        id="wm", name="未末", members=frozenset("未末"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/wm",
        flow=FlowSpec((CTX, BARS)), overlaps=("sz",),
        note="按文意定；文意弃权时按量横长短（groups/bars.py）。与 sz 共用「未」。"),
    "ts": GroupSpec(
        id="ts", name="土士", members=frozenset("土士"),
        backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/ts",
        flow=FlowSpec((CTX, BARS, *_g2("ts"))),
        note="按文意定；文意弃权时按量横长短（groups/bars.py）与整字 HOG（左半），给字须一致。"),
    # —— 第三批形近不同义组（2026-10-19 sheldon 定）：按文意定（L1 规则＋haiku 查表）。只补放，不复核；
    #    L1 零冲突于整理本，其余格由逐册 L2 表（haiku，只收 conf=high）决定，弃权送人审。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((CTX, *_g2(gid)), review=True, families=FAMILIES.get(gid, ()),
                      **({"form_methods": (FREQ, FORM_TOP1)} if gid == "zh" else {})), overlaps=("qin",) if gid == "zh" else (),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("ly", "論諭", "論＝議論；諭＝詔諭、上諭。"), ("dt", "大太", "太只收官名帝号类；大史／太史等两可词弃权。"),
                               ("wj", "問間", "間＝其間、間有、年間；問＝詢問、學問。"), ("zh", "曾會㑹", "會＝會典、附會；曾＝曾經、姓氏。㑹是會的异体：先按文意定曾／會族，會㑹再按刻形（字频→IDS→库形最近）定哪一形。"),
                               ("yh", "遺還", "遺＝遺文、補遺；還＝還朝、返還。"))},
    # —— 第四批（2026-10-19）：象彖、王玉、圓圖。同前，L1 零冲突＋逐册 L2 表。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((CTX, *_g2(gid)), review=True, families=FAMILIES.get(gid, ())),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("xz", "象彖𧰼", "彖傳＝释卦辞；象傳＝释卦象；象數、取象为象。𧰼是象的异体：先按文意定彖／象族，象𧰼再按刻形（字频→IDS→库形最近）定哪一形。"), ("wyu", "王玉", "王＝王弼等人名、帝王；玉＝玉器、玉海。"),
                               ("yt", "圓圖", "圖＝河圖、圖書、圖說；圓＝圓通、渾圓、方圓。"))},
    # —— 日目（2026-10-19）：与 ry 共用「日」（互相声明 overlaps），入口按分差内候选选组：日曰候选归 ry，日目候选归 rm，三者混杂留人审。
    "rm": GroupSpec(
        id="rm", name="日目", members=frozenset("日目"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/rm",
        flow=FlowSpec((CTX,), review=True), overlaps=("ry", "mz"),
        note="按文意定；与 ry 共用「日」。目＝書目、總目、存目；日＝今日、是日、日月。"),
    # —— 第五批（2026-10-19）：目自、一二、千干、十卜、甲申、而面、傅傳、木本。同前：L1 规则（整理本奇偶册交叉验证零冲突）＋逐册 L2 表。
    #    目自与 rm 共用「目」（互相声明 overlaps）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((CTX, *_g2(gid)), review=True), overlaps=ov,
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
        flow=FlowSpec((FREQ, _img("yi_560")), combine="first", tolerate=frozenset("尋舞"), **_rv("yi_560")),
        note="异体字组（#560）：字频→IDS 三段（上彑彐／中米糸米分／下廾大，自动缝，42 格模板）；判不出送人审，不退到库形最近。"
             "只在 seed_admit.group_flow 点名时生效。"),
    # —— 异体组（字组统一流程首批，2026-10-18 sheldon 定）：即旧 `variant_tie_extra` 用户裁过的七组。
    #    判法：字频成立就定；否则 IDS（尚未在线，弃权）；再否则沿用旧 variant_tie「库形最近的码位」（top1 cov ≥ 0.97）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=cfg,
        flow=FlowSpec((FREQ, _img(gid), TOP1), combine="first", **_rv(gid)),
        note="异体组：字频→IDS→库形最近；只在 seed_admit.group_flow 点名时生效。")
       for gid, name, cfg in (("mn", "蒙𫎇", None), ("dian", "點㸃", None), ("can", "參㕘叅", "config/groups/can"),
                              ("chen", "讖識䜟", None), ("li", "隸𨽾", None), ("shen", "慎愼", "config/groups/shen"),
                              ("zhi", "旨㫖", "config/groups/zhi"))},
    # —— 第二批异体组（2026-10-18 sheldon 定）：只靠字频。人裁数不够（主形 <20 或次形不为 0）时弃权、送人审，
    #    不退到 IDS／库形最近；字频表重算后数据攒够就自动放行。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=(), config_dir=None,
        flow=FlowSpec((FREQ,), combine="first"),
        note="异体组：只看字频；数据不够送人审，重算字频表后自动放行。只在 seed_admit.group_flow 点名时生效。")
       for gid, name in (("ji", "即卽"), ("qing", "卿𨜊"), ("bian", "變𠮓"), ("hui", "彙彚"),
                         # 第三批（2026-10-20 sheldon 合审定）：殿本全书只见一形，人裁 ≥10 且来自 ≥2 册
                         ("kan", "刊刋"), ("jiw", "既旣"), ("qx", "清淸"), ("dx", "顚顛"), ("zx", "淄湽"), ("qy", "青靑"),
                         # 第四批（2026-10-20 少样例异体道盘点）：殿本人裁只见一形，≥10 且来自 ≥2 册
                         ("wei", "爲為"), ("shuo", "說説"))},
    # —— 两形混用的异体组（2026-10-20）：字频弃权后走在线 IDS 的「按字分类」判法（`ids_online.SPECS`，by_form）；
    #    判不出就送人审，不退到库形最近。模板库在 config/groups/<组>/ids_bank.json。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((FREQ, _img(gid)), combine="first", **_rv(gid)),
        note="异体组：字频→IDS（按字分类）；只在 seed_admit.group_flow 点名时生效。")
       for gid, name in (("xu", "叙敘"), ("ce", "冊册"), ("jiao", "教敎"),
                         # 第二批（2026-10-20 sheldon 异体对第二批审定）：按册留一 0 错
                         ("qik", "啓啟"), ("lih", "厯歴"), ("jue", "絕絶"))},
    # —— 差别不在缝两侧的两形混用异体对（2026-10-20，道 1 续）：字频弃权后走在线 IDS 的「整字岭回归」判法（`ids_whole`，
    #    `ids_online.SPECS[组].whole`）；判不出送人审，不退到库形最近。模板库在 config/groups/<组>/ids_bank.json。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((FREQ, _img(gid)), combine="first", **_rv(gid)),
        note=f"异体组：字频→IDS（整字岭回归）；{note}只在 seed_admit.group_flow 点名时生效。")
       for gid, name, note in (("lv", "呂吕", "差在中间连笔，"), ("zheng", "徵徴", "差在字中上部细节，"))},
    # —— 未覆盖形近字长尾（2026-10-21）：形近不同义，但字形本身分得开（子于：钩与横；山由出：竖与框），走「整字 HOG＋岭回归」，不看文意。
    #    判不出送人审。模板库在 config/groups/<组>/ids_bank.json（组外的 干／曲 也进库，判成它们就弃权）。
    "zy": GroupSpec(
        id="zy", name="子于", members=frozenset("子于"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/zy",
        flow=FlowSpec((_img("zy"),), combine="first", tolerate=frozenset("干")),
        note="形近不同义，按整字字形判（整字岭回归，按册留一 0 错）；干 当陪衬字；只补放。"),
    "sy": GroupSpec(
        id="sy", name="山由出", members=frozenset("山由出"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/sy",
        flow=FlowSpec((_img("sy"),), combine="first", tolerate=frozenset("曲")), overlaps=("chu",),
        note="形近不同义，按整字字形判（一对多岭回归，按册留一 0 错）；曲 当陪衬字；只补放。"),
    # 长尾线第二批（2026-10-22）：宋朱未、各名、心必也走整字字形判。先试过文意路（L1 规则＋haiku L2 表），
    # 在已放行格里与现判不一致的 21 格，看图 21 格全是文意判错，所以弃用，见 doc/design/M7-未覆盖形近字长尾.md 第五节。
    "sz": GroupSpec(
        id="sz", name="宋朱未", members=frozenset("宋朱未"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/sz", overlaps=("wm",),
        flow=FlowSpec((_img("sz"),), combine="first", tolerate=frozenset("末")),
        note="按整字字形判（一对多岭回归）；末 当陪衬字，模板库里也有末；与 wm 共用「未」；只补放。"),
    "gm": GroupSpec(
        id="gm", name="各名", members=frozenset("各名"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/gm",
        flow=FlowSpec((_img("gm"),), combine="first"),
        note="按整字字形判（上部夂／夕）；只补放。"),
    "xb": GroupSpec(
        id="xb", name="心必", members=frozenset("心必"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/xb",
        flow=FlowSpec((_img("xb"),), combine="first"),
        note="按整字字形判（按册留一 0 错）；只补放。"),
    # 字形判法扩面（2026-10-22）：两形混用的异体对，字频不成立（次形不为 0），走取框 HOG＋岭回归；模板＝dataset 人裁（按册留出 0 错）。
    # 次形（衞／删／扺）样本太少，几乎总是弃权送人审。2026-10-24 起也复核（`SHAPE_REVIEW`）：判出另一形就降审。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((_img(gid),), combine="first", **_rv(gid)),
        note=f"异体组：取框 HOG＋岭回归（{note}）；只在 seed_admit.group_flow 点名时生效。")
       for gid, name, note in (("weiw", "衛衞", "看字中下部"), ("shan", "刪删", "看左下的冊／册"), ("di", "扺抵", "看左下到右下"))},
}


#: 码位归一组（sheldon 2026-10-22 定）：两个码位刻形分不清、书里已定用哪一个（册配置 `codepoints:`，各套书可不同），
#: 方法数组只有 `codepoint`——直接给册配置定的那个字；这套书没定就待定。只补放，不复核（放行字最后本来就落册指定码位）。
#: **单独一张表、不进 `GROUPS`**：`GROUPS` 的成员在 `glyph_match`（弱命中）与 `seed_admit.rare_ref_coord` 里当全局字组集合用，
#: 这几对进去会改那两处的行为；字组流程（`flow`）与 `seed_admit.group_flow` 点名用的是 `FLOW_GROUPS`（两张表合起来）。
CODEPOINT_GROUPS: dict[str, GroupSpec] = {
    gid: GroupSpec(id=gid, name=name, members=frozenset(name), backends=(), kind="variant", solvers=(),
                   flow=FlowSpec((CODEPOINT,), combine="first"), overlaps=ov,
                   note="码位归一：给册配置 codepoints 定的那个字；只在 seed_admit.group_flow 点名时生效。")
    for gid, name, ov in (("nei", "內内", ()), ("bie", "別别", ()), ("chu", "出岀", ("sy",)),
                          ("juan", "卷巻", ()), ("wan", "晚晩", ()))
}

#: 只进字组流程、不进 `GROUPS` 的字形组（2026-10-22）：成员里有命、舍、會 这样的常用字——进了 `GROUPS` 会让 `glyph_match` 的弱命中
#: 与 `seed_admit.rare_ref_coord` 把这些字一律当字组字对待，改变全书其他地方的行为。与 `CODEPOINT_GROUPS` 同理单独成表，
#: 只在册配置 `group_flow` 点名时生效。
SHAPE_GROUPS: dict[str, GroupSpec] = {
    "qin": GroupSpec(
        id="qin", name="禽會俞命舍", members=frozenset("禽會俞命舍"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/qin", overlaps=("zh",),
        flow=FlowSpec((_img("qin"),), combine="first", tolerate=frozenset("合愈含")),
        note="按整字字形判（一对多岭回归；曾 合 愈 也进库，判成它们＝弃权）；會 与 zh 共用，入口按分差内候选选组；只补放。"),
    # 按刻形拆判的异体对（2026-10-24，sheldon「异体看刻形，按 IDS 拆判」）：两形殿本都常见、刻形分得开，整理本与台账给的码位常与刻形不符。
    # 整字 HOG＋岭回归，模板＝殿本 vol04–20 已放行格（去掉看图确认码位错的格），按册留出 0 错（research/m7/glyph_expand/build_shape_pair.py）。
    # 复核时把握够就按刻形改码位（`review_fix`），不够不动。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((_img(gid),), combine="first", review=True, review_fix=True),
        note=f"异体对按刻形判（{note}）；补放与复核改码位；只在 seed_admit.group_flow 点名时生效。")
       for gid, name, note in (("shang", "尙尚", "上部 小／⺌"), ("gai", "蓋葢", "草头下 去／大"), ("ba", "䟦跋", "右边 叐／犮"))},
}

#: 字组流程可点名的全部组。
FLOW_GROUPS: dict[str, GroupSpec] = {**GROUPS, **CODEPOINT_GROUPS, **SHAPE_GROUPS}


def get_group(group_id: str) -> GroupSpec:
    return GROUPS[group_id]


def groups_of(ch: str) -> list[GroupSpec]:
    """一个字属于哪些组（可多个：同字可同属两组）。"""
    return [g for g in GROUPS.values() if ch in g.members]
