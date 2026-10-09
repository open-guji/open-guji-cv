"""C1 进库准入：库判决 + OCR + 上下文定字 → 自动进库 / 落回人审。

包的是 `clustering/seeding.admission_decision`（十条通道，2600+ 条真实裁决
逐轮定型），**算法一行没改**。这一步只负责：把 v2 三步的产物摊成它要的入参、
把裁决落成 numeric 产物，供审查页与 `glyphdb_admit` 消费。

## 通道与证据强度（抄自 glyph_db_first_design §7.2/§7.3）

| 信号 | 难例准确率 | 说明 |
|---|---|---|
| 库 verify same | **100%**（27/27） | 形状证据，cov 0.99 是实测拐点 |
| 整理本·过闸对齐 | 95.8% | 文本证据 |
| OCR | **45.0%** | **置信度也不可信**（「人/入」给了 0.95 仍错） |

**四条原则**（背下来）：整理本在场时它有一票否决权；OCR 只供候选、置信度
不参与任何自动判断；库匹配按 cov 分档采信，0.99 是拐点；凑双信号要挑**误差
独立**的两路——文本 × 形状可以，OCR × 形状不行（那 4 条错例正是两者同错）。

## 这一步现在能走哪几条通道

`admission_decision` 最强的几条（常规 / match_ref / match_replace）都要
**整理本对齐字**，那来自 `align_label` 的页面锚定，还没进 v2 产物（B2 之后
才有）。所以现在只走**纯字形**那两条：

- `match_solo`：无整理本参照 + 库内 cov ≥ 0.99；
- `match_solo_ocr`：cov 0.95~0.99 + OCR 字符背书（语义同字）。

dev_set 3624 字位实测：match_solo 55.8% + match_solo_ocr 17.2% = **自动 73%**，
人审 27%。接上整理本之后自动率会更高（v1 上实测 61% → 77%）。

## 进库不在这一步做

这一步只产出**裁决**。真正写库要走 Event → 路由 → `glyphdb_admit` 消费者，
理由是设计 §3 纪律 1：逐实例证据、可重放。自动通道的裁决由
`review/batches` 转成 `confirm` 事件，人审的进审查页。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from pydantic import BaseModel, field_validator, model_serializer

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (AdmitRec, ColumnAdmit, PageAdmit,
                                    PageAlignRef, PageDecision, PageMatch,
                                    PageOcr)
from ..utils.image_io import imread as cv_imread
from ..utils.ji_yi_si import FAMILY as _JYS

_log = logging.getLogger(__name__)


class SeedAdmitParams(BaseModel):
    variants: str = ""                  # 异体表；空 = VariantMap 默认
    solo_cov: float = 0.99              # match_solo 的 cov 闸，实测拐点
    use_context: bool = True            # 把 Step6 的定字当第三路证据
    context_margin: float = 0.70        # 用它时的 margin 门槛（生产值）
    context_verdicts: str = ""
    """context 通道按**库判 verdict** 加的闸（2026-09-27，D-书级admit覆盖）。
    逗号分隔的允许集合，如 `"same,unsure"`——只在 `r.verdict` 落在这个集合里时
    才允许 context 放行；不在集合里记一条 doubt `context_verdict`、落人审。
    空串 = 不限制（旧行为，所有 verdict 都能走 context）。

    起因：全唐文放行抽检（overview `新书整理/书/全唐文/放行抽检-v0.md`）—— 独立
    两次抽样都测到 `channel=context ∧ verdict=diff` 错率约 50%（n=40），而
    `verdict=same/unsure` 错率低得多（`unsure` 9.1%~5.0%，`same` 未见错）。按
    「锚定页/未锚定页」拆开复核过，错率不随锚定与否变化，说明问题出在
    `verdict=diff` 这个组合本身——库已经明确判"不是这个字"，`context_margin`
    顶格覆盖这条视觉证据不可靠，不是分辨率不够的问题，是这条通道天生守不住。
    """
    always_review: str = "己已巳"
    """这些字不采信字形/OCR 通道的判决（用户 2026-09-04 定，2026-09-11 改口不再是
    「永远人审」）：命中时先清空 `admission_decision` 给的通道，只看 `relax_split_ref`
    （整理本给字）与下面的 context 通道（Step6 上下文判定）能不能定下来；两条都没有
    结果才落人审。"""
    edition: str = "wuyingdian_zongmu"  # 本书用字账（variant_ledger）的键
    # 整理本通道原来在这里配 corpus/corpus_fingerprint，2026-09-09 挪去了
    # `align_ref`（Step5-d，正式 Step，产物带自己的语料指纹）——本步只消费
    # 它的产物，通道开不开看 `align_ref` 锚没锚上，不用再在这里配一份。
    use_exclusions: bool = True         # 查 config/crop_exclusions.jsonl（切坏的图块不进库不出卡）
    exclusions: str = ""                # 名单路径；空 = exclusions.py 默认
    exclusion_origins: str = "human,gate,pipeline"
    """采信名单里的哪几档来源（逗号分隔）。

    **按证据强度分级，别一刀切**（`exclusions.py` 模块头的纪律）：`human` 是人眼实锤；
    `gate` / `pipeline` 是管线确定层旗标；`pipeline-suspect` 那 216 条**实测只有约 27%
    是真有问题**——全采信会误伤约 150 个好格子（58 页上实测命中 68 条）。所以默认不含它，
    要复核时显式打开，或等重扫后逐条判。
    """
    use_note_lexicon: bool = True       # 版本注闭集通道（段级，只作用于夹注格）
    note_lexicon: str = ""              # 词表路径；空 = note_lexicon.py 默认
    note_min_sim: float = 0.70          # 段相似度下限（见 note_lexicon.MIN_SIM）
    note_fingerprint: str = ""          # 自动填：词表变了产物过期
    use_human_verdicts: bool = True     # 人裁过的位直接采信人裁字形（最高优先级）
    db_path: str = ""    # 读人裁记录用；与 glyph_match 同一个库。留空 = 按 workspace 解析
    human_fingerprint: str = ""         # 自动填：人裁进库了本步要重跑
    iron_config_fingerprint: str = ""
    """自动填：`config/iron_extra_confusable.json`（铁证闸的追加形近/形不可分表）
    变了本步要重跑。开不开铁证闸看册配置 `iron_gate:`（`StepSpec.book_deps`
    已经把这个字段收进指纹了，这里只管配置文件内容本身）。"""
    iron_ref_guard: bool = True
    """铁证放行前与整理本互证（2026-09-27 整理 Z7 实测）：铁证定的字与 `align_ref`
    对齐字**语义不同**就不放行、落人审（同 `context_conflicts_ref`）。vol03 铁证放行
    11 格错 3（曰/白、夬/夫、而/面），三格 align_ref 都标了 replace——库里够像的刻例
    是形近字，整理本早就说了不是它。没有对齐字的格不拦。"""
    iron_confusable_guard: bool = True
    """铁证首选与证人（整理本）是**已知形近对**、字又不同就不放行、落人审（overview#426，
    doubt `iron_confusable_ref`）。证人取现役对位字和坐标对位字（`align_ref.coord`）两路——
    vol04 铁证放行 20 格错 3（曰/日×2、人/八），三格现役对位都被库分歧过滤掉了
    （`n_lib_dropped`），`iron_ref_guard` 看不到证人，坐标对位里证人是对的。形近对只认现成表：
    `confusable.partners()`（手工核过 + 人裁确认 + 字体 τ≥0.988）与铁证补充表
    `iron_extra_confusable.json`。语义同字（异体、码位）不拦。"""
    context_blank_gate: bool = True
    """上下文通道对近空白字块弃权（2026-09-27 D 铁证复核：`vol03:9:9:21` 字块几乎
    是空白，`context` 通道仍把它放行成「今」——上下文判定只看文意，不看这一格
    到底有没有墨）。字块（`char_index` 的 `ink_ratio`）低于 `context_min_ink`
    时不走 context 通道，落人审（`context_blank_cell`）。只挡 context 这一条
    通道——`match_solo`/`iron` 等字形通道本身就要求库里能验出「像」，空白格
    verify 不出 same，链路里已经挡住了，不需要重复设闸。"""
    context_min_ink: float = 0.05
    """`context_blank_gate` 的墨量闸。bxgb + vol03 两书全书 `char_index.ink_ratio`
    分布实测（`scripts/measure_context_ink_gate.py`）＋逐格看图定的界：vol03 全
    书 `channel=context` 的 262 格里最低 4 格（0.0415~0.0493，含 `vol03:9:9:21`
    ink=0.0493、`vol03:67:9:21` ink=0.0415）图上看**都是空白**（碎墨点/划痕，
    非字）；再往上第一个「像样」的格是 `vol03:33:2:1`（一，ink=0.0677）——
    「一」只有一横，天然低墨，图上确认是真字；中间 0.0604（莫）图上零散不
    确定，落在闸的"不拦"一侧（新闸第一版，拿不准就不拦，比错拦一个真字更
    安全）。取 **0.05**：压在「确认空白」（≤0.0493）与「确认真字」（0.0677）
    之间。bxgb 全书 `channel=context` 134 格最低也有 0.1093（臣），阈值对它
    是纯保险栓、不会误伤。"""
    relax_split_ref: bool = True
    """己/已/巳：整理本给了字就放行——文意取整理本，字形取库 top1（用户 2026-09-06：
    「没必要每次都单独让我选文意，根据上下文或整理本直接选；字形选哪个都行」）。
    实测 41 条人裁：文意对 39、字形对 40。关掉不等于「永远人审」——下面的 context
    通道（2026-09-11 起对己已巳不再排除）仍可能在没有整理本时单独放行。"""
    ji_yi_si_review: bool = False
    """己/已/巳 一族转人审的三方一致闸（2026-09-27 D 铁证复核）：vol03/vol04 各自
    独立全量穷举，这一族全部自动放行、零送审，vol03 47 格错 55.3%、vol04 34 处——
    见 `_resolve_ji_yi_si` 文档字符串。这条开关是任务书给的「二选一」里更保守的
    那种：非「干支/时辰」（几乎不错，不受此闸影响）的其余路径，要求**上下文判定
    （Step6）＝整理本对齐字＝库候选 top1** 三者一致才放行，不然送人审
    （`doubts` 记 `ji_yi_si_review`）。另一种做法「这一族一律送审」更简单更保守，
    数字见任务书对应 done 单，没实现为第二个开关值——需要时改这一个布尔量的调用点
    即可，不必新增字段。缺省关：用户 09-06/09-11 定的规矩是「整理本给了就放行」，
    这一族默认继续全放行，开不开等用户看完两种做法的数字再定。"""
    ji_yi_si_ctx_rule: bool = False
    """己/已/巳 一族的上下文表放行规则（overview#428，N1，缺省关）。

    开了之后，非「干支/时辰」的路径（搭配/整理本/默认）不再放行整理本或默认字，改为：
    **上下文表**（`utils/near_form_ctx.py`，外部语料建的前后 1–2 字决策表，纯度 ≥ `ji_yi_si_ctx_purity`、
    次数 ≥ `ji_yi_si_ctx_min_n`）高把握定字就放行（通道 `ji_yi_si`，证据 `ji_yi_si.why` 记「上下文表…」），
    定不下来的**一律送人审**（`doubts` 记 `ji_yi_si_ctx_review`）。人裁位不动。
    与 `ji_yi_si_review`（三方一致闸）二选一，本开关开着时以本开关为准。
    数字：强真值格（人裁＋看图）上，现行 `resolve(use_ref=all)` 整理本路 vol02 42/45、vol03 16/28、
    vol04 5/7 错；规则放行的格 vol02 7、vol03 10、vol04 13，全部 0 错；代价是人审率上升
    （全册本族格 vol02 47/60、vol03 32/47、vol04 14/27 送审）。上下文表在整套里**新增**放行的只有
    vol02 8 格、vol03 3 格、vol04 0 格，大头仍是干支/时辰。"""
    ji_yi_si_ctx_purity: float = 0.98
    ji_yi_si_ctx_min_n: int = 5
    ji_yi_si_ctx_fingerprint: str = ""      # 自动填（仅开关开时）：表文件变了产物过期
    ji_yi_si_clf: bool = False
    """己/已/巳 词组分类器放行（overview#443，Z-jys，缺省关；关时下面四个字段都不进 dump，`params_hash` 不变）。

    用户 2026-10-09 四条原则：不靠字形区分、自动通过的必须准、靠前后的词定字、第一候选明显优于第二才放行。
    开了之后（压过 `ji_yi_si_ctx_rule`／`ji_yi_si_review`），非「干支/时辰」的本族格：
    - **规则路**（`utils/ji_yi_si_clf.classify`，纯函数，读前后各 30 字，未放行邻格用整理本字补）命中 →
      放行（通道 `ji_yi_si`，`evidence.ji_yi_si_clf.rule`）；与强通道放行的字冲突、或已是人裁位时不动
      （冲突送审，`doubts` 记 `ji_yi_si_clf_conflict`）；
    - 规则不命中 → **送人审**，并把答案表（`ji_yi_si_clf_table`，离线大模型两遍＋语料分类器）的建议字写进
      `evidence.ji_yi_si_clf.suggest`，让人审时一眼看到；**不放行**，除非另开 `ji_yi_si_clf_llm`；
    - 退役对本族的放行：默认→已、整理本路、`split_ref` 放巳（规则不命中的 `split_ref` 放行格改送审）。
    人裁位不动。累计证据：强真值 0/129、新留出 0/36（见 overview#443）。"""
    ji_yi_si_clf_llm: bool = False
    """答案表路也放行（缺省关）：两遍大模型一致 ∧ 语料分类器同字 ∧ 分类器 top−second ≥ `ji_yi_si_clf_margin`。
    历史上这一路有语义错（「是己出自入者」被判已，差值 0.975 也没挡住），放开条件见 overview#443：
    独立再判一遍仍一致，且 ≥100 个新抽样格 0 错。"""
    ji_yi_si_clf_margin: float = 0.2
    ji_yi_si_clf_table: str = ""            # 答案表 json 路径（可空：没有表就只有规则路）
    ji_yi_si_clf_fingerprint: str = ""      # 自动填（开关开且有表时）：表内容变了产物过期
    relax_ref_agree: bool = True
    """整理本字 ≡ 库 top1（语义同字）或 == 上下文定字 时直接放行（用户 2026-09-06：
    「很多都是在整理本存在时非常明显的选择，能不能放松要求」）。形取库 top1（刻本形），
    文意取整理本。两册人审位实测 整理本≡库top1 10/10、==上下文 4/4，全部 1,1xx 条
    人裁真值上反例 0。同时让「义定形未定」的位在库 top1 属组内形时直接取它当形
    （evidence.form.state=guess，判据 E 会把它算进抽审分母）。"""
    ref_lib_variant_guard: bool = True
    """`ref_lib` 通道变体放行加闸（2026-09-27，R 形近溯源实测 `bxgb:52:11:15` 冶→治
    揪出，做法参照 `iron_ref_guard`，参数缺省开）：`relax_ref_agree` 里「库候选与整理本字
    语义相同（`vmap.semantic` 归一）」这条，此前只要语义相同就放行，完全不看两者字面是否
    一致、也不看 Step6 margin——`variants.auto.tsv` 的 `graph` 来源多数是词典单向登记
    （twedu 那条 冶→治 就是：`directed['冶']={'治':['twedu']}`，没有反向 `directed['治']`），
    不代表刻本场景下两字真同义（`open_guji_cv/variants.py` 模块头「来源分级只是先验」）。
    加闸后：库候选与整理本字**字面相同**（`_top == align_char`）不受影响，照放；**字面不同**
    （变体放行）只有满足以下任一条件才放行，否则记 doubt `ref_lib_variant`、退回人审（不改
    `char`，不采信这条判决）——
    - **可信边**：变体关系在关系层双向确认（`open_guji_cv.variants.regulars_of` 两个方向都
      收，即两个来源都认对方是自己的正字，不是单向词典登记）；或人工审查确认表
      `config/dicts/variants.tsv` 登记过这一对（该表本就是人工确认，不要求关系层双向）；
      或本书用字账人裁过这一对（`BookLedger.pair_confirmed`，双向都查）；或本书
      `codepoints` 配置把两个码位统一成同一个（`BookSpec.codepoint_equal`，书级实证，
      比字典更硬）——见 `_trusted_variant_edge` 的完整判据；
    - **Step6 margin 过线**：复用 `context_margin`（0.70，同一把已经在生产用的尺子，不另开
      一个阈值）——`context_decision` 给这一位的 margin ≥ 它，即便变体边本身单薄也放行。
    三书（bxgb dev_set+p52、vol03 107 页快照、vol01 206 页快照）实测 `ref_lib` 通道共 5 格
    变体放行、0 格字面相同：`躭→耽`（vol01，双向可信）、`彝→彞`×3（vol03，双向可信）margin
    0.12~0.24 全部远低于 0.70；`冶→治`（bxgb，唯一不可信）margin 0.024。加闸后前四格不变，
    冶→治 落人审——详见 done 单。"""
    variant_indirect_guard: bool = True
    """异体等价放行拦**间接路径**（2026-09-28，overview#178，缺省开）。

    `vmap.semantic` 归一只说明两个字挂到了同一个语义正字，不说明它们之间有边：
    `𢑴→彝`（hydzd）与 `彞→彝`（twedu）各自挂到「彝」，`𢑴`/`彞` 就被判成同义，
    关系层里两者却**没有直接边**，是经第三个字间接连起来的（H #62 `vol04:28:3:18a`：
    刻「彝」形，库 top1 `𢑴`、整理本 `彞`，按 `ref_lib` 把 `𢑴` 放行、margin 0.0036）。
    开着时，库形与整理本字字面不同、语义相同、但关系层（`variants.json`，除
    kSpoofingVariant/通假）**没有直接边**的——
    - `match_ref`/`match_replace`/`match_margin`（`admission_decision` 里那几条拿
      `vmap.semantic` 比库形与整理本的通道）撤回放行，记 doubt `variant_indirect`；
    - `ref_lib`：不再能靠 Step6 margin 过闸（直接边的 margin 分支照旧），记
      `ref_lib_variant` + `variant_indirect`。
    例外与 `_trusted_variant_edge` 同口径：人工表 `variants.tsv`、本书用字账人裁、
    书级 `codepoints` 认过这一对的照放。**直接边（双向、单向）行为一概不变**。
    实测（四庫 vol01–04 快照 + 全唐文 v006–v010 快照，见 #178 评论）：靠异体等价放行的
    1,321 格里间接路径 2 格，都是 `𢑴`→`彝`→`彞`，1 格存形错；其余全是直接边。"""
    lib_confident_cov: float = 0.0
    """库高置信兜底通道 `lib_confident`（2026-09-28，D 高置信落审放宽候选）。0 = 关（缺省）。

    对象：上面所有通道都没放行、库判 `unsure`、Step6 退回先验（`source=prior`，
    即人审卡上的「上下文 margin 不足」）的格。库 top1 的 cov ≥ 本值、且领先第二名
    ≥ `lib_confident_gap` 时放行 top1。硬约束（任务书 item 2）：
    - 不碰 己／已／巳 一族（`always_review` 与 `ji_yi_si.FAMILY`）；
    - 不碰形近对表里的字：top1 在 `confusable.partners()`（手工＋人裁＋字体表）或铁证
      补充表（`iron_extra_confusable.json`）里有对手就不放——**按字不按对**，不要求
      对手恰好在候选里；
    - 库无护栏（`guard is None`）；本格没有任何流程内疑问（`near_form`／`replace_align`／
      `context_vs_ref`／`form_open`／`iron_vs_ref` …）——**整理本说了不同（replace）一律不放**；
    - 只当兜底：放在铁证之后、`if not ok` 里，只新增放行，不改动任何已放行格。
    **缺省关、不推荐开**（四册 vol01–04 实测，open-guji-core/overview#59）：这个池子里有人裁的
    109 格库 top1 错 94 格——真字多半库里没收，cov 0.95~0.98 只是「库里最像的那个」；最窄的
    候选档（cov≥0.98、领先≥0.03）四册合计只有 130 格，全审 0 错也压不到 95% 上界 ≤1%。
    留着开关是给「人审过这一档之后」用的，不是现成的放宽。"""
    lib_confident_gap: float = 0.0
    """`lib_confident` 通道要求库 top1 领先第二候选的最小 cov 差。"""
    off_channels: str = ""
    """关掉 `admission_decision` 的哪几条通道（逗号分隔，如 `"match_solo"`；2026-09-28，
    overview#155）。命中的判决作废、记 doubt `channel_off`，后面的兜底通道（context／
    ref_lib／铁证…）照常有机会——关的是**这条路**，不是这个格。空串 = 全开（旧行为）。
    书级用：书 yaml `params: {seed_admit: {off_channels: match_solo}}`。"""
    solo_confusable_guard: bool = False
    """match_solo 系（`match_solo`/`match_solo_ocr`/`match_solo_cnn`）加形近闸（2026-09-28，
    overview#155）：库 top1 在任何一张形近表里（`_confusable_char`：NEAR_FORM_CHARS、
    `confusable.partners()`、铁证追加表）就不单独放行，记 doubt `solo_confusable`、落人审。
    起因：全唐文 v006 match_solo 放行「屢動千戈」的「千」，图与整理本都是「干」——
    这一路只有形状一条证据，千/干 这种形近对 cov 照样过 0.99。缺省关（旧行为）。"""
    solo_ctx_veto: float = 0.0
    """match_solo 系的上下文否决（2026-10-09，overview#450）：`context_decide.ranked` 第一名与
    放行字**语义不同**（异体码点差不算），且第一名概率 ≥ 此值，就不单独放行，记 doubt
    `solo_ctx_veto`、落人审。起因：vol05 `147:9:9` 金标士，库候选 土 0.9955／士 0.9813（纯形状），
    而 context_decide 的 ranked 是 士 0.6327／土 0.2218——系统里已有对的答案，match_solo 这条路
    不看。vol05 377 格 match_solo 里 ranked[0] 与放行字不同仅 27 格。0 = 关（旧行为，不进 dump）。"""
    replace_form: str = "align"
    """`match_replace` 放行时字形（码位）取谁（2026-09-28，overview#155）：
    - `align`（缺省，旧行为）：库没下 same 断言时取整理本字；
    - `lib`：整理本字与库 top1 语义同、字面不同时，取**库 top1**（刻本字形；这条通道要求
      top1 cov ≥ 0.95，形状证据站得住）；
    - `review`：字面不同就不放行，记 doubt `replace_form`、落人审。
    起因：全唐文 v006 `match_replace` 放行「嚐」，图上是「嘗」——整理本（维基）用了
    异体，码位跟着整理本走了。只在 variant_form（本书用字账组内定形）没接手时生效。"""
    ledger_fingerprint: str = ""        # 自动填：账本变了产物过期
    variants_fingerprint: str = ""      # 自动填：语义表（auto + 手工）变了产物过期
    variant_graph_fingerprint: str = ""
    """自动填：关系层 `config/variants/variants.json` 变了本步要重跑——`ref_lib_variant_guard`
    的双向判据直接读它（`open_guji_cv.variants.regulars_of`），此前 `variants_fingerprint`
    只盯 `variants.auto.tsv`/`variants.tsv` 派生表，盯不到关系层本身的改动。"""
    exclusions_fingerprint: str = ""    # 自动填：名单变了产物过期
    rare_agree: bool = False
    """记「像素与 CNN 两路首选是否一致」（2026-09-28，D 道 overview#126），缺省关。
    开了读 `rare_candidates`（5-b），在每格 `evidence.rare` 记 `{pix, cnn, agree}`：
    `pix` = 库（`glyph_match`）首位、`cnn` = 5-b 首位、`agree` = 两字相同。
    **只记、不放行**——R 道实测两路一致时精确率 97.6%（维基锚定集）／90.7%（人裁难例），
    达不到 1% 错判门槛（#86）；记下来是给以后按书标定用的。关着时不读 5-b、不进指纹、
    不进参数哈希，产物逐字节不变。书 yaml `params: {seed_admit: {rare_agree: true}}` 打开。"""
    rare_ref: bool = False
    """规则 A「5-b × 整理本」放行通道 `rare_ref`（2026-10-02，D3 道 overview#349），缺省关。

    给**走完所有现行通道仍待审**的格补一次机会：整理本是 `replace` 段、有整理本字，而 5-b
    （`rare_candidates`，字体模板 emb/CNN，与整理本互相独立）首位**逐字**等于整理本字 → 放行，
    字 = 整理本字，`channel`/`provenance` = `rare_ref`。动机：新册字形库冷启动时整理本字不在库
    候选里，库 unsure 一片，而 5-b 首位就是整理本字（vol02/03 人裁 560 格命中、字形全对 558）。

    硬条件（缺一不放）：整理本字不是己已巳；格上没有 `occluded`／`excluded`／`near_form`／
    `context_blank_cell`／`form_open`／`approx_exemplar` 疑问，库匹配无护栏（`never_match`／`conflict`）；
    库没有 `verdict=same` 认成别的字；库首位不是整理本字的异体（`variants.are_variants`；
    注意这条**只拦不放**——「异体就取库形」实测 75 格只对 11，别用）。
    只会把待审挪到放行，不改任何已放行格；人裁位不经这里。evidence 记 `rare_ref={rare, ref, lib, cov}`。
    关着时不读 5-b、不进参数哈希，产物逐字节不变。书 yaml `params: {seed_admit: {rare_ref: true}}` 打开。"""
    occluded_gate: bool = True
    """印章／大片污损遮挡的格直接拒（2026-09-28，D 道 overview#195，缺省开）。

    检测见 `steps/occlusion.py`（整页中等墨点密度 + 成块，vol03 全册标定只命中 p3 印章）。
    命中的格：**不进任何放行通道**（`admit=False`、`doubts=["occluded"]`）——太脏，字形
    一律不进字形库（用户原话「这些格太脏，全都不能入库」）；`char` = 默认字：整理本的字，
    先取 `align_ref` 的坐标对位（`PageAlignRef.coord`），没有才取现役对位字，都没有为 None；
    坐标对位说这一位是**空格**（印章切出来的假格）的，`char=None` 并记
    `evidence.occluded.ref_blank=True`（文本层当非字跳过，人审卡默认点「非字」）。
    人裁位照旧一票定案，不受这道闸影响。只会把格从放行挪到待审，不会反过来。"""
    occluded_min_density: float = 4.0
    """热格密度门槛（每万像素中等墨点数），标定见 `steps/occlusion.py` 模块头。"""
    occluded_min_cells: int = 12
    """热格连通块至少多少格才算遮挡。"""
    occluded_min_cols: int = 3
    """热格连通块至少横跨几列。"""
    occluded_min_peak: float = 8.0
    """块内最高密度门槛（真印章 9.2~20.2，vol05 p68 碎笔画误报 6.1）。"""
    occluded_min_contrast: float = 2.5
    """块内密度中位 / 本页其余格中位 的下限（真印章 ≥3.1 倍，碎笔画 1.9 倍）。"""
    seal_blank_page: bool = False
    """盖章空栏判空（2026-10-09，道 B 规格 overview#493，缺省关；需同开 `lane_seal`）。

    固定印「乾隆御覽之寶」（`config/seal_templates/`）NCC 命中、印框与格重叠 ≥ `seal_blank_overlap`
    的格，若同时满足：坐标对位无字、且未被强通道（match_ref／match_solo／witness3／match_margin／iron）
    放行、不是人裁格 → 挪成「遮挡待审、默认字 None」，再由 `lane_seal` 的 coord_blank 分支判非字
    （admit=True、char=None、文本层跳过）。context 通道**不算**强通道。只按格判，绝不按列判：印压真字的页
    框内有字的格不动。关着时不进参数哈希，产物逐字节不变。书 yaml `params: {seed_admit: {seal_blank_page: true}}`。"""
    seal_blank_thr: float = 0.35
    """印框 NCC 门槛（留一法 5/5 召回，非印页最高 0.282，阈值两侧余量 ≥0.07）。"""
    seal_blank_overlap: float = 0.5
    """格与印框重叠面积 ÷ 格面积 的下限。"""
    seal_blank_ink_out: float = 0.005
    """第四条保险：格内「模板外墨」＝格框内 <128 且落在本页命中模板覆盖区（二值化＋5px 膨胀）外的像素 ÷ 格面积；
    ≥ 此值的格不算空（退出候选，仍待审）。只收窄。道 A 量法（overview#493）：真字页 vol02 p188 的 4 格真字
    模板外墨 ≥ 0.045，阈值 0.005 与之有 9 倍空档；不是已校准的阈值，只是已知真字都在它外面。"""

    approx_gate: bool = False
    """匹配到的库例是**近似字**时拦不拦自动放行（overview#276；书级参数）。

    近似例 = 人裁时勾了「无匹配（近似字）」的刻例（`approx_labels` 侧表）：Unicode 里没有真正
    对应的字，库里存的只是最像的那个码位。

    **缺省不拦**（用户 2026-09-29 裁定，overview#277 选 C）：近似例像普通刻例一样参与自动放行，
    但靠它定下来的格要**标注**——`evidence["approx"]`（`source="matched"`、`via`、命中的库例与其
    ids/note），文本层据此把这一格记进近似字侧表（`render/approx.py`），控制台卡片显示「近似」。
    开了（`params: {seed_admit: {approx_gate: true}}`）则退回保守做法：`admit=False`、doubt
    `approx_exemplar`、`char` 不改，落人审。

    判「靠近似例」两种情形，都要求这一格的字就是库给的字（整理本/上下文定的字不算）：
    库判 same 命中的那一例（`matched_id`）是近似例（`via="matched_id"`）；或走候选首位、而这个字在库里
    的刻例**全部**是近似例（`via="char_only"`）。人裁位照旧一票定案，不经这里。
    """
    shadow_veto: bool = False
    """影子放行闸（overview#305 第一阶段，缺省关）：对**现行规则已放行**的格再算一次影子预测，
    影子很有把握选了**不同的字**（`shadow_conf`）就降回待审、evidence 记 `shadow_veto`、doubts 加
    `shadow_veto`。**只降级不升级**；人裁通道不动；信号缺失／本格自身在字形库里／异常 → 弃权。
    关着时下面四个字段都不进 dump：没开的书 `params_hash` 与加字段前逐位相同。"""
    shadow_model: str = ""              # 模型文件；空 = models/shadow_admit/shadow_gate_v1.joblib。路径不进指纹（path_params）
    shadow_conf: float = 0.97           # 影子把握度门槛：vol03 标签上影子 top1 错误率 ≤1% 的最低把握度（按页折实测）；实测推荐见 doc/shadow_gate.md
    shadow_low_conf: float = 0.0        # >0：影子最大把握度低于它也降级（缺省关）
    shadow_veto_variant_abstain: bool = True
    """影子选的字与现放行字**语义同字**（`vmap.semantic` 相同，即异体／简繁）时影子弃权、不降级
    （overview#431）：vol04 影子拦 61 格只 5 格真错，56 格是放行字＝证人字＝图上字形的刻本异体
    （㫖/旨、旣/既、尙、郞、刋…），影子 pick 的是通用正字——那是标签口径差，不是认错字。
    例外：放行字是罕用码位（不在 U+4E00–9FFF，同 `context_garble_guard` 口径）时不弃权、照常降级——
    vol04 弃权放回的 5 格真错（𠮓→變、𣼣→漏…）都是这一型；代价是 㫖、㓂 这类罕用区刻本异体也会照常降级。
    只在 `shadow_veto` 开着时进 dump。"""
    shadow_model_fingerprint: str = ""  # 自动填：模型文件内容戳——换模型本步要过期
    shadow_promote: bool = False
    """影子升级（与 `shadow_veto` 并列，缺省关）：对**待审**（admit=False）、无硬护栏、非人裁的格，
    影子首选字必须**等于整理本字或库首位**（至少有一路独立背书），且把握度 ≥ `shadow_promote_conf` →
    放行，字 = 影子首选，`channel`/`provenance` = `shadow`，evidence 记 `shadow_promote`。
    只升不降；人裁、遮挡、排除名单、护栏、形近、空白字块都不碰；信号缺失／本格自身在库里／异常 → 弃权。
    关着时 `shadow_promote*` 不进 dump，产物逐字节不变。"""
    shadow_promote_conf: float = 0.95   # 放行把握度门槛；推荐值与证据见 HANDOFF_D3.md
    approx_fingerprint: str = ""
    """自动填：近似字侧表的内容戳（`approx_labels` 条数 + 内容哈希）。表空 = ""。"""

    context_guard_diff: bool = False
    """context 通道放行前，库判 `diff` 且 `cov < context_guard_cov` 就不放行（doubt
    `ctx_guard_diff`，overview#333 建议 1 前半）。库已经明确说「不像」，上下文单凭文意不该
    把它抬成字。缺省关；五个 `context_guard_*` 全是缺省值时都不进 dump，产物逐字节不变。"""
    context_guard_cov: float = 0.8
    """`context_guard_diff` 的 cov 门槛。"""
    context_guard_flags: bool = False
    """context 通道放行前，这一格在 Step4 `char_index` 上带 `context_guard_flag_set` 里任一
    标记就不放行（doubt `ctx_guard_flag`，建议 1 后半）。没有 `char_index` 产物 = 弃权。"""
    context_guard_flag_set: str = "rule_bar,suspect_empty,bad_seg"
    context_guard_ref_blank: bool = False
    """坐标对位（`align_ref.coord`）说这一位是**空格**（`ref_char == ''`）、而库判不是 `same`
    时，context 通道不放字（doubt `ctx_guard_ref_blank`，`char=None`，卡片默认非字；建议 2）。"""
    context_guard_ref_prefer: bool = False
    """坐标对位给出整理本字、与 context 定字语义不同、库判又不是 `same` 时，不放行 context 字，
    落人审、默认字取整理本字（doubt `ctx_guard_ref`；建议 3）。不直接放行整理本字：这条路没有
    独立形状证据，放不放留给标定结果。"""
    context_garble_guard: bool = True
    """context 通道放行乱码的护栏（overview#427，C1 道，缺省开）。列切窄、卷末印章被切成字格时，
    字块只剩笔画边缘或印文，库判 diff/低 cov、整理本对不上，Step6 仍可能给 margin 1.0——
    vol04 这样放行了 93 格乱码（`𬑹小𢍺箵㫖是𠳋訁…`）。**没有证人背书**（整理本对齐字、
    坐标对位字、OCR 候选里没有一个与 context 字语义相同；全空也算）时，三条判据任一命中就
    不放行、落人审（字照旧，只是 admit=False）：

    - `ctx_garble_shape`：库 top 相似度 `cov < context_garble_cov`——字块不像任何一个刻例；
    - `ctx_garble_rare`：码位不在 U+4E00–9FFF、且 `cov < context_garble_rare_cov`——
      㫖/㕘/𢑴 这类本书常刻的扩展区字 cov 都在 0.96 以上，不拦；
    - `ctx_garble_run`：本列库 top 字里罕用码位（同上口径）在 ±`context_garble_run` 格窗口内
      达到 `context_garble_run` 个——整列切坏的特征；0 = 关这一条。

    vol04（快照 20261006T0716）：乱码列 context 放行 93 格拦 89；其余 339 格拦 43，看图
    全是错放或非字（版框角、圈号、半字、错位夹注），没有一格是对的。vol03 拦 7/93，同样全是
    错放。数字见 HANDOFF_C1.md（合并后移入 doc/handoffs/），重放脚本 research/garble_guard/replay.py。"""
    context_garble_cov: float = 0.90
    context_garble_rare_cov: float = 0.95
    context_garble_run: int = 3

    # ── 待审补放三通道（overview#433，R2 道）。各一个开关，缺省都关，书 yaml 打开 ──────────
    # 接在 iron／ji_yi_si／rare_ref／shadow 之后（页末 `_review_lanes_pass`），只碰仍待审的格：
    # 只升不降、只出文本（`evidence.no_glyph_lib`），人裁位与排除名单不经这里，己/已/巳 一族
    # 一律不走（仍归 `ji_yi_si`）。放行格 `channel`/`provenance` 是通道名，`doubts` 记
    # `lane_<通道名>`，原疑问挪进 `evidence.lane.prev_doubts`。三个开关全关时这一段不进 dump。
    lane_witness3: bool = False
    """R1 三证人一致（通道 `witness3`）：整理本对位来自 `replace` 段、待审类别是 对齐改字层／
    与整理本冲突／形近字（`review.cards.card_class` 同口径），而 `lane_witnesses` 里每家证人
    （逐格读法见 `clustering.witness_cells`）、整理本字、坐标对位字语义全同 → 放行，字 = 整理本字。
    护栏：库首位（刻本原字）与整理本字是已知异体对（语义同、字面不同）→ 不放，照旧送审
    （免得把刻本上的 獘 改成整理本的 弊）。"""
    lane_coord: bool = False
    """R4 坐标对位兜底（通道 `coord_fallback`）：只碰「其余」类待审格。二选一：库首位 == 坐标
    对位字 == 主证人（`lane_witnesses` 质量最高的那家，四庫即 daizhige 逐列本）→ 字取库首位；
    或每家证人 + 坐标对位字全同、库无护栏 → 字取坐标对位字。库首位与坐标对位字是已知异体对时
    两支都不放（同 R1 的护栏）。"""
    lane_seal: bool = False
    """R5 印章区（通道 `seal`）：`occluded_gate` 拦下的格，默认字来源在 `lane_seal_via` 里且有字 →
    放行默认字；坐标对位说这一位是空格（`via=coord_blank`）→ 判非字（`admit=True`、`char=None`、
    `evidence.occluded.ref_blank`，文本层跳过不占位）。护栏：本列坐标对位字连起来含
    `lane_seal_title_marks` 里任一串（卷端／版心题，坐标对位常错位）→ 整列不放。"""
    seal_lib_agree: bool = False
    """R5 的补充（Y1，overview#471「去章」，缺省关；需同开 `lane_seal`）：印章区格的默认字（坐标对位或
    现役对位字）与**库首位同字**且库首位覆盖度 ≥ `seal_lib_cov` → 放行，**不受卷端题列整列不放的限制**，
    `via=align` 也认。卷端题列（欽定四庫全書總目卷…）与卷端 p130 这类页，印章压住的是整理本能对上的
    固定套语，坐标对位常是对的但没有第二证据，这条用库首位当第二证据；库首位与默认字不同（含异体）、
    己已巳一族、`lane_variant_guard` 命中仍照旧送审。关着时不进参数哈希。"""
    seal_lib_cov: float = 0.9
    lane_witnesses: str = ""
    """R1/R4 用哪几家证人：书 yaml `references` 的文件名，逗号分隔；空 = 全部。某家这一位
    缺席（锚不上、不覆盖本册、difflib 没配上）就不算一致。"""
    lane_seal_via: str = "coord"
    """R5 放行哪些来源的默认字（`_occluded` 的 via）：`coord`；加 `align` 连现役对位字也放。"""
    lane_seal_title_marks: str = "總目,四庫全書"
    lane_variant_guard: bool = True
    """三通道统一的异体护栏（overview#433 vol04 实测）：要放的字与图上字形的线索——现候选字
    `rec.char`、库匹配前 `lane_variant_topk` 名候选——任一是**已知异体对**（语义同、字面不同）时
    不走通道、送审，免得把刻本异体改成通用字（vol04 coord_fallback 把 6 格刻本「㫖」放成「旨」：
    库首位是「旨」，㫖 只在候选里）。只在三通道任一开着时进 dump。"""
    lane_variant_topk: int = 3
    lane_witness_fingerprint: str = ""
    """自动填（R1/R4 开着时）：`references` 证人文件内容戳，证人改了本步要过期
    （`core.step._with_witness_fingerprint`）。"""

    juan_rule: bool = False
    """「数字＋卷」放行（Y1，overview#454，缺省关）：库 top1 是「卷」、cov ≥ `juan_cov`、这一格
    前一个正文字是数字（一…十百千）或「幾」，且别无护栏／疑问（只允许 `replace_align`、
    `context_vs_ref` 两条）→ 放行，字取库形「卷」，通道 `juan`。

    起因：vol05 与整理本冲突 45 格里 42 格是书名后的「一卷」，整理本（daizhige）排的是异体
    「巻」，`vmap` 不把巻卷并成同义，于是 `context_vs_ref` 拦下、`replace_align` 再记一笔。
    书名后「数字＋卷」是闭集套语，库形又高覆盖，两路互证。只作用于正文格（夹注格的
    相邻字要按阅读序排，另议）；整理本给了别的字（不是 卷／巻／空）一律不放。"""
    juan_cov: float = 0.98
    """`juan_rule` 的库 top1 cov 门槛（任务书口径）。"""

    variant_tie: bool = False
    """异体并列放行（Y1，overview#471，缺省关）：库候选里 top1 与另一个候选在 `variants.json` 里有**直接异体边**
    （同一个字的两个码位，如 𫎇／蒙、𢑴／彝、㸃／點），它们并列让上下文 margin 不足、库又判 unsure 而送审。
    口径 A（忠实原刻）下不归并、不改字，要的就是库形最近的那个码位——top1——所以变体之间的 margin 小
    不该拦：top1 cov ≥ `variant_tie_cov`、无护栏、`doubts` 只有 replace_align／context_vs_ref、top-3 里 cov 与
    top1 相差不到 0.03 的候选**全部**是 top1 的直接异体（有非异体的近邻＝真歧义，不放）、整理本字缺省或也
    与 top1 同组 → 放行 top1，通道 `variant_tie`。组级「刻形到底是哪个码位」的裁决回来后再按组收窄。"""
    variant_tie_cov: float = 0.97
    variant_tie_extra: str = ""
    """并列组表，逗号分隔，每项是一串码位（组内两两互为异体），如 `"𫎇蒙䝉,㸃點"`。**给了就只认这张表**
    （用户按组裁决过「刻形＝系统码位」的组；`variants.json` 里有不干净的边，如 雨／兩、辦／辨，也没收 𫎇／蒙）；
    缺省空＝退回 `variants.json` 的直接异体边。"""

    nonchar_gate: bool = False
    """非字过滤（Y1，overview#454 第4条，缺省关）：已放行的格若 Step4 `char_index` 标了
    `nonchar_flags` 里任一标记，或放行字是单笔画字符（`nonchar_strokes`，界行竖线／污点读成
    「丨」「亅」…），撤回放行、落人审（doubt `nonchar`）。人裁的格不碰（人裁在最前面一票定案）。
    依据：vol04 已放行格里带 `bad_seg`／`rule_bar` 的 36 格、放行字为单笔画的 3 格，有看图
    结论的全是放行错，零个看图 ok（见 #454 评论的前后对比）。没有 `char_index` 产物的格弃权。"""
    nonchar_flags: str = "bad_seg,rule_bar"
    nonchar_strokes: str = "丨亅丿丶"

    patch_missing: str = "error"
    """铁证 / CNN 背书 / 组内检索三路读本格字块读不到时怎么办（overview#407，2026-10-05）。

    - `error`（缺省，本地真书）：抛 `PatchUnavailable`，这一页 failed。
    - `skip`（云端快照沙箱：只带 products、不带原图与 cache，字块现算不出来）：这几路**不参与**
      这一格，但不静默——该格 `evidence.patch_missing` 记下跳过了哪几路（`iron_scale`／`iron`／
      `cnn`／`form`），日志汇总一行。真书别开：开了等于回到 10-05 前「没图就悄悄关掉」。

    `glyph_match` 没有这个开关：本格没图就没法判，停页是对的。
    缺省值不进 dump，`params_hash` 与加字段前逐位相同。"""

    @model_serializer(mode="wrap")
    def _drop_off_rare(self, handler):
        """`rare_agree` 关着时不进 dump：没开的书 `params_hash` 与加字段前逐位相同。

        `approx_gate`／`approx_fingerprint` 同理（overview#276）：闸是缺省值（关）时不进 dump；
        库里一条近似例都没有时指纹为空、也不进 dump——没用上近似字的书参数哈希不变、产物不过期。
        """
        d = handler(self)
        if isinstance(d, dict) and not self.ji_yi_si_clf:
            for k in ("ji_yi_si_clf", "ji_yi_si_clf_llm", "ji_yi_si_clf_margin",
                      "ji_yi_si_clf_table", "ji_yi_si_clf_fingerprint"):
                d.pop(k, None)
        if isinstance(d, dict) and self.ji_yi_si_clf and not self.ji_yi_si_clf_llm:
            d.pop("ji_yi_si_clf_llm", None)
            d.pop("ji_yi_si_clf_margin", None)
        if isinstance(d, dict) and not self.rare_agree:
            d.pop("rare_agree", None)
        if isinstance(d, dict) and not self.shadow_veto:
            for k in ("shadow_veto", "shadow_conf", "shadow_low_conf", "shadow_veto_variant_abstain"):
                d.pop(k, None)
        if isinstance(d, dict) and not self.rare_ref:
            d.pop("rare_ref", None)
        if isinstance(d, dict) and not self.shadow_promote:
            d.pop("shadow_promote", None)
            d.pop("shadow_promote_conf", None)
        if isinstance(d, dict) and not (self.shadow_veto or self.shadow_promote):
            for k in ("shadow_model", "shadow_model_fingerprint"):
                d.pop(k, None)
        if isinstance(d, dict) and not self.approx_gate:
            d.pop("approx_gate", None)
        if isinstance(d, dict) and not self.approx_fingerprint:
            d.pop("approx_fingerprint", None)
        if isinstance(d, dict) and not self.solo_ctx_veto:
            d.pop("solo_ctx_veto", None)
        if isinstance(d, dict) and not self.seal_blank_page:
            for k in ("seal_blank_page", "seal_blank_thr", "seal_blank_overlap", "seal_blank_ink_out"):
                d.pop(k, None)
        if isinstance(d, dict) and not self.juan_rule:
            d.pop("juan_rule", None)
            d.pop("juan_cov", None)
        if isinstance(d, dict) and not self.variant_tie:
            d.pop("variant_tie", None)
            d.pop("variant_tie_cov", None)
        if isinstance(d, dict) and not self.nonchar_gate:
            for k in ("nonchar_gate", "nonchar_flags", "nonchar_strokes"):
                d.pop(k, None)
        if isinstance(d, dict) and self.patch_missing == "error":
            d.pop("patch_missing", None)
        if isinstance(d, dict) and not (self.lane_witness3 or self.lane_coord or self.lane_seal):
            for k in ("lane_witness3", "lane_coord", "lane_seal", "lane_witnesses", "lane_seal_via",
                      "lane_seal_title_marks", "lane_witness_fingerprint", "lane_variant_guard",
                      "lane_variant_topk"):
                d.pop(k, None)
        if isinstance(d, dict) and not self.seal_lib_agree:
            d.pop("seal_lib_agree", None)
            d.pop("seal_lib_cov", None)
        if isinstance(d, dict) and not self._context_guard_on():
            for k in ("context_guard_diff", "context_guard_cov", "context_guard_flags",
                      "context_guard_flag_set", "context_guard_ref_blank", "context_guard_ref_prefer"):
                d.pop(k, None)
        return d

    @field_validator("patch_missing")
    @classmethod
    def _check_patch_missing(cls, v: str) -> str:
        if v not in ("error", "skip"):
            raise ValueError(f"seed_admit.patch_missing 只能是 error/skip，不是 {v!r}")
        return v

    def _context_guard_on(self) -> bool:
        return (self.context_guard_diff or self.context_guard_flags
                or self.context_guard_ref_blank or self.context_guard_ref_prefer)

    def model_post_init(self, _ctx) -> None:
        if not self.db_path:
            from ..core.workspace import glyph_db_path
            object.__setattr__(self, "db_path", str(glyph_db_path()))
        from ..steps.context_decide import corpus_fingerprint
        # 用字账与语义表同理（2026-09-05）：两张表都是派生物，重建就该让准入重跑
        if not self.ledger_fingerprint:
            from ..variant_ledger import ledger_path
            object.__setattr__(self, "ledger_fingerprint",
                               corpus_fingerprint([str(ledger_path(self.edition))]))
        if not self.variants_fingerprint:
            from ..clustering.variants import (DEFAULT_AUTO_PATH, DEFAULT_VARIANTS_PATH,
                                               NEVER_GROUP_PATH)
            # never_group.json 也管语义层（2026-09-28 overview#201），名单改了产物要过期
            paths = [self.variants] if self.variants else [
                str(DEFAULT_AUTO_PATH), str(DEFAULT_VARIANTS_PATH), str(NEVER_GROUP_PATH)]
            object.__setattr__(self, "variants_fingerprint", corpus_fingerprint(paths))
        if not self.variant_graph_fingerprint:
            from ..variants import DEFAULT_VARIANTS_JSON
            object.__setattr__(self, "variant_graph_fingerprint",
                               corpus_fingerprint([str(DEFAULT_VARIANTS_JSON)]))
        if self.use_exclusions and not self.exclusions_fingerprint:
            from ..clustering.exclusions import default_path as _ex_default
            object.__setattr__(self, "exclusions_fingerprint",
                               corpus_fingerprint([self.exclusions or str(_ex_default())]))
        # 人裁表直接读 glyph.db，这一步自己带库指纹——上游 glyph_match 的指纹只保证
        # 它自己重跑，不会让本步过期（人裁进库时 match 产物可能没变）。
        # 只看 provenance='human' 那部分（2026-09-20）：机器 align 进库、字头改判与本步
        # 的人裁通道无关，用整库指纹会让本步跟着白跑。
        if self.use_human_verdicts and not self.human_fingerprint:
            from .glyph_match import human_verdicts_fingerprint
            object.__setattr__(self, "human_fingerprint",
                               human_verdicts_fingerprint(self.db_path))
        # 版本注词表也是派生物（scripts/build_note_lexicon.py），同理
        if self.use_note_lexicon and not self.note_fingerprint:
            from ..clustering.note_lexicon import DEFAULT_LEXICON
            object.__setattr__(self, "note_fingerprint",
                               corpus_fingerprint([self.note_lexicon or str(DEFAULT_LEXICON)]))
        if (self.shadow_veto or self.shadow_promote) and not self.shadow_model_fingerprint:
            from ..shadow.model import file_fingerprint
            object.__setattr__(self, "shadow_model_fingerprint",
                               file_fingerprint(_shadow_model_path(self)) or "missing")
        if not self.approx_fingerprint:
            object.__setattr__(self, "approx_fingerprint", _approx_fingerprint(self.db_path))
        if self.ji_yi_si_ctx_rule and not self.ji_yi_si_ctx_fingerprint:
            from ..utils.near_form_ctx import CONFIG as _CTX_CONFIG
            object.__setattr__(self, "ji_yi_si_ctx_fingerprint", corpus_fingerprint([str(_CTX_CONFIG)]))
        if self.ji_yi_si_clf and self.ji_yi_si_clf_table and not self.ji_yi_si_clf_fingerprint:
            object.__setattr__(self, "ji_yi_si_clf_fingerprint",
                               corpus_fingerprint([self.ji_yi_si_clf_table]))
        if not self.iron_config_fingerprint:
            from ..clustering.iron_evidence import _CONFIG as _IRON_CONFIG
            object.__setattr__(self, "iron_config_fingerprint",
                               corpus_fingerprint([str(_IRON_CONFIG)]))


@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id="seed_admit", title="C1 进库准入", version="1.14", unit="cell",   # 1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸
        consumes=("glyph_match", "context_decision", "align_ref", "char_index"),
        optional_consumes=("ocr_candidates", "rare_candidates"),
        optional_consumes_when=(("ocr_candidates", "@book.ocr_candidates"), ("rare_candidates", "rare_agree"),
                                ("rare_candidates", "rare_ref"), ("rare_candidates", "shadow_promote"),),
        produces=("seed_admit",),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.clustering.seeding",
                   "open_guji_cv.clustering.variants",
                   "open_guji_cv.clustering.variant_form",
                   "open_guji_cv.variant_ledger",
                   "open_guji_cv.clustering.note_lexicon",
                   "open_guji_cv.utils.jiazhu_order",
                   "open_guji_cv.utils.near_form_ctx",
                   "open_guji_cv.utils.ji_yi_si_clf",
                   "open_guji_cv.clustering.iron_evidence",
                   "open_guji_cv.variants",
                   # 印章遮挡检测（overview#195）；它读的 Step3 `cells` 已经经 `char_index`
                   # 间接进了指纹，原图不变，所以不必加进 consumes。
                   "open_guji_cv.steps.occlusion",
                   # 待审补放三通道（overview#433）的证人逐格读法
                   "open_guji_cv.clustering.witness_cells", "open_guji_cv.report.witness"),
        # 册配置 `iron_gate:` 开不开进指纹——同 glyph_match 的 norm_stroke 那条口子，
        # 不然开关翻了、产物没过期（书级布尔量，不是 Params 字段，走这条路）。
        # `codepoints:` 同理（2026-09-27 加，`ref_lib_variant_guard` 的可信边判据读它）。
        book_deps=("iron_gate", "codepoints"),
        # 路径不进指纹（2026-09-29 K238）：db_path 留空填本机绝对路径；其余三个是「显式
        # 给才有值」的文件路径。内容各有指纹把关：human_fingerprint / variants_fingerprint /
        # note_fingerprint / exclusions_fingerprint（都只认文件名 + 内容哈希）。
        path_params=("db_path", "variants", "note_lexicon", "exclusions", "shadow_model"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.exclusions import excluded_ids
        from ..clustering.note_lexicon import load_lexicon, match_segment
        from ..clustering.seeding import (MATCH_SOLO_OCR_COV, NEAR_FORM_CHARS,
                                          admission_decision)
        from ..clustering.variant_form import decide_form, group_forms
        from ..clustering.variants import VariantMap
        from ..utils.jiazhu_order import segments as jz_segments
        from ..utils.jiazhu_order import sort_by_reading
        from ..variant_ledger import BookLedger
        p: SeedAdmitParams = ctx.params_for(self)  # type: ignore[assignment]
        vmap = VariantMap.load(p.variants or None)
        ledger = BookLedger.load_or_empty(p.edition)
        # 排除名单：人裁标过「切坏 / 带残留 / 非字」的图块**不进库也不出审查卡**
        # （用户 2026-08-25 定的口径，exclusions.py 模块头）。v1 的 seeding 一直
        # 查它，v2 此前漏了——于是标了缺陷的格子下一轮照样出现在待审队列里。
        from ..clustering.exclusions import default_path as _ex_default
        _ex_path = p.exclusions or str(_ex_default())
        _origins = tuple(s.strip() for s in (p.exclusion_origins or "").split(",") if s.strip())
        excluded = (excluded_ids(_ex_path, _origins or None)
                    if p.use_exclusions else frozenset())
        # 人裁过的位：**人裁是最强证据，任何自动通道都不许改写它**（2026-09-06）。
        # 实测 vol02:18:9:5——图上刻的是 曾（八字头），用户人裁 曾 且已进库
        # （provenance=human），但整理本这一处印 會，`context` 通道就按整理本放行成了
        # 會，判据 A 的「对你的裁决」因此掉到 210/211。库匹配、上下文、整理本对齐
        # 全都是间接证据，人看着图下的判断不是——它该一票定案。
        human_shapes = _human_shapes(p.db_path) if p.use_human_verdicts else {}
        if human_shapes:
            # 按入库时的编号记的人裁，先过绑定表找回现在对应的格（总览/15；重切后挂错格的根治）
            from ..feedback.bindings import rebind_library_shapes
            human_shapes = rebind_library_shapes(ctx.book.id, human_shapes)
        # 事件侧的人裁定字（2026-09-20）：勾了「字形不入库」的裁决不进字形库，上面那份就
        # 没有它——但字是定了的，文本采信不能丢。见 `feedback/lookup.human_chars`。
        from ..feedback.lookup import human_chars
        human_texts = human_chars(ctx.book.id) if p.use_human_verdicts else {}

        _ex_cache: dict = {}

        def _ex_records() -> dict:
            # 名单一页要查几十次，load_exclusions 每次重读整个文件——缓存在本次
            # run_page 内（名单是外部状态，不跨页缓存）。
            if not _ex_cache:
                from ..clustering.exclusions import load_exclusions
                _ex_cache.update(load_exclusions(_ex_path) or {"": {}})
            return _ex_cache

        def excluded_note(iid: str) -> str:
            rec = _ex_records().get(iid, {})
            return f"{rec.get('origin', '?')}:{rec.get('reason', '?')}"
        match: PageMatch = ctx.product("glyph_match", page)
        ocr: PageOcr | None = (_opt(ctx, "ocr_candidates", page)
                               if ctx.book.ocr_candidates else None)
        dec: PageDecision | None = _opt(ctx, "context_decision", page)
        chars = _opt(ctx, "char_index", page)

        omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
        dmap = {r.id: r for cc in (dec.columns if dec else []) for r in cc.chars}
        imap = {r.id: r for cc in (chars.columns if chars else []) for r in cc.chars}
        mmap = {r.id: r for cc in match.columns if cc.ok for r in cc.chars}
        rtop: dict[str, list[str]] = {}
        if p.rare_agree or p.rare_ref:
            from .align_ref import rare_topk_map
            rtop = rare_topk_map(_opt(ctx, "rare_candidates", page), 1)
        amap = _align(ctx, page)
        coord_cache: dict = {}
        always = set(p.always_review or "")
        context_verdicts = frozenset(
            s.strip() for s in (p.context_verdicts or "").split(",") if s.strip())
        off_channels = frozenset(
            s.strip() for s in (p.off_channels or "").split(",") if s.strip())
        if p.replace_form not in ("align", "lib", "review"):
            raise ValueError(f"seed_admit.replace_form 只能是 align/lib/review，不是 {p.replace_form!r}")
        out: list[ColumnAdmit] = []
        n_auto = n_review = n_excluded = 0
        # 铁证放行通道（用户 2026-09-27 批：只放行文本，不进字形库）。册配置
        # `iron_gate:` 关时这两个都是 None，下面 `_iron_decide` 直接跳过——
        # 零额外开销，不影响没开这个开关的书。
        iron_ns = getattr(ctx.book, "norm_stroke", None)
        iron_ctx = (_iron_context(p.db_path, iron_ns) if ctx.book.iron_gate else None)
        # 读不到字块：`patch_missing=error` 抛错停页；`skip` 记到 {格 id: [跳过的路]}，落进 evidence。
        patch_missing: dict[str, list[str]] = {}

        def soft_patch(rid: str, lane: str, fn, *a):
            try:
                return fn(*a)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                patch_missing.setdefault(rid, []).append(lane)
                return None
        iron_scale = (_iron_page_scale(ctx, page, match,
                                       on_missing=(None if p.patch_missing != "skip" else
                                                   lambda rid: patch_missing.setdefault(rid, []).append("iron_scale")))
                      if iron_ctx else None)
        # 印章／污损遮挡（`occluded_gate`，overview#195）：{字位 id: (密度, 默认字, 来源)}
        occ = _occluded(ctx, page, match, p, amap) if p.occluded_gate else {}
        # 近似字闸（overview#276）：{近似例 id}、{刻例全是近似例的 (字)}；表空时两个都是空集
        apx_ids, apx_only = (_approx_index(p.db_path) if p.approx_fingerprint
                             else ({}, frozenset()))
        for cc in match.columns:
            if not cc.ok:
                out.append(ColumnAdmit(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[AdmitRec] = []
            # ── 版本注闭集通道（段级预扫，2026-09-06）─────────────────
            # 夹注小字库里样本极少（16,019 例里 59 个），逐字认必然卡在
            # cov 0.93~0.99 的灰带上落人审。但版本注是闭集（78 个短语），
            # 整段一起认反而稳。段级判据见 clustering/note_lexicon 模块头，
            # 三条硬约束（格数相等 / 相似度 / 唯一最佳）缺一不可。
            # 这里只产出「这一格该读什么」的建议，**写不写库仍走下面的
            # 逐格通道**——短语给的是读法，字形还要过账本的组内定形。
            note_char: dict[str, str] = {}
            note_sim: dict[str, float] = {}
            if p.use_note_lexicon:
                jz = [r for r in cc.chars if r.sub]
                if jz:
                    lex = load_lexicon(p.note_lexicon or None)
                    for seg in jz_segments((r.slot, r.sub) for r in jz):
                        sset = set(seg)
                        rs = sort_by_reading([r for r in jz if r.slot in sset])
                        cands: list[set[str]] = []
                        for r in rs:
                            cs = {c for c, _v in r.candidates[:5]}
                            oo = omap.get(r.id)
                            if oo:
                                cs |= {c for c, _v in oo.topk[:5]}
                            dd0 = dmap.get(r.id)
                            if dd0 and dd0.char:
                                cs.add(dd0.char)
                            cands.append(cs)
                        hit = match_segment(cands, lex, min_sim=p.note_min_sim,
                                            semantic=vmap.semantic)
                        if hit:
                            phrase, sim = hit
                            for r, ch in zip(rs, phrase):
                                note_char[r.id] = ch
                                note_sim[r.id] = sim
            garble_run = (_rare_run_ids(cc.chars, p.context_garble_run)
                          if p.context_garble_guard else frozenset())
            for r in cc.chars:
                # 排除名单命中：这块图人已判过切坏/带残留/非字。既不进库也不出
                # 审查卡，只落一行留账（v1 的 seeding 同款处理）。放在最前面——
                # 后面那些证据都建立在「这块图是完整的一个字」之上，图都不成立
                # 就没什么可判的。
                if r.id in excluded:
                    n_excluded += 1
                    # 原图破损档（2026-09-19）：字位**占住**，文本层出 `□`，
                    # 人给的 `guess`（最像哪个字）挂在 evidence 上供渲染括注。
                    # 与其余排除原因（切坏/非字）不同——那些是「这块图不可用」，
                    # 这一档是「原刻就残，字确实在这儿但认不出」，字位不能消失，
                    # 否则整列字数对不上（cv-segmentation §九 的逐列对账）。
                    exrec = _ex_records().get(r.id, {})
                    damaged = exrec.get("reason") == "damaged"
                    guess = ""
                    for tag in exrec.get("evidence") or []:
                        if isinstance(tag, str) and tag.startswith("guess="):
                            guess = tag[6:]
                    evd = {"excluded": excluded_note(r.id)}
                    if damaged:
                        evd["damaged"] = True
                        if guess:
                            evd["guess"] = guess
                    elif exrec.get("reason") != "not_a_char":
                        # 切坏／裁坏（seg_defect／crop_defect）但人已给了字（overview#403 缺口 B）：
                        # 图块照旧不进库、不出卡，字挂在 evidence 上供文本层出字——「不入库」说的是
                        # 这块图不当范本，不是「这个字没定」（同 `lookup.human_chars` 的口径）。
                        hs_x, ht_x = human_shapes.get(r.id), human_texts.get(r.id)
                        hc = ht_x if (ht_x and hs_x in _JYS and ht_x in _JYS) else (hs_x or ht_x)
                        if hc:
                            evd["human_char"] = hc
                    recs.append(AdmitRec(
                        id=r.id, slot=r.slot, sub=r.sub, admit=False,
                        channel=None, char=("□" if damaged else None), provenance="",
                        doubts=["excluded"],
                        evidence=evd))
                    continue
                # 人裁过的位：一票定案，后面所有自动通道都不再看（2026-09-06）。
                # 人是**看着图**判的，库匹配/上下文/整理本对齐全是间接证据；实测
                # vol02:18:9:5 图上刻 曾、用户裁 曾 已进库，整理本这一处印 會，
                # `context` 通道就把它放行成了 會——人裁被机器覆盖，判据 A 的
                # 「对你的裁决」掉到 210/211。放在排除名单之后、其余通道之前。
                hs = human_shapes.get(r.id)
                ht = human_texts.get(r.id)
                if hs or ht:
                    n_auto += 1
                    # 字优先取库里那份（进库时经过清洗）；库里没有（人勾了不入库）就取事件里的。
                    # 己/已/巳 例外：事件侧已按人当时的文意判断归好（`lookup.human_chars`），
                    # 库里存的可能是「看着像的那个」——本族字形不分，取事件的（utils/ji_yi_si.py）。
                    char = ht if (ht and hs in _JYS and ht in _JYS) else (hs or ht)
                    recs.append(AdmitRec(
                        id=r.id, slot=r.slot, sub=r.sub, admit=True,
                        channel="human", char=char,
                        provenance="human", doubts=[],
                        evidence={"human": True, **({} if hs else {"no_glyph_lib": True})}))
                    continue
                # 印章／污损遮挡：一律不放行、不进库，默认字取整理本（坐标对位优先）。
                # 放在人裁之后——人已经看着图定过的字照旧一票定案。
                if r.id in occ:
                    n_review += 1
                    dens, dflt, via = occ[r.id]
                    oev = {"density": round(dens, 2), "via": via}
                    if via == "coord_blank":
                        oev["ref_blank"] = True
                    recs.append(AdmitRec(
                        id=r.id, slot=r.slot, sub=r.sub, admit=False, channel=None,
                        char=dflt, provenance="", doubts=["occluded"],
                        evidence={"verdict": r.verdict, "cov": r.cov, "occluded": oev}))
                    continue
                o = omap.get(r.id)
                # OCR 只供候选，**置信度不参与任何自动判断**（见模块头）
                ocr_in = ({"char": o.topk[0][0], "prob": o.topk[0][1]}
                          if o and o.topk else None)
                # **near_form 疑问要自己判**（2026-09-04 修）。`judge_doubts`
                # 在 v1 里靠整理本/载体产出六条疑问，这里没有整理本，但
                # `near_form` 只看候选字属不属于形近家族，自己就能判——
                # 不判的话 `admission_decision` 的形近防线整条失效。
                # 实锤：vol01:151:8:4 库候选 諭 0.9923 / 論 0.9898 只差
                # 0.0025，matcher 已把它从 same 降档 unsure（但 guard 字段
                # 是 None，v1 就没填），match_solo 只看 cov ≥ 0.99 就放行，
                # 结果把「論」认成「諭」——**dev_set 1619 条金标里唯一的错**。
                cand_chars = {c for c, _v in r.candidates[:3]}
                if r.char:
                    cand_chars.add(r.char)
                doubts = (["near_form"] if cand_chars & NEAR_FORM_CHARS else [])
                # 整理本这一路（2026-09-04 接上）。v1 标定过 match_ref 144/144、
                # match_replace 70/70、match_margin 102/102，靠的就是「文本证据 ×
                # 形状证据同源性为零」；v2 此前一直传 align_char=None，这些通道
                # 一条都没生效，于是每个库 unsure 都要人点。
                # replace 段照 v1 记 DOUBT_REPLACE_ALIGN（那层有独立的更严闸）。
                al = amap.get(r.id)
                align_char = al[0] if al else None
                if al and al[1] == "replace":
                    doubts.append("replace_align")
                note_ch = note_char.get(r.id)
                # 账本人确认过的 T2 对（variant_strategy.md §4.3 第 6 行）：两头都是正字、
                # 语义表不合并（注/註、鍾/鐘），但本书人裁明确记过「刻 X 读 Y」——对这一位
                # 把 X 当 Y 的同义看，让 match_ref / match_replace 照常评。只影响这一次调用。
                lib_top = r.char or (r.candidates[0][0] if r.candidates else None)
                vm_here = vmap
                if (align_char and lib_top and lib_top != align_char
                        and vmap.semantic(lib_top) != vmap.semantic(align_char)
                        and ledger.pair_confirmed(lib_top, align_char)):
                    vm_here = _PairAwareMap(vmap, {lib_top: vmap.semantic(align_char)})
                # CNN 字形背书（match_solo_cnn 用）：只在**灰区且无整理本**时才算，
                # 别的档一律不看它——避免把一路弱独立证据混进已经成立的两路里。
                # 取图有代价（要读 char_patch 并过网络），所以先判档位再算。
                cnn_char = None
                if (align_char is None and r.verdict != "same" and r.candidates
                        and max(c for _, c in r.candidates) >= MATCH_SOLO_OCR_COV):
                    cnn_char = soft_patch(r.id, "cnn", _cnn_top, ctx, page, cc.col, r.slot, r.sub)
                ok, channel = admission_decision(
                    ocr=ocr_in, align_char=align_char, ref_char=None,
                    doubts=doubts, vmap=vm_here,
                    match_char=r.char if r.verdict == "same" else None,
                    match_candidates=list(r.candidates),
                    match_guard=r.guard, match_wmax=r.wmax,
                    solo_cov=p.solo_cov, cnn_char=cnn_char)
                # 书级收紧（overview#155）：关通道 / match_solo 形近闸。放在所有兜底通道之前，
                # 作废的格后面仍可能被别的独立证据接住。
                if ok and channel in off_channels:
                    ok, channel = False, None
                    doubts.append("channel_off")
                elif (ok and p.solo_confusable_guard and channel in _SOLO_CHANNELS
                      and r.candidates and _confusable_char(r.candidates[0][0])):
                    ok, channel = False, None
                    doubts.append("solo_confusable")
                elif (ok and p.solo_ctx_veto and channel in _SOLO_CHANNELS
                      and _solo_ctx_vetoed(dmap.get(r.id), r.candidates, vm_here, p.solo_ctx_veto)):
                    ok, channel = False, None
                    doubts.append("solo_ctx_veto")
                # 异体等价只经间接路径成立的撤回（`variant_indirect_guard`）。库形取
                # 这几条通道自己比的那个字：match_ref 库 same 时是 r.char，其余是 cov 最高的候选。
                if (ok and p.variant_indirect_guard and align_char and r.candidates
                        and channel in ("match_ref", "match_replace", "match_margin")):
                    _shape = (r.char if channel == "match_ref" and r.verdict == "same" and r.char
                              else max(r.candidates, key=lambda t: t[1])[0])
                    if _variant_indirect(_shape, align_char, ledger, ctx.book):
                        ok, channel = False, None
                        doubts.append("variant_indirect")
                # ── 版本注闭集通道 note_lexicon（2026-09-06）──────────
                # 走到这里还没放行、而段级匹配给出了读法时补一刀。判据与
                # match_ref 同构（文本证据 × 形状证据、来源独立），但证据来自
                # **整段**而不是单格，所以另立通道名，出了错能按通道归因。
                # 四条护栏：
                #   1. 只对夹注格（sub 非空）——正文有整理本逐字对齐，用不着它；
                #   2. 库候选里要有语义同字的（形状不背书就不算两路互证）；
                #   3. 形近家族、never_match/db_inconsistent 护栏照拦；
                #   4. always_review 的字不碰（下面那道闸也会再拦一次）。
                #   5. **字级证据强时不许短语改写字形**（2026-09-06 异体字线实锤）：
                #      vol02:157:2:12b 库判 same cov 0.9984、OCR top1 也同字，两路形状
                #      证据一致，而短语把它读成了别的字——产物因此留下一条假转换，
                #      在账本的「关系图外转换对」才露头。段级匹配的价值是「整段比逐字稳」，
                #      但短语只差一个字也能匹配上，于是那个字被短语的读法改写。
                #      所以：库 same 且 cov ≥ solo_cov 时，短语只能**同意**不能**改写**。
                #      全书实测该通道只放行 5 条，加这条护栏一条都不损失。
                lib_same_strong = (r.verdict == "same" and r.char
                                   and r.cov >= p.solo_cov)
                if (not ok and note_ch and r.sub
                        and r.guard is None
                        and "db_inconsistent" not in doubts
                        and not (lib_same_strong
                                 and vmap.semantic(r.char) != vmap.semantic(note_ch))):
                    cands_sem = {vmap.semantic(c) for c, _v in r.candidates[:5]}
                    if (vmap.semantic(note_ch) in cands_sem
                            and note_ch not in NEAR_FORM_CHARS):
                        ok, channel = True, "note_lexicon"
                        align_char = align_char or note_ch
                # 己/已/巳 不采信字形/OCR 通道的判决（用户 2026-09-04 定，2026-09-11
                # 改口己也算同词异写）。这几个字的字形与文意会分岔，字形层护栏拦不住
                # align×库 这种跨源一致，任何自动通道都不该替人决定读法——但清空判决
                # 不等于直接人审，下面 split_ref/context 两条通道仍可能重新放行。
                if (align_char in always
                        or (r.candidates and r.candidates[0][0] in always)
                        or (r.char in always)):
                    if p.relax_split_ref and align_char in always:
                        # 己已巳：字形只定「是这一族」，哪个字按上下文（用户 2026-09-06 / 09-26）。
                        # 这里先放行、字取整理本；页末 `_resolve_ji_yi_si` 按上下文改定。
                        ok, channel = True, "split_ref"
                    elif ok:
                        ok, channel = False, None

                char = _pick_char(
                    ok=ok, channel=channel, align_char=align_char,
                    match_char=r.char, verdict=r.verdict,
                    candidates=list(r.candidates))
                if channel == "split_ref":
                    # 己/已/巳：刻本三字刻法常不分，库 top1 定不了是哪个字，先取整理本字；
                    # 页末 `_resolve_ji_yi_si` 再按上下文定（干支/时辰/搭配压过整理本）。
                    char = align_char
                # variant_form 分支要用**改名前**的 channel 判——见下面「⚠️ dual 档判 variant_form
                # 判早了」。这里先存一份，改名（下一段）之后再用它，别被 "dual" 字符串盖掉。
                is_corpus_channel = channel in _CORPUS_CHANNELS
                # `admission_decision` 给 dual 档返回 None（历史口径，别去改它
                # ——`_pick_char` 与 seeding 的一串标定注释都按 None 写的）。但
                # **产物里不许有匿名准入**：每条自动进库都得说清走的哪条通道，
                # 否则出了错没法按通道归因（test_seed_admit_step 有护栏）。
                # 所以在取完字之后、写产物之前补上名字。
                if ok and channel is None:
                    channel = "dual"
                prov = "match" if ok else ""
                # 「义定形未定」（2026-09-05，variant_strategy.md §4.2）：整理本通道
                # 放行的、库又没下 same 断言的位，`_pick_char` 把整理本形当成了刻本形。
                # 整理本对多数组只用一种形，它定得了义定不了形——刻 髪 存 髮 就是这么
                # 来的。组里有 ≥2 个可能的形时，用形状证据（库候选 / 组内三源检索）
                # 定形；定不了就落人审，卡片只列组内的形，人点一次账本就记住。
                #
                # ⚠️ dual 档判 variant_form 判早了（2026-09-06 实锤）：本该判的是
                # 「这条通道用没用整理本」，但这里一度直接拿**改名后**的 channel 去比
                # `_CORPUS_CHANNELS`（里面收的是 None，不是字符串 "dual"），于是 dual
                # 档永远进不了这个分支——隸/𨽾、變/𠮓 这些账本已经改判优先形（preferred=
                # 𨽾/𠮓）的组，dual 位还是照写库 unsure 时的整理本形，E 报 82/91 才发现。
                form_ev = None
                form_open = False
                if ok and align_char and is_corpus_channel and r.verdict != "same":
                    forms = group_forms(ledger, align_char)
                    if len(forms) >= 2:
                        ranks = None
                        fd = decide_form(align_char, forms, list(r.candidates), ledger)
                        if fd.state == "open":
                            ranks = soft_patch(r.id, "form", _image_ranks,
                                               ctx, page, cc.col, r.slot, r.sub, forms)
                            if ranks:
                                fd = decide_form(align_char, forms, list(r.candidates), ledger, ranks)
                        form_ev = fd.to_evidence()
                        _top = r.candidates[0][0] if r.candidates else None
                        if fd.state == "open" and p.relax_ref_agree and _top in forms:
                            # 用户 2026-09-06「整理本和字形分析一致时直接放行」：组里哪个形
                            # 没定，但库 top1 就是组内的一个形——拿它当形（最好的猜测）。证据里 state=guess，判据 E 的分母（_multi_form）会把
                            # 它算进抽审；错了走 audit_glyph_consistency 那套人裁子库复查。
                            char = _top
                            form_ev = {**form_ev, "state": "guess"}
                        elif fd.state == "open":
                            ok, channel, prov, form_open = False, None, "", True
                            doubts = doubts + ["form_open"]
                            char = None
                        else:
                            char = fd.char
                # match_replace 的码位（overview#155）：整理本字与库 top1 语义同、字面不同，
                # 而用字账没接手定形（form_ev 为空）时，按 `replace_form` 取库形或落审。
                if (ok and channel == "match_replace" and p.replace_form != "align"
                        and form_ev is None and r.verdict != "same" and r.candidates):
                    _top = r.candidates[0][0]
                    if align_char and _top != align_char \
                            and vm_here.semantic(_top) == vm_here.semantic(align_char):
                        if p.replace_form == "lib":
                            char = _top
                        else:
                            ok, channel, prov, char = False, None, "", None
                            doubts = doubts + ["replace_form"]
                # 上下文当第三路：库没定下来、但 Step6 过了门槛，仍可进库
                # （provenance=context，设计 §3.2 的分级）。字形层照录 —— 这里
                # 用的是候选内选出的 surface，不引入候选外的字。形未定时不走：
                # 上下文只能定义，定不了形。
                # 己/已/巳 现在**允许**走 context 通道（用户 2026-09-11 改口，推翻下面
                # 2026-09-06 那版「永远人审」）：「没有整理本兜底时，也允许走 Step6 上下文
                # 判定通道」——这道题字形本就不重要，只要文意判定给了结果就该放行，没结果
                # 才降级人审。
                #
                # 历史教训存档，不再适用：2026-09-06 曾在这里加过 `d.char not in always`
                # 排除，因为 vol01 有 30 条 context 放行的 已/巳，抽审 18 条里 16 条「形不对」
                # （刻 巳 存成整理本的 已）。但那次担心的是「字形库被污染」——2026-09-11 起
                # 己已巳组的样本数在 `glyph_db.admit_instance` 里被封顶（见
                # `CONFUSABLE_SAMPLE_CAP`），达到上限后这组字不再新增 exemplar，字形匹配层
                # 不会继续被这条通道的判决污染，旧顾虑不再成立。
                d = dmap.get(r.id)
                # 2026-09-20 加互证：上下文定的字与整理本对齐字语义不同就不放行
                # （`seeding.context_conflicts_ref`，bxgb 7 条 context 误放行全是这一型）。
                # 用 `vm_here`（账本确认过的 T2 对已并进去），别用裸 vmap。
                from ..clustering.seeding import context_conflicts_ref
                if (not ok and not form_open and p.use_context and d and d.source == "context"
                        and d.char and d.margin >= p.context_margin):
                    _ir = imap.get(r.id)
                    if context_verdicts and r.verdict not in context_verdicts:
                        doubts.append("context_verdict")
                    elif context_conflicts_ref(d.char, align_char, vm_here):
                        doubts.append("context_vs_ref")
                    elif p.context_blank_gate and _ir is not None \
                            and _ir.ink_ratio < p.context_min_ink:
                        doubts.append("context_blank_cell")
                    elif p.context_garble_guard and (_gg := _garble_guard(
                            p, r, d.char, (align_char, _coord_refs(ctx, page, coord_cache).get(r.id),
                                           *(c for c, _ in (o.topk if o else []))),
                            garble_run, vm_here)):
                        doubts.append(_gg)
                    elif p._context_guard_on() and (_g := _context_guard(
                            p, r, d.char, _ir, _coord_refs(ctx, page, coord_cache), vm_here)):
                        doubts.append(_g[0])
                        char = _g[1] or char
                    else:
                        ok, channel, char, prov = True, "context", d.char, "context"

                # 整理本 × 形状/上下文 一致 → 放行（用户 2026-09-06「很多都是整理本存在时
                # 非常明显的选择，能不能放松要求」）。走到这里还没放行的位，若整理本字与库
                # top1 语义同字（刻本形归一后是同一个字），或与 Step6 上下文定字相同，就放行：
                # 形取库 top1（它是刻本形）。两册人审位实测（关掉人裁通道的
                # 产物）整理本≡库top1 10/10、==上下文 4/4；全部人裁真值上反例 0（relax_study）。
                # 己已巳 不走这里（上面 split_ref 单独处理）。
                if (not ok and p.relax_ref_agree and align_char and align_char not in always):
                    _top = r.candidates[0][0] if r.candidates else None
                    _d = dmap.get(r.id)
                    if _top and _top not in always \
                            and vmap.semantic(_top) == vmap.semantic(align_char):
                        # 字面相同不受加闸影响，照放（任务书「字面相同的放行照旧」）。
                        # 字面不同——变体放行——才要过闸：可信边，或 Step6 margin 过线
                        # （复用 context_margin，同一把生产已在用的尺子），否则记
                        # doubt、退回人审，不采信这条判决（ref_lib_variant_guard）。
                        # 间接路径（经共同正字才同义）不许靠 margin 过闸（variant_indirect_guard）。
                        _indirect = (p.variant_indirect_guard and _top != align_char
                                     and not _direct_variant_edge(_top, align_char))
                        if _top == align_char:
                            ok, channel, prov = True, "ref_lib", "match"
                            char = _top
                        elif (_trusted_variant_edge(_top, align_char, ledger, ctx.book)
                              or (not _indirect
                                  and (not p.ref_lib_variant_guard
                                       or (_d is not None and _d.margin >= p.context_margin)))):
                            ok, channel, prov = True, "ref_lib", "match"
                            char = _top
                        else:
                            doubts.append("ref_lib_variant")
                            if _indirect and "variant_indirect" not in doubts:
                                doubts.append("variant_indirect")
                    elif _d and _d.char and _d.char == align_char:
                        ok, channel, prov = True, "ref_ctx", "context"
                        char = align_char

                # 「数字＋卷」（`juan_rule`，Y1）。放在 context／ref_lib 之后、铁证之前：前面都
                # 没放行才补，不覆盖任何已放行的判决。
                if (not ok and p.juan_rule and not form_open and not r.sub and r.guard is None
                        and r.candidates and r.candidates[0][0] == "卷"
                        and r.candidates[0][1] >= p.juan_cov
                        and set(doubts) <= _JUAN_DOUBTS
                        and (align_char is None or align_char in _JUAN_FORMS)
                        and recs and not recs[-1].sub
                        and _after_number(recs[-1], amap, dmap, mmap)):
                    ok, channel, char, prov = True, "juan", "卷", "match"
                    doubts = []

                # 异体并列放行（`variant_tie`，Y1）：前面通道都没放行才补。
                if (not ok and p.variant_tie and not form_open and r.guard is None and r.candidates
                        and r.candidates[0][1] >= p.variant_tie_cov
                        and set(doubts) <= _JUAN_DOUBTS
                        and _variant_tie_ok(r.candidates, align_char, p.variant_tie_extra)):
                    ok, channel, char, prov = True, "variant_tie", r.candidates[0][0], "match"
                    doubts = []

                # 铁证放行（用户 2026-09-27 批准转正，`iron_evidence` 模块）：本格与一个
                # 人裁过、别的格的实例比对，够像就放行文本——不看整理本、不看 OCR，只认
                # 字形库里已确认的刻例。**只当兜底**：放在这里、`if not ok` 之后——只给
                # 上面所有通道都没定下来的格再补一次机会，不覆盖任何已经放行的判决（哪怕
                # 铁证跟它不一致）。开关前后产物 diff 因此只应该多出 `channel="iron"` 的新
                # 增格，一个已有的格都不会变——这是这次转正验证的判据，也是「先不进库」
                # 那种谨慎口子该配的谨慎版本：铁证闸更擅长的「揪出 dual/match_ref 语义对
                # 但字形错的位」（王/玉 那类）这次先不做，只扩覆盖率，不动存量判决。
                if not ok and iron_ctx is not None:
                    iron_char = soft_patch(r.id, "iron", _iron_decide, ctx, page, cc.col, r,
                                           iron_ctx, iron_scale, iron_ns)
                    if iron_char is not None and p.iron_ref_guard \
                            and context_conflicts_ref(iron_char, align_char, vm_here):
                        doubts.append("iron_vs_ref")
                    elif iron_char is not None and p.iron_confusable_guard \
                            and _iron_confusable_witness(
                                iron_char, (align_char, _coord_refs(ctx, page, coord_cache).get(r.id)),
                                vm_here):
                        doubts.append("iron_confusable_ref")
                    elif iron_char is not None:
                        ok, channel, char, prov = True, "iron", iron_char, "iron"
                        doubts = []
                # 库高置信兜底（`lib_confident_cov`，缺省关）：只补「库已经很像、只因 Step6
                # 帮不上（退回先验）」的格。约束见参数文档；`doubts` 非空说明流程里已有别的
                # 理由拦它（整理本 replace、形近、互证冲突……），一律不碰。
                if (not ok and p.lib_confident_cov > 0 and not doubts and not form_open
                        and r.verdict == "unsure" and r.guard is None and r.candidates
                        and d is not None and d.source == "prior"):
                    _top, _c1 = r.candidates[0]
                    _c2 = r.candidates[1][1] if len(r.candidates) > 1 else 0.0
                    if (_c1 >= p.lib_confident_cov and _c1 - _c2 >= p.lib_confident_gap
                            and _top not in always and _top not in _JYS
                            and not (align_char and align_char in _JYS)
                            and not _confusable_char(_top)
                            and not (align_char and vm_here.semantic(align_char)
                                     != vm_here.semantic(_top))):
                        ok, channel, char, prov = True, "lib_confident", _top, "match"
                # 非字过滤（`nonchar_gate`，Y1）：放在所有通道之后，只会把放行挪去待审。
                if ok and p.nonchar_gate:
                    _ir2 = imap.get(r.id)
                    _bad = ({f for f in (p.nonchar_flags or "").split(",") if f}
                            & set(getattr(_ir2, "flags", None) or ()))
                    if _bad or (char and char in (p.nonchar_strokes or "")):
                        ok, channel, prov = False, None, ""
                        doubts.append("nonchar")
                # 近似例（overview#276）：这一格的字就是库给的字、而库给它的依据是近似例 →
                # 缺省照常放行、在 evidence 里标注（文本侧表与卡片读它）；开了闸才挪去人审。
                # 放在所有通道之后：闸只会把格从放行挪到待审，不改字、不会反过来。
                apx_ev = (_approx_hit(r, char, apx_ids, apx_only)
                          if (apx_ids or apx_only) else None)
                if ok and apx_ev and p.approx_gate:
                    ok, channel, prov = False, None, ""
                    doubts.append("approx_exemplar")
                # 库匹配超时（Step5-a `cell_budget_s`，overview#493）：没有任何库证据，哪条通道都不放行
                # （含 match_solo／OCR／上下文／CNN）。放在所有通道之后；后面各遍用 _LANE_HARD／
                # _hard_blocked 认这个码，也不会补放。没开预算就没有 timeout 格，缺省行为不变。
                if r.guard == "timeout":
                    ok, channel, prov = False, None, ""
                    doubts.append("glyph_timeout")
                if ok:
                    n_auto += 1
                else:
                    n_review += 1
                recs.append(AdmitRec(
                    id=r.id, slot=r.slot, sub=r.sub, admit=ok, channel=channel,
                    char=char, provenance=prov,
                    doubts=[] if ok else (_doubts(r, d) + doubts),
                    evidence={"verdict": r.verdict, "cov": r.cov, "wmax": r.wmax,
                              "guard": r.guard,
                              "ocr": (o.topk[:3] if o else []),
                              "ctx_margin": (d.margin if d else None),
                              **({"form": form_ev} if form_ev else {}),
                              **({"rare": _rare_agree(r, rtop.get(r.id))}
                                 if p.rare_agree else {}),
                              **({"approx": apx_ev} if apx_ev else {}),
                              **({"patch_missing": patch_missing[r.id]}
                                 if r.id in patch_missing else {})}))
            out.append(ColumnAdmit(col=cc.col, ok=True, chars=recs))
        d_auto, d_review = _resolve_ji_yi_si(out, amap, dmap, mmap, p.ji_yi_si_review,
                                              ctx_rule=(p.ji_yi_si_ctx_purity, p.ji_yi_si_ctx_min_n) if p.ji_yi_si_ctx_rule else None,
                                              clf=p if p.ji_yi_si_clf else None)
        n_auto += d_auto
        n_review += d_review
        if p.rare_ref:
            d_rr = _rare_ref_pass(out, mmap, amap, rtop)
            n_auto += d_rr
            n_review -= d_rr
        if p.shadow_veto:
            d_veto = _shadow_veto_pass(ctx, page, p, out, mmap, amap)
            n_auto -= d_veto
            n_review += d_veto
        if p.shadow_promote:
            d_pro = _shadow_promote_pass(ctx, page, p, out, mmap, amap)
            n_auto += d_pro
            n_review -= d_pro
        if p.seal_blank_page and p.lane_seal:
            from .occlusion import page_seal_blank
            d_seal = _seal_blank_flip(out, page_seal_blank(ctx, page, p),
                                      _coord_refs(ctx, page, coord_cache))
            n_auto -= d_seal
            n_review += d_seal
        if p.lane_witness3 or p.lane_coord or p.lane_seal:
            d_lane = _review_lanes_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), vmap,
                                        (lambda: _lane_witnesses(ctx.book, p))
                                        if (p.lane_witness3 or p.lane_coord) else None)
            n_auto += d_lane
            n_review -= d_lane
        if patch_missing:
            lanes: dict[str, int] = {}
            for v in patch_missing.values():
                for k in v:
                    lanes[k] = lanes.get(k, 0) + 1
            ctx.log(f"seed_admit p{page}: patch_missing=skip，{len(patch_missing)} 格读不到字块、"
                    f"跳过 {lanes}（见各格 evidence.patch_missing）")
        return {"seed_admit": PageAdmit(page=page, n_auto=n_auto, n_excluded=n_excluded,
                                        n_review=n_review, columns=out)}


_RARE_REF_HARD = ("occluded", "excluded", "near_form", "context_blank_cell", "form_open", "approx_exemplar")


def _variant_tie_ok(cands, align_char, extra: str = "") -> bool:
    """top1 有异体近邻，且 cov 与 top1 相差不到 0.03 的候选（top-3 内）都是它的异体；top1 属形近家族不放。"""
    groups = [g for g in (extra or "").split(",") if g]

    def edge(a: str, b: str) -> bool:
        if a == b:
            return True
        if groups:       # 给了组表就**只认组表**（用户按组裁决过的组），不再认 variants.json 的边
            return any(a in g and b in g for g in groups)
        return _direct_variant_edge(a, b)
    top, c1 = cands[0]
    if _confusable_char(top):
        return False
    near = [c for c, v in cands[1:3] if c1 - v < 0.03]
    if not near or not all(edge(top, c) for c in near):
        return False
    return align_char is None or edge(top, align_char) or align_char in near


_JUAN_FORMS = frozenset("卷巻")
_JUAN_DOUBTS = frozenset({"replace_align", "context_vs_ref"})
_NUMERALS = frozenset("一二三四五六七八九十百千幾")


def _after_number(prev: AdmitRec, amap: dict, dmap: dict, mmap: dict) -> bool:
    """前一格（正文）的字是数字？取已定的字，没定就看整理本对齐字、再看库 top1。"""
    ch = prev.char
    if not ch and prev.id in amap:
        ch = amap[prev.id][0]
    if not ch and prev.id in dmap:
        ch = dmap[prev.id].char
    if not ch and prev.id in mmap:
        ch = mmap[prev.id].char
    return bool(ch) and ch in _NUMERALS


def _hard_blocked(doubts, guard) -> bool:
    """规则 A／影子升级共用的硬护栏：这些格任何新增通道都不碰。"""
    return (guard in ("never_match", "conflict", "timeout")
            or any(d.startswith("护栏:") or d in _RARE_REF_HARD for d in doubts))


def rare_ref_decide(*, doubts, guard, verdict, lib_char, lib_top, ref, op, rare_top, are_variants) -> str | None:
    """规则 A（`SeedAdmitParams.rare_ref`）的判据，纯函数（离线评测与线上共用）。→ 放行字（=整理本字）或 None。

    `lib_char`：库判 same 时的字（否则 None）；`lib_top`：库首位（same 取 char，否则候选第一名）；
    `rare_top`：5-b 首位；`are_variants(a, b)`：两字有无直接异体关系。"""
    if op != "replace" or not ref or ref in _JYS or not rare_top or rare_top != ref:
        return None
    if _hard_blocked(doubts, guard):
        return None
    if verdict == "same" and lib_char and lib_char != ref:
        return None                       # 库明确认成了别的字
    if lib_top and lib_top != ref and are_variants(lib_top, ref):
        return None                       # 库首位是整理本字的异体：形取谁说不准，留给人
    return ref


def _rare_ref_pass(out: list, mmap: dict, amap: dict, rtop: dict) -> int:
    """规则 A 放行通道 `rare_ref`：只把**仍待审**的格升为放行，不改任何已放行格。→ 升级格数。"""
    from ..variants import are_variants
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            al = amap.get(rec.id)
            top5 = rtop.get(rec.id)
            if m is None or al is None or not top5:
                continue
            lib_top = (m.char if m.verdict == "same" and m.char
                       else (m.candidates[0][0] if m.candidates else None))
            ch = rare_ref_decide(doubts=rec.doubts, guard=m.guard, verdict=m.verdict,
                                 lib_char=m.char if m.verdict == "same" else None, lib_top=lib_top,
                                 ref=al[0], op=al[1], rare_top=top5[0], are_variants=are_variants)
            if ch is None:
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "rare_ref", "rare_ref", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "rare_ref": {
                "rare": top5[0], "ref": al[0], "lib": lib_top, "cov": m.cov}}
            n += 1
    return n


_SHADOW_GATES: dict = {}


def _shadow_model_path(p: "SeedAdmitParams"):
    """缺省模型：只开 veto 用 v1（老口径，行为不变）；开了 promote 用 v2（要名次类特征）。"""
    from ..shadow.model import DEFAULT_MODEL, PROMOTE_MODEL
    return p.shadow_model or (PROMOTE_MODEL if p.shadow_promote else DEFAULT_MODEL)


def _shadow_gate(p: "SeedAdmitParams"):
    """进程内缓存：同一 (模型指纹, db, 门槛) 只建一次（字形库人裁表要扫 sqlite）。"""
    key = (p.shadow_model_fingerprint, str(_shadow_model_path(p)), p.db_path, p.variants, p.shadow_conf, p.shadow_low_conf)
    g = _SHADOW_GATES.get(key)
    if g is None:
        from ..shadow.gate import ShadowGate
        from ..shadow.model import load_model
        from ..shadow.signals import load_context
        g = ShadowGate(load_model(_shadow_model_path(p)), load_context(p.db_path, p.variants or None),
                       p.shadow_conf, p.shadow_low_conf)
        _SHADOW_GATES.clear()
        _SHADOW_GATES[key] = g
    return g


def _shadow_veto_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict, amap: dict) -> int:
    """影子放行闸（只降级）：把现行规则已放行、影子有把握说不对的格降回待审。→ 降级格数。

    放在所有通道与 `_resolve_ji_yi_si` 之后：只会把 admit 从 True 改 False，不改字、不升级。
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
            if (vmap is not None and v.pick and rec.char and v.pick != rec.char
                    and not _rare_cp(rec.char)    # 放行字是罕用码位不弃权（#431：𠮓→變、𣼣→漏）
                    and vmap.semantic(v.pick) == vmap.semantic(rec.char)):
                continue                      # 异体同字：标签口径差，不是认错字（#431）
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = _doubts(m, None) + list(rec.doubts) + ["shadow_veto"]
            rec.evidence = {**rec.evidence, "shadow_veto": v.evidence(gate.model, gate.conf, gate.low_conf)}
            n += 1
    return n


def _shadow_promote_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict, amap: dict) -> int:
    """影子升级（`shadow_promote`）：待审格里，影子首选 = 整理本字或库首位且把握度够 → 放行。→ 升级格数。

    只升不降，只碰 admit=False、非人裁、无硬护栏、没被 `shadow_veto` 降过的格；放在 veto 之后，
    所以本遍放行的格不会再被 veto 回头否掉。模型读不到／口径不符 → 抛错（同 veto）。"""
    from ..shadow.gate import promote_judge
    from ..shadow.signals import CellEvidence, jmerge
    gate = _shadow_gate(p)
    rare = _opt(ctx, "rare_candidates", page)
    rmap = {r.id: r for cc in (rare.columns if rare else []) for r in cc.chars}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human" or "shadow_veto" in rec.doubts:
                continue
            m = mmap.get(rec.id)
            if m is None or _hard_blocked(rec.doubts, m.guard):
                continue
            rr = rmap.get(rec.id)
            ref = (amap.get(rec.id) or (None, None))[0]
            ev = CellEvidence(
                id=rec.id, lib=[(c, v) for c, v in (m.candidates or [])],
                rare=[(x.char, x.score) for x in ((rr.candidates if rr else None) or [])],
                ref=ref, cur=rec.char)
            v = promote_judge(gate, ev, p.shadow_promote_conf)
            if not v.promote:
                continue
            lib_top = max(ev.lib, key=lambda t: t[1])[0] if ev.lib else None
            char = ref if (ref and jmerge(ref) == v.pick) else lib_top
            rec.admit, rec.channel, rec.provenance, rec.char = True, "shadow", "shadow", char
            rec.evidence = {**rec.evidence, "shadow_promote": {**v.evidence(gate.model, p.shadow_promote_conf),
                                                                "prev_doubts": list(rec.doubts)}}
            rec.doubts = []
            n += 1
    return n


#: `review.cards` 的类别码（`_CLS_CODES`）照抄一份——那是控制台模块，进 `code_deps` 会让卡片 UI
#: 的改动也判本步过期。`tests/test_seed_admit_lanes.py` 逐类核两边判得一样。
_LANE_CLS_CODES = {
    "ref_conflict": {"context_vs_ref", "iron_vs_ref", "signal_conflict"},
    "near_form": {"near_form", "solo_confusable"},
    "variant": {"variant_indirect", "replace_form", "channel_off", "ref_lib_variant"},
    "replace_align": {"replace_align"},
}
_LANE_R1_CLASSES = frozenset({"replace_align", "ref_conflict", "near_form"})
#: 三通道都不碰的疑问：字块本身不成立（空白、近似例）或形未定。
_LANE_HARD = frozenset({"context_blank_cell", "form_open", "approx_exemplar", "glyph_timeout"})
#: R1/R4 另外不碰的：context 乱码护栏拦下过格的**整列**（overview#427：列切窄、整列字块是
#: 笔画残边，证人字再齐也对不上图——vol04 p217c3 只有 2 格带这个码，同列其余 4 格看图同样是乱码）。
_LANE_GARBLE = frozenset({"ctx_garble_shape", "ctx_garble_rare", "ctx_garble_run"})


def _lane_class(doubts, evidence: dict | None, char, ref_char, lib_top) -> str:
    """待审格归哪一类——`review.cards.card_class` 的镜像（见 `_LANE_CLS_CODES`）。"""
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    codes = {d for d in ds if re.match(r"^[a-z][a-z0-9_]*$", d)}
    ev = evidence or {}
    if "occluded" in codes or ev.get("occluded"):
        return "occluded"
    if "ji_yi_si_review" in codes or ev.get("ji_yi_si") or any(c and c in _JYS for c in (char, ref_char, lib_top)):
        return "ji_yi_si"
    if "form_open" in codes:
        return "form_open"
    for k in ("ref_conflict", "near_form"):
        if codes & _LANE_CLS_CODES[k]:
            return k
    if any(d.startswith("库里没有") for d in ds):
        return "lib_miss"
    for k in ("variant", "replace_align"):
        if codes & _LANE_CLS_CODES[k]:
            return k
    return "other"


def _lane_witnesses(book, p: "SeedAdmitParams") -> list:
    """R1/R4 用的证人（质量降序，`steps.align_ref` 那份进程级缓存），按 `lane_witnesses` 筛。"""
    from .align_ref import _witnesses_for_book
    from pathlib import Path
    want = {s.strip() for s in (p.lane_witnesses or "").split(",") if s.strip()}
    return [w for w in _witnesses_for_book(book) if not want or Path(w.name).name in want]


#: 盖章空栏判空不碰的强通道（context 不在内：vol04 p220 那个经 context 误放行的「一」要能改掉）
_SEAL_STRONG = frozenset({"match_ref", "match_solo", "witness3", "match_margin", "iron"})


def _seal_blank_flip(out: list, seal: dict, coord: dict) -> int:
    """盖章空栏判空的格级保险（`seal_blank_page`，道 B 规格 overview#493）。→ 从放行挪走的格数。

    `seal` 是 `occlusion.page_seal_blank` 的候选格（印框内、重叠够）。候选格同时满足下列三条才挪：
    ①坐标对位无字（缺失或空串；`〓` 占位算有字）；②未被强通道放行（`_SEAL_STRONG`）；③非人裁、非排除、
    不是已被密度遮挡闸（`occluded`）管着的格。挪法：`admit=False`、`char=None`、doubts 记 `occluded`、
    evidence 记 `occluded.via=coord_blank、ref_blank=True`——与 `_review_lanes_pass` 的 coord_blank 分支接上。
    只改格、不改别的；不做任何判空，判非字由 lane 的 `lane_seal` 来做。"""
    if not seal:
        return 0
    demoted = 0
    for col in out:
        for rec in col.chars or []:
            hit = seal.get((col.col, rec.slot, rec.sub or ""))
            if hit is None or rec.channel == "human" or rec.provenance == "human":
                continue
            doubts = set(rec.doubts or [])
            if "excluded" in doubts or "occluded" in doubts:
                continue
            if rec.admit and rec.channel in _SEAL_STRONG:
                continue
            if coord.get(rec.id):                # 坐标对位有字（非空串）：不是空栏
                continue
            if rec.admit:
                demoted += 1
            rec.admit, rec.channel, rec.char, rec.provenance = False, None, None, ""
            rec.doubts = sorted(doubts | {"occluded"})
            rec.evidence = {**(rec.evidence or {}),
                            "occluded": {"via": "coord_blank", "ref_blank": True,
                                         "seal_blank": hit["seal_score"], "overlap": hit["overlap"]}}
    return demoted


def _review_lanes_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict,
                       vmap, witnesses_fn) -> int:
    """待审补放三通道（`lane_witness3`／`lane_coord`／`lane_seal`，overview#433）。→ 放行格数。

    只升不降：只碰 admit=False、非人裁、不在排除名单上的格；己/已/巳 一族一律跳过。
    `witnesses_fn()` → 证人列表（只在 R1/R4 真要看证人时才调，装载与锚定都是懒的）。"""
    from pathlib import Path

    from ..clustering.witness_cells import witness_readings
    from ..utils.jiazhu_order import sort_by_reading
    sem = vmap.semantic

    def same(*cs) -> bool:
        return all(cs) and len({sem(c) for c in cs}) == 1

    def variant_pair(a, b) -> bool:
        """已知异体对：语义同、字面不同（刻本原字 vs 整理本字）。"""
        return bool(a and b and a != b and sem(a) == sem(b))

    def lib_top_of(rid):
        m = mmap.get(rid)
        return (m.char or (m.candidates[0][0] if m.candidates else None)) if m else None

    def guard_of(rid):
        m = mmap.get(rid)
        return getattr(m, "guard", None) if m else None

    cache: dict = {}

    def readings() -> list[tuple[str, dict]]:
        """[(证人文件名, {字位 id: 证人字})]，质量降序；第一次用到才算。"""
        if "r" not in cache:
            ws = witnesses_fn() if witnesses_fn else []
            seq = []
            for col in sorted(out, key=lambda c: c.col):
                for rec in sort_by_reading(col.chars or []):
                    if "excluded" in (rec.doubts or []) and rec.char is None:
                        continue
                    ch = rec.char or (amap.get(rec.id) or (None,))[0] or lib_top_of(rec.id)
                    if ch and len(ch) == 1:
                        seq.append((rec.id, ch))
            cache["r"] = [(Path(w.name).name, witness_readings(seq, w.text, w.index, vmap.normalize_text)) for w in ws]
        return cache["r"]

    seal_vias = {s.strip() for s in (p.lane_seal_via or "").split(",") if s.strip()}
    marks = [s.strip() for s in (p.lane_seal_title_marks or "").split(",") if s.strip()]
    title_cols = set()
    if p.lane_seal and marks:
        for col in out:
            s = "".join(coord.get(r.id) or "" for r in sort_by_reading(col.chars or []))
            if any(mk in s for mk in marks):
                title_cols.add(col.col)

    garble_cols = {col.col for col in out for r in (col.chars or []) if set(r.doubts or []) & _LANE_GARBLE}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if (rec.admit or rec.channel == "human" or rec.provenance == "human"
                    or "excluded" in (rec.doubts or []) or set(rec.doubts or []) & _LANE_HARD):
                continue
            al = amap.get(rec.id)
            ref, op = (al[0], al[1]) if al else (None, None)
            co = coord.get(rec.id)
            if co == "〓":                       # 逐列本的 PUA 生僻字占位：知道有字、不知道是哪个
                co = None
            lib = lib_top_of(rec.id)
            ev = rec.evidence or {}
            occ = ev.get("occluded")
            hit = None                           # (通道, 字, 证据)
            if occ:
                if not p.lane_seal or (rec.char and rec.char in _JYS):
                    continue
                lib_agree = None
                if p.seal_lib_agree and rec.char and occ.get("via") in ("coord", "align"):
                    m = mmap.get(rec.id)
                    top = (m.candidates[0] if m and m.candidates else None)
                    if top and top[0] == rec.char and top[1] >= p.seal_lib_cov:
                        lib_agree = round(float(top[1]), 4)
                if col.col in title_cols and lib_agree is None:
                    continue
                if occ.get("via") == "coord_blank" and occ.get("ref_blank") and rec.char is None:
                    hit = ("seal", None, {"via": "coord_blank", "nonchar": True})
                elif rec.char and occ.get("via") in seal_vias and col.col not in title_cols:
                    hit = ("seal", rec.char, {"via": occ.get("via")})
                elif lib_agree is not None:
                    hit = ("seal", rec.char, {"via": occ.get("via"), "lib_agree": lib_agree})
            else:
                cls = _lane_class(rec.doubts, ev, rec.char, ref, lib)
                if cls == "ji_yi_si" or co in _JYS or col.col in garble_cols:
                    continue
                if p.lane_witness3 and cls in _LANE_R1_CLASSES and op == "replace" and ref:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if rs and not any(c in _JYS for c in wc.values() if c) and same(ref, co, *wc.values()):
                        if variant_pair(lib, ref):
                            rec.evidence = {**ev, "lane_skip": {"lane": "witness3", "why": "lib_variant", "lib": lib}}
                        else:
                            hit = ("witness3", ref, {"cls": cls, "ref": ref, "coord": co, "lib": lib,
                                                     "guard": guard_of(rec.id), "witnesses": wc})
                elif p.lane_coord and cls == "other" and co:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if any(c in _JYS for c in wc.values() if c):
                        continue
                    d = wc.get(rs[0][0]) if rs else None
                    if variant_pair(lib, co):
                        # 库首位与坐标对位字是异体对：哪个是刻本形说不准（vol03 彝/𢑴 人裁取证人形，
                        # vol04 𨽾/𨽻 看图是库形），同 R1 的护栏，送审。
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "lib_variant", "lib": lib}}
                    elif same(lib, co, d):
                        hit = ("coord_fallback", lib, {"via": "lib_coord_primary", "coord": co, "lib": lib,
                                                       "witnesses": wc})
                    elif (rs and same(co, *wc.values()) and not variant_pair(lib, co)
                          and guard_of(rec.id) is None):
                        # 这一支没有字形背书（库首位是别的字），库再带护栏（never_match／conflict：
                        # 库明说「不是这个字」）就不放——vol04 60:9:9 库 一 cov 0.999、证人 二。
                        hit = ("coord_fallback", co, {"via": "witnesses_coord", "coord": co, "lib": lib,
                                                      "witnesses": wc})
            if hit is None:
                continue
            name, char, lev = hit
            if p.lane_variant_guard and char:
                m = mmap.get(rec.id)
                forms = [rec.char] + [c for c, _ in ((m.candidates or [])[:max(p.lane_variant_topk, 0)] if m else [])]
                vf = next((f for f in forms if variant_pair(f, char)), None)
                if vf is not None:      # 图上可能是刻本异体：别把它改成通用字（#433）
                    rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "cand_variant", "form": vf, "char": char}}
                    continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, name, name, char
            rec.evidence = {**ev, "lane": {"lane": name, **lev, "prev_doubts": list(rec.doubts or [])},
                            "no_glyph_lib": True}
            rec.doubts = [f"lane_{name}"]
            n += 1
    return n


def _resolve_ji_yi_si(cols: list[ColumnAdmit], amap: dict, dmap: dict, mmap: dict,
                      review_gate: bool = False, ctx_rule: tuple[float, int] | None = None,
                      clf=None) -> tuple[int, int]:
    """己/已/巳 一族：字形只定「是这一族」，哪个字由文意定（用户 2026-09-26，`utils/ji_yi_si.py`）。

    按本页读序取前后字：
    - **干支 / 时辰**（几乎不会错）：直接定字并放行——哪怕原先落了人审；
    - 其余（「己」的搭配、整理本、默认「已」）：**原已放行的改成规则的字**——原先的字
      不过是库或整理本对字形的猜测，而本族字形本就不分（四庫整理本自己也把「而已」印成「而巳」）；
      原在人审、但字形证据确认是这一族（库 top1 属本族且 cov ≥ 0.95，或 OCR 首选属本族）→
      按规则的字放行；字形证据不足 → 仍人审，证据里写建议字。
    人裁位不动（人定的就是文意）。→ (新增放行数, 新增人审数)。

    **2026-09-27 D 铁证复核改了两处**（vol03/vol04 独立复现同一系统性判偏，见
    `scripts/audit_ji_yi_si_0927.py`）：

    1. **`resolve()` 传 `use_ref="all"`**（原来 `ji_only`，只在整理本给「己」时信它）。
       docstring 原写的「实测干支/时辰全对、搭配与默认约 96%」是在 bxgb + 四庫 vol01/02
       上量的；vol03/vol04 独立穷举发现 pred 系统性偏「已」（vol03 47 格里 55.3% 错、
       vol04 34 处），根因是「默认→已」这条兜底规则抢在整理本前面——vol03/vol04 的
       gold 分布是 已:巳 ≈ 19:28（vol03）/ 42:38（vol04），「其余→已」这个默认假设
       在这两本书上是错的多数派，不是少数例外。把默认前多问一次整理本
       （`use_ref="all"`：干支/时辰仍最先命中，不受影响），vol04 47 格一致率
       53.0%→86.7%、vol03 47 格 42.6%→80.9%。**这一步没有改变"哪条规则优先"
       的顺序，只是把整理本从"只信它说己"扩成"它说什么就参考什么"——跟用户
       09-06/09-11「整理本给了就放行」的规矩方向一致，不是相反。**
    2. **残留错例（vol04 11/83、vol03 9/47）是另一个独立的坑，这次没修**：清一色是
       「己的常见搭配」（`_JI_NEXT` 含"意"）与「干支后为地支」规则里 `未` 的例外分支
       在这两本书上误触发，把已经正确的整理本字覆盖成错的「己」——这两条规则是在
       bxgb/vol01/vol02 上标定的，vol03/vol04 明显不适配（vol03 全书 47 格 gold 里
       "己" 出现 0 次，vol04 只 3 次），但样本太小（各不到 10 例）不够重新拟阈值，
       **负结果**：试过把"意"从 `_JI_NEXT` 删掉，vol04 这 11 例全对，但没有 bxgb/
       vol01/02 数据验证会不会反过来伤到那三本书的搭配判例，没做——把这条判断
       完全交给下面的 `review_gate`。

    `review_gate`（`SeedAdmitParams.ji_yi_si_review`）：非「干支/时辰」的其余路径
    （搭配/整理本/默认）开了之后要求**上下文判定（Step6 `context_decision`）＝
    整理本对齐字＝库候选 top1** 三者一致才放行，不一致就送人审（`doubts` 记
    `ji_yi_si_review`）——刚好接住上面第 2 点没修的残留误判：那些误判本质就是
    "规则给的字"与"整理本"不一致（规则自己覆盖了整理本），三方一致闸会把它们
    挡下来，不需要先分清是哪条规则错的。缺省关（用户 09-06/09-11 定的规矩是
    "整理本给了就放行"，这一族默认仍全放行）。
    """
    from ..utils.jiazhu_order import sort_by_reading
    from ..utils.ji_yi_si import resolve
    seq = [r for c in sorted(cols, key=lambda c: c.col) for r in sort_by_reading(c.chars)
           if not (r.doubts and "excluded" in r.doubts)]
    d_auto = d_review = 0
    for i, r in enumerate(seq):
        if (r.channel == "human" or r.char not in _JYS or "occluded" in (r.doubts or [])
                or "glyph_timeout" in (r.doubts or [])):
            continue
        prev = seq[i - 1].char if i else None
        nxt = seq[i + 1].char if i + 1 < len(seq) else None
        nxt2 = seq[i + 2].char if i + 2 < len(seq) else None
        ref = (amap.get(r.id) or (None, None))[0]
        ch, why = resolve(prev, nxt, ref, use_ref="all", next2=nxt2)
        r.evidence = {**(r.evidence or {}), "ji_yi_si": {"char": ch, "why": why}}
        sure = why.startswith("干支") or why == "时辰"
        if sure:
            if not r.admit:
                d_auto += 1
                d_review -= 1
            r.char, r.admit, r.channel, r.provenance = ch, True, "ji_yi_si", "context"
            r.doubts = [d for d in (r.doubts or []) if d not in ("always_review", "ji_yi_si")]
            continue
        if clf is not None:
            da, dr = _ji_yi_si_clf_cell(r, seq, i, amap, clf)
            d_auto += da
            d_review += dr
            continue
        if ctx_rule is not None:
            # 上下文表规则（overview#428）：表定得下就放行，定不下就送审；不看整理本、不走默认「已」
            from ..utils.near_form_ctx import decide as _ctx_decide
            c2, why2 = _ctx_decide(_ctx_known(seq, i, -1), _ctx_known(seq, i, 1), ctx_rule[0], ctx_rule[1])
            r.evidence = {**(r.evidence or {}), "ji_yi_si": {"char": c2, "why": why2}}
            if c2:
                if not r.admit:
                    d_auto += 1
                    d_review -= 1
                r.char, r.admit, r.channel, r.provenance = c2, True, "ji_yi_si", "context"
                r.doubts = [d for d in (r.doubts or []) if d not in ("always_review", "ji_yi_si")]
            elif r.admit:
                r.char, r.admit, r.channel, r.provenance = None, False, None, ""
                r.doubts = list(dict.fromkeys((r.doubts or []) + ["ji_yi_si_ctx_review"]))
                d_auto -= 1
                d_review += 1
            continue
        m = mmap.get(r.id)
        top1 = (m.candidates[0][0] if m and m.candidates else (m.char if m else None))
        d = dmap.get(r.id)
        ctx_char = d.char if d and d.source == "context" else None
        agree = review_gate and ref and ctx_char == ref and top1 == ref
        blocked = review_gate and not agree
        if r.admit:
            if blocked:
                r.char, r.admit, r.channel, r.provenance = None, False, None, ""
                r.doubts = list(dict.fromkeys((r.doubts or []) + ["ji_yi_si_review"]))
                d_auto -= 1
                d_review += 1
            else:
                r.char = ch
        else:
            ev = r.evidence or {}
            ocr1 = (ev.get("ocr") or [[None]])[0][0] if ev.get("ocr") else None
            if ((ev.get("cov") or 0) >= 0.95 or ocr1 in _JYS) and not blocked:
                r.char, r.admit, r.channel, r.provenance = ch, True, "ji_yi_si", "context"
                d_auto += 1
                d_review -= 1
    return d_auto, d_review


def _clf_ctx(seq: list, amap: dict, i: int, step: int, width: int = 30) -> str:
    """第 i 格前（step=-1）/后（step=1）至多 width 字，读序；只用邻格**已放行**的字，否则用整理本对位字，再没有记「□」。
    与离线 G0 快照的取法一致（`research/char_groups/build.py`：未放行格用整理本字补）。"""
    out: list[str] = []
    j = i + step
    while 0 <= j < len(seq) and len(out) < width:
        # 只用已放行的字：待审格的 `char` 是库 top1 默认字（`_pick_char`），可能是乱码，不是读法
        out.append((seq[j].char if seq[j].admit else None) or (amap.get(seq[j].id) or (None, None))[0] or "□")
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


def _ji_yi_si_clf_cell(r, seq: list, i: int, amap: dict, p) -> tuple[int, int]:
    """`ji_yi_si_clf` 开着时一格的处理（规则放行／答案表只写建议／退役 split_ref 放行）→ (新增放行, 新增人审)。

    见 `SeedAdmitParams.ji_yi_si_clf` 与 `utils/ji_yi_si_clf.py`。人裁位调用方已跳过。"""
    from ..utils.ji_yi_si_clf import FAMILY, STRONG_CHANNELS, classify, suggest
    left, right = _clf_ctx(seq, amap, i, -1), _clf_ctx(seq, amap, i, 1)
    rule, rwhy = classify(left, right)
    ev: dict = {"rule": rule, "why": rwhy}
    sug = suggest(p.ji_yi_si_clf_table, r.id, left, right) if p.ji_yi_si_clf_table else None
    if sug:
        ev["suggest"] = sug
    by = "rule" if rule else None
    ch = rule
    if (not ch and p.ji_yi_si_clf_llm and sug and sug.get("char")
            and (sug.get("lr_margin") or 0) >= p.ji_yi_si_clf_margin):
        ch, by = sug["char"], "llm+lr"
    ev["via"] = by
    r.evidence = {**(r.evidence or {}), "ji_yi_si_clf": ev, "ji_yi_si": {"char": ch, "why": rwhy}}
    strong = bool(r.admit and r.channel in STRONG_CHANNELS and r.char in FAMILY)
    if ch:
        if strong and r.char == ch:
            return 0, 0
        if strong:        # 强通道放行的字与规则冲突：两边都不信，送审
            r.char, r.admit, r.channel, r.provenance = None, False, None, ""
            r.doubts = list(dict.fromkeys((r.doubts or []) + ["ji_yi_si_clf_conflict"]))
            return -1, 1
        da, dr = (0, 0) if r.admit else (1, -1)
        r.char, r.admit, r.channel, r.provenance = ch, True, "ji_yi_si", "context"
        r.doubts = [d for d in (r.doubts or []) if d not in ("always_review", "ji_yi_si")]
        return da, dr
    if r.admit and r.channel == "split_ref":      # 退役：整理本路放行
        r.char, r.admit, r.channel, r.provenance = None, False, None, ""
        r.doubts = list(dict.fromkeys((r.doubts or []) + ["ji_yi_si_clf_review"]))
        return -1, 1
    return 0, 0


def _ctx_known(seq: list, i: int, step: int, width: int = 2) -> str:
    """第 i 格前（step=-1）/ 后（step=1）连续已知的至多 width 个字；碰到未知字就停（不跨过空位拼接）。"""
    out: list[str] = []
    j = i + step
    while 0 <= j < len(seq) and len(out) < width and seq[j].char:
        out.append(seq[j].char)
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


@lru_cache(maxsize=4)
def _human_shapes(db_path: str) -> dict[str, str]:
    """字形库里人裁过的位 → 人裁的**字形**。`{裸 id: shape}`（去掉 v2: 前缀）。

    取 `provenance='human'` 的 admissions，字形从 glyphs 经 exemplars 取——
    `admissions.char` 存的是**释读**，己/已/巳 那三个字它与字形会分岔，
    拿它当字形会把「刻 巳 读 已」写成「刻 已」（09-06 那批 62 条脏数据就是这么来的）。

    ## ⚠️ 人裁会**过期**：切分改了，这一格就不是当初看的那一格

    「人裁一票定案」的前提是那一格没变。2026-09-08~11 那几批裁完之后 Step2/Step3 改过多轮
    （去框、候选池、U-Net 裁判），格重新分了、slot 号整体偏移，旧裁决就钉在了错误的格上：
    p75 列1 实测人裁 slot4=用 / 9=自 / 12=已，而重切后这三格的图是 互 / 左 / 言（逐格看图核对过，
    与整理本一致）。一旦钉住，`human` 压过库匹配与上下文，**整段跟着错**，且没有任何报错。

    vol02 全书查出 61 条这种「与列内上一位重字」的人裁位，撤掉其中与整理本不一致的 56 条后，
    全书一致率 97.43% → 97.61%、`sub.other` 335 → 288。撤法是把 `provenance` 改成
    `human_stale_<日期>`（不删账，本函数只认 `'human'`）。

    **这是个反复会犯的坑**：只要切分再改一次，现有人裁就可能再过期一批。检测签名见
    `scripts/check_stale_human.py`（人裁位与上一位重字 → 疑似错位），跑批后应该定期跑一次。

    ## ⚠️ 只认 `v2:` 前缀，v1 的记录一条都不能要

    库里 1,925 条人裁有 **1,021 条是 v1 的 id**（`book:page:col:idx`，idx 从 0、含
    margin 格），与 v2 的 `book:page:col:slot`（slot 从 1）**长得一模一样但指的不是
    同一格**——这正是 `glyphdb_admit` 当初给 v2 加前缀要隔离的东西
    （见该消费者 docstring「v2 的 id 必须加前缀，否则会污染 15332 条已有记录」）。
    第一版这里去掉前缀后不加区分地收，vol01 判据 A 当场从 100% 掉到 94.70%：
    `vol01:4:1:10` 判「編」而金标「三」，整列错开。
    """
    import sqlite3
    from pathlib import Path

    from ..feedback.mojibake import is_legal_shape
    if not Path(db_path).exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT a.instance_id, g.char FROM admissions a "
            "  JOIN exemplars e ON e.instance_id = a.instance_id "
            "  JOIN glyphs g ON g.glyph_id = e.glyph_id "
            " WHERE a.provenance = 'human' AND a.instance_id LIKE 'v2:%'").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    # 字形字段合法性校验（2026-09-27，H 道乱码普查）：`glyphdb_admit` 写入口自
    # `b162e64` 起已经挡乱码（单字校验），但这道闸是那次改动之后才加的——库里
    # 可能留着更早年代写进去的坏数据（这里同样只挡、不吞：跳过并记 warning，
    # 不让老坏数据悄悄消失）。见 `feedback/mojibake.py`。
    out: dict[str, str] = {}
    for iid, ch in rows:
        if not ch:
            continue
        if not is_legal_shape(ch):
            _log.warning("_human_shapes: %s 字形字段不合法，跳过：%r", iid, ch)
            continue
        out[iid[3:]] = ch
    return out


@lru_cache(maxsize=4)
def _iron_context(db_path: str, norm_stroke: int | None):
    """铁证闸的匹配上下文：只吃人裁实例的内存匹配器 + 人裁字集合 + 形近表 + 按字分组的
    人裁实例 id（供判别器成对复核取原始字块）。跨页/跨 run 缓存（同 `_human_shapes`），
    只在 db_path/norm_stroke 换了才重建——一本书一次，不是一页一次。"""
    from ..clustering.confusable import partners as _confusable_partners
    from ..clustering.glyph_db import GlyphDB
    from ..clustering.iron_evidence import human_matcher
    matcher, _n = human_matcher(db_path, norm_stroke)
    human_chars_set = set(matcher._chars)
    partners_map = _confusable_partners()
    db = GlyphDB(db_path)
    human_ids: dict[str, list[str]] = {}
    for ch, iid in db.conn.execute(
            """SELECT g.char, e.instance_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
        human_ids.setdefault(ch, []).append(iid.replace("v2:", ""))
    return matcher, human_chars_set, partners_map, human_ids


class PatchUnavailable(RuntimeError):
    """本页字块读不到也再生不出来——这一页停下，不降级（overview#407）。"""


def _page_patch(src, page: int, col: int, slot, sub):
    """读**本页**一格的字块，读不到就抛 `PatchUnavailable`。

    `src` 是 `RunContext`（管线里）就走 `ctx.image`：验页戳、缓存没有就现算；
    是册 id 字符串（离线审计脚本）就只查缓存。2026-10-05 前这四处（铁证尺度 / 铁证判定 /
    CNN 背书 / 组内检索）都是 `ImageCache().get()` 不验戳不再生、没图 `return None`——
    缓存缺了或读不出来，铁证与 CNN 两路就**悄悄关掉**，放行结果变了而状态显示正常。
    """
    import cv2

    key = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    try:
        if hasattr(src, "image"):
            return src.image("char_patch", key)
        from ..products.cache import ImageCache
        path = ImageCache().get(src, "char_patch", key)
        if path is None:
            raise FileNotFoundError(f"缓存里没有 {src}/char_patch/{key}")
        return cv_imread(str(path), cv2.IMREAD_GRAYSCALE, strict=True)
    except Exception as e:                  # noqa: BLE001 —— 换成带页号与键的错误再抛，不吞
        raise PatchUnavailable(f"p{page} 字块 {key} 读不到: {type(e).__name__}: {e}") from e


def _iron_page_scale(book, page: int, match: PageMatch, on_missing=None) -> float:
    """书级判别器归一尺度（`iron_evidence.book_scale_from_patches`）：从**这一页**的字块
    原图取中位边长——影子验收（research/shadow_admit/iron_shadow.py）验证过
    的口径是抽样几百个字块算一次全书通用值，这里改成逐页现算（一页的字数通常也有
    几百个，够稳），免得要在 `run_page` 的单页边界之外维护跨页状态。"""
    from ..clustering.iron_evidence import book_scale_from_patches
    patches = []
    for cc in match.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            try:
                patches.append(_page_patch(book, page, cc.col, r.slot, r.sub))
            except PatchUnavailable:
                if on_missing is None:          # 缺省（patch_missing=error）：停页
                    raise
                on_missing(r.id)                # skip：尺度用读得到的那些算，缺的记账
    return book_scale_from_patches(patches)


def _iron_decide(book, page: int, col: int, r, iron_ctx, scale: float,
                 norm_stroke: int | None) -> str | None:
    """这一格铁证放行的字，放不了返回 None。`r` 是 `glyph_match` 产物里的逐格记录
    （`.id/.slot/.sub/.candidates/.verdict/.char/.cov`），候选集重算方式与
    `iron_shadow.py` 的批处理壳完全一致——两边现在都读同一个 `iron_with_disc`。"""
    import cv2

    from ..clustering.iron_evidence import iron_with_disc
    from ..clustering.normalize import normalize_patch
    from ..products.cache import ImageCache
    cache = ImageCache()
    matcher, human_chars_set, partners_map, human_ids = iron_ctx
    img = _page_patch(book, page, col, r.slot, r.sub)
    res = matcher.match(normalize_patch(img, stroke_width=norm_stroke), exclude_id=f"v2:{r.id}")
    cands = [(c, float(v)) for c, v in res.candidates]
    if res.verdict == "same" and res.char and all(c != res.char for c, _ in cands):
        cands.insert(0, (res.char, float(res.cov)))
    cands.sort(key=lambda t: -t[1])

    raw_cache: dict[str, object] = {}

    def raw_of(cid: str):
        if cid not in raw_cache:
            parts = cid.split(":")
            if parts and parts[0] == "v2":      # 人裁重键后的格号坐标，去前缀即可
                parts = parts[1:]
            # `v1:` 是旧管线的 idx 坐标、没经形状确认，不拿来当铁证对照图；
            # 其它认不出的形状也一律跳过（服务器 #40：v1: 人裁 id 让 vol03 p3/p74 崩）。
            if len(parts) != 4 or parts[0] == "v1" or not parts[3].rstrip("ab").isdigit() \
                    or not (parts[1].isdigit() and parts[2].isdigit()):
                raw_cache[cid] = None
                return None
            bk_, p_, c_, s_ = parts
            sub = s_[-1] if s_[-1] in "ab" else ""
            s_ = s_.rstrip("ab")
            # 对照图是别页/别册的人裁刻例，缓存里没有属正常（跳过这一例）；
            # 文件在却解不出来是坏缓存，照样报错（strict），不当「没有」处理。
            pth = cache.get(bk_, "char_patch", f"p{int(p_):04d}c{int(c_):02d}s{s_}{sub}")
            raw_cache[cid] = (None if pth is None
                              else cv_imread(str(pth), cv2.IMREAD_GRAYSCALE, strict=True))
        return raw_cache[cid]

    def ex_raws(ch: str):
        ids = [i for i in human_ids.get(ch, []) if i != r.id]
        return [x for i in ids[:8] if (x := raw_of(i)) is not None]

    winner, _top, _second, _why, _disc = iron_with_disc(
        cands, human_chars_set, partners_map, img, ex_raws, scale)
    return winner


def _solo_ctx_vetoed(dec, cands, vmap, thresh: float) -> bool:
    """`solo_ctx_veto`：上下文第一名与库 top1 语义不同、且概率 ≥ thresh（无 ranked／候选 = 不拦）。"""
    ranked = getattr(dec, "ranked", None)
    if not ranked or not cands:
        return False
    top, prob = ranked[0]
    lib = max(cands, key=lambda t: t[1])[0]
    return prob >= thresh and vmap.semantic(top) != vmap.semantic(lib)


#: match_solo 系：只靠库形状（± OCR/CNN 背书）放行、没有整理本的通道（`solo_confusable_guard` 用）
_SOLO_CHANNELS = frozenset({"match_solo", "match_solo_ocr", "match_solo_cnn"})

_CORPUS_CHANNELS = (None, "match_ref", "match_replace", "match_ref_weak", "match_margin",
                    # 整理本参与的通道（match_ref 2026-09-05 补、note_lexicon 2026-09-06 补）：
                    # 库没下 same 断言时拿整理本字当字形估计，且要走「义定形未定」的组内定形；
                    # 漏进这个元组，variant_form 整段跳过（刻本形被整理本形盖掉，判据 E 82/91 那次）。
                    "note_lexicon")


def _pick_char(ok: bool, channel: str | None, align_char: str | None,
               match_char: str | None, verdict: str,
               candidates: list) -> str | None:
    """决定这一位的**字**（刻本字形；2026-09-26 起没有「读法」）。

    same 档用库继承的字；整理本参与的通道、库又没下 same 断言时取整理本字；
    否则取**库候选 top1**——那正是 match_solo / match_solo_ocr 采信的东西。

    ## ⚠️ 库判 same 时整理本字不能覆盖

    第一版让整理本字直接覆盖，7 条异体字位被写成了整理本的形：刻本刻「㫖」存成「旨」、
    「彚」存成「彙」、「卽」存成「即」。字形库存的是刻本上实际刻的形（charset_and_lm.md §四）。

    ## ⚠️ `channel is None` 也是一条通道

    `dual` 档（align × OCR 双信号一致且零疑问）在 `admission_decision` 里是
    `return True, None`——**没有通道名**。所以按「这条通道用没用整理本」判，而不是列通道名。
    """
    char = match_char if verdict == "same" else None
    if ok and align_char and channel in _CORPUS_CHANNELS:
        # ⚠️ 库 unsure 时，**别拿库 top1 当字形**。
        #
        # unsure 的字面意思就是「库不知道这是什么」：实测 8 条 dual 位
        # （vol01:42:3:20 等）库 top1 与 top2 只差 0.0017~0.0023，而 align 与
        # OCR 两路独立证据都指向另一个字，且那个字**根本不在库的候选里**
        # （敷/顯/毫/昌）。此时把库的猜测写进 `char`，等于往字形库塞 8 个错
        # 例——下一页再遇到同形字就会继承这个错（charset_and_lm.md §四）。
        #
        # 库判 same 才有资格定字形（那是它下了断言）；unsure 时两路零同源证据
        # 一致，整理本字是更好的字形估计。异体位（㫖/旨、彚/彙）不受影响：
        # 库对它们判 same，char 仍照录刻本的形。
        if char is None:
            char = align_char
    if char is None and candidates:
        char = candidates[0][0]
    return char


def _align(ctx: RunContext, page: int) -> dict[str, tuple[str, str]]:
    """`align_ref` 的产物 → {字位: (整理本字, equal|replace)}。

    Step5-d 已经把 8-gram 锚定 + difflib 挪成正式 Step（`steps/align_ref.py`）：
    这里只读它的产物，不再自己 import `gold.v2_align` 的私有函数现算一遍——
    那是任务书点名的"绕道读金标"，对齐这个动作因此在两处各算一遍、互相漂移。
    产物缺失或未锚定就返回空表，所有整理本通道自动失效，退回改动之前的行为，
    不会把错的/缺的对齐硬塞进准入。这是「拿不准就保持基线」在这一层的落法。
    """
    ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
    if ref is None or not ref.anchored:
        return {}
    return {c.id: (c.align_char, c.align_op) for c in ref.chars}


def _occluded(ctx: RunContext, page: int, match: PageMatch, p: "SeedAdmitParams",
              amap: dict) -> dict[str, tuple[float, str | None, str]]:
    """本页被印章／大片污损遮住的格 → {字位 id: (密度, 默认字, 默认字来源)}。

    来源：`coord`（坐标对位的整理本字）/ `coord_blank`（坐标对位说是空格位，默认字 None）/
    `align`（现役对位字）/ `none`。读不到 Step3 字格或原图就当没有遮挡（返回空表）。"""
    from .occlusion import page_occluded
    hit = page_occluded(ctx, page, p)
    if not hit:
        return {}
    ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
    coord = {c.id: c.ref_char for c in (ref.coord if ref else [])}
    out: dict[str, tuple[float, str | None, str]] = {}
    for cc in match.columns:
        for r in cc.chars:
            dens = hit.get((cc.col, r.slot, r.sub or ""))
            if dens is None:
                continue
            if r.id in coord and coord[r.id] == "〓":
                # 逐列本里没有码表的 PUA 生僻字占位：知道这儿有字、不知道是哪个
                out[r.id] = (dens, None, "coord_pua")
            elif r.id in coord:
                ch = coord[r.id]
                out[r.id] = (dens, ch or None, "coord" if ch else "coord_blank")
            elif r.id in amap:
                out[r.id] = (dens, amap[r.id][0], "align")
            else:
                out[r.id] = (dens, None, "none")
    return out


def _coord_refs(ctx: RunContext, page: int, cache: dict) -> dict[str, str]:
    """本页 `align_ref.coord` → {字位 id: 整理本字（空串 = 坐标对位说是空格位）}；页内缓存。"""
    if "coord" not in cache:
        ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
        cache["coord"] = {c.id: c.ref_char for c in (ref.coord if ref else [])}
    return cache["coord"]


def _context_guard(p: "SeedAdmitParams", r, ctx_char: str, im, coord: dict[str, str],
                   vmap) -> tuple[str, str | None] | None:
    """context 通道放行前的最后一道闸（overview#333，G1 道）。命中返回 `(doubt, 默认字|None)`，
    不命中 None。四条各有开关（`context_guard_*`），依次判，先中先返回；缺信号一律弃权：
    没有 `char_index` 就不看标记，没有坐标对位就不看整理本。

    - `ctx_guard_diff`：库判 diff 且 cov < `context_guard_cov`；
    - `ctx_guard_flag`：字块带 rule_bar／suspect_empty／bad_seg（界行杆、空薄片、坏切）；
    - `ctx_guard_ref_blank`：坐标对位说此位是空格、库又不是 same → 字块不是字；
    - `ctx_guard_ref`：坐标对位的整理本字与 context 字语义不同、库不是 same → 默认字取整理本。
    """
    if p.context_guard_diff and r.verdict == "diff" and r.cov < p.context_guard_cov:
        return "ctx_guard_diff", None
    if p.context_guard_flags and im is not None:
        bad = set(p.context_guard_flag_set.split(",")) & set(im.flags)
        if bad:
            return "ctx_guard_flag", None
    ref = coord.get(r.id)
    if ref is not None and r.verdict != "same" and ref != "〓":
        if ref == "":
            if p.context_guard_ref_blank:
                return "ctx_guard_ref_blank", None
        elif p.context_guard_ref_prefer and vmap.semantic(ref) != vmap.semantic(ctx_char):
            return "ctx_guard_ref", ref
    return None


def _rare_cp(ch: str | None) -> bool:
    """码位不在 CJK 基本区（U+4E00–9FFF）：扩展区、部首、兼容区都算罕用。"""
    return bool(ch) and not ("一" <= ch <= "鿿")


def _rare_run_ids(recs, k: int) -> frozenset[str]:
    """本列（`glyph_match` 一列的字位，按列内顺序）里，库 top 字是罕用码位、在 ±k 格窗口内
    凑满 k 个的那些格的 id——整列切坏时的乱码串（overview#427）。k ≤ 0 = 关。"""
    if k <= 0:
        return frozenset()
    rare = [_rare_cp(r.char or (r.candidates[0][0] if r.candidates else None)) for r in recs]
    return frozenset(r.id for i, r in enumerate(recs)
                     if sum(rare[max(0, i - k):i + k + 1]) >= k)


def _garble_guard(p: "SeedAdmitParams", r, ctx_char: str, witnesses, run_ids, vmap) -> str | None:
    """context 通道放行乱码的护栏（`context_garble_guard`，overview#427）。命中返回 doubt 名。

    `witnesses`：整理本对齐字、坐标对位字、OCR 候选（None/空串/〓 不算证人）。有一个与
    context 字语义相同就是有背书，不拦；其余按 shape → rare → run 依次判。"""
    sem = vmap.semantic(ctx_char)
    if any(w and w != "〓" and vmap.semantic(w) == sem for w in witnesses):
        return None
    if r.cov < p.context_garble_cov:
        return "ctx_garble_shape"
    if _rare_cp(ctx_char) and r.cov < p.context_garble_rare_cov:
        return "ctx_garble_rare"
    if r.id in run_ids:
        return "ctx_garble_run"
    return None


def _approx_fingerprint(db_path: str) -> str:
    """近似字侧表的内容戳；库不存在、没有这张表、表空 → ""（见 `SeedAdmitParams.approx_gate`）。"""
    import hashlib
    import sqlite3
    from pathlib import Path
    if not db_path or not Path(db_path).exists():
        return ""
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            rows = c.execute("SELECT instance_id, label FROM approx_labels ORDER BY instance_id").fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    return f"{len(rows)}:" + hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=4)
def _approx_index_cached(db_path: str, _fp: str) -> tuple[dict[str, tuple], frozenset[str]]:
    """({近似例 id: (ids, note)}, {刻例全是近似例的字})。"""
    import sqlite3
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        ids = {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT instance_id, ids, note FROM approx_labels")}
        # 刻例全是近似例的字（按字头算，跨 edition 合并；字体域不算——它们不会是近似例，
        # 算进去反而让「全是近似」永远不成立）
        only = frozenset(r[0] for r in c.execute(
            "SELECT g.char FROM exemplars e JOIN glyphs g USING(glyph_id) "
            " WHERE g.edition_tag NOT LIKE 'font:%' GROUP BY g.char "
            "HAVING sum(e.instance_id IN (SELECT instance_id FROM approx_labels)) = count(*)"))
    return ids, only


def _approx_index(db_path: str) -> tuple[dict[str, tuple], frozenset[str]]:
    return _approx_index_cached(db_path, _approx_fingerprint(db_path))


def _approx_hit(r, char: str | None, apx_ids: dict[str, tuple], apx_only: frozenset[str]) -> dict | None:
    """这一格的字是不是**靠近似例**得来的（见 `SeedAdmitParams.approx_gate`）。

    是 → `evidence["approx"]` 那一段：`{"source": "matched", "via", "exemplar", "ids", "note"}`
    （`char_only` 时没有具体哪一例，`exemplar`/`ids`/`note` 为 None）；不是 → None。
    """
    if not char:
        return None
    if r.verdict == "same" and r.char == char and r.matched_id in apx_ids:
        ids, note = apx_ids[r.matched_id]
        return {"source": "matched", "via": "matched_id", "exemplar": r.matched_id,
                "ids": ids, "note": note}
    lib_top = r.char or (r.candidates[0][0] if r.candidates else None)
    if lib_top == char and char in apx_only:
        return {"source": "matched", "via": "char_only", "exemplar": None, "ids": None, "note": None}
    return None


def _rare_agree(match_rec, cnn: list[str] | None) -> dict:
    """`SeedAdmitParams.rare_agree` 记的那一笔：库首位、5-b 首位、两者是否相同。
    库判 `same` 时首位取 `char`，否则取候选第一名；任一路没有 → `agree` 为 None。"""
    pix = (match_rec.char if match_rec.verdict == "same" and match_rec.char
           else (match_rec.candidates[0][0] if match_rec.candidates else None))
    c1 = cnn[0] if cnn else None
    return {"pix": pix, "cnn": c1,
            "agree": (pix == c1) if (pix is not None and c1 is not None) else None}


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：缺了就 None，不炸——OCR 要引擎、上下文要语料，都可能没有。"""
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


class _PairAwareMap:
    """VariantMap 的一次性包装：额外把几个形映到指定语义（本书人确认过的 T2 转换对）。
    只给 `admission_decision` 这一次调用用，不改全局语义表。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._extra.get(char) or self._base.semantic(char)

    def __getattr__(self, name):
        return getattr(self._base, name)


def _cnn_top(book, page: int, col: int, slot: int, sub: str | None) -> str | None:
    """CNN embedding 检索的 top1 字（模板 = 字体 + 康熙字头 + 字统网真刻本）。

    只给 `match_solo_cnn` 用：无整理本 + 库形状落在 0.95~0.99 灰区时的第二路背书。
    没 checkpoint / 没装 torch → None（通道自动不触发）；**没图 → 抛 `PatchUnavailable`**
    （2026-10-05 前是 None，图读不到这一路就悄悄关了，overview#407）。
    """
    try:
        from ..clustering.cnn_candidates import shared
        cc = shared()
        if not cc.available:
            return None
    except Exception:
        return None
    img = _page_patch(book, page, col, slot, sub)     # 通道开着才读图；读不到抛错
    try:
        from ..clustering.font_candidates import book_charset
        from ..clustering.normalize import normalize_patch
        top = cc.emb_topk(normalize_patch(img), tuple(book_charset()), k=1)
        return top[0][0] if top else None
    except Exception:
        return None


def _image_ranks(book, page: int, col: int, slot: int, sub: str | None,
                 forms: list[str]) -> dict | None:
    """组内 closed-set 检索要看图：取 Step4 的 `char_patch`。**没图 → 抛 `PatchUnavailable`**
    （2026-10-05 前是 None，overview#407）；检索本身出错仍是 None。"""
    img = _page_patch(book, page, col, slot, sub)
    try:
        from ..clustering.normalize import normalize_patch
        from ..clustering.variant_form import image_ranks_for
        return image_ranks_for(normalize_patch(img), forms)
    except Exception:
        return None


def _doubts(match_rec, dec_rec) -> list[str]:
    """人审时把「为什么拿不准」说出来——审查页要显示它。"""
    out: list[str] = []
    if match_rec.guard:
        out.append(f"护栏:{match_rec.guard}")
    if match_rec.verdict == "unsure":
        out.append(f"库 unsure(cov={match_rec.cov:.3f})")
    elif match_rec.verdict == "diff":
        out.append("库里没有这个字")
    elif match_rec.verdict == "same":
        # same 档还落回人审，只可能是 admission_decision 的某条防线拦下的
        # （异语义对手同到阈档、残差窗超限需 OCR 背书……）。不写原因的话
        # 审查页显示空白，人不知道在问什么。
        out.append(f"库 same 但准入被拦(cov={match_rec.cov:.3f}, wmax={match_rec.wmax:.1f})")
    if dec_rec is not None and dec_rec.source == "prior":
        out.append(f"上下文 margin 不足({dec_rec.margin:.2f})")
    return out


def _confusable_char(ch: str) -> bool:
    """`lib_confident` 用：这个字在不在任何一张形近表里（按字，不看对手是否在候选里）。"""
    from ..clustering.confusable import partners
    from ..clustering.iron_evidence import extra_confusable_partners
    from ..clustering.seeding import NEAR_FORM_CHARS
    return (ch in NEAR_FORM_CHARS or ch in partners()
            or ch in extra_confusable_partners())


def _iron_confusable_witness(iron_char: str, witnesses, vmap) -> str | None:
    """`iron_confusable_guard` 用：证人里与铁证首选语义不同、又同在一张形近表里的那个字，
    没有返回 None。`〓`（逐列本的 PUA 占位）与空串（空格位）不算证人。"""
    from ..clustering.confusable import partners
    from ..clustering.iron_evidence import extra_confusable_partners
    near = partners().get(iron_char, frozenset()) | extra_confusable_partners().get(iron_char, frozenset())
    for w in witnesses:
        if w and w != "〓" and w in near and vmap.semantic(w) != vmap.semantic(iron_char):
            return w
    return None


def _trusted_variant_edge(top: str, align_char: str, ledger, book) -> bool:
    """`ref_lib` 变体放行（库候选与整理本字字面不同、语义同）时，这条变体边可不可信。

    `vmap.semantic(top) == vmap.semantic(align_char)` 只说明两者在 `variants.auto.tsv`/
    `variants.tsv` 里被登记成了同一语义正字，**不等于这条边本身够硬**——`graph` 来源的
    条目多数是关系层某个词典单向登记（见 `SeedAdmitParams.ref_lib_variant_guard` 的
    docstring，`冶→治` 就是 twedu 单向边），拿它当「两字同义」的唯一依据会把形近而
    异义的字放过闸。可信边四选一：

    - **双向**：关系层（`open_guji_cv.variants`）两个方向都把对方登记成正字——
      `directed[top][align_char]` 与 `directed[align_char][top]` 都有条目，不是单向
      「异体→正字」的登记，是两个来源互认；
    - **人工审查确认表**：`config/dicts/variants.tsv`（手工表，文件头「种子条目：随人工
      审查确认逐步扩充」）登记过这一对，双向都查——**这条不能略**：该表 17 条里有 10 条
      在关系层查不到双向（为→爲、逰→遊、无→無、迴→回、囬→回、彚→彙、厯→歷、㫖→旨、
      𨽾→隸、櫽→檃），全部人工确认过，若只认双向会被本闸误拦，比不加闸还倒退；
    - **人裁**：本书用字账记过这一对的人工确认（`BookLedger.pair_confirmed`，刻本形/
      整理本形谁在前不确定，两个方向都查）；
    - **书级 codepoints**：本书 `codepoints:` 配置把两个码位统一成了同一个
      （`BookSpec.codepoint_equal`，书级实证，比字典更硬）。
    """
    from ..variants import regulars_of
    a_to_b = any(r == align_char for r, _tags in regulars_of(top))
    b_to_a = any(r == top for r, _tags in regulars_of(align_char))
    if a_to_b and b_to_a:
        return True
    if (top, align_char) in _hand_variant_pairs() or (align_char, top) in _hand_variant_pairs():
        return True
    if ledger.pair_confirmed(top, align_char) or ledger.pair_confirmed(align_char, top):
        return True
    if book.codepoint_equal(top, align_char):
        return True
    return False


def _direct_variant_edge(a: str, b: str) -> bool:
    """关系层（`variants.json`）里 a、b 之间有没有**直接**异体边，方向不论。

    只收 kSpoofingVariant（形近易混）/ hydzd-borrowed（通假）的边不算——那两个
    来源永不当异体用（`variants.NEVER_SOURCES`）。"""
    from ..variants import NEVER_SOURCES, _graph
    return bool(set(_graph().sources_of(a, b)) - NEVER_SOURCES)


def _variant_indirect(shape: str, align_char: str, ledger, book) -> bool:
    """库形 `shape` 与整理本字只经间接路径同义（字面不同、关系层无直接边、
    也没有人工表/人裁/书级 codepoints 认过这一对）——`variant_indirect_guard` 要拦的。

    调用方已保证两者 `semantic` 相同（通道本身就是靠这个放行的），这里不再比。"""
    if shape == align_char or _direct_variant_edge(shape, align_char):
        return False
    return not _trusted_variant_edge(shape, align_char, ledger, book)


@lru_cache(maxsize=1)
def _hand_variant_pairs() -> frozenset[tuple[str, str]]:
    """`config/dicts/variants.tsv`（人工表）的全部条目，`{(异体, 正字)}`。

    人工确认过的边不要求关系层双向——它本身就是比关系层更硬的证据（人工审查过，
    不是词典单向登记）。缺省表很小（17 条），一次读全，跨 run_page 调用缓存
    （同 `_human_shapes`/`_iron_context` 的做法，进程内不重读文件）。
    """
    from ..clustering.variants import DEFAULT_VARIANTS_PATH
    pairs: set[tuple[str, str]] = set()
    if DEFAULT_VARIANTS_PATH.exists():
        for line in DEFAULT_VARIANTS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                pairs.add((parts[0], parts[1]))
    return frozenset(pairs)
