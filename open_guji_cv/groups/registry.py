"""字组注册表：单一真源。加一组＝在 `GROUPS` 加一项（成员＋`FlowSpec` 方法数组，方法见 `groups/methods.py`），不碰 `seed_admit`。

`seed_admit` 里字组只有一条路：`group_flow`（`groups/flow.py`）。旧的各组开关（`ji_yi_si_*`、`ry_group`、`rr_clf`、
`m7_*`、`variant_tie*`）与它们的升降策略 `GroupPolicy`／`apply.py` 已于 2026-10-18 并进 `group_flow` 后删除（方案 S6）。

⚠ 现有各处还有自己的成员常量（`ji_yi_si_clf.FAMILY`、`rr_clf.CLASSES`…）；
`tests/test_groups_registry.py` 断言这里的成员与它们一致，防漂移。
"""
from __future__ import annotations

from dataclasses import dataclass

from .methods import BARS, CODEPOINT, CTX, FORM_TOP1, JYS_CTX, FREQ, IDS, RR_IMG, RY_SHAPE, TOP1, YR_BARS, Method, Only, describe, hog_or_crop


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
    - `strong_over_ref`：L1 规则给的字与 strong 的 L2 表一致也算 strong（`methods.Chain`，配 `review_fix_strong` 可改字）；补放时
      整理本是组里另一个字（`lift_ref_guard` 的 ref_dissent），文意 strong 也照放。日曰（A24 10-26：「顧炎武日知錄」被 match_ref
      放成曰、「日者列傳」整理本作曰）；
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
      （2026-10-24，A24：字频永远说主形，拿它复核会把真次形也降掉），如 旨㫖：补放 字频→IDS，复核只跑 IDS；
    - `lift_ref_agree`：补放时方法给的字须与整理本字（现役对位缺这一格时用坐标对位字）同字，否则留人审——整理本缺位
      `group_flow_ref_missing`、不同字 `group_flow_ref_dissent`。形近不同义、组员很多的部首族用（門族、辶族，2026-10-24）：
      字形只负责认刻形，字由文本互证，两路一致才放。
    - `lift_ref_veto`：补放时整理本字是组里**另一个字**就留人审（`group_flow_ref_dissent`），不论哪个方法给的字；整理本缺位照常补放。
      一二（2026-10-25，A24）：字块切错时两路字形会一起错（vol19:116:9:8「無一不謬」的格切进了「不」的上横，整字 HOG 与数横都判二），
      整理本作「一」就不该补成「二」。
    - `review_weak`：复核时这几个方法（按名字）只算弱票：它们给了别的字、而别的方法给的都是放行字（至少一个）时不降审。
      入人八随机森林 `rr_img`：vol06–20 复核里单独反对 7 格，5 格是它错（入 判成 人，整字 HOG 与文意都说 入；A24 10-25）。
    - `review_fix_margin`：复核时给了别的字的方法 margin ≥ 这个值才照 `review_fix` 改字，不到照常降审（0＝不用）。改字门槛
      单独按册留出定、比降审门槛高（徵徴：线上同款字块按册留出错例最大 0.63 → 取 0.70；A24 10-25）。
    - `ref_enter`：库 top1 是本组的陪衬字（`tolerate`）、不在组里，但整理本字在组里 → 也许补放进入（字形库里没有这一形，
      库把它排成别的字：算𮅕 的 𮅕 被排成 莫；A24 10-25）。只在同时声明了 `lift_ref_agree` 的组生效。
      先于库首位字所在的组（闗 被库排成 闡間，不先拦就进了门族 men）；现役对位缺格时用坐标对位字（vol49 整页对位缺）。
      声明了 `tolerate_ref_agree` 的组也生效。
    - `ref_enter_member`：`ref_enter` 也放宽到 top1 是本组另一成员、而这个成员又先被别的组点名的情形（選𨕖：整理本作 𨕖、
      库首位 選 是辶族 chuo 的成员，不先拦就进了 chuo；A24 10-26）。整理本字与 top1 相同时不走这条。
    - `tolerate_ref_agree`：补放时分差内（含 top1）出现了**组外**陪衬字的格，方法给的字须与整理本字（缺位时坐标对位字）同字，
      否则留人审（`group_flow_ref_dissent`／`group_flow_ref_missing`）；分差内没有陪衬字的格照旧。陪衬字是库里个别刻例
      「挡门」造成的（形近护栏 N 类，2026-10-26 A24：于千子 被 亍 的一个刻例挡、日曰 被 師 的一个旧切分字块挡），
      放宽进入时多要整理本一路互证，不让陪衬字带进来的格单凭文意改字。
    - `ref_top_enter`：库 top1 在组里、整理本字（现役对位缺格时用坐标对位字）也在组里（按书级码位归一）→ 分差内有组外候选也进入。
      码位归一组用（2026-10-26，A24 全册任务 04）：两码位归同一字，整理本×库首位一致就是要放的字（同 `match_ref` 的文本×形状互证，
      只是库 cov 不到 0.98、整理本只有坐标对位）；繁复字库形常把一串组外字排在分差内（夔 后紧咬 囊蘗𮑮聽臺…，類 后 頗頻顚…），
      逐个登记陪衬登记不完。没有整理本字的格不走这条。
    - `ctx_over`：文意够硬（L1 规则或 L2 表 strong）时，这几个字形方法给了别的字只算弱票，补放、复核都照文意
      （其余方法须不反对）。入人八（A24 10-26）：殿本 入 多刻成两笔分开，整字 HOG 常把 入 判成 八；「不看上下文无法判」。
    - `lift_img_ref_veto`：补放时文意没给这个字（只有字形方法给字）、整理本又是组里另一个字 → 留人审（`group_flow_ref_dissent`）。
      入人八（A24 10-26）：文意查表落空时整字 HOG 单独把整理本的 入 补成了 八（vol12:147:2:17「分其半入禮器」）。
    - `ref_canon`：整理本字、已放行字按书级 `codepoints` 归一后与某个组员归一后同字，也算组里的字（入口、复核都认）；复核时方法给的字与
      放行字归一后同字（且两字不同为组员）算一致。同一刻法有几个码位、组员只用字形库的那个时用（隸𨽾：士示 整理本作 隷／𨽻，
      库标 𨽾，册里 𨽾 𨽻→隷；A24 2026-10-26）。
    - `review_ref_agree`：复核时放行字与整理本字（按码位归一）不是同一字、方法又没给出整理本的字 → 降审（`group_flow_ref_dissent`）；
      方法给了整理本的字照 `review_fix` 改字。整理本跟刻形走得很准、放行字常被别的通道放错码位的组用（隸𨽾：整理本 隸 被放成 𨽾
      44 格，夹注小字 HOG 多弃权，A24 2026-10-26）。
    - `rule_strong`：L1 规则里至少这么多条（不同 id）给了同一个字，文意答案就记 strong（配 `review_fix_strong` 可改字、
      配 `strong_over_ref` 可越过整理本补放）；0＝不用。木本（A24 2026-10-27）：「採進本」「家藏本」夹注小字刻形是本，
      字形库木本分不开（木 1.00 本 0.99），match_solo／match_ref 放成木；全册 113 格送审看图，两条以上规则同说本的 0 错。
    - `review_fix_ref_rule`：复核时 L1 规则给的字与整理本字（现役对位缺格时用坐标对位字，按码位归一）相同、方法之间一致 → 照 `review_fix` 改字
      （文本两路互证压过库形）；只有一条规则、整理本又不同意时照常降审。木本同上（「王楙所見本」「古本」整理本作本、库放木）。
    - `solo_margin`：补放时整理本没有证人——现役对位缺、坐标对位也缺或是 `〓`（逐列本缺字占位）——只凭字形方法补放，
      且给字方法每一段的 margin 都要 ≥ 这个值（`ids` 留痕的 `margins`），不到留人审（`group_flow_solo_weak`）；声明了它的组，
      坐标对位字是 `〓` 不再当「组外字」拦（`coord_dissent`）。0＝不用（`〓` 照旧拦）。
      彝（A24 2026-10-26）：整理本缺字的格逐列本写 〓，80/90 格 U-Net 三段读作 彐米分大（𢑱）；整理本有字的 651 格里，
      与整理本对不上、看图能定的段全是整理本记的码位不跟刻形，唯一字形错例（vol45:59:4:20 下段 大 读成 廾）margin 0.16 → 取 0.3。"""
    methods: tuple
    combine: str = "agree"
    review: bool = False
    review_fix: bool = False
    review_fix_strong: bool = False
    strong_over_ref: bool = False
    pair: tuple = ()
    lift_needs: tuple = ()
    review_abstain: bool = False
    tolerate: frozenset = frozenset()
    families: tuple = ()
    form_methods: tuple = (FREQ, IDS, FORM_TOP1)
    review_methods: tuple = ()
    lift_ref_agree: bool = False
    lift_ref_veto: bool = False
    review_weak: tuple = ()
    review_fix_margin: float = 0.0
    ref_enter: bool = False
    ref_enter_member: bool = False
    tolerate_ref_agree: bool = False
    ref_top_enter: bool = False
    ctx_over: tuple = ()
    lift_img_ref_veto: bool = False
    rule_strong: int = 0
    review_fix_ref_rule: bool = False
    ref_canon: bool = False
    review_ref_agree: bool = False
    solo_margin: float = 0.0

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
SHAPE_REVIEW = frozenset({"zhi", "can", "xu", "jiao", "qik", "lih", "jue", "lv", "weiw", "shan", "di", "yi_560"})


def _rv(gid: str) -> dict:
    return {"review": True, "review_methods": (_img(gid),)} if gid in SHAPE_REVIEW else {}


#: 按刻形拆判的异体对里复核只降不改的：瑣𤨏（2026-10-25）：𤨏 模板只 9 格，攒够前只降审。
#: 尙尚 10-25 曾因 vol16 两格进过这里，放大看是 尙（殿本 尙 上部也有中竖，差在两边外撇／内收），判法没错，已恢复改字。
_SHAPE_PAIR_NO_FIX = frozenset({"suo"})

#: 按刻形拆判的异体对的额外流程设置（2026-10-25，vol21–50 首跑 V 类）：字形库没有少的一形，库把它排成别的字（紧咬的陪衬），
#: 陪衬也进模板库（判成它们＝弃权）；补放须与整理本同字。
#: 整理本作 隠 的格与 𨼆 是同一刻形（建库并成 𨼆，`build_shape_pair.ALIAS`），码位待定前 隠 只作陪衬：已放行的 隠 不复核，整理本作 隠 不补放。
_SHAPE_PAIR_FLOW = {
    "yin": dict(tolerate=frozenset("隠隙臆匱應隔間隋騭隨陋"), lift_ref_agree=True),
    "suan": dict(tolerate=frozenset("莫㝠箕集𡚁篇奧負簋窠纂𢑴簣冀其雙"), lift_ref_agree=True, ref_enter=True),
    "guanm": dict(tolerate=frozenset("闡間閱閣聞闌閩開閑問闚闢"), lift_ref_agree=True, ref_enter=True),
    # vol51–99 首跑 V 类（2026-10-26）：字形库没有 𣲖，库排成 泒孤弧；竒 库常排成 青音；嵗 库排成 歲，也常排成 熾康
    "pai": dict(tolerate=frozenset("泒孤弧滅渢"), lift_ref_agree=True, ref_enter=True),
    "qi": dict(tolerate=frozenset("青音靑苛司可"), lift_ref_agree=True, ref_enter=True),
    "sui": dict(tolerate=frozenset("熾康嚴巖咸戌戲燬"), lift_ref_agree=True, ref_enter=True),
    # 隸𨽾（2026-10-26）：整理本 隸 有 44 格被别的通道放成 𨽾（码位放错），复核改回；库常把 棣練竦 排在分差内
    "li": dict(tolerate=frozenset("隷𨽻棣練竦款羔"), ref_canon=True, lift_ref_agree=True, review_ref_agree=True),
    # 蒙𫎇：整理本 蒙／𫎇 混用（整理本作 蒙、刻 〢丷 的常见），不要求与整理本同字；库常把 家 排在分差内
    "mn": dict(tolerate=frozenset("䝉家冡豪"), ref_canon=True),
    # 選𨕖（2026-10-26，A24 全册任务 03，sheldon 定按刻形照录）：字形库没有 𨕖，库排成 選；整理本两形混用（放行 選 里有丌形），
    # 补放须与整理本同字；整理本作 𨕖、库首位 選 的格先进本组（`ref_enter_member`，選 本是辶族 chuo 的成员）；
    # 复核（已放行 選）按刻形改码位，不看整理本（放行 選 里有 7 格丌形，整理本作 選）。
    # 陪衬放宽到整个辶族：库在辶族里紧咬（選 遺 遵 連 還…分差 0.01–0.03），补放须整理本作 𨕖、字形也判 𨕖，陪衬只放进门。
    "xuan": dict(tolerate=frozenset("通過遺適迥遇運道迫遁遣進違逋邁還遼逆遍逸遭連邇遠退逾述近迎造遵遞追邊巡遷遜遲避邀𨒪遴題"),
                 lift_ref_agree=True, ref_enter=True, ref_enter_member=True),
    # 勢𫝑 發𤼵（2026-10-25，sheldon 定按刻形分拆）：库首位几乎都是 勢／發；分差内常紧咬的组外字当陪衬放进入口
    # （登務條 也进模板库，判成它们＝弃权；𫉬顧勞 不进库，只放行入口，字仍由本组判 發𤼵／勢𫝑）。整理本两形混用，不要求与整理本同字。
    "shi": dict(tolerate=frozenset("勞")),
    "fa": dict(tolerate=frozenset("登務條𫉬顧")),
}
#: 闗關 与门族 men 共用 關：men 只补放不复核，已放行的 關 归 guanm 复核（刻 闗 放成 關 的改码位）
_SHAPE_PAIR_OVERLAPS = {"guanm": ("men",), "xuan": ("chuo",), "xun": ("chuo",)}


#: 文意组里加了字形第二路的组（2026-10-22；判法与门槛见 `ids_online.SPECS` 同名行）。方法数组里排在文意之后，`agree`：
#: 文意弃权时字形可单独补放，两路都给字须一致，否则送审；复核时字形给了别的字就降审。
GLYPH2 = frozenset({"rr", "ts", "ly", "wj", "zh", "yh", "yt", "js", "em", "fc", "yr"})


def _g2(gid: str) -> tuple:
    return (_img(gid),) if gid in GLYPH2 else ()


#: 一二（2026-10-25，A24「优化一二判别」）：文意 → 整字 HOG → 数横（`bars.count_bars`），三路 `agree`。
#: 文意规则在册外回测冲突、10-24 下线了 21 条，剩下的格文意大多定不了（「此本僅◎十卷」「壬戌◎月」），刻形却一眼可辨。
#: - 补放须文意或数横给字（`lift_needs`）：整字 HOG 在列尾格会把边框线当成第二横（vol08:7:6:21），不许单独补放；
#: - 整理本是组里另一个字就不补放（`lift_ref_veto`）：字块切错时两路字形一起错（vol19:116:9:8）；
#: - 复核：任何一路给了另一个字就降审（只降不改）。
#: vol04–20 已放行 7,545 格：数横给字 7,148、与放行字 0 不一致。见 `doc/字组/yr.md`。
_YR_FLOW = FlowSpec((CTX, _img("yr"), YR_BARS), review=True, lift_needs=("ctx", "yr_bars"), lift_ref_veto=True)

#: 木本（2026-10-27，A24「压低木本送审」）：文意定字，字形库分不开（夹注小字 本 被库排成 木 1.00）。
#: - 两条以上 L1 规则同说一个字算 strong（`rule_strong=2`）：复核改字（`review_fix_strong`）、补放越过整理本（`strong_over_ref`）；
#: - 一条规则＋整理本同字也改字（`review_fix_ref_rule`）；其余照旧降审。
#: 全册 main 包 60 册离线回放：送审 113→33，改字／补放 83 格逐格看图 0 错。见 `doc/字组/mb.md`。
_MB_FLOW = FlowSpec((CTX, *_g2("mb")), review=True, review_fix_strong=True, strong_over_ref=True, rule_strong=2,
                    review_fix_ref_rule=True)


#: 文意组与字形组共字（入口按分差内候选选组，点名靠前的先试）：會（zh／qin）、問間（wj／men）、遺還（yh／chuo）、圓圖（yt／kou）。
_GLYPH_OVERLAPS = {"zh": ("qin",), "wj": ("men",), "yh": ("chuo",), "yt": ("kou",)}

GROUPS: dict[str, GroupSpec] = {
    "jys": GroupSpec(
        id="jys", name="己已巳", members=frozenset("己已巳"),
        backends=("rule", "ctx_table", "table"),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/jys",
        flow=FlowSpec((JYS_CTX,), review=True, review_fix=True, review_abstain=True, tolerate=frozenset("巴"),
                     pair=("己", "巳")), ref_free=True,
        note="按文意定（L1 规则含旧 ji_yi_si_clf 规则路，弃权查 L2 表）；已放行的本族格无文意证据也降审。巴是库形陪衬（vol04–10 有 17 格因分差内的巴没进流程；L2 有「其他」出口，真是巴会弃权）。前一字也是族字（干支「己巳」的第二字）时不查 L2 表。L2 表由 haiku 建、Opus＋Sonnet 离线复核（`groups/l2_panel`：Opus high 反对就否决；haiku 不是 high 时 Opus high 且 Sonnet 同字才补字）。"),
    "ry": GroupSpec(
        id="ry", name="日曰", members=frozenset("日曰"),
        backends=("table",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/ry",
        flow=FlowSpec((CTX, RY_SHAPE), review=True, review_fix_strong=True, strong_over_ref=True, lift_needs=("ctx",),
                     tolerate=frozenset("師"), tolerate_ref_agree=True, ref_enter=True), overlaps=("rm",),
        note="按文意定（L1 规则，弃权查 L2 表）＋字形宽高比（日窄曰宽，只当第二路：强烈指向另一个字就降审，不单独补放）；补放，也复核（只降审不改字）。与日目组 rm 共用「日」。"),
    "rr": GroupSpec(
        id="rr", name="入人八", members=frozenset("人入八"),
        backends=("image",),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "image"), config_dir="config/groups/rr",
        flow=FlowSpec((CTX, RR_IMG, *_g2("rr")), review=True, lift_needs=("ctx", "ids"), review_weak=("rr_img",),
                      ctx_over=("rr_img", "ids"), lift_img_ref_veto=True, review_fix_strong=True),
        note="文意＋字形分类器＋整字 HOG（上半）；补放要文意或整字 HOG 给字且各路不冲突（随机森林分类器不单独补放），复核时任一路给了别的字就降审（随机森林是弱票：别的路都支持放行字时它单独反对不降）。文意 strong 或 L1 规则时两路字形都只算弱票，复核可照 strong 文意改字；文意没给字时字形不许拗整理本补放（A24 10-26）。"),
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
                      **({"form_methods": (FREQ, FORM_TOP1)} if gid == "zh" else {})), overlaps=_GLYPH_OVERLAPS.get(gid, ()),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("ly", "論諭", "論＝議論；諭＝詔諭、上諭。"), ("dt", "大太", "太只收官名帝号类；大史／太史等两可词弃权。"),
                               ("wj", "問間", "間＝其間、間有、年間；問＝詢問、學問。"), ("zh", "曾會㑹", "會＝會典、附會；曾＝曾經、姓氏。㑹是會的异体：先按文意定曾／會族，會㑹再按刻形（字频→IDS→库形最近）定哪一形。"),
                               ("yh", "遺還", "遺＝遺文、補遺；還＝還朝、返還。"))},
    # —— 第四批（2026-10-19）：象彖、王玉、圓圖。同前，L1 零冲突＋逐册 L2 表。
    #    象彖𧰼 加 `lift_ref_agree`（2026-10-26，A24 全册任务 08）：象／𧰼 刻形差一竖，字形单判过不了按册留出 0 错，
    #    补放须与整理本（缺位用坐标对位字）同字；整理本跟刻形走（人裁 𧰼 里整理本也作 𧰼 的约九成）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((CTX, *_g2(gid)), review=True, families=FAMILIES.get(gid, ()),
                      **({"lift_ref_agree": True} if gid == "xz" else {})), overlaps=_GLYPH_OVERLAPS.get(gid, ()),
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, note in (("xz", "象彖𧰼", "彖傳＝释卦辞；象傳＝释卦象；象數、取象为象。𧰼是象的异体：先按文意定彖／象族，象𧰼再按刻形（字频→IDS→库形最近）定哪一形。"), ("wyu", "王玉", "王＝王弼等人名、帝王；玉＝玉器、玉海。"),
                               ("yt", "圓圖", "圖＝河圖、圖書、圖說；圓＝圓通、渾圓、方圓。"))},
    # —— 日目（2026-10-19）：与 ry 共用「日」（互相声明 overlaps），入口按分差内候选选组：日曰候选归 ry，日目候选归 rm，三者混杂留人审。
    "rm": GroupSpec(
        id="rm", name="日目", members=frozenset("日目"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/rm",
        flow=FlowSpec((CTX,), review=True), overlaps=("ry", "mz"),
        note="按文意定；与 ry 共用「日」。目＝書目、總目、存目；日＝今日、是日、日月。"),
    # —— 第五批（2026-10-19）：目自、一二、十卜、甲申、而面、傅傳、木本。同前：L1 规则（整理本奇偶册交叉验证零冲突）＋逐册 L2 表。
    #    目自与 rm 共用「目」（互相声明 overlaps）。千干 qg 2026-10-24 并进 于千子干 zy（`RENAMED`）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=_YR_FLOW if gid == "yr" else _MB_FLOW if gid == "mb" else FlowSpec((CTX, *_g2(gid)), review=True), overlaps=ov,
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（{'规则够硬时改字' if gid == 'mb' else '只降审不改字'}）。{note}")
       for gid, name, ov, note in (
           ("mz", "目自", ("rm",), "目＝總目、書目、存目；自＝自序、所自、自某代以來。"),
           ("yr", "一二", (), "数词序列：卷一、第二、一二、二十一。"),
           ("sb", "十卜", (), "十＝十二、十卷；卜＝占卜、卜筮、卜子。"),
           ("js", "甲申", (), "干支：甲子、甲乙；申＝申明、申屠、庚申。"),
           ("em", "而面", (), "而＝虚词；面＝東面、南面、四面。"),
           ("fc", "傅傳", (), "傳＝傳注、經傳、傳記；傅＝傅會、傅寅、傅以漸、太傅。"),
           ("mb", "木本", (), "本＝版本、原本、本草；木＝草木、木瓜、木部。"))},
    "yi_560": GroupSpec(
        id="yi_560", name="彝彛彜彞𢑱𢑴", members=frozenset("彝彛彜彞𢑱𢑴"),
        backends=(),
        kind="variant", solvers=("ids",), config_dir="config/groups/yi_560",
        flow=FlowSpec((FREQ, _img("yi_560")), combine="first", tolerate=frozenset("尋舞彚"), solo_margin=0.3,
                     review_fix_margin=0.3, **_rv("yi_560")),
        note="异体字组（#560）：字频→IDS 三段（上彑彐／中米糸米分／下廾大，自动缝，42 格模板）；判不出送人审，不退到库形最近。"
             "只在 seed_admit.group_flow 点名时生效。"),
    # —— 异体组（字组统一流程首批，2026-10-18 sheldon 定）：即旧 `variant_tie_extra` 用户裁过的七组。
    #    判法：字频成立就定；否则 IDS（尚未在线，弃权）；再否则沿用旧 variant_tie「库形最近的码位」（top1 cov ≥ 0.97）。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=cfg,
        flow=FlowSpec((FREQ, _img(gid), TOP1), combine="first", **_rv(gid)),
        note="异体组：字频→IDS→库形最近；只在 seed_admit.group_flow 点名时生效。")
        for gid, name, cfg in (("dian", "點㸃", None),
                               ("chen", "讖識䜟", None), ("shen", "慎愼", "config/groups/shen"),
                              ("zhi", "旨㫖", "config/groups/zhi"))},
    # 參㕘叅（2026-10-26，A24「压低參㕘叅送审」）：殿本 㕘／叅 刻形只差下部钩右边一笔（㕘）还是一点一撇两笔（叅）；
    # 整理本一律作 叅、字形库偏 㕘，都不能当证据，所以去掉库形最近（TOP1）。IDS 下块（两刀）＋整字 HOG 两路一致才给字
    # （`ids_online.SPECS["can"].dual`）；复核时两路都判成组里另一形就按刻形改码位（`review_fix`），判不出不动。
    "can": GroupSpec(
        id="can", name="參㕘叅", members=frozenset("參㕘叅"), backends=(),
        kind="variant", solvers=("ids",), config_dir="config/groups/can",
        flow=FlowSpec((FREQ, _img("can")), combine="first", review_fix=True, **_rv("can")),
        note="异体组：字频→IDS 下块与整字 HOG 两路一致；补放与复核改码位；只在 seed_admit.group_flow 点名时生效。"),
    # —— 第二批异体组（2026-10-18 sheldon 定）：只靠字频。人裁数不够（主形 <20 或次形不为 0）时弃权、送人审，
    #    不退到 IDS／库形最近；字频表重算后数据攒够就自动放行。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=(), config_dir=None,
        flow=FlowSpec((FREQ,), combine="first"),
        note="异体组：只看字频；数据不够送人审，重算字频表后自动放行。只在 seed_admit.group_flow 点名时生效。")
       # 變𠮓 2026-10-25 改为按刻形拆判（见下方 SHAPE 组 bian）
       for gid, name in (("ji", "即卽"), ("qing", "卿𨜊"), ("hui", "彙彚"),
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
        flow=FlowSpec((FREQ, _img(gid)), combine="first", **_rv(gid), review_fix_margin=fm),
        note=f"异体组：字频→IDS（整字岭回归）；{note}只在 seed_admit.group_flow 点名时生效。")
       # 徵徴 zheng 2026-10-27 改成码位组（sheldon 定暂归一到 徴，见下方 `CODEPOINT_GROUPS`）
       for gid, name, note, fm in (("lv", "呂吕", "差在中间连笔，", 0.0),)},
    # —— 未覆盖形近字长尾（2026-10-21）：形近不同义，但字形本身分得开（子于：钩与横；山由出：竖与框），走「整字 HOG＋岭回归」，不看文意。
    #    判不出送人审。模板库在 config/groups/<组>/ids_bank.json（组外的 干／曲 也进库，判成它们就弃权）。
    # 于千子干（2026-10-24，A24「强化于千子干等形近判别」）：子于 zy 与 千干 qg 并成一组。vol04–20 送审里这四个字常三四个一起紧咬
    #   （「禘【于】太廟」库排 子于干千），哪一组都装不下。不同义，按文意定（L1 规则＋L2 表）；原子于整字 HOG 留作第二路，
    #   只在分差内候选与整理本字都落在 子于干 时跑、只给 子于（`Only`：它没见过 千，干 在库里只当陪衬），两路给字须一致。复核只跑文意（L1；表里没有的格不动）。
    "zy": GroupSpec(
        id="zy", name="于千子干", members=frozenset("于千子干"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2", "ids"), config_dir="config/groups/zy",
        flow=FlowSpec((CTX, Only("ids", inner=_img("zy"), chars=frozenset("子于干"), give=frozenset("子于"))), review=True, review_methods=(CTX,),
                      tolerate=frozenset("干亍"), tolerate_ref_agree=True, ref_enter=True), overlaps=("yz",),
        note="形近不同义，按文意定（L1 规则，弃权查 L2 表）；子于整字 HOG 当第二路（只在分差内全是 子于干 时跑），给字须一致；"
             "补放，也复核（只跑文意，只降审不改字）。与 予子 yz 共用「子」。千干 qg 已并入（册配置里的 qg 读作 zy）。"),
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
#: 2026-10-26（A24 全册任务 04「码位已定仍送审」）：码位组都开 `ref_top_enter`（库首位与整理本／坐标对位字同在组里就进，分差内的组外字不拦），
#: 出岀 除外（与 山由出 sy 共字，分差内有 山由 的归 sy 按文意判）；加 類𩔖 竄𥨥 郎郞（sheldon 10-25 定暂归一）。
#: 別别 改成按字形判（移到 `_NEAR_FAMILY`）：库首位常是 刖 則 所（cov 0.99 一档里分不开），要整字 HOG 认出 別 才补放。
_CP_NO_TOP = frozenset({"chu"})
CODEPOINT_GROUPS: dict[str, GroupSpec] = {
    gid: GroupSpec(id=gid, name=name, members=frozenset(name), backends=(), kind="variant", solvers=(),
                   flow=FlowSpec((CODEPOINT,), combine="first", tolerate=frozenset(tol), lift_ref_agree=bool(tol),
                                 ref_top_enter=gid not in _CP_NO_TOP), overlaps=ov,
                   note="码位归一：给册配置 codepoints 定的那个字；只在 seed_admit.group_flow 点名时生效。")
    for gid, name, ov, tol in (("nei", "內内", (), ""), ("chu", "出岀", ("sy",), ""),
                               ("juan", "卷巻", (), ""), ("wan", "晚晩", (), ""),
                               # 2026-10-25（A24 异体对 5–11 格）：殿本每对只一种刻法，码位 sheldon 逐对定（𫉬→獲、夔→䕫、獵→𤢪）。
                               # 繁复字库形常把组外的繁复字排在分差内（夔 后紧咬 囊蘗𢑱憂…），`tolerate` 放它们进入；
                               # 进入放宽了，所以补放须与整理本同字（`lift_ref_agree`，按书级码位归一后比）。
                               ("huo", "獲𫉬", (), "覆複藻襲搜護"),
                               # vol21–50 首跑（A24 10-25）：夔 后还紧咬 𮑮襄𠮓變雙凌，16 格进不了组送审，补进陪衬
                               ("kui", "夔䕫", (), "囊蘗蔑𢑱𢑴憂藝難璉襲喪藎謩蔓雜製鑒甄𮑮襄𠮓變雙凌"),
                               ("lie", "獵𤢪", (), "猶亂侃猥"),
                               # 2026-10-26（A24 全册任务 04）：sheldon 10-25 定暂归一的三对（𩔖→類 竄→𥨥 郎→郞）
                               ("lei", "類𩔖", (), ""), ("cuan", "竄𥨥", (), ""), ("lang", "郎郞", (), ""),
                               # 2026-10-27 sheldon 定 徵→徴 暂归一：整字 HOG 加 59 格人裁重训仍有错（margin 到 0.85），原整字判法撤下
                               ("zheng", "徵徴", (), ""),
                               # 2026-10-28（A24 第 1 轮「䇿/策 送审暴涨」）：策→䇿 是 10-26 sheldon 定的组外异体对暂归一（codepoints 已在中心库），
                               # 但库里 策／䇿 cov 并列（0.97–0.99 < same 档 0.996）、文意 margin≈0，整理本字（归一后 䇿）又进不了任何组，
                               # 全册 244 格送审。建成码位组，库首位与整理本同在组里就进。
                               ("cek", "策䇿", (), ""))
}

#: 码位已定、库在形近字间拿不准的族（2026-10-26，A24 全册任务 04）：(组, 成员, 入口陪衬, 说明)。入口陪衬＝全 98 册整理本作本组字的格里
#: 库形排在分差内的组外字（模板库只收其中常见的几个，见 build_shape_pair.PLAN；其余判不成它们，靠与整理本同字兜）。
_NEAR_FAMILY = (
    ("xiang", "鄉鄕", "卿嫏瑯郡郞鄭柳御綱鄒那郎細邲紳錦郷郵聊辨廓劍螂鄊純絀鉤總酈緗部締鄱狎廁蒯", "左边 乡／卯左；陪衬 卿鄭鄒郡"),
    ("weim", "微㣲", "徴徵徹倣敝撤", "中部 山一几（口）／山一王；陪衬 徵徴徹"),
    ("bie", "別别", "刖所則冊册刑問刪創副加", "左边 另／月 等；陪衬 刖則所冊册"),
    ("zhen", "鎭鎮", "鏤鍾愼錢銀鏡鈿錄傎領鉞鉤銅鑽鐵銷顚集填慎欽鐫窺纂續錐鐘龔錦鈎僎類輿蹟無蠡翼鍵僕鉅餉頒創與錟",
     "右边 眞／重 等；陪衬 鍾愼慎鏡鏤銷續錢鈿鑽錄鉤鉞銀鍵"),
)

#: 只进字组流程、不进 `GROUPS` 的字形组（2026-10-22）：成员里有命、舍、會 这样的常用字——进了 `GROUPS` 会让 `glyph_match` 的弱命中
#: 与 `seed_admit.rare_ref_coord` 把这些字一律当字组字对待，改变全书其他地方的行为。与 `CODEPOINT_GROUPS` 同理单独成表，
#: 只在册配置 `group_flow` 点名时生效。
SHAPE_GROUPS: dict[str, GroupSpec] = {
    "qin": GroupSpec(
        id="qin", name="禽會俞命舍", members=frozenset("禽會俞命舍"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/qin", overlaps=("zh",),
        flow=FlowSpec((_img("qin"),), combine="first", tolerate=frozenset("合愈含")),
        note="按整字字形判（一对多岭回归；曾 合 愈 也进库，判成它们＝弃权）；會 与 zh 共用，入口按分差内候选选组；只补放。"),
    # 口框族（2026-10-24，A24 铺开计划 #2）：國圖圍園固圓圜 都是 囗 框，差在框内部件，形近不同义但字形分得开（库形常在几字间判不定，
    # vol11–20 形近护栏送审约 13 格）。框内取块（x 0.12–0.88、y 0.1–0.9）整字 HOG 一对多；圃 圈 囿 进库当陪衬（判成它们＝弃权）。
    # 團 殿本 vol04–20 没有一格放行，建不了模板，不进组（整理本作 團 的格进不了流程，照旧人审）。
    # 字形单独判不稳（按册留出 2,996 格里清楚的 國 偶有高把握判成 圓），所以补放还要整理本（缺时坐标对位字）同字（`lift_ref_agree`）。
    # 与 yt（圓圖，文意）共用 圓 圖：册 group_flow 里 yt 排在前面，只有 圓圖 两个候选的格仍归 yt 按文意判。只补放。
    "kou": GroupSpec(
        id="kou", name="國圖圍園固圓圜", members=frozenset("國圖圍園固圓圜"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/kou", overlaps=("yt",),
        flow=FlowSpec((_img("kou"),), combine="first", tolerate=frozenset("圃圈囿"), lift_ref_agree=True),
        note="口框族：按框内字形判（一对多岭回归；圃 圈 囿 也进库，判成它们＝弃权），须与整理本同字才补放；与 yt 共用 圓 圖，册里 yt 排前；只补放。"),
    # 按刻形拆判的异体对（2026-10-24，sheldon「异体看刻形，按 IDS 拆判」）：两形殿本都常见、刻形分得开，整理本与台账给的码位常与刻形不符。
    # 整字 HOG＋岭回归，模板＝殿本 vol04–20 已放行格（去掉看图确认码位错的格），按册留出 0 错（research/m7/glyph_expand/build_shape_pair.py）。
    # 复核时把握够就按刻形改码位（`review_fix`），不够不动。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}", overlaps=_SHAPE_PAIR_OVERLAPS.get(gid, ()),
        flow=FlowSpec((_img(gid),), combine="first", review=True, review_fix=gid not in _SHAPE_PAIR_NO_FIX,
                      **_SHAPE_PAIR_FLOW.get(gid, {})),
        note=f"异体对按刻形判（{note}）；{'补放，复核只降审' if gid in _SHAPE_PAIR_NO_FIX else '补放与复核改码位'}；只在 seed_admit.group_flow 点名时生效。")
       for gid, name, note in (("shang", "尙尚", "上部 小／⺌"), ("gai", "蓋葢", "草头下 去／大"), ("ba", "䟦跋", "右边 叐／犮"),
                               # 长尾异体对（2026-10-24）：两形放行都 ≥20、刻形分得开的只有这两对；緒緖、鄉鄕 殿本只一种刻形，不建组
                               ("zhun", "凖準", "左旁 冫／氵"), ("mi", "宻密", "中部 㐅／必"),
                               # 3–4 格异体对（2026-10-24）：7 对里只有这一对两形放行都 ≥20、刻形分得开
                               ("zhuan", "撰𢰅", "右下 共／丌"),
                               # 䘮喪（2026-10-25）：殿本两形都常见；整理本 䘮喪 混用，放行跟整理本走时有刻 䘮 放成 喪 的
                               ("sang", "䘮喪", "中部 从／吅"),
                               # 變𠮓（2026-10-25）：工作区码位归一 變→𠮓 早先当「殿本只一种刻形」，sheldon 看图标出 107 格 變（下部 攵，左上多一短撇）；
                               # 只给 變（判成 𠮓 弃权，保持码位归一的 𠮓），复核改码位
                               ("bian", "變𠮓", "下部 攵／又"),
                               # 瑣𤨏（2026-10-25，GUJI-719）：两种刻法一眼可分，但 𤨏 只 9 格（每类至少 5 例才给字），复核只降审不改码位
                               ("suo", "瑣𤨏", "右上 ⺌／巛"),
                               # vol21–50 首跑 V 类（2026-10-25）：字形库没有少的一形（𨼆 𮅕），库排成常见形或别的字；刻形一眼可分
                               ("yin", "隱𨼆", "右上 爫工／平顶 丅⺊"), ("suan", "算𮅕", "下部 廾／大"), ("guanm", "闗關", "門内下部 灬／丱"),
                               # 勢𫝑 發𤼵（2026-10-25）：放行格两形混放，标签全是 sheldon 在标注页逐格过的（dataset variant/{shi,fa}）
                               ("shi", "勢𫝑", "左上 坴／幸"), ("fa", "發𤼵", "右下 殳／矢"),
                               # vol51–99 首跑 V 类（2026-10-26）：两形都有、刻形一眼可分；放行字跟整理本走、混放，首轮留出错例看图改标
                               ("pai", "派𣲖", "右边 𠂢 有横／无横三竖"), ("qi", "奇竒", "上部 大／立"), ("sui", "歲嵗", "上部 止／山"),
                               # 隸𨽾（2026-10-26，A24 全册任务 07；原第一批 字频→IDS→库形最近）：殿本两种刻法，左上 木（柰）／士（士示）；
                               # 士示 整理本作 隷 或 𨽻、字形库标 𨽾，录哪个码位由书级 `codepoints` 定（组只认刻形）
                               ("li", "隸𨽾", "左上 木（柰）／士（士示）"),
                               # 蒙𫎇（2026-10-26，同上；原第一批）：头部 艹／〢丷。旧判法「库形最近」会把 艹 头放成 𫎇（库两形紧咬）；
                               # 整理本作 䝉 的与 𫎇 同一刻法，录哪个码位由书级 `codepoints` 定
                               ("mn", "蒙𫎇", "头部 艹／〢丷（两竖带点）"),
                               # 组外异体对（2026-10-26，A24 全册任务 01）：sheldon 在定码位页选「留人审」＝建组按刻形分；HOG 两类聚类看图，
                               # 15 对确有两种刻法，建了其中复核看图没出错的 11 对（彦彥 㓜幼 复核把已放行格判反、劫刼 𪔂鼎 切块残，不建；另 17 对看不出差别，照旧人审）。标签＝聚类去掉低把握 15%（dataset variant/<组>/）
                               ("yinv", "陰隂", "右边 今云／侌"), ("xian", "陷䧟", "右上 臽 头 ⺈／平头"), ("shu", "䟽疏", "左旁 足字旁／疋"),
                               ("ning", "寧寜", "中部 皿／用"), ("yao", "謠謡", "右边写法两种（看组卡图）"),
                               ("jim", "覊羈", "上部 覀／罒"), ("xun", "巡廵", "走之 辶／廴"),
                               ("jian", "劍劔", "右边 刂／刃"), ("chi", "勅敕", "右边 力／攵"),
                               ("bi", "𡚁弊", "下部 大／廾"), ("huiq", "囘回", "内部 己／口"),
                               # 全册任务 03（2026-10-26）：两形都有、整理本混用，sheldon 定按刻形照录
                               ("xuan", "選𨕖", "巽下 共／丌"))},
    # 码位已定仍送审的形近族（2026-10-26，A24 全册任务 04）：整理本作 鄉鄕／㣲微／別别／鎭鎮（码位已定 鄉→鄕 㣲→微 别→別 鎮→鎭），字形库却在
    # 形近的另一个字上拿不准（cov 差 0.01 内），库首位常就是它：鄉 排成 卿（殿本 卿 右作 阝，与 鄉 只差左边 乡／卯左），㣲 排成 徵徴，
    # 別 排成 刖所則（cov 0.99 一档），鎭 排成 鍾愼鏤…。別别 原是码位组（只给码位），10-26 移到这里。
    # 整字 HOG 一对多：两码位并成一类，形近字当陪衬进库（判成它们＝弃权）；补放须与整理本（缺位时坐标对位字）同字，库首位是陪衬也按整理本进入
    # （`ref_enter`）。只补放：成员只一类，复核不会给出组里另一个字。陪衬见 `_NEAR_FAMILY`，判法与门槛见 `ids_online.SPECS` 与卡。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="variant", solvers=("ids",), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((_img(gid),), combine="first", tolerate=frozenset(tol), lift_ref_agree=True, ref_enter=True),
        note=f"{name[0]} 与形近字按整字字形判（{note}；陪衬进库，判成它们＝弃权），须与整理本同字才补放；只补放。")
       for gid, name, tol, note in _NEAR_FAMILY},
    # 广宀族（2026-10-24，A24）：「蕤賔」的 賔 字形库里没有，库把它排成 實廣（再往后 墳須寅賞…），形近护栏拦下送审（vol19 十几格）。
    # 整字 HOG 一对多，只给 賔／賓（`ids_online.SPECS["guang"].give`；實廣 判出来也弃权，库本来认得）；賔賓 按刻形各给各的码位。
    # 陪衬＝模板库里的陪衬类（判成它们＝弃权），入口才容许它们紧咬。复核只降不改：已放行 實廣 而判出 賔賓 的降审
    # （vol19 回放 2 格，看图都是刻 賔、被文意通道放成 廣／實 的错放）。
    "guang": GroupSpec(
        id="guang", name="廣實賔賓宸", members=frozenset("廣實賔賓宸"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/guang",
        flow=FlowSpec((_img("guang"),), combine="first", review=True, tolerate=frozenset("寶寳寅賞墳須煩裒盧資質贋寫竇賁責貴")),
        note="按整字字形判（一对多岭回归，只给 賔賓；成员 實廣宸 只当入口，陪衬与「其他」池判中＝弃权）；补放＋复核降审。"),
    # 形近护栏的部首族（2026-10-24，A24）：库形在一族字里紧咬（間0.955 閩0.952 聞0.951…），形近护栏拦下送审。
    # 整字 HOG 一对多认刻形（模板＝殿本 vol04–20 已放行格，组外常见陪衬字也进库，判成它们＝弃权），
    # 与整理本同字才补放（`lift_ref_agree`）；只补放，不复核。组员是殿本里常见的族字，陪衬是库形常排在分差内的组外字。
    "men": GroupSpec(
        id="men", name="門族", members=frozenset("間聞問闡閱閣闢關閩閭開闌閔闇閑闕閨門閒閻閏閉闚閶閎闈闞"), backends=(),
        kind="near_form", solvers=("ids",), config_dir="config/groups/men", overlaps=("wj", "guanm"),
        flow=FlowSpec((_img("men"),), combine="first", lift_ref_agree=True,
                      tolerate=frozenset("刪删圖固同國岡剛圓冊因曲罔四明附則圍副嗣隅制冏團潤蘭困題順顯昭用"
                                         "𠕢𨴀閳䕡𨴏閜閹𨶽𦣧𨳼閰𨵅𨷺𢢅𦚻𭟧𨴕劂𨳸腢闆𨷯𨶇𭬸𠱬𨶏")),
        note="門族（形近不同义）：整字 HOG 一对多认刻形，与整理本同字才补放；問間 与 wj 共用（点名排在 wj 之后）、關 与 guanm 共用；只补放。"),
    "chuo": GroupSpec(
        id="chuo", name="辶族", members=frozenset("通過遺適迥遇運道迫遁遣進違逋邁還遼逆遍逸遭連邇遠退逾選述近迎造遵遞追邊巡遷遜"),
        backends=(), kind="near_form", solvers=("ids",), config_dir="config/groups/chuo", overlaps=("yh", "xuan", "xun"),
        flow=FlowSpec((_img("chuo"),), combine="first", lift_ref_agree=True,
                      tolerate=frozenset("逈𮞉䢛𨓺𮞘蓮𨖳𨒪遖遗𨑬迵𨒵週𬨡遴适𨒒𨓓逓𲆌逝題𨒡𨓠𨕝𨖍𨗞𮞪䢗地")),
        note="辶族（形近不同义）：取右上框（避开走之底）HOG 一对多认刻形，与整理本同字才补放；遺還 与 yh 共用（点名排在 yh 之后）；"
             "逈（迥的异体）不进组，归异体对处理；只补放。"),
    # 形近不同字对族（2026-10-26，A24「组外异体对未定码位」）：整理本×库首位是一对形近不同字（住往 冶治 壙曠 翦前 冷令…），
    # 刻形分得开、库里却缺刻例或排错。同门族：整字 HOG 一对多认刻形，与整理本同字才补放；只补放。
    "xjz": GroupSpec(
        id="xjz", name="形近不同字对", members=frozenset("冶治冐冑胄齊齋住往榮滎祇祗前翦揚楊水永孰熟窿隆嘗當勾句仝全章草壙曠卑埤可阿令冷偏徧釆采"),
        backends=(), kind="near_form", solvers=("ids",), config_dir="config/groups/xjz",
        flow=FlowSpec((_img("xjz"),), combine="first", lift_ref_agree=True, ref_enter=True,
                      tolerate=frozenset("柱木未耒米朱洽蔣朝剌牘擴墳墉蹟廣編冒問目常官旬勻甸幻金有舍革尊揭場粲柴禄陸歴匪氷僅性仲周何卓阜肅亦書𤰞"
                                         "晰岀自日蕪轉華敦")),
        note="形近不同字对族：整字 HOG 一对多认刻形（门槛 0.7），与整理本同字才补放；只补放。釆 只当入口（库里的 釆 刻例都是 采）。"),
    # 形近不同义、按文意定的小组（2026-10-24，A24「强化于千子干等形近判别」）：库常把两三个字排到分差 0.003 以内（「學【官】」库排 宫官），
    # 形近护栏拦下送审。按文意定（L1 规则＋L2 表；L2 表由 haiku 建、Opus＋Sonnet 复核，同 jys）；补放，也复核（只降审不改字）。
    # 放这张表不放 `GROUPS`：官 兩 侯 是常用字，进 `GROUPS` 会改 glyph_match 弱命中与 rare_ref_coord 的行为。
    # 族里有同字异体的走两段判（`families`）：文意定族，族内按库形最近（领先族内另一形 ≥ form_margin），定不下来送审。
    # 宫宮：殿本 宮 放行只 8 格、人裁 3 格，刻法也不一，不够建字形判法（#5 线程 10-24 结论），所以族内只靠库形最近。
    **{gid: GroupSpec(
        id=gid, name=name, members=frozenset(name), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir=f"config/groups/{gid}",
        flow=FlowSpec((CTX,), review=True, families=fam, form_methods=(FORM_TOP1,)), overlaps=ov,
        note=f"按文意定（L1 规则，弃权查 L2 表）；补放，也复核（只降审不改字）。{note}")
       for gid, name, fam, ov, note in (
           ("yz", "予子", (), ("zy",), "予＝賜予、予奪、我；子＝孔子、國子、君子。與 于千子干 zy 共用「子」，分差内有 予 的格归本组。"),
           ("guan", "官宫宮", ("官", "宫宮"), (), "官＝官至、職官、天官；宫＝宫室、殯宫、宫調。宮是宫的异体：先定 官／宫族，族内按库形最近。"),
           ("hou", "侯候𠉀俟", ("侯", "候𠉀", "俟"), (), "侯＝諸侯、夏侯、某國侯；候＝氣候、七十二候、候補；俟＝等待。𠉀是候的异体。"),
           ("liang", "兩雨", (), (), "兩＝兩江、兩淮、兩家；雨＝風雨、雨水。"))},
    # 逄逢（2026-10-26，A24「组外异体对未定码位」）：殿本 逢 的刻形与库里的 逄 一样（库形 逄 多是 逢 的刻例），整理本也有把「遭逢」
    # 录成 逄 的（vol93:12:2:7）。按文意定：逄 只作姓（逄蒙、逄萌、辨逄逢的字书条）；文意 strong 才改已放行的字、才不跟整理本。
    # 刺剌（2026-10-27，A24；sheldon 10-27 定按文意录）：殿本 刺 常刻成 剌 的样子（左作 束），库形分不开。按文意定：剌 只用于译音人名
    # （薩都剌、阿剌）与 乖剌、剌謬 这类；其余是 刺。文意 strong 才改已放行的字、才不跟整理本。
    "ci": GroupSpec(
        id="ci", name="刺剌", members=frozenset("刺剌"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/ci",
        flow=FlowSpec((CTX,), review=True, review_fix_strong=True, strong_over_ref=True,
                      tolerate=frozenset("刻利刑勸剥軸刪敕勅朝剩"), tolerate_ref_agree=True),
        note="按文意定（L1 规则，弃权查 L2 表）：剌 只用于译音与 乖剌、剌謬，其余是 刺；补放，也复核，文意 strong 才改字（同 日曰）。"),
    "feng": GroupSpec(
        id="feng", name="逄逢", members=frozenset("逄逢"), backends=(),
        kind="near_form", solvers=("ctx_l1", "ctx_l2"), config_dir="config/groups/feng",
        flow=FlowSpec((CTX,), review=True, review_fix_strong=True, strong_over_ref=True,
                      tolerate=frozenset("進違達運逸通遙遜途遥迄遲逕迤遴蓬𨒪"), tolerate_ref_agree=True),
        note="按文意定（L1 规则，弃权查 L2 表）：逄 只作姓，其余是 逢；补放，也复核，文意 strong 才改字（同 日曰）。"),
}

#: 字组流程可点名的全部组。
FLOW_GROUPS: dict[str, GroupSpec] = {**GROUPS, **CODEPOINT_GROUPS, **SHAPE_GROUPS}


@dataclass(frozen=True)
class Provisional:
    """同义组的暂归一兜底（sheldon 2026-10-27）：方法（IDS／字形／字频…）拆不开、置信度不够或与整理本说法不一时，
    只要「是这个字」两路都认（见 `flow._provisional`），就把格放成 `to`（这组最常见的字形），证据记 `decision: provisional`，
    将来按这个标记筛出来再拆。`forms`＝算作同一个字的写法（组员＋整理本／库里出现的同字码位，减掉组里意思不同的字）；
    `gap`：整理本缺字（`〓`）也算「是这个字」的一路（库首位要够 `FlowConfig.provisional_gap_cov`）。"""
    to: str
    forms: frozenset
    gap: bool = False


#: 暂归一兜底表（2026-10-27，A24「收尾同义形近字组送审」）：只收同义（`kind="variant"`）组，`to` 取 vol07–99 重落后放行最多的字形
#: （已在书级 `codepoints` 暂归一的组取归到的字）。意思不同的字绝不进 `forms`：讖識䜟 的 識、
#: 陪衬（家 卿 徵 刖 鍾…）都不在里面。登记见 cv `doc/字组/README.md` 第二节「暂归一兜底」。
PROVISIONAL: dict[str, Provisional] = {
    gid: Provisional(to, frozenset(forms), gap=gid in {"yi_560"})
    for gid, to, forms in (
        ("yi_560", "𢑱", "彝彛彜彞𢑱𢑴"), ("dian", "㸃", "點㸃"), ("chen", "䜟", "讖䜟"), ("shen", "愼", "慎愼"),
        ("zhi", "㫖", "旨㫖"), ("can", "參", "參㕘叅"), ("ji", "卽", "即卽"), ("qing", "卿", "卿𨜊"), ("hui", "彚", "彙彚"),
        ("kan", "刋", "刊刋"), ("jiw", "旣", "既旣"), ("qx", "淸", "清淸"), ("dx", "顚", "顚顛"), ("zx", "淄", "淄湽"),
        ("qy", "靑", "青靑"), ("wei", "爲", "爲為"), ("shuo", "說", "說説"), ("xu", "敘", "叙敘"), ("ce", "冊", "冊册"),
        ("jiao", "教", "教敎"), ("qik", "啟", "啓啟"), ("lih", "厯", "厯歴"), ("jue", "絶", "絕絶"), ("lv", "吕", "呂吕"),
        ("weiw", "衛", "衛衞"), ("shan", "刪", "刪删"), ("di", "抵", "扺抵"),
        ("nei", "内", "內内"), ("chu", "出", "出岀"), ("juan", "卷", "卷巻"), ("wan", "晚", "晚晩"), ("huo", "獲", "獲𫉬"),
        ("kui", "䕫", "夔䕫"), ("lie", "𤢪", "獵𤢪"), ("lei", "類", "類𩔖"), ("cuan", "𥨥", "竄𥨥"), ("lang", "郞", "郎郞"),
        ("zheng", "徴", "徵徴"),
        ("cek", "䇿", "策䇿"),
        ("shang", "尙", "尙尚"), ("gai", "葢", "蓋葢"), ("ba", "跋", "䟦跋"), ("zhun", "準", "凖準"), ("mi", "密", "宻密"),
        ("zhuan", "撰", "撰𢰅"), ("sang", "喪", "䘮喪"), ("bian", "𠮓", "變𠮓"), ("suo", "𤨏", "瑣𤨏"), ("yin", "隱", "隱𨼆隠"),
        ("suan", "算", "算𮅕"), ("guanm", "關", "闗關"), ("shi", "勢", "勢𫝑"), ("fa", "發", "發𤼵"), ("pai", "派", "派𣲖"),
        ("qi", "奇", "奇竒"), ("sui", "歲", "歲嵗𡻕"), ("li", "𨽾", "隸𨽾隷𨽻"), ("mn", "𫎇", "蒙𫎇䝉"),
        ("yinv", "陰", "陰隂"), ("xian", "陷", "陷䧟"), ("shu", "疏", "䟽疏"), ("ning", "寧", "寧寜"), ("yao", "謠", "謠謡"),
        ("jim", "羈", "覊羈"), ("xun", "巡", "巡廵"), ("jian", "劍", "劍劔"), ("chi", "勅", "勅敕"), ("bi", "弊", "𡚁弊"),
        ("huiq", "回", "囘回"), ("xuan", "選", "選𨕖"),
        ("xiang", "鄕", "鄉鄕郷"), ("weim", "微", "微㣲"), ("bie", "別", "別别"), ("zhen", "鎭", "鎭鎮"))
}

#: 并掉或改名的组：旧 id → 新 id。册配置 `group_flow` 里还写着旧 id 的照新 id 读（`flow_names`），等成批上线改册配置时再换掉。
RENAMED: dict[str, str] = {"qg": "zy"}


def flow_names(names) -> tuple:
    """册配置点名的组 id → 现行 id（按 `RENAMED` 换，去重，保持先后）。"""
    return tuple(dict.fromkeys(RENAMED.get(g, g) for g in names))


def get_group(group_id: str) -> GroupSpec:
    return GROUPS[group_id]


def groups_of(ch: str) -> list[GroupSpec]:
    """一个字属于哪些组（可多个：同字可同属两组）。"""
    return [g for g in GROUPS.values() if ch in g.members]
