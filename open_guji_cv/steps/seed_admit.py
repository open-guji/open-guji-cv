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

## 通道一览（2026-11-06 重写；旧版只写了 match_solo 两条，早已过时）

主循环里有 match_ref／match_replace／context／iron 等；主循环之后是后处理各遍（升＝补放，降＝挪回待审），
次序写在 `_run_page` 的「后处理遍的次序」注释里，**改次序＝改产物**。一格放不放，看三件事：
①库匹配（`glyph_match`）给的 verdict／候选／guard；②整理本对位（`align_ref`，现役 chars 与坐标 coord 两路）；
③疑问码 `doubts`（`near_form`、`护栏:*`、`iron_*`、`ctx_guard_*` 等，会拦一批通道，见 `_hard_blocked`）。

各通道的条件、缺省参数、哪本书开了哪个，对形近格（待审原因 N01）已整理成表：
guji-manager `doc/01-粗校/待审原因/near_form_guard/流程.md` 第二节；逐书生效值用 `guji book show --effective`。
常规与 match_ref／match_replace 的设计依据见 `clustering/seeding.admission_decision`（v1 十条通道的原始实现，v2 沿用其裁决）。

## 进库不在这一步做

这一步只产出**裁决**。真正写库要走 Event → 路由 → `glyphdb_admit` 消费者，
理由是设计 §3 纪律 1：逐实例证据、可重放。自动通道的裁决由
`review/batches` 转成 `confirm` 事件，人审的进审查页。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import re
from contextvars import ContextVar
from functools import lru_cache

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (AdmitRec, ColumnAdmit, PageAdmit,
                                    PageAlignRef, PageDecision, PageMatch,
                                    PageOcr)
from ..utils.image_io import imread as cv_imread
from ..utils.gap import GAP_CHARS, GAP_IMAGE, is_gap
from ..utils.ji_yi_si import FAMILY as _JYS
from .seed_admit_params import (  # noqa: F401  参数与参数表搬到 seed_admit_params（2026-11-23），这里 re-export
    REFERENCE_TRUST_SHAPE_GROUPS, REFERENCE_TRUST_ABSTAIN_GROUPS, REFERENCE_TRUST_LIFT_SHAPE_GROUPS,
    FOLLOW_REF_VARIANTS_REV, _RARE_REF_COORD_MIN_COV, _flow_groups, _default_flow_groups, _SAME_WRITING_KEEP,
    _RETIRED, _RETIRED_IN_DUMP, _SEAL_LIB_COV, _ALWAYS_ON, _ALWAYS_ON_IN_DUMP, _DUMP_DROP, SeedAdmitParams,
)

_log = logging.getLogger(__name__)






@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id="seed_admit", title="C1 进库准入", version="1.82", unit="cell",   # 1.82：规则 A（rare_ref／rare_ref_sparse）不在折叠组待文意格（evidence.fold_pending）里拿整理本字定组内字（殿本 vol41:55:4:19「六日僧道」被放成日，r7 殿本影响 2 格，A24 11-08）；（#1277 的 1.82 撤回为 1.81：group_flow_llm_half_groups 缺省空时逐字节不变，改用 code_equiv 登记，免得各书 seed_admit 全量过期；A31 11-08）（solo_5b 刻例门槛改读可信刻例数 trusted_keben_counts、放行格带 evidence.no_glyph_lib、solo_5b_borrow_db 同族借库：同样不升版本号，缺省关、逐字节不变、code_equiv 登记，A24 11-08）1.82：group_flow_llm_half_groups 这几组的夹注半格不受 llm_skip_half 限制、照样记 L3 问（书级，缺省空、不进参数 dump；SJ 史記 H01 半格写不了裁定键，A24 11-08）；（solo_5b 不升版本号：缺省关、逐字节不变、code_equiv 登记，免得各书 seed_admit 全量过期）solo_5b_cov 无参照格「库首位＋5-b 作证」放行通道 match_solo_5b（书级，缺省关、关时不进参数 dump；全唐文 001–003 总目／韵编，形近字线 11-08，A24 定口径）；1.81：fold_aspect_ctx_veto 的组内文意一支不认 L1 规则、带概率的要到阈值（SJ 史記 06:46「李奇曰」被 ry-ext-r1 误否决，A24 11-08）；1.80：fold_aspect_ink 折叠宽高改量墨迹主体（字组 ry_shape ratio），书级缺省关、不进参数 dump（SJ 史記看图框比字宽，A24 11-08）；1.79：alt_select="admit" 开 p_ref 时选列另跑两遍不带 p_ref 的准入来比（撤 1.77 的「p_ref 格按待审算」：那些格不开 p_ref 时多由后面的通道放，按待审算多换了列；史記 r19 06:26 回放，SJ 11-08）；1.78：fold_aspect_ctx_veto 也认字组文意解法给的另一个字（开着时；SJ 史記 01:45「日講官」宽高比 1.15 判曰没挡住，A24 11-08）；1.77：alt_select="admit" 换列比较时 p_ref 放的格按待审算（开 p_ref 后主切法错位列不再换备选、坏格被整理本字盖住；史記 r19 06:26:1、03:88:4，SJ 11-08）；1.76：p_ref_min_cov（缺省 0.8 开，缺省值不进参数 dump；p_ref 不取库里认不出［diff 档、cov<0.8］的格，挡住切分坏格被整理本字盖住；史記 r19 离线重跑 7 格，SJ 11-08，A24）；1.75：follow_ref_seen_conflict follow_ref_seen 也接「护栏 conflict」格（候选前两名恰是 ref 与 seen 对里另一形；书级，缺省关、关时不进参数 dump；A24 N01 第 7 轮复查 11-08，殿本 七／𠤎 字形相同 28 格按整理本）；1.74：lane_group_img_veto 补放三通道不放字组图像判官（rr_img）反对的字（书级，缺省关、关时不进参数 dump；A23 Z02 r7 人入 2 格，11-08）；1.73：group_flow_ref_pair／ref_pair_coord 不把共字组搭档的码位解法（`组:codepoint`，只回报码位归一目标、无图像证据）当反对票（只对开了这两项的书生效；A24 Z02 r7，殿本 sy 山由出 4 格看图全是山）；1.72：fold_occluded_lib_max_cov 遮挡格库首位无把握（cov<阈值）时仍按整理本字归组（书级，缺省关、关时不进参数 dump；殿本 r7 D01 己已巳 19 格，A24 11-08）；1.71：p_ref_irregular_gap（书级，缺省关、关时不进参数 dump；整理本字是异体写法［槪寳囘竒厯］且字族 cov 贴近机器字时取整理本字、不受 p_ref_max_cov 约束；殿本 r7 P01 异体被库认成形近字 83 格＋同类，A24 11-08）；1.70：暂归一兜底放宽 group_flow_pv_ref_gap（缺省 0.01 开、缺省值不进参数 dump；整理本与库首位都是某组暂归一写法、首位 cov≥0.95、领先组外最好候选≥0.01 时，分差内有组外形近字也进组兜底；A24 V01 第 7 轮 11-08，殿本 𨽻→𨽾 被 諫據綠裁 紧咬拦下 20 格）；1.69：group_flow_dissent_keep_form（dissent_keep 认 ids 弃权票刻形＝放行字，缺省开；A24 Z03 11-08，r7 殿本一二 19 格）；1.68：fold_ctx_vias／fold_ctx_strong 折叠组认字组文意路已给的字（书级，缺省空、不进参数 dump；A24 H01 第 7 轮复盘 11-08，殿本 L3 strong 68 格盲读全同）；1.67：pua_code_admit 族里是别的码表字的字不算互证（F1001 族 乖垂埀 是形近异字合码，乖是 EA36 的表字；第 7 轮 3 格垂放成乖；A24 11-08）；1.66：私用码表的殆知阁码本身也登记（pua_v2_codes），格→码事件可写殆知阁码（新图源文本层对不上、按整理本窗口回查的格；A24 R01 第 7 轮 38 格）；1.65：pair_shape 整理本／坐标对位是两字以外的第三个字时不补放（全唐文 r16 三→王，库首位王、整理本三，QTW 11-07）；1.64：alt_require_matched 备选格网比主切法多出没有坐标字的格就不换列（书级，缺省关、关时不进参数 dump；史記 r18 02:106:7，A24）；1.63：group_flow_lift_shape_ratio(_jiazhu) 给 lift_shape_ref 加宽高门、reference_trust_skip 让 reference_trust 自动并入的各项可单独关（书级，缺省空、不进参数 dump；SJ 史記 r18 日曰 71 格，A24 11-07）；1.62：lane_coord_blind_guard 坐标对位兜底「靠证人同意参校字」一支，参校字在库里刻例≥N却不在库候选、库首位 cov≥0.98 → 留审（书级，缺省关、关时不进参数 dump；Z04 殿本错放 餘／三，A23 建议，A24）；1.61：group_flow_same_writing_keep／group_flow_review_fix_agree（A24 Z03 11-07，见 1.59）；1.60：group_flow_ctx_agree 书级（缺省关）dissent_keep／ref_pair 的组还要本组文意同意放行字；1.59：坐标对位的缅甸字母占位（整理本以图代字，史記）当〓看，机器字不再取占位符（A24 R01 深挖 11-07，sheldon 同意）；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.57：group_flow_dissent_l1 书级（缺省关）复核时 L1 规则孤证＋整理本×ids 同意放行字不降审（A24 Z02 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸
        consumes=("glyph_match", "context_decision", "align_ref", "char_index"),
        optional_consumes=("rare_candidates", "seals"),
        optional_consumes_when=(("rare_candidates", "rare_ref"), ("rare_candidates", "symbol_review"), ("rare_candidates", "rare_ref_sparse"),
                                ("rare_candidates", "solo_5b_cov"), ("rare_candidates", "solo_adapt_pct"),
                                ("rare_candidates", "num_run_cov_5b"), ("rare_candidates", "solo_cal_5b_cov"),
                                ("rare_candidates", "lead_5b"), ("rare_candidates", "ref_lib_5b_veto")),
        produces=("seed_admit",),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.steps.seed_admit_params",   # 参数类与参数表（2026-11-23 从本模块搬出，SPLITS 合回）
                   "open_guji_cv.clustering.seeding",
                   "open_guji_cv.clustering.variants",
                   "open_guji_cv.clustering.variant_form",
                   "open_guji_cv.variant_ledger",
                   "open_guji_cv.clustering.note_lexicon",
                   "open_guji_cv.utils.jiazhu_order",
                   "open_guji_cv.steps.align_ref_coord",      # COORD_PAST_LEAF（occluded_past_leaf_blank）
                   # 字组统一流程（group_flow，缺省关）及其解法：文意 L1 规则（jys 的 legacy 规则在 utils.ji_yi_si_clf）、
                   # L2 答案表、量横、入人八字形分类器、字频
                   "open_guji_cv.groups.flow", "open_guji_cv.groups.freq", "open_guji_cv.groups.registry", "open_guji_cv.groups.edge_pairs",
                   "open_guji_cv.groups.methods",
                   "open_guji_cv.groups.ctx_l1", "open_guji_cv.groups.ctx_l2", "open_guji_cv.groups.rr_shape",
                   # 候𠋫 书级刻形判法（group_flow_hou_shape，#1729）：补进指纹；经 code_equiv.SPLITS 合回 rr_shape 一项，现有产物不过期（A31 11-20）
                   "open_guji_cv.groups.hou_shape", "open_guji_cv.groups.pair_shape", "open_guji_cv.groups.book_knn", "open_guji_cv.groups.near_knn", "open_guji_cv.groups.pair_attr", "open_guji_cv.groups.ctx_l3", "open_guji_cv.groups.ctx_llm", "open_guji_cv.groups.vis_llm",
                   "open_guji_cv.groups.prompt_template", "open_guji_cv.feedback.rulings",
                   # 人裁取字与撤下标记、绑定重挂（human_chars／stale_human_rules／rebind_library_shapes）：
                   # 这两处改了，有作废记录或重绑的格输出就变，要让第 7 步判过期（#1673、#1676 之后补，A31 11-18）。
                   # 裁决数据本身照旧不进指纹，靠显式重跑。
                   "open_guji_cv.feedback.lookup", "open_guji_cv.feedback.bindings",
                   "open_guji_cv.groups.context", "open_guji_cv.groups.textlayer_ref",
                   "open_guji_cv.groups.bars", "open_guji_cv.groups.aspect", "open_guji_cv.utils.ji_yi_si_clf", "open_guji_cv.utils.rr_clf",
                   "open_guji_cv.utils.gap",                   # 整理本缺字占位 〓／▣（is_gap，2026-11-16）
                   # 其 `ids` 解法（方案 S7）：在线判别＋它用到的 IDS 路模块
                   "open_guji_cv.groups.ids_online", "open_guji_cv.groups.ids", "open_guji_cv.groups.ids_two",
                   "open_guji_cv.groups.ids_parts", "open_guji_cv.groups.ids_segment", "open_guji_cv.groups.ids_solver",
                   "open_guji_cv.groups.ids_whole", "open_guji_cv.groups.ids_generic", "open_guji_cv.groups.ids_plan",
                   "open_guji_cv.groups.ids_unet",
                   "open_guji_cv.clustering.iron_evidence",
                   # 字形证据（variant_form.image_ranks_for）查字体模板走它；2026-10-20 修了它按 id
                   # 缓存行模长、拿错矩阵模长的 bug，结果可能变，此前漏登记，补上
                   "open_guji_cv.clustering.font_candidates",
                   "open_guji_cv.variants",
                   # 印章遮挡检测（overview#195）；它读的 Step3 `cells` 已经经 `char_index`
                   # 间接进了指纹，原图不变，所以不必加进 consumes。2026-10-22 起读印章定位 `seals`。
                   "open_guji_cv.steps.occlusion", "open_guji_cv.steps.seal_detect",
                   # 待审补放三通道（overview#433）的证人逐格读法
                   "open_guji_cv.clustering.witness_cells", "open_guji_cv.report.witness",
                   # 2026-11-06 补登记（1.37 pua_code_table 起 import，当时漏列）：私用码表读法。指纹靠 code_equiv.SPLITS 不变
                   "open_guji_cv.utils.pua_v2_codes",
                   # 2026-11-13 书级钩子（follow_ref 领先差不当对手的字，缺省 None；史記书仓覆盖）。指纹靠 code_equiv.SPLITS 不变
                   "open_guji_cv.impl.keben.follow_ref_hooks"),
        # 册配置 `iron_gate:` 开不开进指纹——同 glyph_match 的 norm_stroke 那条口子，
        # 不然开关翻了、产物没过期（书级布尔量，不是 Params 字段，走这条路）。
        # `codepoints:` 同理（2026-09-27 加，`ref_lib_variant_guard` 的可信边判据读它）。
        book_deps=("iron_gate", "codepoints"),
        # 路径不进指纹（2026-09-29 K238）：db_path 留空填本机绝对路径；其余三个是「显式
        # 给才有值」的文件路径。内容各有指纹把关：human_fingerprint / variants_fingerprint /
        # note_fingerprint / exclusions_fingerprint（都只认文件名 + 内容哈希）。
        path_params=("db_path", "variants", "note_lexicon", "exclusions", "shadow_model",
                     "group_flow_freq", "group_flow_tables", "group_flow_models", "group_flow_rr_shape", "group_flow_wu_shape", "group_flow_hou_shape", "group_flow_part_shape", "group_flow_pair_shape", "group_flow_pair_shapes", "group_flow_book_knn", "group_flow_near_knn",
                     "solo_adapt_profile", "stroke_veto", "pair_form", "lane_shape_first"),
    )

    def parallel_warm(self, ctx: RunContext) -> None:
        """页级并行 fork 前在主进程预建两份大缓存（`core/parallel.warm`）：三份证人的 8-gram 索引
        （复核通道才用，懒加载，第一页常碰不到）与铁证人裁匹配器。键与 run_page 里一致。只管提速。"""
        p: SeedAdmitParams = ctx.params_for(self)  # type: ignore[assignment]
        if p.lane_witness3 or p.lane_coord or p.lane_seal:
            _lane_witnesses(ctx.book, p)
        if ctx.book.iron_gate:
            _iron_context(p.db_path, getattr(ctx.book, "norm_stroke", None))

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        # row_segment `alt_cut`：align_ref 挑中备选切法的列，这一页读 Step3/4/5a 一律读备选那份、
        # 字块换备选键，5b/6 丢掉这些列（见 `products.alt_view`）。没换列就原样，产物逐字节不变。
        from ..products.alt_view import AltView, alt_override
        try:
            cand = list(getattr(ctx.product("align_ref", page), "alt_cand", None) or ())
        except Exception:                      # noqa: BLE001 —— 没有 align_ref 就没有候选
            cand = []
        if not cand:
            av = AltView(ctx)
            token = _ALT_SCOPE.set((ctx.book.id, av))
            try:
                return self._run_page(av if av.alt_cols(page) else ctx, page)
            finally:
                _ALT_SCOPE.reset(token)
        # align_ref `alt_select="admit"`：准入两遍——主切法一遍、候选列全换成备选一遍，逐列比后定列
        # （A22 11-04 评审：只跑两遍，不一列一遍；别的列一律主切法，定列后不重算）。
        p_ref = ctx.params_for(self).p_ref_admit

        def _two_runs(no_p_ref: bool):
            runs = []
            for cols in (frozenset(), frozenset(cand)):
                av = AltView(ctx)
                token = _ALT_SCOPE.set((ctx.book.id, av))
                tok_p = _NO_P_REF.set(no_p_ref)
                try:
                    with alt_override(ctx.book.id, page, cols):
                        runs.append(self._run_page(av if cols else ctx, page)["seed_admit"])
                finally:
                    _NO_P_REF.reset(tok_p)
                    _ALT_SCOPE.reset(token)
            return runs
        main, alt = _two_runs(False)
        # 开 p_ref 时选列用不跑 p_ref 的两遍（见 `_NO_P_REF`），结果仍取跑了 p_ref 的两遍
        sel_main, sel_alt = _two_runs(True) if p_ref else (main, alt)
        with alt_override(ctx.book.id, page, frozenset(cand)):
            ref_alt = AltView(ctx).product("align_ref", page)
            chars_alt = AltView(ctx).product("char_index", page)
        chosen = _pick_alt_cols(cand, sel_main, sel_alt, ctx.product("align_ref", page), ref_alt,
                                _opt_product(ctx, "char_index", page), chars_alt,
                                require_matched=ctx.params_for(self).alt_require_matched,
                                backed_gain=ctx.params_for(self).alt_backed_gain,
                                note_region=ctx.params_for(self).alt_note_region)
        if chosen:
            ctx.log(f"seed_admit p{page}: alt_cut 候选 {cand} → 换 {chosen}")
        return {"seed_admit": _merge_admit(main, alt, chosen)}

    def _run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
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
        p = no_ref_page_params(p, page)
        vmap = VariantMap.load(p.variants or None)
        if p.semantic_extra:
            vmap = _ExtraSemanticMap(vmap, _parse_semantic_extra(p.semantic_extra))
        if ctx.book.codepoints:
            vmap = _CodepointMap(vmap, ctx.book)
        ledger = BookLedger.load_or_empty(p.edition)
        # 排除名单：人裁标过「切坏 / 带残留 / 非字」的图块**不进库也不出审查卡**
        # （用户 2026-08-25 定的口径，exclusions.py 模块头）。v1 的 seeding 一直
        # 查它，v2 此前漏了——于是标了缺陷的格子下一轮照样出现在待审队列里。
        from ..clustering.exclusions import default_path as _ex_default
        _ex_path = p.exclusions or str(_ex_default())
        _origins = tuple(s.strip() for s in (p.exclusion_origins or "").split(",") if s.strip())
        excluded = excluded_ids(_ex_path, _origins or None)
        # 人裁过的位：**人裁是最强证据，任何自动通道都不许改写它**（2026-09-06）。
        # 实测 vol02:18:9:5——图上刻的是 曾（八字头），用户人裁 曾 且已进库
        # （provenance=human），但整理本这一处印 會，`context` 通道就按整理本放行成了
        # 會，判据 A 的「对你的裁决」因此掉到 210/211。库匹配、上下文、整理本对齐
        # 全都是间接证据，人看着图下的判断不是——它该一票定案。
        human_shapes = _human_shapes(p.db_path) if p.use_human_verdicts else {}
        _lost_lib: dict = {}
        if human_shapes:
            # 按入库时的编号记的人裁，先过绑定表找回现在对应的格（总览/15；重切后挂错格的根治）
            from ..feedback.bindings import rebind_library_shapes
            human_shapes = rebind_library_shapes(
                ctx.book.id, human_shapes, lost=_lost_lib,
                relabeled_at=_human_relabeled_at(p.db_path))
        # 事件侧的人裁定字（2026-09-20）：勾了「字形不入库」的裁决不进字形库，上面那份就
        # 没有它——但字是定了的，文本采信不能丢。见 `feedback/lookup.human_chars`。
        from ..feedback.lookup import human_chars
        _lost_ev: dict = {}
        human_texts = (human_chars(ctx.book.id, lost=_lost_ev)
                       if p.use_human_verdicts else {})
        # 人裁绑丢闸（见 `SeedAdmitParams.human_unbound_review`）：绑定后不采信的人裁，按原编号
        human_lost: dict = {}
        if p.use_human_verdicts:
            human_lost = {**_lost_lib, **_lost_ev}
            for k in [k for k in human_lost if k in human_shapes or k in human_texts]:
                del human_lost[k]

        evict_rv: dict = {}
        if p.use_human_verdicts:
            from ..feedback.lookup import evict_review_cells
            evict_rv = evict_review_cells(ctx.book.id)
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
        ocr: PageOcr | None = None          # Step5-c 已删（2026-10-18，sheldon 定）：OCR 这一路恒缺席
        dec: PageDecision | None = _opt(ctx, "context_decision", page)
        chars = _opt(ctx, "char_index", page)

        omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
        dmap = {r.id: r for cc in (dec.columns if dec else []) for r in cc.chars}
        imap = {r.id: r for cc in (chars.columns if chars else []) for r in cc.chars}
        mmap = {r.id: r for cc in match.columns if cc.ok for r in cc.chars}
        rtop: dict[str, list[str]] = {}
        if p.rare_ref:
            from .align_ref import rare_topk_map
            rtop = rare_topk_map(_opt(ctx, "rare_candidates", page), 1)
        amap = _align(ctx, page)
        mmap_raw = mmap                   # 共识退档前的 glyph_match 记录（solo_5b_same_cov 认库原判 same）
        if p.consensus_fallback:
            match = _consensus_fallback(match, amap)
            n_fb = sum(1 for cc in match.columns if cc.ok for r in cc.chars if r.id in mmap and mmap[r.id] is not r)
            mmap = {r.id: r for cc in match.columns if cc.ok for r in cc.chars}
            if n_fb:
                ctx.log(f"seed_admit p{page}: 共识升档 same 退回 unsure {n_fb} 格（consensus_fallback）")
        _aref: PageAlignRef | None = _opt(ctx, "align_ref", page)
        coord_conflict = frozenset(_aref.coord_conflict_ids) if _aref else frozenset()
        coord_cache: dict = {}
        always = set(p.always_review or "")
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
        iron_ex_missing: dict[str, int] = {}     # {格 id: 铁证判别时缺的刻例原图数}（iron_ex_missing_guard）

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
        # 本页读序最后一格（`context_page_end_review`）：末列（col 最大）按读序的最后一个字位
        _ok_cols = [c for c in match.columns if c.ok and c.chars]
        page_last_id = (sort_by_reading(max(_ok_cols, key=lambda c: c.col).chars)[-1].id
                        if (_ok_cols and p.context_page_end_review) else None)
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
                # 注意口径：`near_form` ＝ 候选前三＋本格字里**任一**个属**手工形近表**（NEVER_MATCH_FAMILIES，20 对）。
                # 它不要求那个字是真字、也不要求与整理本字成对，所以「家族字碰巧排进候选」也会记；
                # 与匹配层 `guard=never_match`（三表并集）、待审原因 N01（参校字与候选成表内对）是三个不同口径，
                # 见 guji-manager doc/01-粗校/待审原因/near_form_guard/流程.md 第一节。
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
                ok, channel = admission_decision(
                    ocr=ocr_in, align_char=align_char, ref_char=None,
                    doubts=doubts, vmap=vm_here,
                    match_char=r.char if r.verdict == "same" else None,
                    match_candidates=list(r.candidates),
                    match_guard=r.guard, match_wmax=r.wmax,
                    solo_cov=p.solo_cov)
                # 书级收紧（overview#155）：关通道 / match_solo 形近闸。放在所有兜底通道之前，
                # 作废的格后面仍可能被别的独立证据接住。
                if (ok and p.solo_ctx_veto and channel in _SOLO_CHANNELS
                      and _solo_ctx_vetoed(dmap.get(r.id), r.candidates, vm_here, p.solo_ctx_veto)):
                    ok, channel = False, None
                    doubts.append("solo_ctx_veto")
                elif (ok and p.solo_coord_dissent and channel in _SOLO_CHANNELS
                      and _solo_coord_dissented(r, vm_here, _coord_refs(ctx, page, coord_cache))):
                    ok, channel = False, None
                    doubts.append("solo_coord_dissent")
                # 异体等价只经间接路径成立的撤回（`variant_indirect_guard`）。库形取
                # 这几条通道自己比的那个字：match_ref 库 same 时是 r.char，其余是 cov 最高的候选。
                if (ok and align_char and r.candidates
                        and channel in ("match_ref", "match_replace", "match_margin")):
                    _shape = (r.char if channel == "match_ref" and r.verdict == "same" and r.char
                              else max(r.candidates, key=lambda t: t[1])[0])
                    if _variant_indirect(_shape, align_char, ledger, ctx.book):
                        ok, channel = False, None
                        doubts.append("variant_indirect")
                # 库 × 整理本不放两路对位打架的格（A23 2026-10-23，常开、无开关）：`align_ref.coord_conflict_ids`
                # 里坐标字≠现役 equal 字的格，现役字恰是存疑那一路，「库 top == 现役字」不再是两路独立证据
                # （vol14 cv0.5.9：60:1:5 拱→撰，库 撰 0.9393／撤 0.9391；103:2:7 双行小注两字被切一格，库 diff 仍放「中」）。
                # 只拦 match_ref；落人审，doubt `coord_conflict`。vol14 两版产物回放每版拦 8 格，看图确认拦中 2 个真错、误伤 1。
                if ok and channel == "match_ref" and r.id in coord_conflict:
                    ok, channel = False, None
                    doubts.append("coord_conflict")
                if ok and channel == "match_ref" and p.match_ref_diff_guard and r.verdict == "diff":
                    ok, channel = False, None
                    doubts.append("match_ref_diff")
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
                    if align_char in always:
                        # 己已巳：字形只定「是这一族」，哪个字按上下文（用户 2026-09-06 / 09-26）。
                        # 这里先放行、字取整理本；页末 `group_flow`（jys 组）按文意复核，没文意证据或文意给了别的字就降审。
                        ok, channel = True, "split_ref"
                    elif ok:
                        ok, channel = False, None

                char = _pick_char(
                    ok=ok, channel=channel, align_char=align_char,
                    match_char=r.char, verdict=r.verdict,
                    candidates=list(r.candidates))
                if channel == "split_ref":
                    # 己/已/巳：刻本三字刻法常不分，库 top1 定不了是哪个字，先取整理本字；
                    # 页末 `group_flow`（jys 组）再按文意复核。
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
                        if fd.state == "open" and _top in forms:
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
                            if not (p.replace_form_edge_exclude and _edge_pair_excluded(_top, align_char)):
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
                    if context_conflicts_ref(d.char, align_char, vm_here):
                        doubts.append("context_vs_ref")
                    elif _ir is not None \
                            and _ir.ink_ratio < p.context_min_ink:
                        doubts.append("context_blank_cell")
                    elif p.context_max_aspect > 0 and _ir is not None and not r.sub and _ir.width > 0 \
                            and _ir.height / _ir.width > p.context_max_aspect:
                        doubts.append("context_tall_cell")
                    elif p.context_garble_guard and (_gg := _garble_guard(
                            p, r, d.char, (align_char, _coord_refs(ctx, page, coord_cache).get(r.id),
                                           *(c for c, _ in (o.topk if o else []))),
                            vm_here)):
                        doubts.append(_gg)
                    elif p._context_guard_on() and (_g := _context_guard(
                            p, r, d.char, _coord_refs(ctx, page, coord_cache), vm_here)):
                        doubts.append(_g[0])
                        char = _g[1] or char
                    elif _context_variant_tie(
                            d, r.candidates, vm_here, p.context_variant_ratio, p.context_variant_lib_gap,
                            ctx.book.canonical_char if (ctx is not None and ctx.book.codepoints) else None):
                        doubts.append("context_variant_form")
                    elif r.id == page_last_id:
                        doubts.append("context_page_end")
                    elif p.context_lib_dissent_gap > 0 and _context_lib_dissent(
                            d.char, r.candidates, vm_here, p.context_lib_dissent_gap, p.context_lib_dissent_cov):
                        doubts.append("context_lib_dissent")
                    else:
                        ok, channel, char, prov = True, "context", d.char, "context"

                # 整理本 × 形状/上下文 一致 → 放行（用户 2026-09-06「很多都是整理本存在时
                # 非常明显的选择，能不能放松要求」）。走到这里还没放行的位，若整理本字与库
                # top1 语义同字（刻本形归一后是同一个字），或与 Step6 上下文定字相同，就放行：
                # 形取库 top1（它是刻本形）。两册人审位实测（关掉人裁通道的
                # 产物）整理本≡库top1 10/10、==上下文 4/4；全部人裁真值上反例 0（relax_study）。
                # 己已巳 不走这里（上面 split_ref 单独处理）。
                if (not ok and align_char and align_char not in always):
                    _top = r.candidates[0][0] if r.candidates else None
                    _d = dmap.get(r.id)
                    if _top and _top not in always and r.verdict == "diff" \
                            and vmap.semantic(_top) == vmap.semantic(align_char):
                        doubts.append("ref_lib_diff")
                    elif _top and _top not in always and p.ref_lib_coord_dissent \
                            and vmap.semantic(_top) == vmap.semantic(align_char) \
                            and (_cr := _coord_refs(ctx, page, coord_cache).get(r.id)) not in (None, "", *GAP_CHARS) \
                            and vmap.semantic(_cr) != vmap.semantic(align_char):
                        doubts.append("ref_lib_coord_dissent")
                    elif _top and _top not in always \
                            and vmap.semantic(_top) == vmap.semantic(align_char):
                        # 字面相同不受加闸影响，照放（任务书「字面相同的放行照旧」）。
                        # 字面不同——变体放行——才要过闸：可信边，或 Step6 margin 过线
                        # （复用 context_margin，同一把生产已在用的尺子），否则记
                        # doubt、退回人审，不采信这条判决（ref_lib_variant_guard）。
                        # 间接路径（经共同正字才同义）不许靠 margin 过闸（variant_indirect_guard）。
                        _indirect = (_top != align_char
                                     and not _direct_variant_edge(_top, align_char))
                        if _top == align_char:
                            ok, channel, prov = True, "ref_lib", "match"
                            char = _top
                        elif (_trusted_variant_edge(_top, align_char, ledger, ctx.book)
                              or (not _indirect
                                  and _d is not None and _d.margin >= p.context_margin)):
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

                # 铁证放行（用户 2026-09-27 批准转正，`iron_evidence` 模块）：本格与一个
                # 人裁过、别的格的实例比对，够像就放行文本——不看整理本、不看 OCR，只认
                # 字形库里已确认的刻例。**只当兜底**：放在这里、`if not ok` 之后——只给
                # 上面所有通道都没定下来的格再补一次机会，不覆盖任何已经放行的判决（哪怕
                # 铁证跟它不一致）。开关前后产物 diff 因此只应该多出 `channel="iron"` 的新
                # 增格，一个已有的格都不会变——这是这次转正验证的判据，也是「先不进库」
                # 那种谨慎口子该配的谨慎版本：铁证闸更擅长的「揪出 dual/match_ref 语义对
                # 但字形错的位」（王/玉 那类）这次先不做，只扩覆盖率，不动存量判决。
                if not ok and iron_ctx is not None:
                    ex_miss: list[str] = []
                    iron_char = soft_patch(r.id, "iron", _iron_decide, ctx, page, cc.col, r,
                                           iron_ctx, iron_scale, iron_ns,
                                           ex_miss,
                                           p.db_path)
                    if iron_char is not None and ex_miss:
                        # 对照刻例原图缺（缓存里没有）：结果随缓存内容变，不放，转待审（overview#554）
                        doubts.append("iron_ex_missing")
                        iron_ex_missing[r.id] = len(ex_miss)
                        iron_char = None
                    if iron_char is not None \
                            and context_conflicts_ref(iron_char, align_char, vm_here):
                        doubts.append("iron_vs_ref")
                    elif iron_char is not None \
                            and _iron_confusable_witness(
                                iron_char, (align_char, _coord_refs(ctx, page, coord_cache).get(r.id)),
                                vm_here):
                        doubts.append("iron_confusable_ref")
                    elif iron_char is not None and not align_char \
                            and _iron_coord_dissent(iron_char, _coord_refs(ctx, page, coord_cache).get(r.id),
                                                    vm_here):
                        doubts.append("iron_vs_coord")
                    elif iron_char is not None and _iron_ctx_dissent(
                            iron_char, dmap.get(r.id), r.candidates, vm_here, p.iron_ctx_prob, p.iron_ctx_gap):
                        doubts.append("iron_vs_ctx")
                    elif iron_char is not None:
                        ok, channel, char, prov = True, "iron", iron_char, "iron"
                        doubts = []
                # 近似例（overview#276）：这一格的字就是库给的字、而库给它的依据是近似例 →
                # 照常放行、在 evidence 里标注（文本侧表与卡片读它）。
                apx_ev = (_approx_hit(r, char, apx_ids, apx_only)
                          if (apx_ids or apx_only) else None)
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
                              **({"approx": apx_ev} if apx_ev else {}),
                              **({"patch_missing": patch_missing[r.id]}
                                 if r.id in patch_missing else {}),
                              **({"iron_ex_missing": iron_ex_missing[r.id]}
                                 if r.id in iron_ex_missing else {})}))
            out.append(ColumnAdmit(col=cc.col, ok=True, chars=recs))
        # —— 后处理遍的次序（W5，GUJI-49；改次序＝改产物，别动）——
        #   0 group_flow（字组统一流程，升／降，缺省关）→ 1 rare_ref（升）→ 3 shadow_veto（降）→
        #   4 seal_blank_flip（降）→ 5 _review_lanes_pass（升）→ 5b rare_ref_coord（升）→ （6 rare_cp_ctx_review 已于 2026-10-18 删除）→
        #   （8 oversplit hint、9 runt_cell_review 已于 2026-10-23 删除）→ 9b symbol_review（降）→ 10 human_unbound（降，人裁绑丢闸，放最后）。（shadow_promote 已于 W2 删除；_resolve_ji_yi_si、
        #   ry_group、rr_clf、m7 各遍已于 2026-10-18 并进 group_flow 删除，编号留空不改）
        #   「降」的遍在置空 channel 前调 `_demote()`，把放行时的 channel 与遍名写进 `evidence.demoted_from`；
        #   主循环内就地置空（放行记录生成之前）的不记。
        # 字组统一流程（group_flow）紧接主循环：组内格先按组判，免得 rare_ref 等补放遍把整理本字
        # 放进来（vol04 A/B：rare_ref 把刻作 𫎇 的格放成整理本的 蒙）
        if p.group_flow:
            d_gf = _group_flow_pass(p, out, amap, mmap, ctx, page, patch_missing)
            n_auto += d_gf
            n_review -= d_gf
            if p.group_flow_rr_shape:
                d_rs = _rr_shape_pass(p, out, amap, ctx, page, patch_missing)
                n_auto += d_rs
                n_review -= d_rs
            if p.group_flow_wu_shape:
                d_ws = _wu_shape_pass(p, out, amap, ctx, page, patch_missing)
                n_auto += d_ws
                n_review -= d_ws
            if p.group_flow_hou_shape:
                _hou_shape_pass(p, out, ctx, page, patch_missing)
            if p.group_flow_part_shape:
                d_pt = _part_shape_pass(p, out, amap, ctx, page, patch_missing)
                n_auto += d_pt
                n_review -= d_pt
            if p.group_flow_pair_shape:
                d_ps = _pair_shape_pass(p, out, amap, ctx, page, patch_missing, _coord_refs(ctx, page, coord_cache))
                n_auto += d_ps
                n_review -= d_ps
            _nm5 = None
            if p.group_flow_pair_shape_nm_5b and p.group_flow_pair_shapes:
                from .align_ref import rare_topk_map
                _nm5 = {k: v[0] for k, v in rare_topk_map(_opt(ctx, "rare_candidates", page), 1).items() if v}
            for _pair in sorted(p.group_flow_pair_shapes):      # 多对两字刻形（墨量图），逐对补放；开 veto 时再降刻形强烈反对的已放行格
                d_ps = _pair_shape_pass(p, out, amap, ctx, page, patch_missing, _coord_refs(ctx, page, coord_cache),
                                        model_path=p.group_flow_pair_shapes[_pair], veto=p.group_flow_pair_shape_veto,
                                        nm_5b=_nm5)
                n_auto += d_ps
                n_review -= d_ps
            if p.group_flow_book_knn:
                d_bk = _book_knn_pass(p, out, amap, ctx, page, patch_missing)
                n_auto += d_bk
                n_review -= d_bk
            if p.group_flow_near_knn:
                d_nk = _near_knn_pass(p, out, amap, mmap, ctx, page, patch_missing)
                n_auto += d_nk
                n_review -= d_nk
            if p.p_ref_admit and not _NO_P_REF.get():
                d_pr = _p_ref_pass(p, out, amap, mmap)
                n_auto += d_pr
                n_review -= d_pr
            if p.fold_groups:
                _ci = _opt(ctx, "char_index", page) if p.fold_aspect else None
                d_fd = _fold_pass(p, out, amap, mmap,
                                  coord=_coord_refs(ctx, page, coord_cache) if p.fold_coord_ref else None,
                                  wh={c.id: (c.width, c.height) for col in (_ci.columns if _ci else []) for c in col.chars}
                                  if _ci else None,
                                  dmap=dmap if p.fold_aspect_ctx_veto is not None else None)
                n_auto += d_fd
                n_review -= d_fd
        if p.rare_ref:
            d_rr = _rare_ref_pass(out, mmap, amap, rtop, keep_ref_review=True)
            n_auto += d_rr
            n_review -= d_rr
        if p.shadow_veto:
            d_veto = _shadow_veto_pass(ctx, page, p, out, mmap, amap)
            n_auto -= d_veto
            n_review += d_veto
        if p.seal_blank_page and p.lane_seal:
            from .occlusion import page_seal_blank
            d_seal = _seal_blank_flip(out, page_seal_blank(ctx, page, p),
                                      _coord_refs(ctx, page, coord_cache))
            n_auto -= d_seal
            n_review += d_seal
        if p.lane_witness3 or p.lane_coord or p.lane_seal:
            d_lane = _review_lanes_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), vmap,
                                        (lambda: _lane_witnesses(ctx.book, p))
                                        if (p.lane_witness3 or p.lane_coord) else None,
                                        canon=ctx.book.canonical_char if ctx.book.codepoints else None,
                                        variant_hook=_lane_variant_hook(ctx),
                                        rank_hook=_lane_variant_hook(ctx, "variant_rank"),
                                        knn_veto=(_witness3_knn_veto_fn(p, ctx, page)
                                                  if p.witness3_knn_veto and p.group_flow_near_knn else None),
                                        lib_n=(_keben_counts(p.db_path) or None)
                                        if ((p.lane_seal and p.lane_seal_lib_veto_min_n > 0) or p.lane_coord_blind_guard) else None)
            n_auto += d_lane
            n_review -= d_lane
        if p.blank_ink_nonchar:
            _aref_bi = _opt(ctx, "align_ref", page)
            d_bi = _blank_ink_pass(p, out, mmap, _coord_refs(ctx, page, coord_cache),
                                   frozenset(getattr(_aref_bi, "coord_conflict_ids", None) or []), vmap)
            n_auto += d_bi
            n_review -= d_bi
        if p.lane_header_formula:
            d_hf = _header_formula_pass(ctx, page, p, out)
            n_auto += d_hf
            n_review -= d_hf
        if p.pua_rules:
            # 5a pua_rule（升）：整理本缺字（〓）按人定的刻形规则表录字
            d_pua = _pua_rule_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache))
            n_auto += d_pua
            n_review -= d_pua
        if p.follow_ref or p.follow_ref_seen or p._follow_variants():
            # 5a' follow_ref（升＋改字）：照录整理本的异体对
            d_fr = _follow_ref_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), dmap,
                                    vmap if p._follow_variants() else None, _follow_ref_rival_hook(ctx))
            n_auto += d_fr
            n_review -= d_fr
        # 5a'' edge_pair（升）：库首位与整理本是边表自动认的同词异形对 → 暂归一放常见形
        d_ep = _edge_pair_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), dmap)
        n_auto += d_ep
        n_review -= d_ep
        if p._rt_rank() >= 1 or p.ref_lib_coord:
            # 5a''' ref_lib_coord（升）：坐标对位的整理本字＝库首位，按整理本放（史記 2026-11-01）
            d_rlc = _ref_lib_coord_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), vmap)
            n_auto += d_rlc
            n_review -= d_rlc
            if p.ref_topk_follow and p._rt_rank() >= 2:
                d_tk = _ref_topk_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache), vmap)
                n_auto += d_tk
                n_review -= d_tk
        if p.rare_ref and amap:
            # 5b rare_ref_coord（升）：排在审路之后，坐标对位兜底（coord_fallback）已接走的格不改通道
            d_rc = _rare_ref_pass(out, mmap, amap, rtop, _coord_refs(ctx, page, coord_cache), p.lane_variant_topk,
                                  keep_ref_review=True,
                                  coord_min_cov=p.rare_ref_coord_min_cov,
                                  group_top_ok=p.rare_ref_coord_group_top,
                                  nf=((_keben_counts(p.db_path), p.rare_ref_nf_max_n, p.rare_ref_nf_cov,
                                       frozenset(k for kv in (ctx.book.codepoints or {}).items() for k in kv))))
            n_auto += d_rc
            n_review -= d_rc
        if p.rare_ref_sparse:
            # 5b'' rare_ref_sparse（升）：少刻例整理本字、5-b 首位作证（A23 L02，缺省关）
            d_rs = _rare_ref_sparse_pass(p, out, mmap, amap, _opt(ctx, "rare_candidates", page),
                                         _coord_refs(ctx, page, coord_cache), _keben_counts(p.db_path))
            n_auto += d_rs
            n_review -= d_rs
        if p.solo_5b_cov is not None:
            # 5b-s solo_5b（升）：无参照格，库首位 cov／领先／刻例够，5-b 首位作证（形近字线 001/002，缺省关）
            d_s5 = _solo_5b_pass(p, out, mmap, amap, _opt(ctx, "rare_candidates", page),
                                 _coord_refs(ctx, page, coord_cache),
                                 _trusted_keben_counts(p.db_path),
                                 mmap_raw=mmap_raw)
            n_auto += d_s5
            n_review -= d_s5
        if p.solo_adapt_pct is not None:
            # 5b-a solo_adapt（升）：无参照格按字自适应门槛（字自比分布＋高危字对，形近字线 001–003，缺省关）
            d_sa = _solo_adapt_pass(p, out, mmap, amap, _opt(ctx, "rare_candidates", page),
                                    _coord_refs(ctx, page, coord_cache))
            n_auto += d_sa
            n_review -= d_sa
        if p.num_run_cov is not None:
            # 5b-n num_run（升）：无参照格，数字串里的数字放过 never_match 护栏（形近字线 001–003 卷数小注，缺省关）
            d_nr = _num_run_pass(p, out, mmap, amap, _coord_refs(ctx, page, coord_cache),
                                 _opt(ctx, "rare_candidates", page) if p.num_run_cov_5b is not None else None)
            n_auto += d_nr
            n_review -= d_nr
        if p.solo_cal:
            # 5b-c solo_cal（升）：无参照格 5a 校准直放（cov／gap 两档，排在各补放通道最后，缺省关）
            d_sc = _solo_cal_pass(p, out, mmap, amap,
                                  _opt(ctx, "rare_candidates", page) if p.solo_cal_5b_cov is not None else None,
                                  _coord_refs(ctx, page, coord_cache),
                                  canon=(ctx.book.canonical_char if (p.solo_cal_5b_canon and ctx is not None
                                                                     and ctx.book.codepoints) else None))
            n_auto += d_sc
            n_review -= d_sc
        if p.lead_5b:
            # 5b-l lead_5b（升）：无参照格库与 5-b 不一致、5-b 首位领先明显 → 放 5-b 首位（缺省关）
            d_l5 = _lead_5b_pass(p, out, mmap, amap, _opt(ctx, "rare_candidates", page),
                                 _coord_refs(ctx, page, coord_cache))
            n_auto += d_l5
            n_review -= d_l5
        if p.ref_lib_5b_veto is not None:
            # 5b-v ref_lib_5b_veto（降）：整理本＝库首位放行、5-b 明确偏向别的字 → 退回人审（缺省关）
            d_rv = _ref_lib_5b_veto_pass(p, out, _opt(ctx, "rare_candidates", page))
            n_auto -= d_rv
            n_review += d_rv
        n_code_fix = n_code_mismatch = 0
        if p.pua_code_table:
            # 5b' code_table（改字，不降审）：格的私用码在码表里、非人裁放行字≠码表字 → 改放码表字；族外字降审。放在 vis_ruling 之前
            n_code_fix, n_code_mismatch, d_cd = _pua_code_pass(out, amap, p=p, pin=_pua_pin(ctx))
            n_auto -= d_cd
            n_review += d_cd
            if p.pua_code_admit:
                # 5b'' code_table 放行（升）：未放行格，码表字＝库首位 → 放（缺省关）
                d_ca = _pua_code_admit_pass(out, amap, mmap, p=p, pin=_pua_pin(ctx))
                n_auto += d_ca
                n_review -= d_ca
        # 5c vis_ruling（升）：待审格的窗口命中看图判裁定 → 放行（无组入口，裁定库缓存；放在降审遍之前）
        d_vr = _vis_ruling_pass(p, out, amap)
        n_auto += d_vr
        n_review -= d_vr
        if d_vr and p.group_flow_hou_shape_late and p.group_flow and p.group_flow_hou_shape:
            # 5c 补放的 候／𠋫 格补跑刻形判（只判还没判过的格；只改字、不改放行）
            _hou_shape_pass(p, out, ctx, page, patch_missing, only_unjudged=True)
        if p.symbol_review:
            d_sym = _symbol_review_pass(ctx, page, p, out, mmap, human_shapes)
            n_auto -= d_sym
            n_review += d_sym
        if p.symbol_ref_blank:
            d_srb = _symbol_ref_blank_pass(p, out, mmap, _coord_refs(ctx, page, coord_cache))
            n_auto += d_srb
            n_review -= d_srb
        if p.near_knn_gap and p.group_flow and p.group_flow_near_knn:
            # near_knn 入口放宽：排在各补放通道之后，只收它们都没放的格（见 `_near_knn_pass` 的 stage）
            d_ng = _near_knn_pass(p, out, amap, mmap, ctx, page, patch_missing, stage="gap")
            n_auto += d_ng
            n_review -= d_ng
        if p.consensus_lib_cov is not None:
            # 5b-c consensus_lib（升）：共识升档 same、库字＝库首位、cov 够、无护栏、字组没留审 → 放库字
            # （字形线 f4，缺省关；排在各补放通道与 near_knn_gap 之后，只收它们都没放的格）
            d_cl = _consensus_lib_pass(p, out, mmap_raw, amap, _coord_refs(ctx, page, coord_cache))
            n_auto += d_cl
            n_review -= d_cl
        if p.stroke_veto:
            # 笔画反向护栏（降）：已放行非人裁格，笔画判与放行字相反 → 降审（排在各补放通道之后，缺省关）
            d_sv = _stroke_veto_pass(p, out, ctx, page, patch_missing)
            n_auto -= d_sv
            n_review += d_sv
        if p.pair_form:
            # 放行字按刻形改（升前的字、不降审）：5a.3 在第 5 步给了字的格，放行字是同一对里的另一个字 → 改放刻形字（缺省关）
            _pf_n = _pair_form_pass(p, out, mmap, ctx)
        if human_lost:
            # 顺移豁免对位表：现役对位为主，缺格的补坐标对位字（coord_fallback 放行的格没有现役对位；史記 2026-11-03）
            d_hu = _human_unbound_pass(ctx, page, out, human_lost,
                                       ({**{k: (v,) for k, v in _coord_refs(ctx, page, coord_cache).items() if v}, **(amap or {})}
                                        if p.human_unbound_shift_ok else None))
            n_auto -= d_hu
            n_review += d_hu
        if evict_rv:
            d_ev = _evict_review_pass(ctx, page, out, evict_rv)
            n_auto -= d_ev
            n_review += d_ev
        d_ju = _jiazhu_uneven_pass(ctx, page, out, mmap, amap, _coord_refs(ctx, page, coord_cache))
        n_auto -= d_ju
        n_review += d_ju
        if ctx.book.codepoints:
            # 放行字落到册指定码位。放在所有后处理遍之后：`group_flow` 的文意 L2 表键是按整理本原字
            # 建的（`_clf_ctx` 取邻格放行字），提前改邻格字会让键对不上、组内格被误降。
            for col in out:
                for rec in col.chars or []:
                    if rec.admit and rec.char and not _codepoint_exempt(rec, ctx.book):
                        rec.char = ctx.book.canonical_char(rec.char)
        if patch_missing:
            lanes: dict[str, int] = {}
            for v in patch_missing.values():
                for k in v:
                    lanes[k] = lanes.get(k, 0) + 1
            ctx.log(f"seed_admit p{page}: patch_missing=skip，{len(patch_missing)} 格读不到字块、"
                    f"跳过 {lanes}（见各格 evidence.patch_missing）")
        return {"seed_admit": PageAdmit(page=page, n_auto=n_auto, n_excluded=n_excluded,
                                        n_review=n_review, columns=out,
                                        n_code_fix=n_code_fix, n_code_mismatch=n_code_mismatch)}


def _codepoint_exempt(rec, book) -> bool:
    """放行字落册码位的例外：这对字已有按刻形拆判的字组（`registry.SHAPE_GROUPS`，如 變𠮓 bian），
    码位归一只是兜底（「暂归一」），人裁的刻形、该组判出的刻形照录，不归一。
    vol04:197:7:3 人裁 變 被工作区 變→𠮓 改回 𠮓（A32 10-25 报），bian 组判出的 變 也一样被改回（A24 10-25）。"""
    tgt = book.canonical_char(rec.char)
    if tgt == rec.char:
        return False
    if ((rec.evidence or {}).get("hou_shape") or {}).get("char") == rec.char:
        return True                       # 候𠋫 书级刻形判法判出的 候 照录，不归 𠋫
    gids = _shape_split(rec.char, tgt)
    if not gids:
        return False
    if rec.channel == "human" or rec.provenance == "human":
        return True
    grp = (rec.evidence or {}).get("group") or {}
    return grp.get("id") in gids and grp.get("pick") == rec.char


@lru_cache(maxsize=256)
def _shape_split(a: str, b: str) -> frozenset[str]:
    """把 a、b 拆成两个字判的字组 id。两形同在一族（`FlowSpec.families`，如 guan 的 宫宮：族内只按库形最近取，
    宮→宫 是 sheldon 定的暂归一）不算拆判。"""
    from ..groups.registry import SHAPE_GROUPS
    return frozenset(g for g, s in SHAPE_GROUPS.items() if a in s.members and b in s.members
                     and not any(a in f and b in f for f in s.flow.families))


def _demote(rec, by: str) -> None:
    """W5（GUJI-49）：后处理遍把**已放行**格降回待审之前，在 `evidence.demoted_from` 记下放行时的通道与降级遍
    （`{"channel": <放行时 channel>, "by": <遍名>}`，字段格式 Mila 10-14 代定、Eliot 如有异议 10-16 中午前提）。
    只在 `rec.admit` 为真时记（没放行过的格不是「降级」，不加键）；只追加 evidence 键，不改放行结果。
    **必须在 `rec.channel` 被置空之前调用。**"""
    if rec.admit:
        rec.evidence = {**(rec.evidence or {}), "demoted_from": {"channel": rec.channel, "by": by}}


_RARE_REF_HARD = ("occluded", "excluded", "near_form", "context_blank_cell", "context_tall_cell", "form_open", "approx_exemplar")


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


def _hard_blocked(doubts, guard, allow_near_form: bool = False) -> bool:
    """规则 A／影子升级共用的硬护栏：这些格任何新增通道都不碰。
    `allow_near_form`：规则 A 坐标对位那支放宽 `near_form`（`rare_ref_nf`，见 `_rare_ref_nf_ok`），其余照拦。"""
    return (guard in ("never_match", "conflict", "timeout")
            or any(d.startswith("护栏:") or (d in _RARE_REF_HARD and not (allow_near_form and d == "near_form"))
                   for d in doubts))


def rare_ref_decide(*, doubts, guard, verdict, lib_char, lib_top, ref, op, rare_top, are_variants,
                    allow_near_form: bool = False) -> str | None:
    """规则 A（`SeedAdmitParams.rare_ref`）的判据，纯函数（离线评测与线上共用）。→ 放行字（=整理本字）或 None。

    `lib_char`：库判 same 时的字（否则 None）；`lib_top`：库首位（same 取 char，否则候选第一名）；
    `rare_top`：5-b 首位；`are_variants(a, b)`：两字有无直接异体关系。"""
    if op != "replace" or not ref or ref in _JYS or not rare_top or rare_top != ref:
        return None
    if _hard_blocked(doubts, guard, allow_near_form):
        return None
    if verdict == "same" and lib_char and lib_char != ref:
        return None                       # 库明确认成了别的字
    if lib_top and lib_top != ref and are_variants(lib_top, ref):
        return None                       # 库首位是整理本字的异体：形取谁说不准，留给人
    return ref




def _rare_ref_coord_ok(ref: str, lib_top: str | None, cands: list, doubts, topk: int,
                       are_variants, group_chars: frozenset[str], cov: float = 1.0,
                       min_cov: float = _RARE_REF_COORD_MIN_COV, group_top_ok: bool = False) -> bool:
    """规则 A 坐标对位那支（`SeedAdmitParams.rare_ref_coord`）比现役对位多的护栏。纯函数。
    `group_top_ok`（`rare_ref_coord_group_top`）：库首位在字组里不拦，坐标对位字在字组里仍拦。"""
    if not ref or is_gap(ref):                  # 空格位／逐列本生僻字占位：不知道是哪个字
        return False
    if cov < min_cov:
        return False
    if ref in group_chars or (lib_top and lib_top in group_chars and not group_top_ok):
        return False                            # 字组里的字归 group_flow 判
    if any(isinstance(d, str) and d.startswith(("group_flow", "shadow_veto")) for d in doubts or ()):
        return False
    forms = [c for c, _v in cands[:max(topk, 0)]]
    return not any(f != ref and are_variants(f, ref) for f in forms)


_KEBEN_COUNTS: dict = {}


def _keben_counts(db_path: str) -> dict[str, int]:
    """字形库里每个字的刻例（exemplar）数，`rare_ref_nf` 用；按库路径＋mtime 缓存。读不了＝空表（调用方当没有这路放宽）。"""
    import sqlite3
    try:
        from pathlib import Path
        key = (db_path, Path(db_path).stat().st_mtime_ns)
    except OSError:
        return {}
    hit = _KEBEN_COUNTS.get(key)
    if hit is not None:
        return hit
    out: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            for ch, n in c.execute("SELECT g.char, COUNT(*) FROM exemplars e JOIN glyphs g USING(glyph_id) GROUP BY g.char"):
                out[str(ch)] = int(n or 0)
    except Exception:
        return {}
    _KEBEN_COUNTS.clear()
    _KEBEN_COUNTS[key] = out
    return out


_TRUSTED_COUNTS: dict = {}


def _trusted_keben_counts(db_path: str) -> dict[str, int]:
    """字 → 可信刻例数（人裁＋有参照互证；借库、solo、来源不明的不算，`clustering.keben_counts`），
    `solo_5b_min_n` 读它（参校本属性 C1，A23 #1275／#1276；无参照放行不自喂）。按库路径＋mtime 缓存；读不了＝空表（通道不放）。"""
    from pathlib import Path
    try:
        key = (db_path, Path(db_path).stat().st_mtime_ns)
    except OSError:
        return {}
    hit = _TRUSTED_COUNTS.get(key)
    if hit is not None:
        return hit
    from ..clustering.keben_counts import trusted_keben_counts
    out = trusted_keben_counts(db_path)
    _TRUSTED_COUNTS.clear()
    _TRUSTED_COUNTS[key] = out
    return out


def no_ref_page_params(p: "SeedAdmitParams", page: int) -> "SeedAdmitParams":
    """无参校本页（`no_ref_pages`）上把 `no_ref_params` 叠到本步参数上；别的页、或没配，原样返回同一个对象。"""
    if not p.no_ref_pages or not p.no_ref_params:
        return p
    from ..core.book import _expand_pages
    if page not in set(_expand_pages(list(p.no_ref_pages))):
        return p
    bad = [k for k in p.no_ref_params if k not in type(p).model_fields or k.startswith("no_ref_")]
    if bad:
        raise ValueError(f"seed_admit.no_ref_params: 不认的参数 {bad}（须是 seed_admit 的参数名，且不能是 no_ref_*）")
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **p.no_ref_params})


def _rare_ref_nf_ok(ref: str, cands: list, n_lib: int, max_n: int, strong_cov: float, are_variants,
                    cp_skip: frozenset = frozenset()) -> bool:
    """规则 A 坐标对位那支放宽 `near_form` 的条件（`rare_ref_nf`）。纯函数。BMP 字、库对该字没有判力（刻例 ≤ max_n）、
    候选里没有强对手（非该字且 cov ≥ strong_cov）、cov ≥ 0.80 的候选不是该字的异体、该字不在册 codepoints 里。"""
    if not ref or ord(ref[0]) >= 0x20000 or n_lib > max_n or ref in cp_skip:
        return False                       # cp_skip：册 codepoints 登记过的字（异体对码位未定，如 竄／𥨥，金标里错放都在这类）
    for ch, cov in cands:
        if ch == ref:
            continue
        if cov >= strong_cov or (cov >= 0.80 and are_variants(ch, ref)):
            return False
    return True


def _fold_hold(rec, ch) -> bool:
    """折叠组（`fold_ref_char: false` 等）已把这格归组、字等文意（`evidence.fold_pending`）：整理本字不算数，
    规则 A（rare_ref／rare_ref_sparse）不得拿整理本字在组内定字（殿本 vol41:55:4:19「六日僧道」应为曰，A24 11-08）。"""
    fp = (rec.evidence or {}).get("fold_pending")
    if not fp or not ch:
        return False
    from ..groups.registry import FLOW_GROUPS
    g = FLOW_GROUPS.get(fp.get("group"))
    return bool(g and ch in g.members)


def _rare_ref_pass(out: list, mmap: dict, amap: dict, rtop: dict,
                   coord: dict[str, str] | None = None, variant_topk: int = 3,
                   keep_ref_review: bool = False, nf: tuple | None = None,
                   coord_min_cov: float = _RARE_REF_COORD_MIN_COV, group_top_ok: bool = False) -> int:
    """规则 A 放行通道 `rare_ref`：只把**仍待审**的格升为放行，不改任何已放行格。→ 升级格数。

    `coord` 不给：只看现役对位（`amap`）里的格。`coord` 给了（`rare_ref_coord`，排在审路之后另跑一遍）：
    只看现役对位里**没有**的格，拿坐标对位字当整理本字（护栏见 `_rare_ref_coord_ok`）。
    `keep_ref_review`（＝`lane_keep_ref_review`）：护栏拿整理本字拦下的格（`_LANE_REF_REVIEW`）不按整理本字放回，
    同审路（vol18:115:6:3 刻「本」、整理本与 5-b 都作「木」、字组文意判「本」，旧版 rare_ref 放成「木」）。"""
    from ..variants import look_alike as are_variants   # C 对也拦（字对关系表删了 C 边，护栏不能跟着松）
    group_chars: frozenset[str] = frozenset()
    if coord:
        from ..groups.registry import GROUPS
        group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if keep_ref_review and set(rec.doubts or []) & _LANE_REF_REVIEW:
                continue
            m = mmap.get(rec.id)
            al = amap.get(rec.id)
            top5 = rtop.get(rec.id)
            if m is None or not top5:
                continue
            lib_top = (m.char if m.verdict == "same" and m.char
                       else (m.candidates[0][0] if m.candidates else None))
            via = None
            if coord is not None:
                if al is not None:
                    continue
                co = coord.get(rec.id)
                if not co or not _rare_ref_coord_ok(co, lib_top, list(m.candidates or []), rec.doubts,
                                                    variant_topk, are_variants, group_chars, m.cov, coord_min_cov,
                                                    group_top_ok):
                    continue
                al, via = (co, "replace"), "coord"      # 坐标对位字与库首位不同才有意义，按 replace 段判
            elif al is None:
                continue
            nf_ok = bool(nf and via == "coord" and _rare_ref_nf_ok(
                al[0], list(m.candidates or []), nf[0].get(al[0], 0), nf[1], nf[2], are_variants, nf[3]))
            ch = rare_ref_decide(doubts=rec.doubts, guard=m.guard, verdict=m.verdict,
                                 lib_char=m.char if m.verdict == "same" else None, lib_top=lib_top,
                                 ref=al[0], op=al[1], rare_top=top5[0], are_variants=are_variants,
                                 allow_near_form=nf_ok)
            if ch is None or _fold_hold(rec, ch):
                continue
            nf_used = nf_ok and "near_form" in (rec.doubts or [])
            rec.admit, rec.channel, rec.provenance, rec.char = True, "rare_ref", "rare_ref", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "rare_ref": {
                "rare": top5[0], "ref": al[0], "lib": lib_top, "cov": m.cov, **({"via": via} if via else {}),
                **({"near_form_relaxed": True} if nf_used else {})}}
            n += 1
    return n



def _is_hanzi(ch: str) -> bool:
    if not ch or len(ch) != 1:
        return False
    o = ord(ch)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3347F)


def rare_sparse_decide(*, ref: str | None, cands: list, n_lib: int, doubts, guard, verdict, lib_char, lib_top,
                       max_n: int, lead_min: float, variant: bool, are_variants,
                       group_chars: frozenset = frozenset()) -> tuple[str, float] | None:
    """规则 A 少刻例支（`SeedAdmitParams.rare_ref_sparse`）的判据，纯函数。`cands`＝5-b 候选 [(字, 分, 来源)…]，按融合名次。
    → (放行字＝整理本字, 领先量) 或 None。"""
    if not ref or is_gap(ref) or ref in _JYS or not _is_hanzi(ref) or not cands:
        return None
    if n_lib > max_n:
        return None
    if _hard_blocked(doubts or [], guard):
        return None
    if verdict == "same" and lib_char and lib_char != ref:
        return None
    if ref in group_chars or (lib_top and lib_top in group_chars):
        return None
    if any(isinstance(d, str) and d.startswith(("group_flow", "shadow_veto")) for d in doubts or ()):
        return None

    def mine(c: str) -> bool:
        return c == ref or bool(variant and ord(ref) >= 0x20000 and c and are_variants(ref, c))

    top_c, top_s, top_src = cands[0]
    if not mine(top_c):
        return None
    rivals = [sc for c, sc, src in cands[1:] if src == top_src and not mine(c)]
    if not rivals:
        return None                       # 没有同来源的对手：领先量说不清，不放
    lead = float(top_s) - max(float(x) for x in rivals)
    return (ref, round(lead, 4)) if lead >= lead_min else None


def _rare_ref_sparse_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str],
                          keben: dict[str, int]) -> int:
    """规则 A 少刻例支：只把**仍待审**的格升为放行。→ 升级格数。见 `SeedAdmitParams.rare_ref_sparse`。"""
    if rare is None:
        return 0
    from ..groups.registry import GROUPS
    from ..variants import are_variants
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    rmap = {r.id: [(c.char, c.score, getattr(c, "font", None)) for c in r.candidates if c.char]
            for cc in rare.columns for r in cc.chars}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if set(rec.doubts or []) & _LANE_REF_REVIEW:
                continue                  # 同规则 A：护栏拿整理本字拦下的格不按整理本字放回
            m = mmap.get(rec.id)
            cands = rmap.get(rec.id)
            if m is None or not cands:
                continue
            al = amap.get(rec.id)
            ref, via = (al[0], "sparse") if al is not None else (coord.get(rec.id), "sparse_coord")
            lib_top = m.char if m.verdict == "same" and m.char else (m.candidates[0][0] if m.candidates else None)
            got = rare_sparse_decide(ref=ref, cands=cands, n_lib=keben.get(ref or "", 0), doubts=rec.doubts,
                                     guard=m.guard, verdict=m.verdict, lib_char=m.char if m.verdict == "same" else None,
                                     lib_top=lib_top, max_n=p.rare_ref_sparse_max_n, lead_min=p.rare_ref_sparse_lead,
                                     variant=True, are_variants=are_variants, group_chars=group_chars)
            if got is None:
                continue
            ch, lead = got
            if _fold_hold(rec, ch):
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "rare_ref", "rare_ref", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "rare_ref": {
                "rare": cands[0][0], "ref": ch, "lib": lib_top, "cov": m.cov, "via": via, "lead": lead,
                "n_lib": keben.get(ch, 0)}}
            n += 1
    return n



def solo_5b_decide(*, cands: list, rare_top: str | None, n_lib: dict | int, doubts, guard, cov_min: float,
                   gap_min: float, min_n: int, are_variants, group_chars, near_form_chars,
                   same_char: str | None = None, cov_min_same: float | None = None) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.solo_5b_cov` 的判据，纯函数（离线评测与线上共用）。`cands`：库候选 [(字, cov)]；
    `n_lib`：刻例数表（字→例数）或库首位的例数。→ (放行字, cov, gap) 或 None。"""
    if not cands or not rare_top:
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    top, cov1 = ranked[0]
    if cov_min_same is not None and same_char is not None and same_char == top:
        cov_min = min(cov_min, cov_min_same)      # 库已判 same 的格降一档（solo_5b_same_cov）
    if (not top or is_gap(top) or top in _JYS or not _is_hanzi(top) or top in group_chars
            or top in near_form_chars or float(cov1) < cov_min):
        return None
    if guard is not None or _hard_blocked(doubts or [], guard):
        return None
    if len(ranked) > 1 and ranked[1][0] in near_form_chars:
        return None

    def same(c: str) -> bool:
        return c == top or bool(are_variants(c, top))

    if not same(rare_top):
        return None
    n = n_lib.get(top, 0) if isinstance(n_lib, dict) else int(n_lib)
    if n < min_n:
        return None
    rivals = [float(v) for c, v in ranked[1:] if c and not same(c)]
    gap = float(cov1) - (max(rivals) if rivals else 0.0)
    if gap < gap_min:
        return None
    return top, float(cov1), round(gap, 4)


def _raw_same_char(m, mmap_raw: dict | None) -> str | None:
    """库判 same 的字：有退档前记录就看它（`consensus_fallback` 会把无参照格的共识 same 退成 unsure）。"""
    r = (mmap_raw or {}).get(m.id, m)
    return r.char if r.verdict == "same" else None


def _solo_5b_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str],
                  keben: dict[str, int],
                  mmap_raw: dict | None = None) -> int:
    """无参照格「库首位＋5-b 作证」：只把**仍待审**、无任何整理本对位的格升为放行。→ 升级格数。见 `SeedAdmitParams.solo_5b_cov`。

    `mmap_raw`：`consensus_fallback` 退档前的 glyph_match 记录。无参照格没有整理本字，共识升档的 same
    一律被退回 unsure，`solo_5b_same_cov` 要认的正是这批「库原判 same」，所以按退档前的记录看。"""
    if rare is None:
        return 0
    from ..clustering.seeding import NEAR_FORM_CHARS
    from ..groups.registry import GROUPS
    from ..variants import are_variants
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    rmap = {r.id: r.candidates[0].char for cc in rare.columns for r in cc.chars if r.candidates and r.candidates[0].char}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                continue                  # 有整理本对位的格归别的通道
            m = mmap.get(rec.id)
            if m is None or not m.candidates:
                continue
            got = solo_5b_decide(cands=list(m.candidates), rare_top=rmap.get(rec.id), n_lib=keben,
                                 doubts=rec.doubts, guard=m.guard, cov_min=p.solo_5b_cov, gap_min=p.solo_5b_gap,
                                 min_n=p.solo_5b_min_n, are_variants=are_variants, group_chars=group_chars,
                                 near_form_chars=NEAR_FORM_CHARS,
                                 same_char=_raw_same_char(m, mmap_raw),
                                 cov_min_same=p.solo_5b_same_cov)
            if got is None:
                continue
            ch, cov1, gap = got
            rec.admit, rec.channel, rec.provenance, rec.char = True, "match_solo_5b", "match_solo_5b", ch
            rec.doubts = []
            # 无参照页放行的格不进字形库（C4 不自喂）：入库会抬高同字的刻例数与 cov，错标越放越笃定
            rec.evidence = {**rec.evidence, "no_glyph_lib": True, "solo_5b": {
                "lib": ch, "cov": round(cov1, 4), "gap": gap, "rare": rmap.get(rec.id), "n_trusted": keben.get(ch, 0)}}
            n += 1
    return n


def consensus_lib_decide(*, raw, doubts, cov_min: float, group_review: bool = False) -> str | None:
    """`SeedAdmitParams.consensus_lib_cov` 的判据，纯函数。`raw`：共识退档前的 glyph_match 记录；
    `group_review`：形近字组已判留审（如 一/二 组弃权，f4 027:154:6:1 是黑条）→ 不放。
    不要求整理本字＝库字：f4 实放 81 格里 55 格整理本是别字（剌/刺、寖/寢 等整理本错）、23 格无整理本字，看图都是库对。→ 放行字或 None。"""
    if group_review:
        return None
    if raw is None or not _is_consensus_same(raw) or not raw.char or not raw.candidates:
        return None
    top, cov1 = max(raw.candidates, key=lambda t: t[1])
    ch = raw.char
    if top != ch or float(cov1) < cov_min or float(raw.cov or 0.0) < cov_min:
        return None
    if is_gap(ch) or ch in _JYS or not _is_hanzi(ch):
        return None
    if raw.guard is not None or _hard_blocked(doubts or [], raw.guard):
        return None
    return ch


def _consensus_lib_pass(p: "SeedAdmitParams", out: list, mmap_raw: dict, amap: dict | None = None,
                        coord: dict | None = None) -> int:
    """共识升档 same 的库字放行：只把**仍待审**的格升为放行。→ 升级格数。见 `SeedAdmitParams.consensus_lib_cov`。"""
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            raw = mmap_raw.get(rec.id)
            ref = ((amap or {}).get(rec.id) or (None, None))[0] or (coord or {}).get(rec.id)
            grp = (rec.evidence or {}).get("group")
            ch = consensus_lib_decide(raw=raw, doubts=rec.doubts, cov_min=p.consensus_lib_cov,
                                      group_review=isinstance(grp, dict) and grp.get("decision") == "review")
            if ch is None:
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "consensus_lib", "consensus_lib", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "no_glyph_lib": True, "consensus_lib": {
                "lib": ch, "ref": ref, "cov": round(float(raw.cov or 0.0), 4), "via": raw.via}}
            n += 1
    return n


def _resolve_adapt_profile(v: str) -> str:
    """`solo_adapt_profile` 解析成绝对路径：给了相对路径按数据目录、再按工作区找；没给找 `config/groups/char_cov_profile.json`。找不到＝空。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    cands = []
    if v:
        q = Path(v).expanduser()
        cands = [q] if q.is_absolute() else [(data_root() or REPO_ROOT) / q, (workspace_root() or REPO_ROOT) / q]
    else:
        cands = [(data_root() or REPO_ROOT) / "config" / "groups" / "char_cov_profile.json"]
    for q in cands:
        if q.exists():
            return str(q)
    return ""


_ADAPT_CACHE: dict = {}


def load_adapt_profile(path: str) -> dict | None:
    """读字表（schema `char_cov_profile/1`）→ {"prof": {字: {n, miss, p10, p25, med}}, "cross": {"a|b": 上限}, "risk": {(a, b)}}。"""
    if not path:
        return None
    if path in _ADAPT_CACHE:
        return _ADAPT_CACHE[path]
    import json as _json
    with open(path, encoding="utf-8") as f:
        raw = _json.load(f)
    if raw.get("schema") != "char_cov_profile/1":
        raise ValueError(f"{path}: 不是 char_cov_profile/1 字表")
    risk = set()
    for a, b in raw.get("risk", []):
        risk.add((a, b))
        risk.add((b, a))
    out = {"prof": raw["prof"], "cross": raw.get("cross", {}), "risk": risk}
    _ADAPT_CACHE[path] = out
    return out


#: 字表 `cross` 只记互比 ≥ 这个值的字对（`scripts/char_cov_profile.py` 的 min_cross）
_ADAPT_CROSS_MIN = 0.90
_ADAPT_OK_DOUBTS = ("上下文 margin 不足", "库 unsure", "库 same 但准入被拦", "group_flow_ref_missing")


def solo_adapt_decide(*, cands: list, rare_top: str | None, guard, doubts, prof: dict, cross: dict, risk: set,
                      pct: str, floor: float, gap_min: float, min_n: int, window: float, are_variants,
                      group_chars, near_form_chars, risk_gap: float | None = None, abstain_ok: bool = False,
                      abstain_skip: str = "", near_slack: float | None = None, near_gap: float = 0.03,
                      nf_ok: bool = False) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.solo_adapt_pct` 的判据，纯函数（离线评测与线上共用）。→ (放行字, cov, gap) 或 None。"""
    if guard is not None or not cands:
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    c, v = ranked[0]
    v = float(v)
    ok = _ADAPT_OK_DOUBTS
    if abstain_ok and c not in group_chars and c not in abstain_skip:
        ok = ok + ("group_flow_abstain",)     # solo_adapt_abstain_ok：首位不在字组，字组流程弃权不算数
    if nf_ok and c not in group_chars and c not in near_form_chars:
        ok = ok + ("near_form",)              # solo_adapt_nf_ok：形近家族字只是候选；窗口内的形近表对手下面照拦
    if any(not (isinstance(d, str) and d.startswith(ok)) for d in (doubts or [])):
        return None
    if (not c or is_gap(c) or c in _JYS or not _is_hanzi(c) or c in group_chars or c in near_form_chars):
        return None
    pc = prof.get(c)
    thr = max(floor, pc[pct]) if pc else 1.0
    if not pc or pc["n"] < min_n or pc["miss"] > 0.2 or v < thr - (near_slack or 0.0):
        return None
    below = v < thr                       # solo_adapt_near_slack：差分位一点的格，领先要更大
    if rare_top != c:                     # 5-b 首位必须就是库首位（不认异体）
        return None
    rivals = [(d, float(w)) for d, w in ranked[1:] if d and d != c and not are_variants(d, c)]
    gap = v - max((w for _, w in rivals), default=0.0)
    if gap < gap_min or (below and gap < near_gap):
        return None
    for d, w in rivals:
        if w < v - window:
            continue
        if (c, d) in risk and risk_gap is not None and v - w >= risk_gap:
            continue                      # solo_adapt_risk_gap：高危对手落后够多，不拦
        if (c, d) in risk or d in near_form_chars:
            return None                   # 高危字对／形近表
        xm = cross.get(f"{c}|{d}", _ADAPT_CROSS_MIN)   # 字表只记 ≥ 0.90 的互比；没记＝c 的刻例像 d 不到 0.90
        if w > xm + 0.005:
            return None                   # 本格像 d 的程度超过 c 的刻例像 d 的上限
        xr = cross.get(f"{d}|{c}")
        if xr is not None and v <= xr:
            return None                   # d 的刻例也能这么像 c
    return c, v, round(gap, 4)


def _solo_adapt_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str]) -> int:
    """无参照格按字自适应门槛放行。→ 升级格数。见 `SeedAdmitParams.solo_adapt_pct`。"""
    prof = load_adapt_profile(p.solo_adapt_profile)
    if prof is None or rare is None:
        return 0
    from ..clustering.seeding import NEAR_FORM_CHARS
    from ..groups.registry import GROUPS
    from ..variants import are_variants
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    rmap = {r.id: r.candidates[0].char for cc in rare.columns for r in cc.chars if r.candidates and r.candidates[0].char}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                continue                  # 有整理本对位的格归别的通道
            m = mmap.get(rec.id)
            if m is None or not m.candidates:
                continue
            got = solo_adapt_decide(cands=list(m.candidates), rare_top=rmap.get(rec.id), guard=m.guard, doubts=rec.doubts,
                                    prof=prof["prof"], cross=prof["cross"], risk=prof["risk"], pct=p.solo_adapt_pct,
                                    floor=p.solo_adapt_floor, gap_min=p.solo_adapt_gap, min_n=p.solo_adapt_min_n,
                                    window=p.solo_adapt_window, are_variants=are_variants, group_chars=group_chars,
                                    near_form_chars=NEAR_FORM_CHARS, risk_gap=p.solo_adapt_risk_gap,
                                    abstain_ok=p.solo_adapt_abstain_ok, abstain_skip=p.solo_adapt_abstain_skip,
                                    near_slack=p.solo_adapt_near_slack, near_gap=p.solo_adapt_near_gap,
                                    nf_ok=p.solo_adapt_nf_ok)
            if got is None:
                continue
            ch, cov1, gap = got
            rec.admit, rec.channel, rec.provenance, rec.char = True, "match_solo_adapt", "match_solo_adapt", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "no_glyph_lib": True, "solo_adapt": {
                "lib": ch, "cov": round(cov1, 4), "gap": gap, "self": round(float(prof["prof"][ch][p.solo_adapt_pct]), 4)}}
            n += 1
    return n


#: `num_run_cov` 认的数字（卷数小注只用到这些）
NUM_RUN_DIGITS = frozenset("一二三四五六七八九十百千")
#: `num_run_cov` 允许的疑问（前缀）；别的疑问一律不碰
_NUM_RUN_OK_DOUBTS = ("护栏:never_match", "库 unsure", "库 same 但准入被拦", "上下文 margin 不足", "near_form",
                      "group_flow_ref_missing", "group_flow_abstain")
#: 邻格「是数字」时库首位的最低 cov（邻格未放行时）
_NUM_RUN_NEIGHBOR_COV = 0.98


def num_run_decide(*, cands: list, guard, doubts, prev: str | None, nxt: str | None, cov_min: float,
                   gap_min: float, are_variants, juan_cov: float | None = None, rare_top: str | None = None,
                   cov_5b: float | None = None, gap_5b: float | None = None) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.num_run_cov` 的判据，纯函数（离线评测与线上共用）。`cands`：库候选 [(字, cov)]；
    `prev`／`nxt`：同列同半格前后格的字（已判成数字才算，调用方给 None 表示不是／没有）。→ (放行字, cov, gap) 或 None。"""
    if guard not in (None, "never_match") or not cands:
        return None
    if any(not (isinstance(d, str) and d.startswith(_NUM_RUN_OK_DOUBTS)) for d in (doubts or [])):
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    top, cov1 = ranked[0]
    if (cov_5b is not None and rare_top is not None and rare_top == top and top in NUM_RUN_DIGITS
            and cov_5b <= float(cov1) < cov_min):
        # 原门槛差一点、5-b 首位作证的数字：cov 降档、领先升档（num_run_cov_5b）；够原门槛的照原规则
        cov_min, gap_min = cov_5b, max(gap_min, gap_5b if gap_5b is not None else gap_min)
    if top == "卷" and juan_cov is not None:
        # 卷数前的「卷」：只认后一格是数字
        if float(cov1) < juan_cov or nxt not in NUM_RUN_DIGITS:
            return None
    elif top not in NUM_RUN_DIGITS or float(cov1) < cov_min:
        return None
    elif prev not in NUM_RUN_DIGITS and nxt not in NUM_RUN_DIGITS:
        return None
    rivals = [float(v) for c, v in ranked[1:] if c and c != top and not are_variants(c, top)]
    gap = float(cov1) - (max(rivals) if rivals else 0.0)
    if gap < gap_min:
        return None
    return top, float(cov1), round(gap, 4)


def _num_run_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict[str, str], rare=None) -> int:
    """无参照格「数字串里的数字」放过 never_match 护栏。→ 升级格数。见 `SeedAdmitParams.num_run_cov`。"""
    from ..variants import are_variants
    rmap = ({r.id: r.candidates[0].char for cc in rare.columns for r in cc.chars if r.candidates and r.candidates[0].char}
            if rare is not None and p.num_run_cov_5b is not None else {})

    def digit_of(rec) -> str | None:
        if rec.admit:
            return rec.char if rec.char in NUM_RUN_DIGITS else None
        m = mmap.get(rec.id)
        if m is None or not m.candidates:
            return None
        c, v = max(m.candidates, key=lambda t: t[1])
        return c if c in NUM_RUN_DIGITS and float(v) >= _NUM_RUN_NEIGHBOR_COV else None

    n = 0
    for col in out:
        recs = list(col.chars or [])
        # 先按放行前的状态定邻格（本支放的格不互相作证，结果与格的先后无关）
        digit = {r.id: digit_of(r) for r in recs}
        by_sub: dict = {}
        for r in recs:
            by_sub.setdefault(r.sub, []).append(r)
        for seq in by_sub.values():
            for i, rec in enumerate(seq):
                if rec.admit or rec.provenance == "human" or rec.channel == "human":
                    continue
                if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                    continue              # 有整理本对位的格归别的通道
                m = mmap.get(rec.id)
                if m is None or not m.candidates:
                    continue
                prev = digit[seq[i - 1].id] if i > 0 else None
                nxt = digit[seq[i + 1].id] if i + 1 < len(seq) else None
                got = num_run_decide(cands=list(m.candidates), guard=m.guard, doubts=rec.doubts, prev=prev, nxt=nxt,
                                     cov_min=p.num_run_cov, gap_min=p.num_run_gap, are_variants=are_variants,
                                     juan_cov=p.num_run_juan_cov, rare_top=rmap.get(rec.id),
                                     cov_5b=p.num_run_cov_5b, gap_5b=p.num_run_gap_5b)
                if got is None:
                    continue
                ch, cov1, gap = got
                rec.admit, rec.channel, rec.provenance, rec.char = True, "match_num_run", "match_num_run", ch
                rec.doubts = []
                rec.evidence = {**rec.evidence, "no_glyph_lib": True, "num_run": {
                    "lib": ch, "cov": round(cov1, 4), "gap": gap, "prev": prev, "next": nxt}}
                n += 1
    return n


#: `solo_cal` 允许的疑问（前缀）；group_flow_abstain 只在首位不在字组时认（字组首位本来就不放）；near_form 照拦
_SOLO_CAL_OK_DOUBTS = ("上下文 margin 不足", "护栏:never_match", "库 unsure", "库 same 但准入被拦",
                       "group_flow_ref_missing", "group_flow_abstain")


def _parse_cal_tiers(spec: str) -> list[tuple[float, float]]:
    out = []
    for part in (spec or "").split(","):
        if part.strip():
            c, g = part.split(":")
            out.append((float(c), float(g)))
    return out


def solo_cal_decide(*, cands: list, guard, doubts, tiers: list, skip: str, group_chars, near_form_chars,
                    rare_top: str | None = None, cov_5b: float | None = None,
                    ok_doubts: tuple = _SOLO_CAL_OK_DOUBTS, allow: str = "") -> tuple[str, float, float, str] | None:
    """`SeedAdmitParams.solo_cal` 的判据，纯函数。`cands`：库候选 [(字, cov)]。→ (放行字, cov, gap, 档) 或 None；
    档＝"tier"（cov／gap 档）或 "5b"（库首位＝5-b 首位且 cov ≥ cov_5b）。"""
    if guard not in (None, "never_match") or not cands:
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    c, v = ranked[0]
    v = float(v)
    if not c or is_gap(c) or not _is_hanzi(c):
        return None
    got = _solo_cal_plain(c, v, ranked, doubts=doubts, tiers=tiers, skip=skip, group_chars=group_chars,
                          near_form_chars=near_form_chars, rare_top=rare_top, cov_5b=cov_5b, ok_doubts=ok_doubts)
    if got is None and c in allow and cov_5b is not None and rare_top == c and v >= cov_5b:
        # 白名单字（`solo_cal_allow`）：照常的档没放时，5-b 档不看 skip／字组／形近表，多认 near_form
        okd = ok_doubts + ("near_form",)
        if all(isinstance(d, str) and d.startswith(okd) for d in (doubts or [])):
            rival = next((float(w) for d, w in ranked[1:] if d and d != c), None)
            got = c, v, round(v - rival if rival is not None else v, 4), "allow"
    return got


def _solo_cal_plain(c, v, ranked, *, doubts, tiers, skip, group_chars, near_form_chars, rare_top, cov_5b, ok_doubts):
    if c in skip or c in group_chars or c in near_form_chars:
        return None
    if any(not (isinstance(d, str) and d.startswith(ok_doubts)) for d in (doubts or [])):
        return None
    rival = next(((d, float(w)) for d, w in ranked[1:] if d and d != c), None)
    if rival is not None and rival[0] in skip:
        return None
    gap = v - rival[1] if rival is not None else v
    if any(v >= tc and gap >= tg for tc, tg in tiers):
        return c, v, round(gap, 4), "tier"
    if cov_5b is not None and rare_top == c and v >= cov_5b:
        return c, v, round(gap, 4), "5b"
    return None


def _solo_cal_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str],
                   canon=None) -> int:
    """无参照格 5a 校准直放。→ 升级格数。见 `SeedAdmitParams.solo_cal`。
    `canon`：本书码位归一（`solo_cal_5b_canon` 开时给）；5-b 首位与库首位归一后同字，就把 5-b 首位当库首位比。"""
    from ..clustering.seeding import NEAR_FORM_CHARS
    from ..groups.registry import GROUPS
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    tiers = _parse_cal_tiers(p.solo_cal_tiers)
    rmap = ({r.id: r.candidates[0].char for cc in rare.columns for r in cc.chars if r.candidates and r.candidates[0].char}
            if rare is not None and p.solo_cal_5b_cov is not None else {})
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                continue                  # 有整理本对位的格归别的通道
            m = mmap.get(rec.id)
            if m is None or not m.candidates:
                continue
            rt = rmap.get(rec.id)
            if canon is not None and rt:
                lt = max(m.candidates, key=lambda t: t[1])[0]
                if lt and rt != lt and canon(rt) == canon(lt):
                    rt = lt
            got = solo_cal_decide(cands=list(m.candidates), guard=m.guard, doubts=rec.doubts, tiers=tiers,
                                  skip=p.solo_cal_skip, group_chars=group_chars, near_form_chars=NEAR_FORM_CHARS,
                                  rare_top=rt, cov_5b=p.solo_cal_5b_cov, allow=p.solo_cal_allow)
            if got is None:
                continue
            ch, cov1, gap, how = got
            rec.admit, rec.channel, rec.provenance, rec.char = True, "match_solo_cal", "match_solo_cal", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "no_glyph_lib": True,
                            "solo_cal": {"lib": ch, "cov": round(cov1, 4), "gap": gap, "by": how, "rare": rmap.get(rec.id)}}
            n += 1
    return n


#: `lead_5b` 允许的疑问（前缀）
_LEAD_5B_OK_DOUBTS = ("库 unsure", "上下文 margin 不足")


def lead_5b_decide(*, cands: list, rare: list, guard, doubts, cell_id: str, skip: str, are_variants,
                   gap_out: float, gap_in: float, lib_min: float,
                   ok_doubts: tuple = _LEAD_5B_OK_DOUBTS) -> tuple[str, float, str] | None:
    """`SeedAdmitParams.lead_5b` 的判据，纯函数。`cands`：库候选 [(字, cov)]；`rare`：5-b 候选 [(字, 分)]（按 5-b 原序，
    首位＝5-b 首选）。→ (放行字, 5-b 领先量, 档 "out"／"in") 或 None。"""
    if guard is not None or not cands or not rare:
        return None
    if cell_id and cell_id[-1].isalpha():
        return None                       # 拆分子格（001:162:2:17b）多是半字碎块
    if any(not (isinstance(d, str) and d.startswith(ok_doubts)) for d in (doubts or [])):
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    c = ranked[0][0]
    r0, s0 = rare[0][0], float(rare[0][1])
    if (not r0 or is_gap(r0) or not _is_hanzi(r0) or not c or r0 == c
            or r0 in skip or c in skip or are_variants(r0, c)):
        return None
    lead = s0 - max((float(s) for d, s in rare[1:] if d != r0), default=0.0)
    lib = [d for d, _ in ranked]
    if r0 not in lib:
        return (r0, round(lead, 4), "out") if lead >= gap_out else None
    second = next((d for d in lib[1:] if d and d != c), None)
    if r0 == second and lead >= gap_in and float(dict(ranked)[r0]) >= lib_min:
        return r0, round(lead, 4), "in"
    return None


def _lead_5b_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str]) -> int:
    """无参照格库与 5-b 不一致时听 5-b。→ 升级格数。见 `SeedAdmitParams.lead_5b`。"""
    if rare is None:
        return 0
    from ..variants import look_alike as are_variants   # C 对也跳过（同规则 A）
    rlist = {r.id: [(x.char, x.score) for x in r.candidates] for cc in rare.columns for r in cc.chars if r.candidates}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                continue
            m = mmap.get(rec.id)
            if m is None or not m.candidates or rec.id not in rlist:
                continue
            got = lead_5b_decide(cands=list(m.candidates), rare=rlist[rec.id], guard=m.guard, doubts=rec.doubts,
                                 cell_id=rec.id, skip=p.solo_cal_skip, are_variants=are_variants,
                                 gap_out=p.lead_5b_gap_out, gap_in=p.lead_5b_gap_in, lib_min=p.lead_5b_lib_min)
            if got is None:
                continue
            ch, lead, how = got
            lib_top = sorted(m.candidates, key=lambda t: -t[1])[0]
            rec.admit, rec.channel, rec.provenance, rec.char = True, "match_lead_5b", "match_lead_5b", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "no_glyph_lib": True,
                            "lead_5b": {"rare": ch, "lead": lead, "by": how, "lib": lib_top[0],
                                        "lib_cov": round(float(lib_top[1]), 4)}}
            n += 1
    return n


def ref_lib_5b_veto_decide(char: str, rare: list, score: float, lead: float) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.ref_lib_5b_veto` 的判据，纯函数。`rare`：5-b 候选 [(字, 分)]（5-b 原序）。
    → (5-b 首位, 分, 领先量)＝要否决；None＝不否决。"""
    if not rare or not char:
        return None
    r0, s0 = rare[0][0], float(rare[0][1])
    if not r0 or r0 == char or is_gap(r0) or not _is_hanzi(r0) or s0 < score:
        return None
    ld = s0 - max((float(s) for d, s in rare[1:] if d != r0), default=0.0)
    return (r0, round(s0, 4), round(ld, 4)) if ld >= lead else None


def _ref_lib_5b_veto_pass(p: "SeedAdmitParams", out: list, rare) -> int:
    """`ref_lib` 放行格里 5-b 明确偏向别的字的退回人审。→ 退回格数。见 `SeedAdmitParams.ref_lib_5b_veto`。"""
    if rare is None:
        return 0
    rlist = {r.id: [(x.char, x.score) for x in r.candidates] for cc in rare.columns for r in cc.chars if r.candidates}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if not rec.admit or rec.channel != "ref_lib":
                continue
            got = ref_lib_5b_veto_decide(rec.char, rlist.get(rec.id) or [], p.ref_lib_5b_veto, p.ref_lib_5b_veto_lead)
            if got is None:
                continue
            r0, s0, ld = got
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = [*(rec.doubts or []), "ref_lib_5b_veto"]
            rec.evidence = {**rec.evidence, "ref_lib_5b_veto": {"rare": r0, "score": s0, "lead": ld}}
            n += 1
    return n


_SHADOW_GATES: dict = {}


def _shadow_model_path(p: "SeedAdmitParams"):
    """缺省模型：只开 veto 用 v1（老口径，行为不变）；开了 promote 用 v2（要名次类特征）。"""
    from ..shadow.model import DEFAULT_MODEL
    return p.shadow_model or DEFAULT_MODEL


def _shadow_gate(p: "SeedAdmitParams"):
    """进程内缓存：同一 (模型指纹, db, 门槛) 只建一次（字形库人裁表要扫 sqlite）。"""
    key = (p.shadow_model_fingerprint, str(_shadow_model_path(p)), p.db_path, p.variants, p.shadow_conf)
    g = _SHADOW_GATES.get(key)
    if g is None:
        from ..shadow.gate import ShadowGate
        from ..shadow.model import load_model
        from ..shadow.signals import load_context
        g = ShadowGate(load_model(_shadow_model_path(p)), load_context(p.db_path, p.variants or None),
                       p.shadow_conf)
        _SHADOW_GATES.clear()
        _SHADOW_GATES[key] = g
    return g


def _group_members(gid) -> frozenset:
    from ..groups.registry import FLOW_GROUPS
    spec = FLOW_GROUPS.get(gid) if gid else None
    return spec.members if spec is not None else frozenset()


def _group_variant(gid) -> bool:
    from ..groups.registry import FLOW_GROUPS
    spec = FLOW_GROUPS.get(gid) if gid else None
    return spec is not None and spec.kind == "variant"


def _provisional_forms(gid) -> frozenset:
    from ..groups.registry import PROVISIONAL
    pv = PROVISIONAL.get(gid) if gid else None
    return pv.forms if pv is not None else frozenset()


def _follow_ref_veto(rec, pick, ref, g: dict) -> bool:
    """影子闸挑的字＝整理本字、放行字与它同属一个「兜底归整理本」同义组（`Provisional.follow_ref`：can 參㕘叅、ba 䟦跋、dian 點㸃𭶑）：
    sheldon 11-03 定「拆不开的格兜底放成整理本字」，而放行字是库首位（ref_lib 通道，不经字组补放，组流程复核只回 keep），
    影子一否决就降审。这里直接改成整理本字、不降审，证据记 `group.decision=provisional`、`follow_ref_veto`。
    整理本须是现役对位（缺位的坐标对位不算）；有分族的组（can 參／叅㕘）放行字与整理本须同族。→ 改了字 True。"""
    from ..groups.registry import PROVISIONAL
    gid = g.get("id") if g else None
    pv = PROVISIONAL.get(gid) if gid else None
    if pv is None or not pv.follow_ref or not pick or not ref or pick != ref or rec.char == ref:
        return False
    if rec.char not in pv.forms or ref not in (pv.forms | pv.ref_forms):
        return False
    if pv.fams and not any(rec.char in f and ref in f for f in pv.fams):
        return False
    old = rec.char
    rec.char = ref
    ev = dict(rec.evidence or {})
    ev["group"] = {**g, "decision": "provisional", "pick": ref, "why": "follow_ref_veto"}
    ev["follow_ref_veto"] = {"from": old, "to": ref}
    rec.evidence = ev
    return True


def _shadow_veto_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict, amap: dict) -> int:
    """影子放行闸（只降级）：把现行规则已放行、影子有把握说不对的格降回待审。→ 降级格数。

    放在所有通道与 `group_flow` 之后：只会把 admit 从 True 改 False，不改字、不升级。
    字组按文意定的字（通道 `group_flow`、provenance `context`）影子要改成同组另一个字时不降：形近字的库形本就分不开，
    影子挑的只是同一个难点的另一边（sheldon 10-22「文意置信度特别高可以改掉整理本」，vol09:251 改成曰后被影子降、
    又被 coord_fallback 按坐标放回日）。同义（异体）字组的流程已给字且与放行字相同（补放、复核同意或改字）时，影子挑同组
    另一个码位也不降：同义组里只差码位，由字组按刻形定（A24 10-25：參㕘叅 整理本作叅、刻形是㕘，影子照整理本降审 15 格）。字组补放时整字 HOG（`ids`）过门槛给了放行字的，影子挑同组另一个字也不降（形近组同理，vol16:42:4:3 傳）。
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
    book = getattr(ctx, "book", None)
    cbook = book if getattr(book, "codepoints", None) else None
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
            g = (rec.evidence or {}).get("group") or {}
            if (rec.channel == "group_flow" and rec.provenance == "context" and v.pick
                    and v.pick in _group_members(g.get("id"))):
                continue                      # 字组按文意定的字，影子只是挑了同组另一个字：形近本就分不开（vol09:251 曰）
            if (rec.channel == "group_flow" and v.pick and v.pick in _group_members(g.get("id"))
                    and any(t.get("solver") == "ids" and t.get("char") == rec.char and t.get("margin") for t in g.get("solvers") or [])):
                # 字组补放时整字 HOG 过了门槛给的字（按册留出 0 错），影子挑同组另一个字：不降。vol07–18 这样被降的形近组 8 格
                # 看图全是组对（傳傅 二一 會曾 子于 出山 山由 宋朱 間問），降审后 6 格又被坐标兜底按整理本放错（A24 10-25）
                continue
            if (v.pick and _group_variant(g.get("id")) and g.get("why") == "agree" and g.get("pick") == rec.char
                    and g.get("decision") in ("admit", "keep", "fix") and v.pick in _group_members(g.get("id"))):
                continue                      # 同义字组按刻形定了码位，影子挑同组另一个码位只是码位口径差（vol13–20 參㕘叅 15 格，A24 10-25）
            if (v.pick and g.get("decision") == "provisional" and g.get("pick") == rec.char
                    and v.pick in _provisional_forms(g.get("id"))):
                continue                      # 暂归一兜底定的字，影子挑同字的另一写法：写法本来就没拆（A24 10-27）
            if _follow_ref_veto(rec, v.pick, (amap.get(rec.id) or (None, None))[0], g):
                # 兜底归整理本字（sheldon 11-03，參㕘叅、䟦跋、點㸃𭶑）：影子挑的正是整理本字，改成它，不降审（第 4 轮）
                continue
            if (cbook is not None and v.pick and rec.char and v.pick != rec.char
                    and cbook.canonical_char(v.pick) == cbook.canonical_char(rec.char)):
                continue                      # 册 `codepoints:` 归一后同字（別别、晚晩、出岀）：影子比字没按册归一，不是认错
            if (vmap is not None and v.pick and rec.char and v.pick != rec.char
                    and not _rare_cp(rec.char)    # 放行字是罕用码位不弃权（#431：𠮓→變、𣼣→漏）
                    and vmap.semantic(v.pick) == vmap.semantic(rec.char)):
                continue                      # 异体同字：标签口径差，不是认错字（#431）
            _demote(rec, "shadow_veto")
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = _doubts(m, None) + list(rec.doubts) + ["shadow_veto"]
            rec.evidence = {**rec.evidence, "shadow_veto": v.evidence(gate.model, gate.conf, gate.low_conf)}
            n += 1
    return n


_JIAZHU_UNEVEN_RE = re.compile(r"jiazhu_uneven:(\d+)-(\d+)")


def _jiazhu_uneven_pass(ctx: RunContext, page: int, out: list, mmap: dict | None = None,
                        amap: dict | None = None, coord: dict | None = None) -> int:
    """雙行小注分法不均闸（只降级）。→ 降级格数。

    Step3 雙行小注逐步切（书级钩子 `impl/keben/jiazhu_step`，史記书仓覆盖）按整理本分法切、两行分法不是 ⌈N/2⌉／⌊N/2⌋ 的段，
    列旗记 `jiazhu_uneven:<首格>-<末格>`；段内的夹注格（sub a／b）送审，doubt 码 `jiazhu_uneven`、
    `evidence.seg_kind=jiazhu_uneven`（待审归 seg_defect，细分 jiazhu_uneven，review/reasons.py，A31 11-04 定）。
    已放行、且放行字＝字形库首选＝整理本字（三者一致，图上有字形证据）的格不降（第 10 轮整列送审 8 列 276 格、其中 210 格三者一致，11-04 收窄）。
    没有这面列旗（开关关、别的书）时什么都不做。备选格网（alt_columns）的列旗一并认：换了列的格也送审。人裁不动。"""
    cells = _opt(ctx, "cells", page)
    if cells is None:
        return 0
    spans: dict[int, list[tuple[int, int]]] = {}
    for cc in list(cells.columns) + list(getattr(cells, "alt_columns", None) or []):
        for fl in cc.flags or []:
            m = _JIAZHU_UNEVEN_RE.match(fl)
            if m:
                spans.setdefault(cc.col, []).append((int(m.group(1)), int(m.group(2))))
    if not spans:
        return 0
    n = 0
    for col in out:
        sp = spans.get(col.col)
        if not sp:
            continue
        for rec in col.chars or []:
            if rec.sub not in ("a", "b") or not any(a <= rec.slot <= b for a, b in sp):
                continue
            if rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.admit and _jiazhu_three_agree(rec, (mmap or {}).get(rec.id), amap or {}, coord or {}):
                continue                      # 放行字＝库首选＝整理本字：图上有字形证据说这格切对了，不降（第 10 轮 8 列 210 格，11-04）
            if "jiazhu_uneven" not in (rec.doubts or []):
                rec.doubts = list(rec.doubts or []) + ["jiazhu_uneven"]
            rec.evidence = {**(rec.evidence or {}), "seg_kind": "jiazhu_uneven"}
            if rec.admit:
                _demote(rec, "jiazhu_uneven")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
    return n


def _jiazhu_three_agree(rec, m, amap: dict, coord: dict) -> bool:
    """放行字、字形库首选、整理本字（现役对位，没有就坐标对位）三者相同。"""
    top = (m.candidates[0][0] if m is not None and m.candidates else None)
    ref = (amap.get(rec.id) or (None, None))[0] or coord.get(rec.id)
    return bool(rec.char) and top == rec.char and ref == rec.char


def _unbound_shifted(rec, h: dict, amap: dict) -> int | None:
    """`human_unbound_shift_ok` 的判据：旧人裁像是顺移到邻格的 → 顺移量；否则 None。"""
    if h.get("status") != "unanchored" or not h.get("char"):
        return None
    here = amap.get(rec.id)
    if not here or here[0] != rec.char or h["char"] == rec.char:
        return None
    head = rec.id.rpartition(":")[0]
    sub = rec.sub or ""
    for d in (-1, 1, -2, 2):
        nb = amap.get(f"{head}:{rec.slot + d}{sub}")
        if nb and nb[0] == h["char"]:
            return d
    return None


def _human_unbound_pass(ctx: RunContext, page: int, out: list, lost: dict,
                        amap: dict | None = None) -> int:
    """人裁绑丢闸（只降级，放在所有通道与各遍之后）。→ 降级格数。见 `SeedAdmitParams.human_unbound_review`。

    `lost`：`{原编号: {"char", "status", "event", ...}}`，绑定后不采信的人裁。本格放行的字与人裁不同 →
    退回待审；相同 → 照常放行。两种都在 evidence 上挂 `human_unbound`，没放行的格也挂（给审的人看旧裁决）。"""
    n = 0
    hits: list[str] = []
    for col in out:
        for rec in col.chars or []:
            h = lost.get(rec.id)
            if h is None or rec.provenance == "human" or rec.channel == "human":
                continue
            rec.evidence = {**(rec.evidence or {}),
                            "human_unbound": {k: h.get(k) for k in ("char", "status", "event")}}
            sh = _unbound_shifted(rec, h, amap) if (amap and rec.admit) else None
            if sh is not None:
                rec.evidence["human_unbound"]["shift_ok"] = sh
                continue
            if rec.admit and rec.char != h.get("char"):
                _demote(rec, "human_unbound")
                hits.append(f"{rec.id} 人裁「{h.get('char')}」/放行「{rec.char}」({h.get('status')})")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["human_unbound"]))
                n += 1
    if hits:
        _log.warning("seed_admit p%s: %d 格人裁绑丢、机器放行了别的字，已退回待审：%s",
                     page, len(hits), "；".join(hits))
        ctx.log(f"⚠ seed_admit p{page}: 人裁绑丢 {len(hits)} 格，机器放行的字与人裁不同，已退回待审"
                f"（doubt human_unbound）：{'；'.join(hits)}")
    return n


def _evict_review_pass(ctx: RunContext, page: int, out: list, cells: dict) -> int:
    """撤库重审闸（只降级）。→ 降级格数。见 `SeedAdmitParams.evict_review`。人裁过的格（channel/provenance=human）不拦。"""
    n = 0
    hits: list[str] = []
    for col in out:
        for rec in col.chars or []:
            h = cells.get(rec.id)
            if h is None or rec.provenance == "human" or rec.channel == "human":
                continue
            rec.evidence = {**(rec.evidence or {}), "evict_review": {k: h.get(k) for k in ("char", "event")},
                            "seg_kind": "evict_review"}
            rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["evict_review"]))
            if rec.admit:
                _demote(rec, "evict_review")
                hits.append(f"{rec.id}「{rec.char}」")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
    if hits:
        ctx.log(f"seed_admit p{page}: 撤库重审 {len(hits)} 格退回待审（doubt evict_review）：{'；'.join(hits)}")
    return n


_LIB_CHANNELS = ("match_", "dual", "iron")


def _symbol_ref_blank_pass(p: "SeedAdmitParams", out: list, mmap: dict, coord: dict) -> int:
    """符号字块遇整理本空格位（`symbol_ref_blank`）：库首位是册里点名的符号、cov 够、对位说此位是空格 → 放行为该符号（升）。
    → 新放行格数。放在 `symbol_review` 之后，把它降下去的那批圈号接回来。"""
    syms = frozenset(p.symbol_ref_blank)
    n = 0
    for col in out:
        col_cov = sum(1 for r in col.chars or [] if coord.get(r.id) is not None) if p.symbol_ref_gap else 0
        for rec in col.chars or []:
            if rec.provenance == "human" or rec.channel == "human":
                continue
            ds = {d for d in (rec.doubts or []) if isinstance(d, str)}
            if "occluded" in ds or "excluded" in ds or (rec.evidence or {}).get("occluded"):
                continue
            c0 = coord.get(rec.id)
            gap = c0 is None and p.symbol_ref_gap and col_cov >= p.symbol_ref_gap_min_col
            if c0 != "" and not gap:
                continue
            if rec.char and rec.char not in syms:
                continue
            m = mmap.get(rec.id)
            cands = list(getattr(m, "candidates", None) or [])
            if not cands or cands[0][0] not in syms or float(cands[0][1]) < (p.symbol_ref_gap_cov if gap else p.symbol_ref_blank_cov):
                continue
            sym, cov = cands[0][0], float(cands[0][1])
            _demote(rec, "symbol_ref_blank")
            ev = dict(rec.evidence or {})
            ev["lane"] = {"lane": "symbol_ref_blank", "lib": sym, "cov": round(cov, 4),
                          "prev_doubts": list(rec.doubts or []), **({"via": "gap"} if gap else {})}
            ev.pop("symbol", None)
            rec.evidence = ev
            rec.admit, rec.channel, rec.provenance, rec.char = True, "symbol_ref_blank", "match", sym
            rec.doubts = ["lane_symbol_ref_blank"]
            n += 1
    return n



def _symbol_review_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict,
                        human_shapes: dict) -> int:
    """特殊符号送审（只降级，放在各补放遍之后、human_unbound 之前）。→ 降级格数。见 `SeedAdmitParams.symbol_review`。"""
    from collections import Counter

    from .align_ref import rare_topk_map
    from ..hanzi.symbols import is_symbol
    rtop = rare_topk_map(_opt(ctx, "rare_candidates", page), 1)
    n_human = Counter(c for c in human_shapes.values() if is_symbol(c))
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            lib_top = getattr(m, "char", None) if m is not None else None
            rare_top = (rtop.get(rec.id) or [None])[0]
            hint = [c for c in (rec.char, lib_top, rare_top) if c and is_symbol(c)]
            if not hint:
                continue
            ch_ = rec.channel or ""
            if rec.admit and rec.char and is_symbol(rec.char):
                down = not (ch_.startswith(_LIB_CHANNELS) and n_human[rec.char] >= p.symbol_min_human)
            else:
                down = rec.admit and ch_.startswith("context")
            if down:
                _demote(rec, "symbol_review")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
            if not rec.admit:
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["symbol"]))
                rec.evidence = {**(rec.evidence or {}), "symbol": hint[0]}
    if n:
        ctx.log(f"seed_admit p{page}: 特殊符号送审 {n} 格（doubt symbol）")
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
_LANE_HARD = frozenset({"context_blank_cell", "context_tall_cell", "form_open", "approx_exemplar", "glyph_timeout",
                        # 字组流程复核时文意明确给了别的字（或解法互相冲突）而降审的格：待审补放通道不许再放回去
                        # （vol04：象彖复核降审的格被 coord_fallback 按整理本字又放行，降审白降）
                        "group_flow_disagree", "group_flow_conflict",
                        # 补放时文意给了与整理本不同的字、没放成的格（`flow.group_flow_pass`）：同理不许按整理本字放回
                        "group_flow_ctx_contra",
                        # 库判 diff 拦下的 ref_lib 格：整理本字正是被库否掉的那个，补放通道不按它放回
                        "ref_lib_diff",
                        # match_ref 库判 diff 拦下的格（`match_ref_diff_guard`）：同理
                        "match_ref_diff",
                        # 坐标对位与现役对位不一致拦下的 ref_lib 格（`ref_lib_coord_dissent`）：同理
                        "ref_lib_coord_dissent",
                        # 坐标对位与 match_solo 系放行字不一致拦下的格（`solo_coord_dissent`）：同理
                        "solo_coord_dissent"})
#: R1/R4 另外不碰的：context 乱码护栏拦下过格的**整列**（overview#427：列切窄、整列字块是
#: 笔画残边，证人字再齐也对不上图——vol04 p217c3 只有 2 格带这个码，同列其余 4 格看图同样是乱码）。
_LANE_GARBLE = frozenset({"ctx_garble_shape", "ctx_garble_rare"})
#: `lane_keep_ref_review` 开着时 R1/R4/R5 不碰的：护栏已拿整理本字比过、判定该人看的格。
_LANE_REF_REVIEW = frozenset({"ctx_guard_ref", "group_flow_ref_dissent", "group_flow_coord_dissent"})


def _lane_class(doubts, evidence: dict | None, char, ref_char, lib_top) -> str:
    """待审格归哪一类——`review.cards.card_class` 的镜像（见 `_LANE_CLS_CODES`）。"""
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    codes = {d for d in ds if re.match(r"^[a-z][a-z0-9_]*$", d)}
    ev = evidence or {}
    if "occluded" in codes or ev.get("occluded"):
        return "occluded"
    if ev.get("ji_yi_si") or any(c and c in _JYS for c in (char, ref_char, lib_top)):
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


def _group_img_dissent(group: dict | None, char: str, min_p: float) -> dict | None:
    """`lane_group_img_veto` 的判据，纯函数：字组流程里**图像判官**（solver 名以 `_img` 结尾，现只有人入八组的
    `rr_img`）给了字、与要放的字不同、自己那个字的概率 ≥ `min_p` → {solver, img, p}；否则 None。
    group 缺、判官弃权、没给概率、或判官同意要放的字 → None（不拦）。"""
    for s in (group or {}).get("solvers") or []:
        name, ch = str(s.get("solver") or ""), s.get("char")
        if not name.endswith("_img") or not ch or ch == char:
            continue
        pr = (s.get("probs") or {}).get(ch)
        if pr is not None and float(pr) >= min_p:
            return {"solver": name, "img": ch, "p": round(float(pr), 3)}
    return None


def _lane_witnesses(book, p: "SeedAdmitParams") -> list:
    """R1/R4 用的证人（质量降序，`steps.align_ref` 那份进程级缓存），全部用（原 `lane_witnesses` 筛选无书用，2026-11-23 删）。"""
    from .align_ref import _witnesses_for_book
    return list(_witnesses_for_book(book))


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
            _demote(rec, "seal_blank_flip")
            rec.admit, rec.channel, rec.char, rec.provenance = False, None, None, ""
            rec.doubts = sorted(doubts | {"occluded"})
            rec.evidence = {**(rec.evidence or {}),
                            "occluded": {"via": "coord_blank", "ref_blank": True,
                                         "seal_blank": hit["seal_score"], "overlap": hit["overlap"]}}
    return demoted


def _parse_pua_rules(spec: str) -> dict[str, str]:
    """`pua_rules` → {库首位字: 录入字}。纯函数；空项、多字项跳过。"""
    out: dict[str, str] = {}
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        lib, _, to = item.partition("=")
        lib, to = lib.strip(), (to.strip() or lib.strip())
        if len(lib) == 1 and len(to) == 1:
            out[lib] = to
    return out


def _pua_rule_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict) -> int:
    """整理本缺字特殊规则（`pua_rules`）。→ 放行格数。

    只升不降：只碰 admit=False、非人裁、不在排除名单、没有硬疑问（`_LANE_HARD`）、不是印章区的格。
    条件：整理本这一位是 〓（坐标对位字，没有坐标对位时看现役对位字）；库首位字在表里、cov ≥ `pua_rule_cov`、
    库没判 diff、没有护栏（never_match／conflict）。字取表里的录入字，通道 `pua_rule`。"""
    rules = _parse_pua_rules(p.pua_rules)
    if not rules:
        return 0
    n = 0
    for col in out:
        for rec in col.chars or []:
            ds = set(rec.doubts or [])
            if (rec.admit or rec.channel == "human" or rec.provenance == "human"
                    or "excluded" in ds or "occluded" in ds or ds & _LANE_HARD):
                continue
            ref = coord.get(rec.id)
            if ref is None:
                ref = (amap.get(rec.id) or (None,))[0]
            if not is_gap(ref):
                continue
            m = mmap.get(rec.id)
            if not m or not m.candidates or getattr(m, "guard", None) is not None:
                continue
            if getattr(m, "verdict", None) == "diff":
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            char = rules.get(top)
            if char is None or cov < p.pua_rule_cov:
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "pua_rule", "pua_rule", char
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "pua_rule", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_pua_rule"]
            n += 1
    return n


#: `reference_trust` 各项的书无关默认：字形路 ids 反对、字＝参校字时不降审的组（看图核对过的写本形错判与同义异体）；
#: 解法全弃权时按参校本走的组；字组补放字形路给参校字就放的组；库首位放行的 cov 下限与对手差。
REFERENCE_TRUST_COV = 0.90
REFERENCE_TRUST_GAP = 0.005
#: `reference_trust` 的库首位放行不碰的字：有专门解法（字组流程）的几族——日曰目、己已巳、入人八、一二。
def _is_han(c) -> bool:
    """整理本字是不是汉字（CJK 各区、兼容区、私用区——私用码是整理本里的造字，仍算字）。缅文、拉丁、符号等 → False：
    这类对位多半是对位错位或版面符号，不能拿来当「整理本字」放行（史記 r12，03:114:2:20 参校字 ခ、库首位 六）。"""
    if not c or len(c) != 1:
        return False
    o = ord(c)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3FFFF
            or 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0x10FFFF or 0x2E80 <= o <= 0x2FDF)


_REF_LIB_COORD_SKIP = frozenset("日曰目己已巳入人八一二")
#: `ref_lib_coord` 认的疑问（白名单，别的一律不碰）：库不确定／上下文不足、整理本护栏、字组只弃权或只有分歧、人裁绑丢（另判）。
_REF_LIB_COORD_DOUBTS = ("库 unsure", "库 same 但准入被拦", "上下文 margin 不足", "near_form", "ctx_guard_ref",
                         "context_variant_form", "group_flow_abstain", "group_flow_joint", "group_flow_ref_dissent",
                         "group_flow_coord_dissent", "human_unbound", "lane_coord_fallback", "context_page_end")


#: `ref_topk_follow`：整理本字在库前 5 名候选里、与首位 cov 差不超过这个数才按整理本放。
REFERENCE_TRUST_TOPK_GAP = 0.05


def ref_topk_decide(*, char, ref, cands, verdict, guard, doubts, evidence, semantic, shape_ok=frozenset(),
                    gap_max: float = REFERENCE_TRUST_TOPK_GAP) -> int:
    """`ref_topk_follow` 的判据，纯函数。待审格：库首位≠整理本字、整理本字在前 5 名且 cov 差 ≤ `gap_max` →
    返回整理本字在候选里的名次（2–5），否则 0。"""
    if not char or not ref or is_gap(ref) or char == ref or char in _REF_LIB_COORD_SKIP or ref in _REF_LIB_COORD_SKIP:
        return 0
    if char in _JYS or ref in _JYS or guard is not None or verdict == "diff" or not cands:
        return 0
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    if any(not d.startswith(_REF_LIB_COORD_DOUBTS) for d in ds):
        return 0
    names = [c for c, _v in cands[:5]]
    if ref not in names or names[0] == ref:
        return 0
    if float(cands[0][1]) - float(cands[names.index(ref)][1]) > gap_max:
        return 0
    ev = evidence or {}
    h = ev.get("human_unbound")
    if h and h.get("char") != ref:
        return 0
    g = ev.get("group") or {}
    for t in g.get("solvers") or []:
        c = t.get("char")
        if c and c != ref and not (str(t.get("solver", "")) == "ids" and (semantic(c) == semantic(ref)
                                                                         or g.get("id") in shape_ok)):
            return 0
    return names.index(ref) + 1


def _ref_topk_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, vmap) -> int:
    """`ref_topk_follow`：库首位是形近字、整理本字在前 5 名且 cov 接近 → 按整理本放。→ 放行格数。"""
    n = 0
    ok_groups = p._rt_shape_ref_ok()
    for col in out:
        hit = tot = 0
        for r in col.chars or []:
            if r.admit and r.char:
                rf = coord.get(r.id) or (amap.get(r.id) or (None,))[0]
                if rf and not is_gap(rf):
                    tot += 1
                    hit += r.char == rf
        if not (tot >= 3 and hit / tot >= 0.8):
            continue
        for rec in col.chars or []:
            if rec.admit or rec.channel == "human" or rec.provenance == "human":
                continue
            ds = set(rec.doubts or [])
            if "excluded" in ds or "occluded" in ds:
                continue
            ref = coord.get(rec.id) or (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if not m or not ref:
                continue
            rank = ref_topk_decide(char=rec.char, ref=ref, cands=list(m.candidates or []),
                                   verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                   doubts=rec.doubts, evidence=rec.evidence, semantic=vmap.semantic,
                                   shape_ok=ok_groups)
            if not rank:
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            rec.char = ref
            rec.admit, rec.channel, rec.provenance = True, "ref_lib_coord", "match"
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "ref_lib_coord", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "topk_rank": rank, "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_ref_lib_coord"]
            n += 1
    return n


def ref_lib_coord_decide(*, char, ref, cands, verdict, guard, doubts, evidence, semantic, cov_min: float,
                         gap_min: float, shape_ok=frozenset(), blind_ok: bool = False,
                         blind_cov_max: float = 0.975) -> bool:
    """`ref_lib_coord` 的判据，纯函数（离线回放与线上共用）。待审格是否按整理本字放行。
    `blind_ok`（调用方已验过本列对位健康）：库首位不是整理本字、但格带 `ctx_guard_ref`（库认不出、文意又与整理本不同）、
    库首位 cov < `blind_cov_max`（库没有强烈说是别的字）→ 也按整理本放。"""
    if not char or not ref or is_gap(ref) or char != ref or char in _REF_LIB_COORD_SKIP or char in _JYS or not _is_han(ref):
        return False
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    if any(not d.startswith(_REF_LIB_COORD_DOUBTS) for d in ds):
        return False
    if guard is not None or verdict == "diff" or not cands:
        return False
    top = float(cands[0][1])
    if cands[0][0] != ref:
        if not (blind_ok and "ctx_guard_ref" in ds and top < blind_cov_max):
            return False
    else:
        if top < cov_min:
            return False
        if any(semantic(c) != semantic(ref) and top - float(v) < gap_min for c, v in cands[1:6]):
            return False
    ev = evidence or {}
    h = ev.get("human_unbound")
    if h and h.get("char") != char:
        return False
    g = ev.get("group") or {}
    for t in g.get("solvers") or []:
        c = t.get("char")
        if c and c != char and not (str(t.get("solver", "")) == "ids" and (semantic(c) == semantic(ref)
                                                                         or g.get("id") in shape_ok)):
            return False
    return True


def _ref_lib_coord_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, vmap) -> int:
    """按整理本放行：坐标对位字（没有时看现役对位字）＝库首位＝本格字（`ref_lib_coord`）。→ 放行格数。判据见 `ref_lib_coord_decide`。"""
    n = 0
    ok_groups = p._rt_shape_ref_ok()
    if p._rt_rank() >= 1:
        cov_min, gap_min = REFERENCE_TRUST_COV, REFERENCE_TRUST_GAP
    else:                                    # 只开 `ref_lib_coord`（殿本）：用它自己更严的门槛
        cov_min, gap_min = p.ref_lib_coord_cov, p.ref_lib_coord_gap
    for col in out:
        blind_ok = False
        if p._rt_rank() >= 2:
            # 本列对位健康：列内已放行格里字＝整理本字的占比 ≥ 0.8（至少 3 格）——坐标对位没有整体错位
            hit = tot = 0
            for r in col.chars or []:
                if r.admit and r.char:
                    rf = coord.get(r.id) or (amap.get(r.id) or (None,))[0]
                    if rf and not is_gap(rf):
                        tot += 1
                        hit += r.char == rf
            blind_ok = tot >= 3 and hit / tot >= 0.8
        for rec in col.chars or []:
            if rec.admit or rec.channel == "human" or rec.provenance == "human":
                continue
            ds = set(rec.doubts or [])
            if "excluded" in ds or "occluded" in ds:
                continue
            ref = coord.get(rec.id)
            if not ref:
                ref = (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if not m or not ref:
                continue
            if not ref_lib_coord_decide(char=rec.char, ref=ref, cands=list(m.candidates or []),
                                        verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                        doubts=rec.doubts, evidence=rec.evidence, semantic=vmap.semantic,
                                        cov_min=cov_min, gap_min=gap_min,
                                        shape_ok=ok_groups, blind_ok=blind_ok):
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            rec.admit, rec.channel, rec.provenance = True, "ref_lib_coord", "match"
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "ref_lib_coord", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     **({"blind": True} if top != ref else {}),
                                     "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_ref_lib_coord"]
            n += 1
    return n


#: 1：`follow_ref` 表里有整理本形、本格字不是表里那一形时，仍按参校本取异体（cv#1438）。


def _parse_follow_ref(spec: str) -> dict[str, str]:
    """`follow_ref` → {整理本形: 库里另一形}。纯函数；空项、不是「单字=单字」的项跳过。"""
    out: dict[str, str] = {}
    for item in (spec or "").split(","):
        a, _, b = item.strip().partition("=")
        a, b = a.strip(), b.strip()
        if len(a) == 1 and len(b) == 1 and a != b:
            out[a] = b
    return out


def follow_ref_decide(*, admit: bool, channel, char, doubts, ref, cands, verdict, guard, ctx_char,
                      rules: dict, cov_min: float, gap_min: float, allow_occluded: bool = False,
                      rival_skip: frozenset = frozenset()) -> str | None:
    """`follow_ref` 的判据，纯函数（离线回放与线上共用）。→ "fix"（已放行格改回整理本形）、"admit"（待审格放行整理本形）或 None。
    `rival_skip`：算领先差时不当对手的字（书级钩子 `impl/keben/follow_ref_hooks.rival_skip` 给，缺省空＝只排除这一对）。"""
    other = rules.get(ref) if ref else None
    if other is None or channel == "human":
        return None
    if admit:
        return "fix" if char == other else None
    ds = set(doubts or [])
    if allow_occluded:                       # `occluded_variant_first`：异体规则先于印章
        ds.discard("occluded")
        doubts = [d for d in (doubts or []) if d != "occluded"]
    if "excluded" in ds or "occluded" in ds or ds & _LANE_HARD or ds & _LANE_GARBLE or _hard_blocked(doubts or [], guard):
        return None
    if verdict == "diff" or not cands:
        return None
    pair = {ref, other}
    top, cov = cands[0][0], float(cands[0][1])
    if top not in pair or cov < cov_min:
        return None
    rival = max((float(c) for ch, c in cands if ch not in pair and ch not in rival_skip), default=0.0)
    if cov - rival < gap_min:
        return None
    if ds & _LANE_REF_REVIEW and ctx_char not in pair:
        return None
    return "admit"


#: `follow_ref_seen` 仍然不碰的硬疑问：遮挡／排除、乱码、字组解法或文意明确给了别的字（不是弃权）、库判 diff 的 ref_lib 格
_SEEN_HARD = frozenset({"excluded", "occluded"}) | _LANE_HARD | _LANE_GARBLE


def _parse_follow_ref_seen(spec: str) -> dict[str, frozenset]:
    """`follow_ref_seen` → {整理本形: {库里的另几形}}（同一整理本形可以对多个，如 永=氷,永=未）。"""
    out: dict[str, set] = {}
    for item in (spec or "").split(","):
        a, _, b = item.strip().partition("=")
        a, b = a.strip(), b.strip()
        if len(a) == 1 and len(b) == 1 and a != b:
            out.setdefault(a, set()).add(b)
    return {k: frozenset(v) for k, v in out.items()}


def seen_pair_decide(*, admit: bool, channel, char, doubts, ref, cands, verdict, guard, rules: dict,
                     cov_min: float, gap_min: float, allow_conflict: bool = False) -> str | None:
    """`follow_ref_seen` 的判据，纯函数。→ "admit"｜None。只管待审格；与 `follow_ref_decide` 的区别是不拦 near_form、
    group_flow_abstain、上下文 margin 不足、replace_align 这类「没有人给出别的字」的疑问。
    `rules`：{整理本形: {库里的另几形}}；库首位须是整理本形或其中一形，领先对外（整理本形、核实过的另几形之外）最好候选 ≥ gap_min。"""
    others = rules.get(ref) if ref else None
    if not others or admit or channel == "human":
        return None
    ds = set(doubts or [])
    pair = {ref} | set(others)
    if allow_conflict and guard == "conflict" and len(cands) >= 2 and len(pair) == 2 and {cands[0][0], cands[1][0]} == pair:
        ds = ds - {"护栏:conflict"}                # 两字字形一样、都判 same：交给整理本文意（`follow_ref_seen_conflict`）
        guard = None
    if ds & _SEEN_HARD or any(isinstance(d, str) and d.startswith("护栏:") for d in ds) or guard in ("never_match", "conflict", "timeout"):
        return None
    if verdict == "diff" or not cands:
        return None
    top, cov = cands[0][0], float(cands[0][1])
    if top not in pair or cov < cov_min:
        return None
    rival = max((float(c) for ch, c in cands if ch not in pair), default=0.0)
    if cov - rival < gap_min:
        return None
    return "admit"


class _RivalFacts:
    """交给书级钩子 `follow_ref_hooks.rival_skip` 的关系层查询（书级代码不许 import cv 内部模块，事实由这里给）。

    `facts(a, b)` → `_PairFacts`；`facts.semantic(ch)` → 同义归并后的字（`follow_ref_variants` 的 vmap，没开时原字）。"""
    __slots__ = ("_vmap",)

    def __init__(self, vmap):
        self._vmap = vmap

    def semantic(self, ch: str) -> str:
        return self._vmap.semantic(ch) if self._vmap is not None else ch

    def __call__(self, a: str, b: str) -> "_PairFacts":
        return _pair_facts(a, b, self.semantic(a) == self.semantic(b))


@dataclass(frozen=True)
class _PairFacts:
    """一对字的关系层事实（只读）。

    - `same_semantic`：同义归并后相同（`follow_ref_variants` 的 vmap）；
    - `tier`／`sources`／`n_bridge`／`never_only`／`is_variant`：边表 `variants.variant_edge`（T1 纯异体、T2 互通·一对多、
      T3 通假·形近·简繁、None 无边；`n_bridge` 异体字典来源数）；
    - `never`：人工审定永不并组（`config/variants/never_group.json`）；
    - `edge_excluded`：本书假边表（`config/variants/edge_pair_exclude.tsv`）；
    - `groups`：两字同在的字组 `((组 id, kind), …)`，kind＝"variant"｜"near_form"（`groups.registry.FLOW_GROUPS`）。"""
    same_semantic: bool
    tier: str | None
    sources: tuple
    n_bridge: int
    never_only: bool
    is_variant: bool
    never: bool
    edge_excluded: bool
    groups: tuple


@lru_cache(maxsize=65536)
def _pair_facts(a: str, b: str, same_semantic: bool) -> _PairFacts:
    from ..variants import variant_edge
    from ..groups.registry import FLOW_GROUPS
    e = variant_edge(a, b)
    groups = tuple(sorted((gid, getattr(g, "kind", "") or "") for gid, g in FLOW_GROUPS.items()
                          if a in g.members and b in g.members))
    return _PairFacts(same_semantic=same_semantic, tier=e.tier, sources=tuple(e.sources), n_bridge=e.n_bridge,
                      never_only=e.never_only, is_variant=e.is_variant, never=frozenset((a, b)) in _never_pairs(),
                      edge_excluded=_edge_pair_excluded(a, b), groups=groups)


@lru_cache(maxsize=1)
def _never_pairs() -> frozenset:
    from ..clustering.variants import never_group_pairs
    return never_group_pairs()


def _follow_ref_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, dmap: dict,
                     vmap=None, rival_hook=None) -> int:
    """照录整理本的异体对（`follow_ref`）。→ 新放行格数（改字的格不计数）。判据见 `follow_ref_decide`。
    `vmap` 给了（`follow_ref_variants`）：表里没有的整理本字，与本格字（已放行字／库首位）同义异体的也按一对处理。
    `rival_hook`：书级钩子 `follow_ref_hooks.rival_skip`（缺省 None＝不调），只对待审格调，见该模块。"""
    rules = _parse_follow_ref(p.follow_ref) if p.follow_ref else {}
    seen = _parse_follow_ref_seen(p.follow_ref_seen) if p.follow_ref_seen else {}
    if not rules and not seen and vmap is None:
        return 0
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.provenance == "human":
                continue
            if ((rec.evidence or {}).get("lane") or {}).get("variant_rank") == "hook":
                continue        # 书级钩子 variant_rank 按刻形放的字（史記 圗兾凢来，Sheldon 11-16）：别再按整理本改回去
            ref = coord.get(rec.id)
            if not ref:
                ref = (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if ref in seen and not rec.admit and m is not None:
                if seen_pair_decide(admit=rec.admit, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=list(m.candidates or []), verdict=getattr(m, "verdict", None),
                                    guard=getattr(m, "guard", None), rules=seen,
                                    cov_min=p.follow_ref_cov, gap_min=p.follow_ref_gap,
                                    allow_conflict=p.follow_ref_seen_conflict) == "admit":
                    top, cov = m.candidates[0][0], float(m.candidates[0][1])
                    rec.admit, rec.channel, rec.provenance, rec.char = True, "follow_ref", "match", ref
                    rec.evidence = {**(rec.evidence or {}),
                                    "lane": {"lane": "follow_ref", "lib": top, "cov": round(cov, 4), "ref": ref, "via": "seen",
                                             "prev_doubts": list(rec.doubts or [])}}
                    rec.doubts = ["lane_follow_ref"]
                    n += 1
                    continue
            m = mmap.get(rec.id)
            here, via = rules, None
            if ref not in rules or (vmap is not None and not is_gap(ref)):
                # 表里没有这个整理本形：按参校本取异体（`follow_ref_variants`）。表里有、但本格的字不是表里那一形
                # （史記 r45：表加了 嵗=歳，嵗 的格放行字是 歲，表路只认 歳 不改）时同样走这条路，别让表项接管。
                if vmap is None or not ref or is_gap(ref):
                    continue
                other = rec.char if rec.admit else ((m.candidates or [(None,)])[0][0] if m else None)
                if ref in rules and (not other or other == rules[ref]):
                    pass                                   # 就是表里那一形：表路照旧
                elif not other or other == ref or vmap.semantic(other) != vmap.semantic(ref):
                    continue
                else:
                    here, via = {ref: other}, "variants"
            d = dmap.get(rec.id)
            cov_min, gap_min = p.follow_ref_cov, p.follow_ref_gap
            skip: frozenset = frozenset()
            if rival_hook is not None and not rec.admit and m is not None and rec.channel != "human" and ref in here:
                cands_l = [(ch, float(c)) for ch, c in (m.candidates or [])]
                got = rival_hook(ref=ref, lib=here[ref], cands=cands_l, via=via, facts=_RivalFacts(vmap))
                skip = frozenset(got or ()) - {ref, here[ref]}
            act = follow_ref_decide(admit=rec.admit, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=list(m.candidates or []) if m else [], verdict=getattr(m, "verdict", None),
                                    guard=getattr(m, "guard", None), ctx_char=getattr(d, "char", None), rules=here,
                                    cov_min=cov_min, gap_min=gap_min,
                                    allow_occluded=True, rival_skip=skip)
            if act == "fix":
                rec.evidence = {**(rec.evidence or {}), "follow_ref": {"from": rec.char, "ref": ref,
                                                                       **({"via": via} if via else {})}}
                rec.char = ref
            elif act == "admit":
                top, cov = m.candidates[0][0], float(m.candidates[0][1])
                rec.admit, rec.channel, rec.provenance, rec.char = True, "follow_ref", "match", ref
                rec.evidence = {**(rec.evidence or {}),
                                "lane": {"lane": "follow_ref", "lib": top, "cov": round(cov, 4), "ref": ref,
                                         **({"via": via} if via else {}),
                                         **({"rival_skip": hit} if (hit := sorted({ch for ch, _ in m.candidates or []
                                                                                   if ch in skip})) else {}),
                                         "prev_doubts": list(rec.doubts or [])}}
                rec.doubts = ["lane_follow_ref"]
                n += 1
    return n


def _edge_pair_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, dmap: dict) -> int:
    """异体边表自动暂归一（`edge_pair`）。→ 新放行格数。判据＝`follow_ref_decide`（待审格一支），对子由 `edge_pairs.is_auto_pair` 认。"""
    from ..groups.edge_pairs import is_auto_pair, pair_to, seam_pair
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            ref = coord.get(rec.id) or (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            cands = list(m.candidates or []) if m else []
            if not ref or not cands:
                continue
            top, cov = cands[0][0], float(cands[0][1])
            if ref == top:
                continue
            gap_min, seam = p.edge_pair_gap, None
            if not is_auto_pair(ref, top):
                if not p.edge_pair_group_seam or (rec.evidence or {}).get("group"):
                    continue
                if p.replace_form == "review" and "replace_form" in (rec.doubts or []):
                    continue                     # 书要求改字层异体一律人审：补缝不越过
                seam = seam_pair(ref, top)
                if seam is None:
                    continue
                if seam == "near_form":
                    gap_min = max(gap_min, p.edge_pair_group_seam_nf_gap)
            d = dmap.get(rec.id)
            act = follow_ref_decide(admit=False, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=cands, verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                    ctx_char=getattr(d, "char", None), rules={ref: top},
                                    cov_min=p.edge_pair_cov, gap_min=gap_min,
                                    allow_occluded=True)
            if act != "admit":
                continue
            to = top if p.edge_pair_to == "lib" else ref if p.edge_pair_to == "ref" else pair_to(ref, top, lib_top=top)
            rec.admit, rec.channel, rec.provenance, rec.char = True, "edge_pair", "match", to
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "edge_pair", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "prev_doubts": list(rec.doubts or [])},
                            "edge_pair": {"decision": {"lib": "keben", "ref": "ref"}.get(p.edge_pair_to, "provisional"),
                                          "pair": [ref, top], "to": to,
                                          **({"seam": seam} if seam else {})}}
            rec.doubts = ["lane_edge_pair"]
            n += 1
    return n


def _header_formula_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list) -> int:
    """`lane_header_formula`：题列（列旗 `header_ref:<整理本行>`）整行是套语、字格数＝字数 → 未放行的格按整理本行逐字放行。→ 放行格数。"""
    cells = _opt(ctx, "cells", page)
    if cells is None:
        return 0
    formula = re.compile(p.lane_header_formula_re)
    lines: dict[int, str] = {}
    for cc in cells.columns:
        # 列端有格被判成框线／碎墨记空（layout_frame_junk）＝这一列格位与字对不上，数字数靠不住
        if any(fl.startswith("layout_frame_junk") for fl in cc.flags or []):
            continue
        for fl in cc.flags or []:
            if fl.startswith("header_ref:") and formula.fullmatch(fl[len("header_ref:"):]):
                lines[cc.col] = fl[len("header_ref:"):]
    n = 0
    for col in out:
        line = lines.get(col.col)
        if not line:
            continue
        recs = [r for r in (col.chars or []) if "excluded" not in (r.doubts or []) or r.char]
        try:
            recs.sort(key=lambda r: int(str(r.id).split(":")[3].rstrip("ab")))
        except (IndexError, ValueError):
            continue
        if len(recs) != len(line):
            continue
        # 已放行的格与整理本行同位字不一致：个别格是机器放错（一/二、九/十 近形，目錄页题列常见），按整理本改；
        # 超过三分之一不一致＝整列错位（字数碰巧相等），整列不动。人裁的格不碰。
        conflicts = sum(1 for r, ch in zip(recs, line)
                        if r.admit and r.char and r.char != ch and r.channel != "human" and r.provenance != "human")
        if conflicts * 3 > len(recs):
            continue
        for rec, ch in zip(recs, line):
            if rec.channel == "human" or rec.provenance == "human" or (rec.admit and rec.char == ch):
                continue
            ev = rec.evidence or {}
            prev_char, prev_admit = rec.char, rec.admit
            rec.admit, rec.channel, rec.provenance, rec.char = True, "header_formula", "align", ch
            rec.evidence = {**ev, "lane": {"lane": "header_formula", "line": line, "prev_admit": prev_admit,
                                           "prev_doubts": list(rec.doubts or []), "prev_char": prev_char},
                            "no_glyph_lib": True}
            rec.doubts = ["lane_header_formula"]
            n += 1 if not prev_admit else 0
    return n


def _witness3_knn_veto_fn(p, ctx, page: int):
    """`witness3_knn_veto` 的判官：(栏, 格, 库首位, 整理本字) → 否决证据 dict 或 None（不否决）。见该参数说明。"""
    from ..groups import near_knn
    from ..groups.registry import FLOW_GROUPS
    model = near_knn.load(p.group_flow_near_knn)
    skip_sets = [frozenset(FLOW_GROUPS[g].members) for g in model["skip_groups"] if g in FLOW_GROUPS]

    def veto(col, rec, lib, ref):
        if not lib or not ref or lib == ref or {lib, ref} & model["skip_chars"]:
            return None
        if any(lib in m and ref in m for m in skip_sets):
            return None
        try:
            img = _page_patch(ctx, page, col, rec.slot, rec.sub)
        except PatchUnavailable:
            return None
        v = near_knn.judge(img, model, [lib, ref])
        if (v.get("pick") == lib and v["votes"] >= model["votes_min"] - 1 and v["full"] == lib
                and v["full_votes"] >= model["full_votes_min"] and v["nn"] <= model["guard"]):
            return {k: v[k] for k in ("pick", "votes", "ratio", "full", "full_votes", "nn")}
        return None
    return veto


def _blind_ref_behind(m, co: str, top_cov: float, gap: float) -> bool:
    """库首位 cov ≥ top_cov，参校字 co 在候选里且比首位低 ≥ gap（`lane_coord_blind_guard`）。"""
    cs = list(getattr(m, "candidates", None) or [])
    if not cs or float(cs[0][1]) < top_cov:
        return False
    sc = next((float(v) for c, v in cs if c == co), None)
    return sc is not None and float(cs[0][1]) - sc >= gap


def _review_lanes_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict,
                       vmap, witnesses_fn, canon=None, lib_n: dict | None = None, knn_veto=None,
                       variant_hook=None, rank_hook=None) -> int:
    """待审补放三通道（`lane_witness3`／`lane_coord`／`lane_seal`，overview#433）。→ 放行格数。

    `variant_hook`：书级钩子 `follow_ref_hooks.variant_norm`（缺省 None＝不调），`lane_variant_guard` 内建例外都不放时
    最后问一次，见该模块。`rank_hook`：书级钩子 `follow_ref_hooks.variant_rank`（缺省 None＝不调），`variant_hook`
    也不放时再问一次。
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

    from ..groups.registry import GROUPS
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)

    def keep_rare(name, char, lib, co, lev) -> bool:
        """`lane_variant_keep_rare`：放的字＝坐标对位字＝库首位，且是少见异体、不属任何字组。"""
        return bool(name == "coord_fallback" and lev.get("via") == "lib_coord_primary"
                    and char and char == lib == co and sem(char) != char and char not in group_chars)

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
    formula = re.compile(p.lane_seal_title_formula) if p.lane_seal and p.lane_seal_title_formula else None
    title_norm = dict(zip(p.lane_seal_title_norm[0::2], p.lane_seal_title_norm[1::2]))
    title_cols, formula_cols = set(), set()
    title_bad: dict[int, set] = {}          # 题列容错：列号 → 与套语前缀不一致的格 id（不放）
    tol, pre = p.lane_seal_title_tolerance, p.lane_seal_title_prefix
    if p.lane_seal and (marks or formula):
        for col in out:
            srt = sort_by_reading(col.chars or [])
            s = "".join(coord.get(r.id) or "" for r in srt)
            if formula is not None and formula.fullmatch(s):
                formula_cols.add(col.col)
            elif (formula is not None and tol > 0 and pre and len(s) > len(pre)
                  and all(coord.get(r.id) for r in srt[:len(pre)])
                  and 0 < sum(a != b for a, b in zip(s, pre)) <= tol
                  and formula.fullmatch(pre + s[len(pre):])):
                formula_cols.add(col.col)
                title_bad[col.col] = {r.id for r, a, b in zip([r for r in srt if coord.get(r.id)], s, pre) if a != b}
            elif any(mk in s for mk in marks):
                title_cols.add(col.col)
    page_shift = p.lane_seal and _seal_page_shifted(out, mmap)

    garble_cols = {col.col for col in out for r in (col.chars or []) if set(r.doubts or []) & _LANE_GARBLE}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if (rec.admit or rec.channel == "human" or rec.provenance == "human"
                    or "excluded" in (rec.doubts or []) or set(rec.doubts or []) & _LANE_HARD
                    or set(rec.doubts or []) & _LANE_REF_REVIEW):
                continue
            al = amap.get(rec.id)
            ref, op = (al[0], al[1]) if al else (None, None)
            co = coord.get(rec.id)
            if is_gap(co):                       # 逐列本的 PUA 生僻字占位：知道有字、不知道是哪个
                co = None
            lib = lib_top_of(rec.id)
            ev = rec.evidence or {}
            occ = ev.get("occluded")
            hit = None                           # (通道, 字, 证据)
            if occ:
                if not p.lane_seal or (rec.char and rec.char in _JYS):
                    continue
                if page_shift:
                    rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "page_shift"}}
                    continue
                if col.col in formula_cols and rec.id in title_bad.get(col.col, ()):
                    rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "title_mismatch"}}
                    continue
                if col.col in formula_cols and rec.char:
                    ch = title_norm.get(rec.char, rec.char)
                    lev = {"via": occ.get("via"), "title_formula": True}
                    if ch != rec.char:
                        lev["norm_from"] = rec.char
                    rec.admit, rec.channel, rec.provenance, rec.char = True, "seal", "seal", ch
                    rec.evidence = {**ev, "lane": {"lane": "seal", **lev, "prev_doubts": list(rec.doubts or [])},
                                    "no_glyph_lib": True}
                    rec.doubts = ["lane_seal"]
                    n += 1
                    continue
                if col.col in title_cols:
                    continue
                if occ.get("via") == "coord_blank" and occ.get("ref_blank") and rec.char is None:
                    hit = ("seal", None, {"via": "coord_blank", "nonchar": True})
                elif rec.char and occ.get("via") in seal_vias:
                    hit = ("seal", rec.char, {"via": occ.get("via")})
                if hit is not None and hit[1] and p.lane_seal_lib_veto:
                    m = mmap.get(rec.id)
                    top = (m.candidates[0] if m and m.candidates else None)
                    second = (m.candidates[1][0] if m and len(m.candidates or []) > 1 else None)
                    if (top and top[1] >= p.lane_seal_lib_veto and top[0] != hit[1]
                            and not variant_pair(top[0], hit[1])
                            and second != hit[1]
                            and not (lib_n is not None and lib_n.get(hit[1], 0) < p.lane_seal_lib_veto_min_n)):
                        rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "lib_veto", "lib": top[0],
                                                            "cov": round(float(top[1]), 4)}}
                        continue
            else:
                cls = _lane_class(rec.doubts, ev, rec.char, ref, lib)
                if cls == "ji_yi_si" or co in _JYS or col.col in garble_cols:
                    continue
                if p.lane_witness3 and cls in _LANE_R1_CLASSES and op == "replace" and ref:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if rs and not any(c in _JYS for c in wc.values() if c) and same(ref, co, *wc.values()):
                        if variant_pair(lib, ref):
                            _sf = _shape_first_lib(p, mmap.get(rec.id), lib, ref)
                            if _sf is not None:      # 表里是刻形同字异形、库首位把握够高：放库形（刻本原字）
                                hit = ("witness3", lib, {"cls": cls, "ref": ref, "coord": co, "lib": lib, "guard": guard_of(rec.id),
                                                         "witnesses": wc, "lib_form": {"from": ref, "cov": _sf, "via": "shape_first"}})
                            else:
                                rec.evidence = {**ev, "lane_skip": {"lane": "witness3", "why": "lib_variant", "lib": lib}}
                        elif knn_veto is not None and (kv := knn_veto(col.col, rec, lib, ref)):
                            rec.evidence = {**ev, "lane_skip": {"lane": "witness3", "why": "knn_veto", "lib": lib, **kv}}
                            rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["witness3_knn_veto"]))
                        else:
                            hit = ("witness3", ref, {"cls": cls, "ref": ref, "coord": co, "lib": lib,
                                                     "guard": guard_of(rec.id), "witnesses": wc})
                elif p.lane_coord and cls == "other" and co:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if any(c in _JYS for c in wc.values() if c):
                        continue
                    d = wc.get(rs[0][0]) if rs else None
                    if variant_pair(lib, co) and p.lane_coord_codepoint_variant and (
                            norm := _coord_codepoint_norm(p, mmap.get(rec.id), lib, co, canon)):
                        # 两形本书 codepoints 已归一：放哪个都落同一码位，不必看图定刻本形
                        hit = ("coord_fallback", norm, {"via": "lib_coord_codepoint", "coord": co, "lib": lib,
                                                         "variant_norm": "codepoint", "witnesses": wc})
                    elif variant_pair(lib, co):
                        # 库首位与坐标对位字是异体对：哪个是刻本形说不准（vol03 彝/𢑴 人裁取证人形，
                        # vol04 𨽾/𨽻 看图是库形），同 R1 的护栏，送审。
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "lib_variant", "lib": lib}}
                    elif same(lib, co, d):
                        hit = ("coord_fallback", lib, {"via": "lib_coord_primary", "coord": co, "lib": lib,
                                                       "witnesses": wc})
                    elif not _is_han(co) and lib != co:
                        # 坐标对位字不是汉字（ခ 之类对位错位／符号）、库首位是别的字：不取参校字，留审（史記 r12 03:114:2:20）
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "ref_non_han", "lib": lib, "coord": co}}
                    elif (p.lane_coord_blind_guard and lib != co and lib_n is not None
                          and lib_n.get(co, 0) >= p.lane_coord_blind_min_n
                          and _blind_ref_behind(mmap.get(rec.id), co, p.lane_coord_blind_lib_cov, p.lane_coord_blind_gap)):
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "ref_blind", "lib": lib, "coord": co}}
                    elif (rs and same(co, *wc.values()) and not variant_pair(lib, co)
                          and guard_of(rec.id) is None):
                        # 这一支没有字形背书（库首位是别的字），库再带护栏（never_match／conflict：
                        # 库明说「不是这个字」）就不放——vol04 60:9:9 库 一 cov 0.999、证人 二。
                        hit = ("coord_fallback", co, {"via": "witnesses_coord", "coord": co, "lib": lib,
                                                      "witnesses": wc})
            if hit is None:
                continue
            name, char, lev = hit
            if p.lane_lib_veto and char and name in ("witness3", "coord_fallback"):
                m = mmap.get(rec.id)
                top = (m.candidates[0] if m and m.candidates else None)
                if top and float(top[1]) >= p.lane_lib_veto and top[0] != char and not same(top[0], char):
                    if (p.lane_lib_veto_pairs and any(len(q) == 2 and {q[0], q[1]} == {top[0], char} for q in p.lane_lib_veto_pairs)) or (
                            p.lane_shape_first and _shape_first_ok(p, m, top[0], char, top[0])):
                        lev = {**lev, "lib_form": {"from": char, "cov": round(float(top[1]), 4)}}
                        char = top[0]                       # 照刻形：放库首位的形，不否决
                    else:
                        rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "lib_veto", "lib": top[0],
                                                            "cov": round(float(top[1]), 4)}}
                        rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["lane_lib_veto"]))
                        continue
            if p.lane_group_img_veto is not None and char and (
                    gv := _group_img_dissent(ev.get("group"), char, p.lane_group_img_veto)):
                rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "group_img", **gv}}
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["lane_group_img"]))
                continue
            if p.lane_variant_guard and char and not (p.lane_shape_first and lev.get("lib_form")):
                # 放的是库形（刻本原字，`lane_shape_first`）：不是把异体改成通用字，不必拦
                m = mmap.get(rec.id)
                forms = [rec.char] + [c for c, _ in ((m.candidates or [])[:max(p.lane_variant_topk, 0)] if m else [])]
                vf = next((f for f in forms if variant_pair(f, char)), None)
                if vf is not None and keep_rare(name, char, lib, co, lev):
                    lev = {**lev, "keep_rare": vf}
                elif vf is not None and name == "seal" and _seal_lib_same(m, char, _SEAL_LIB_COV):
                    lev = {**lev, "variant_first": vf}      # 库首位就是默认字：放的是库形，不是把异体改成通用字
                elif vf is not None and name == "seal" and (
                        norm := _seal_variant_norm(char, vf, canon)):
                    char, how = norm                        # 两形本书已定归一：放哪个都落同一码位
                    lev = {**lev, "variant_norm": how, "variant_from": vf}
                elif (vf is not None and lev.get("via") == "lib_coord_codepoint" and canon is not None
                      and canon(vf) == canon(char)):
                    pass                                    # 候选里的另一形本书已归到同一码位
                elif vf is not None and variant_hook is not None and (
                        vn := variant_hook(lane=name, char=char, form=vf, canon=canon, lib=lib)) and same(vn, char):
                    char = vn                               # 书级钩子：两形本书已归一（史記，follow_ref_hooks.variant_norm）
                    lev = {**lev, "variant_norm": "hook", "variant_from": vf}
                elif vf is not None and rank_hook is not None and (
                        vr := _lane_variant_rank(rank_hook, name, char, rec.char, m, p.lane_variant_topk, variant_pair, lib)
                ) and same(vr[0], char):
                    char = vr[0]                            # 书级钩子：异体只排库后几名（史記，follow_ref_hooks.variant_rank）
                    lev = {**lev, "variant_rank": "hook", "variant_from": vf, "variant_ranks": vr[1]}
                elif vf is not None:    # 图上可能是刻本异体：别把它改成通用字（#433）
                    rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "cand_variant", "form": vf, "char": char}}
                    continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, name, name, char
            rec.evidence = {**ev, "lane": {"lane": name, **lev, "prev_doubts": list(rec.doubts or [])},
                            "no_glyph_lib": True}
            rec.doubts = [f"lane_{name}"]
            n += 1
    return n


def _coord_codepoint_norm(p: "SeedAdmitParams", m, lib: str, co: str, canon) -> str | None:
    """`lane_coord_codepoint_variant`：库首位 `lib` 与坐标对位字 `co` 在本书 codepoints 里归一到同一码位、
    首位不是 diff、归一后不同字的最强候选比首位低 `lane_coord_codepoint_gap` 以上 → 归一后的码位，否则 None。"""
    if canon is None or canon(lib) != canon(co):
        return None
    cands = list(getattr(m, "candidates", None) or []) if m is not None else []
    if not cands or cands[0][0] != lib or getattr(m, "verdict", None) == "diff":
        return None
    top = float(cands[0][1])
    rival = max((float(c) for ch, c in cands[1:] if canon(ch) != canon(lib)), default=0.0)
    if top - rival < p.lane_coord_codepoint_gap:
        return None
    return canon(lib)


def _seal_variant_norm(char: str, form: str, canon) -> tuple[str, str] | None:
    """`lane_seal_codepoint_variant`：`char`、`form` 两形本书已定归一时 → (放行字, 依据)，否则 None。

    依据 `codepoint`：本书 `codepoints:` 把两形归到同一码位，放该码位；`provisional`：两形同在一个暂归一组
    （`groups.registry.PROVISIONAL`），放组定的字。"""
    if canon is not None and canon(char) == canon(form):
        return canon(char), "codepoint"
    from ..groups.registry import PROVISIONAL
    for pv in PROVISIONAL.values():
        if char in pv.forms and form in pv.forms:
            return pv.to, "provisional"
    return None


def _seal_lib_same(m, char: str | None, min_cov: float) -> bool:
    """库首位＝默认字且覆盖度 ≥ min_cov（`occluded_variant_first` ①）。"""
    top = m.candidates[0] if m and m.candidates else None
    return bool(top and char and top[0] == char and float(top[1]) >= min_cov
                and getattr(m, "verdict", None) != "diff")


def _seal_page_shifted(out: list, mmap: dict, min_cov: float = 0.9, min_hits: int = 3) -> bool:
    """`lane_seal_shift_guard`：本页印章格的默认字是否整体错了一格。

    每列按格号排（夹注半格不算），字形库首位（覆盖度 ≥ `min_cov`）分别与本格、下一格、上一格的默认字比；
    错一格吻合的次数 ≥ `min_hits` 且多过对齐吻合 → 错位。人裁格不算（字是人定的，不是默认字）。"""
    aligned = nxt = prv = 0
    for col in out:
        rs = sorted((r for r in (col.chars or []) if (r.evidence or {}).get("occluded") and not r.sub
                     and r.channel != "human" and r.provenance != "human"), key=lambda r: max(r.slot, 0))
        for i, r in enumerate(rs):
            m = mmap.get(r.id)
            top = m.candidates[0] if m and m.candidates else None
            if not top or top[1] < min_cov:
                continue
            aligned += top[0] == r.char
            nxt += i + 1 < len(rs) and rs[i + 1].char == top[0]
            prv += i > 0 and rs[i - 1].char == top[0]
    shifted = max(nxt, prv)
    return shifted >= min_hits and shifted > aligned


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


def _resolve_group_flow_paths(p) -> None:
    """`group_flow` 的表路径：相对路径按工作区解释；没给时找工作区约定位置
    （字频 `config/groups/freq.json`、文意 L2 表 `config/groups/l2/<组>.json`），找不到就空着（该解法弃权）。
    路径不进参数哈希，表内容哈希进 `group_flow_fingerprint`。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    from ..groups.registry import FLOW_GROUPS as GROUPS
    base = workspace_root() or REPO_ROOT
    cfg = (data_root() or REPO_ROOT) / "config" / "groups"     # 迁到中心库后在数据目录（GUJI-608）

    def _abs(v: str) -> str:
        q = Path(v).expanduser()
        return str(q if q.is_absolute() else base / q)
    freq = _abs(p.group_flow_freq) if p.group_flow_freq else ""
    if not freq and (cfg / "freq.json").exists():
        freq = str(cfg / "freq.json")
    tables = {g: _abs(v) for g, v in p.group_flow_tables.items()}
    for g in p.group_flow:
        if "ctx" in GROUPS[g].flow.solvers and g not in tables:
            t = cfg / "l2" / f"{g}.json"
            if t.exists():
                tables[g] = str(t)
    models = {g: _abs(v) for g, v in p.group_flow_models.items()}
    for g in p.group_flow:
        if "ctx" in GROUPS[g].flow.solvers and g not in models:
            t = cfg / "l2model" / f"{g}.json"
            if t.exists():
                models[g] = str(t)
    object.__setattr__(p, "group_flow_freq", freq)
    object.__setattr__(p, "group_flow_tables", tables)
    object.__setattr__(p, "group_flow_models", models)
    rs = _abs(p.group_flow_rr_shape) if p.group_flow_rr_shape else ""
    if not rs and "rr" in p.group_flow and (cfg / "rr_shape.json").exists():
        rs = str(cfg / "rr_shape.json")
    object.__setattr__(p, "group_flow_rr_shape", rs)
    ws = _abs(p.group_flow_wu_shape) if p.group_flow_wu_shape else ""
    if not ws and "wu" in p.group_flow and (cfg / "wu_shape.json").exists():
        ws = str(cfg / "wu_shape.json")
    object.__setattr__(p, "group_flow_wu_shape", ws)
    hs = _abs(p.group_flow_hou_shape) if p.group_flow_hou_shape else ""
    if not hs and "hou" in p.group_flow and (cfg / "hou_shape.json").exists():
        hs = str(cfg / "hou_shape.json")
    object.__setattr__(p, "group_flow_hou_shape", hs)
    if p.group_flow_part_shape:                  # 相对路径先找数据目录（config/groups/part_shape.json，随中心库走），再找工作区
        _q = Path(p.group_flow_part_shape).expanduser()
        _dr = data_root()
        object.__setattr__(p, "group_flow_part_shape",
                           str(_dr / _q) if not _q.is_absolute() and _dr is not None and (_dr / _q).exists() else _abs(p.group_flow_part_shape))
    if p.group_flow_pair_shape:
        object.__setattr__(p, "group_flow_pair_shape", _abs(p.group_flow_pair_shape))
    if p.group_flow_pair_shapes:                 # 相对路径先找数据目录（模型随中心库走：config/groups/pair_shape_<组>.json），再找工作区
        droot = data_root()

        def _abs_data(v: str) -> str:
            q = Path(v).expanduser()
            if not q.is_absolute() and droot is not None and (droot / q).exists():
                return str(droot / q)
            return _abs(v)
        object.__setattr__(p, "group_flow_pair_shapes", {k: _abs_data(v) for k, v in p.group_flow_pair_shapes.items()})
    bk = {g: _abs(v) for g, v in p.group_flow_book_knn.items()}
    for g in p.group_flow:
        t = cfg / "book_knn" / f"{g}.json"
        if g not in bk and t.exists():
            bk[g] = str(t)
    object.__setattr__(p, "group_flow_book_knn", bk)
    nk = _abs(p.group_flow_near_knn) if p.group_flow_near_knn else ""
    if not nk and (cfg / "near_knn.json").exists():
        nk = str(cfg / "near_knn.json")
    object.__setattr__(p, "group_flow_near_knn", nk)


def _l3_groups(p) -> tuple:
    from ..groups.flow import rules_path
    if not p.group_flow_llm_model:
        return ()
    return tuple(g for g in p.group_flow_llm_groups
                 if g in p.group_flow and rules_path(g).with_name("prompt.md").exists())


_L3_ONLINE: dict = {}
_FLOW_MOUNT_LOGGED: list = []     # 本进程只记一次文意挂载情况（见 _flow_config）


def _l3_online(p) -> dict:
    """文意 L3 在线各组的 {system, ver, rulings}：提示词按本书变量填好（`prompt_template`），问过的窗口存成大模型裁定事件
    （`feedback/rulings`，按窗口内容查，见 `groups/ctx_llm`）。"""
    from ..core.workspace import REPO_ROOT, data_root
    from ..groups.flow import rules_path
    from ..groups.prompt_template import book_prompt_vars, load_rendered_prompt
    gs = _l3_groups(p)
    root = data_root() or REPO_ROOT
    key = (gs, str(root))
    if key not in _L3_ONLINE:
        bv = book_prompt_vars()
        d = {}
        for g in gs:
            try:
                meta, body = load_rendered_prompt(rules_path(g).with_name("prompt.md"), bv)
            except KeyError:              # 本书没给提示词变量（book_prompt.json）：这组不问
                continue
            d[g] = {"system": body, "ver": meta.get("ver", "")}
        if d:                  # 问过的窗口存成裁定事件（feedback/rulings，同人裁事件库），下次先查它
            from ..feedback.rulings import RulingCache, RulingStore
            rc = RulingCache(RulingStore())
            for o in d.values():
                o["rulings"] = rc
        _L3_ONLINE[key] = d
    return _L3_ONLINE[key]


_VIS_CACHE: list = []


def _vis_cache():
    """字块图像＋文意 L4 的缓存：同文意 L3，落裁定库（按组、字块哈希、前后文）。"""
    if not _VIS_CACHE:
        from ..feedback.rulings import RulingCache, RulingStore
        _VIS_CACHE.append(RulingCache(RulingStore()))
    return _VIS_CACHE[0]


def _l3_fingerprint(p) -> str:
    import hashlib
    h = hashlib.sha256(f"{p.group_flow_llm_model}|{p.group_flow_llm_effort}|False|{','.join(p.group_flow_llm_panel)}|{','.join(p.group_flow_llm_panel_groups)}".encode())
    for g, o in sorted(_l3_online(p).items()):
        h.update(f"|{g}|{o['ver']}|".encode() + o["system"].encode("utf-8"))
    return h.hexdigest()[:16]


#: 字组统一流程不碰的格：硬护栏（同规则 A）＋待审补放不碰的＋乱码护栏＋排除、非字、超时；形近护栏除外（见 `blocked`）
_GROUP_FLOW_OWN_GUARDS = frozenset({"never_match", "conflict"})
_GROUP_FLOW_OWN_DOUBTS = frozenset({"near_form"} | {f"护栏:{g}" for g in _GROUP_FLOW_OWN_GUARDS})
_GROUP_FLOW_HARD = ((frozenset(_RARE_REF_HARD) | _LANE_HARD | _LANE_GARBLE | {"excluded", "glyph_timeout"})
                    - _GROUP_FLOW_OWN_DOUBTS)


#: 入人八 刻形判法不碰的格：看不到字、排除、空格／瘦高格、开放字形、近似刻例、超时
_RR_SHAPE_HARD = frozenset({"occluded", "excluded", "context_blank_cell", "context_tall_cell", "form_open",
                            "approx_exemplar", "glyph_timeout"})
_RR = frozenset("人入八")


#: 看图判裁定（`feedback/rulings`，group=O）：提示词版本、A24 名下的子类、不碰的疑问
_VIS_RULING_GROUP, _VIS_RULING_VER = "O", "vis-o1"
_VIS_RULING_SUBCLASSES = frozenset({"A68", "B99", "D130", "L04"})
#: 整理本缺字（〓）按新图源文本层取字／私用码「一码一字」表（`research/a24/pua_src`，A24 2026-11-03），提示词版本 → 收的子类
#: ctx-m1＝只读文意终审（A24 2026-11-04，两路独立会话双 high＋字形分或≥2 来源，按组定越不越过整理本；`admit_ok` 写入时已判），Z＝字组格、N＝形近护栏格
_VIS_RULING_SPECS = ((_VIS_RULING_VER, _VIS_RULING_SUBCLASSES), ("src-1", frozenset({"PUA", "GB"})), ("ctx-m1", frozenset({"Z", "N"})))
_VIS_RULING_HARD = frozenset({"occluded", "excluded", "glyph_timeout"})
_VIS_HALF_BAD = frozenset({"clipped", "frame_residue"})   # vis_ruling_half 下带这些切分疑点的半格不放


def _ruling_han(c) -> bool:
    """裁定字须是汉字（统一表意文字各区＋兼容表意）：汉字区以外的码位、私用码、符号、占位一律不放（Ext J 的 U+323B0–3347F 是 Unicode 17 的真汉字，算）
    （A31 11-05：不能让非汉字经 vis_ruling 通道放行；比 `_is_han` 严，后者连私用码也算）。"""
    if not c or len(c) != 1:
        return False
    o = ord(c)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x323AF
            or 0x323B0 <= o <= 0x3347F or 0x2F800 <= o <= 0x2FA1F)


def _override_ok(groups, a: str, b: str) -> bool:
    """a、b 同属 `groups` 里的某个字组（成员含两字）。"""
    from ..groups.registry import FLOW_GROUPS
    return any(g in FLOW_GROUPS and a in FLOW_GROUPS[g].members and b in FLOW_GROUPS[g].members for g in groups)


def _pua_pin(ctx) -> int | None:
    """册钉的 PUA 码表共享层版本（`Book.pua_table_pin`）；没钉或没有 ctx 给 None（读本书码表）。"""
    return getattr(getattr(ctx, "book", None), "pua_table_pin", None)


def _pua_code_pass(out: list, amap: dict, store=None, table=None, p=None, pin=None) -> tuple[int, int, int]:
    """按私用码表放字（`SeedAdmitParams.pua_code_table`）。→ (改字格数, 遍后仍不一致格数, 降审格数)。

    格→码对应来自裁定库 `src-2`（按格号取，见 `RulingStore.cell_codes`）；对位字 `ref` 与现对位不同的不认（重切后格号可能挪了）。
    ① 非人裁已放行、放行字≠码表字 → 改成码表字（通道 `code_table`，provenance `match`）；② 一码多字的码：放行字在族内 → 不动，
    族外 → 降审（doubt `src_code_conflict`；`True` 关则只计数）；③ 人裁格不动，只计入「仍不一致」；
    ④ 未放行格不动。码表字须是汉字。（原⑤ `pua_code_keep_channels` 无书用，2026-11-23 删。）"""
    from ..utils.pua_v2_codes import load_table
    if store is None:
        store = _vis_cache().store_
    cc = store.cell_codes()
    if not cc:
        return 0, 0, 0
    if table is None:
        from ..core.workspace import ws_config_dir
        table = load_table(ws_config_dir(), pin=pin)
    codes, fams = table
    fam_demote = True
    fix = mism = dem = 0
    for col in out:
        for r in col.chars:
            info = cc.get(r.id)
            if not info or not r.admit or (r.doubts and "excluded" in r.doubts):
                continue
            T = codes.get(info["code"])
            fam = fams.get(info["code"])
            if (not T and not fam) or (T and not _ruling_han(T)) or (info.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or ""):
                continue
            T = T or ""                              # 纯多字码（表里只登族、没有单字）：只管族外降审，不改字
            if r.char == T or (fam and r.char in fam):
                continue
            if r.provenance == "human" or r.channel == "human":
                mism += 1
                continue
            if fam and not fam_demote:
                mism += 1
                continue
            if fam:                                  # 族外字：码表字也不是铁证，退回人审
                _demote(r, "src_code_conflict")
                r.evidence = {**(r.evidence or {}), "src_code_conflict": {"code": info["code"], "char": T, "family": "".join(sorted(fam))}}
                r.admit, r.channel, r.provenance = False, None, ""
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + ["src_code_conflict"]))
                dem += 1
                continue
            r.evidence = {**(r.evidence or {}), "code_table": {"code": info["code"], "char": T, "was": r.char, "was_channel": r.channel}}
            r.char, r.channel, r.provenance = T, "code_table", "match"
            fix += 1
    return fix, mism, dem



def _pua_code_admit_pass(out: list, amap: dict, mmap: dict, store=None, table=None, p=None, pin=None) -> int:
    """`SeedAdmitParams.pua_code_admit`：未放行格按私用码表＋库首位互证放行。→ 放行格数。

    只升不降：只碰 admit=False、非人裁、不在排除名单、没遮挡、没有硬疑问（`_LANE_HARD`）的格。格→码同 `_pua_code_pass`
    （裁定库 `src-2`，对位字 `ref` 与现对位不同的不认）；码表字须是汉字；库首位须是码表字（一码多字则族内任一字）、
    cov ≥ `p.pua_code_admit_cov`、库没判 diff、无护栏。放的字取库首位（族内字按刻形，不按码改）。"""
    from ..utils.pua_v2_codes import load_table
    if store is None:
        store = _vis_cache().store_
    cc = store.cell_codes()
    if not cc:
        return 0
    if table is None:
        from ..core.workspace import ws_config_dir
        table = load_table(ws_config_dir(), pin=pin)
    codes, fams = table
    all_T = set(codes.values())
    min_cov = float(getattr(p, "pua_code_admit_cov", 0.85) if p is not None else 0.85)
    n = 0
    for col in out:
        for r in col.chars:
            ds = {d for d in (r.doubts or []) if isinstance(d, str)}
            if (r.admit or r.provenance == "human" or r.channel == "human"
                    or "excluded" in ds or "occluded" in ds or ds & _LANE_HARD):
                continue
            info = cc.get(r.id)
            if not info or (info.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or ""):
                continue
            T, fam = codes.get(info["code"]), fams.get(info["code"])
            other_T = {c for c in all_T if c != T}
            # 族里若有别的码的表字，那是文本层把形近的不同字合用一码（F1001 乖垂埀：乖是 EA36、埀是 EA39），
            # 库首位落到这种字不算互证（第 7 轮 vol26:30:7:11 等 3 格「垂四十年」「垂紳正笏」放成了乖，A24 11-08）
            ok = ({T} if T and _ruling_han(T) else set()) | {x for x in (fam or ()) if x == T or x not in other_T}
            if not ok:
                continue
            m = mmap.get(r.id)
            if not m or not m.candidates or getattr(m, "guard", None) is not None or getattr(m, "verdict", None) == "diff":
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            if top not in ok or cov < min_cov:
                continue
            r.evidence = {**(r.evidence or {}), "code_table": {"code": info["code"], "char": T or "".join(sorted(fam or ())),
                                                               "admit": True, "lib": top, "cov": round(cov, 4),
                                                               "prev_doubts": list(r.doubts or [])}}
            r.admit, r.char, r.channel, r.provenance = True, top, "code_table", "match"
            r.doubts = ["code_table_admit"]
            n += 1
    return n

def _vis_ruling_pass(p, out: list, amap: dict, store=None) -> int:
    """无组格的看图判裁定（`SeedAdmitParams.vis_rulings`）：待审格按前后文窗口（与 `ctx_hash` 同口径，宽 20）查裁定库，
    命中高把握可放的裁定 → 放行成裁定的字（通道 `vis_ruling`，provenance `match`，`evidence.vis_ruling` 留裁定摘要）。
    另：已放行格命中 `route=code_conflict` 的 src-1 裁定（同一私用码在源文本里是另一个字）→ 降回待审（见下）。
    → 放行格净增数（新放行减降审；调用方据此改页头 n_auto/n_review，v0.6.2 漏减降审致页头与格数不符）。窗口先整页算好再改格（相邻漏字格互为上下文，边改边算会让窗口变样、键对不上）。"""
    from ..groups.context import WIDTH
    from ..utils.jiazhu_order import sort_by_reading
    store = store if store is not None else _vis_cache().store_
    seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
           if not (r.doubts and "excluded" in r.doubts)]
    todo, adm = [], []
    for i, r in enumerate(seq):
        if r.provenance == "human" or r.channel == "human":
            continue
        if _VIS_RULING_HARD & {d for d in (r.doubts or []) if isinstance(d, str)} or (r.evidence or {}).get("occluded"):
            continue
        (adm if r.admit else todo).append((r, _clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)))
    n = 0
    # 降审：已放行（非人裁）格的窗口命中 src-1 的 code_conflict 裁定（该码的唯一字≠现放行字，admit_ok=False）→ 降回待审，
    # doubt `src_code_conflict`。从净增数里减掉；放行遍在后，同格不会被本遍降下来又放回去（它已是 admit 才进 adm）。
    for r, left, right in adm:
        v = store.get(_VIS_RULING_GROUP, "src-1", left, right)
        if (not v or v.get("route") != "code_conflict" or v.get("admit_ok") or v.get("conf") != "high"
                or v.get("subclass") != "PUA" or not v.get("char") or v["char"] == r.char
                or (v.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or "")):
            continue
        _demote(r, "src_code_conflict")
        r.evidence = {**(r.evidence or {}), "src_code_conflict": {k: v.get(k) for k in ("char", "why", "cell", "src")}}
        r.admit, r.channel, r.provenance = False, None, ""
        r.doubts = list(dict.fromkeys(list(r.doubts or []) + ["src_code_conflict"]))
        n -= 1
    ovr = p.ruling_override_groups
    extra = frozenset(x.strip() for x in (getattr(p, "vis_ruling_ctx_subclasses", "") or "").split(",") if x.strip())
    specs = tuple((ver, subs | extra) if ver == "ctx-m1" else (ver, subs) for ver, subs in _VIS_RULING_SPECS) if extra else _VIS_RULING_SPECS
    skip_half = getattr(p, "group_flow_llm_skip_half", False) and not getattr(p, "vis_ruling_half", False)
    half_ok = getattr(p, "group_flow_llm_skip_half", False) and getattr(p, "vis_ruling_half", False)
    rget = getattr(store, "get_equiv", store.get)
    for r, left, right in todo:
        # 当场记下本遍的窗口（裁定键）：产物是整遍跑完的状态，后面几遍放行／降审的邻格会让从产物重算的窗口与这里不同，
        # manager 写终审裁定键、rulings-hits 补键直接用这个（A33 11-20，全唐文 027:59:4:7）。
        r.evidence = {**(r.evidence or {}), "vis_ctx": {"left": left, "right": right,
                                                        "ref": (amap.get(r.id) or (None,))[0] or ""}}
        is_half = (r.id or "")[-1:] in ("a", "b")
        if half_ok and is_half and any(isinstance(d, str) and (d in _VIS_HALF_BAD or d.startswith(("jiazhu_", "split_")))
                                        for d in (r.doubts or [])):
            continue                                 # 半格本身带切分疑点：不放（A22 评估 11-12）
        if skip_half and (r.id or "")[-1:] in ("a", "b"):
            continue                                 # 夹注半格不靠终审裁定放行（等金标证据再开）
        # 精确键没中再查版本等价表（`RulingStore.get_equiv`，GM4／CV4 11-24）；护栏照旧，白名单按目标版本 vt 判
        hit = next(((ver, x) for ver, subs in specs
                    for x in [rget(_VIS_RULING_GROUP, ver, left, right)]
                    if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                    and _ruling_han(x["char"]) and x.get("subclass") in subs), None)
        vt, v = hit if hit else (None, None)
        ref_ = (amap.get(r.id) or (None,))[0]
        if not v:
            f = store.get(_VIS_RULING_GROUP, "ctx-m1", left, right)
            if f and f.get("gate") == "ref_lead_fail" and (f.get("ref") or "") == (ref_ or ""):
                r.evidence = {**(r.evidence or {}), "ref_lead_fail": f.get("ref_lead") or {}}   # 终审 ref_lead 证人没过：留审，记下供统计
            continue
        if (v.get("ref") or "") != (ref_ or ""):
            continue                                 # 整理本对位字变了：不是当初看的那一格
        if half_ok and is_half and (v.get("cell") != r.id or v["char"] != ref_):
            continue                                 # 半格：裁定的格号须＝当前格号（重切后不落到别的图），且字＝整理本字（不走白名单越过）
        if ovr is not None and vt == "ctx-m1" and ref_ and v["char"] != ref_ and not _override_ok(ovr, v["char"], ref_):
            continue                                 # 越过整理本：字与整理本字不同属白名单字组 → 留审
        ds = list(r.doubts or [])
        vr = {k: v.get(k) for k in ("char", "conf", "why", "model", "prompt_ver", "cell", "subclass", "route")}
        vr.update({k: v[k] for k in ("via", "ref_lead", "ruling_key", "ruling_ver") if v.get(k)})   # 非窗口精确命中才有 ruling_key   # 终审 ref_lead 证人放行：via=ref_lead（层、领先量）
        r.evidence = {**(r.evidence or {}), "vis_ruling": vr,
                      "lifted_from": {"char": r.char, "doubts": ds}}
        if half_ok and is_half:
            r.evidence["half"] = True                # 统计用，字形库可据此排除
        r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "vis_ruling", "match", []
        n += 1
    return n


def _blank_ink_pass(p: "SeedAdmitParams", out: list, mmap: dict, coord: dict, conflict: frozenset, vmap) -> int:
    """`blank_ink_nonchar`：整理本空格位上有墨、库认不出的格判非字放行。→ 放行格数。只升不降。"""
    n = 0
    for col in out:
        recs = col.chars or []
        ref_n = agree = 0
        for rec in recs:
            ch = coord.get(rec.id)
            if not ch or is_gap(ch):
                continue
            ref_n += 1
            m = mmap.get(rec.id)
            top = (m.candidates[0][0] if m and m.candidates else None) or rec.char
            agree += int(bool(top) and vmap.semantic(top) == vmap.semantic(ch))
        if agree < p.blank_ink_col_min_agree or agree < p.blank_ink_col_min_frac * ref_n:
            continue
        for rec in recs:
            doubts = set(rec.doubts or [])
            if (rec.admit or rec.channel == "human" or rec.provenance == "human" or "excluded" in doubts
                    or "occluded" in doubts or doubts & _LANE_HARD):
                continue
            if coord.get(rec.id, None) != "" or rec.id in conflict:
                continue
            m = mmap.get(rec.id)
            if m is None:
                continue
            top = m.candidates[0] if m.candidates else None
            cov = float(top[1]) if top else 0.0
            if m.verdict == "same" or cov >= p.blank_ink_max_cov:
                continue
            ev = rec.evidence or {}
            rec.admit, rec.channel, rec.provenance, rec.char = True, "blank_ink", "blank_ink", None
            rec.evidence = {**ev, "lane": {"lane": "blank_ink", "nonchar": True, "ref_blank": True,
                                           "verdict": m.verdict, "lib": top[0] if top else None,
                                           "cov": round(cov, 4), "prev_doubts": sorted(doubts)},
                            "no_glyph_lib": True}
            rec.doubts = ["blank_ink"]
            n += 1
    return n


_IRREGULAR_SOURCES = frozenset({"twedu", "local:keben"})


@lru_cache(maxsize=None)
def _ref_regulars(ref: str) -> tuple[str, ...]:
    """整理本字是异体写法时它的正字（`_IRREGULAR_SOURCES` 指认的），不是异体写法 → 空。"""
    from ..variants import _graph
    return tuple(r for r, tags in _graph().regulars_of(ref) if set(tags) & _IRREGULAR_SOURCES)


def _irregular_ref_gap(machine: str, ref: str, cands) -> float | None:
    """`p_ref_irregular_gap` 判据：整理本字是异体写法时，机器字 cov 减去「整理本字及其正字」在库候选里的最高 cov。
    整理本字不是异体写法、机器字不在候选里、整理本字族一个都不在候选里、机器字与整理本字有直接异体边 → `None`。"""
    regs = _ref_regulars(ref)
    if not regs or _direct_variant_edge(machine, ref):
        return None
    sc = {c: float(v) for c, v in (cands or [])}
    fam = [sc[c] for c in (ref, *regs) if c in sc and c != machine]
    if machine not in sc or not fam or machine in regs:
        return None
    return sc[machine] - max(fam)


def _p_ref_pass(p, out: list, amap: dict, mmap: dict | None = None) -> int:
    """P 类取整理本字（`SeedAdmitParams.p_ref_admit`）。→ 放行数净增。

    （原 `p_ref_coord`：退到坐标对位的整理本字，P02 11-06 加、无书开，2026-11-23 CV4 删。）"""
    from ..groups.registry import FLOW_GROUPS
    in_group = {c for g in FLOW_GROUPS.values() for c in g.members}

    def ref_of(r):
        return (amap.get(r.id) or (None,))[0] or None

    def irregular_ok(r) -> bool:
        """`p_ref_irregular_gap`：整理本字是异体写法且字族 cov 贴近机器字 → 不看 `p_ref_max_cov`，整理本字在字组里也放（机器字不在组里，组流程没有对这格表态；第 7 轮 P01 里 46 格整理本字在 寳／𭔃／竒／囘／厯 等组内）。"""
        if p.p_ref_irregular_gap is None or mmap is None:
            return False
        m = mmap.get(r.id)
        gap = _irregular_ref_gap(r.char, ref_of(r), getattr(m, "candidates", None)) if m is not None else None
        return gap is not None and gap <= p.p_ref_irregular_gap

    def cand(r) -> bool:
        if r.admit or r.provenance == "human" or r.channel == "human" or ((r.id or "")[-1:] in ("a", "b") and not p.p_ref_jiazhu):
            return False
        ds = {d for d in (r.doubts or []) if isinstance(d, str)}
        if _VIS_RULING_HARD & ds or "occluded" in ds or "excluded" in ds or (r.evidence or {}).get("occluded"):
            return False
        if ((r.evidence or {}).get("group") or {}).get("id"):
            return False
        if p.p_ref_min_cov is not None:
            cov = (r.evidence or {}).get("cov")
            if "库里没有这个字" in ds or (isinstance(cov, (int, float)) and cov < p.p_ref_min_cov):
                return False            # 库认不出的格（多是切分坏格）不取整理本字，盖住切分错
        ref = ref_of(r)
        if not (ref and r.char and r.char != ref and r.char not in in_group and (ref not in in_group or irregular_ok(r))):
            return False
        return not (p.p_ref_skip_variant and _direct_variant_edge(r.char, ref))

    def cov_ok(r) -> bool:
        """`p_ref_max_cov`：机器字库覆盖率须低于它（相邻判断仍按不含这条的 cand，成片就是成片）。"""
        lim = p.p_ref_max_cov
        if lim is None:
            return True
        cov = (r.evidence or {}).get("cov")
        return isinstance(cov, (int, float)) and cov < lim

    n = 0
    for c in out:
        rs = sorted(c.chars or [], key=lambda r: (r.slot, r.sub or ""))
        flags = [cand(r) for r in rs]
        for i, r in enumerate(rs):
            if not flags[i] or not (cov_ok(r) or irregular_ok(r)):
                continue
            if not p.p_ref_adjacent and ((i > 0 and flags[i - 1]) or (i + 1 < len(rs) and flags[i + 1])):
                continue
            ref = ref_of(r)
            r.evidence = {**(r.evidence or {}), "p_ref": {"ref": ref, "machine": r.char, **({"irregular": True} if not cov_ok(r) else {}), "cov": (r.evidence or {}).get("cov")},
                          "lifted_from": {"char": r.char, "doubts": list(r.doubts or [])}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = ref, True, "p_ref", "match", []
            n += 1
    return n


#: `fold_aspect` 判窄字／宽字的组与字（组 id → (窄字, 宽字)）
_FOLD_ASPECT_PAIRS = {"ry": ("日", "曰")}


def _fold_pass(p, out: list, amap: dict, mmap: dict | None = None, store=None, coord: dict | None = None,
               wh: dict | None = None, dmap: dict | None = None) -> int:
    """折叠组（`SeedAdmitParams.fold_groups`）：待审格的字组在名单里、整理本字在组内 → 放整理本字。→ 放行数净增。
    护栏（缺省关）：`fold_ruling_first` 有本组裁定先用裁定字；`fold_lib_top_in_group` 库首位须在组内；
    扩展 `fold_coord_ref`（`coord` 由调用方给）：现役对位缺用坐标对位、未入组格按库首位入折叠组。
    字形宽高（`fold_aspect`，`wh` 由调用方给）按 `_FOLD_ASPECT_PAIRS` 判窄字／宽字；`fold_aspect_ctx_veto`（`dmap`＝context_decide）可否决。
    夹注 a/b 半格不处理（原 `fold_jiazhu`／`fold_aspect_jiazhu`／`fold_aspect_pairs`／`fold_aspect_ink` 无书开，2026-11-23 CV4 删）。
    框架与各书标定见 `doc/字组/折叠组.md`。"""
    from ..groups.registry import FLOW_GROUPS
    pairs = _FOLD_ASPECT_PAIRS
    wins: dict = {}
    no_ref = not p.fold_ref_char
    if p.fold_ruling_first or no_ref:
        from ..groups.context import WIDTH
        from ..utils.jiazhu_order import sort_by_reading
        seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
               if not (r.doubts and "excluded" in r.doubts)]
        wins = {r.id: (_clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)) for i, r in enumerate(seq)}
        store = store if store is not None else _vis_cache().store_
        l3 = _l3_online(p)
    n = 0
    for c in out:
        for r in c.chars or []:
            half = (r.id or "")[-1:] in ("a", "b")
            if r.admit or r.provenance == "human" or r.channel == "human" or half:
                continue
            ds = {d for d in (r.doubts or []) if isinstance(d, str)}
            occ = "occluded" in ds or bool((r.evidence or {}).get("occluded"))
            if (_VIS_RULING_HARD - {"occluded"}) & ds or "excluded" in ds or (occ and not p.fold_occluded):
                continue
            gid = ((r.evidence or {}).get("group") or {}).get("id")
            ref = (amap.get(r.id) or (None,))[0]
            via_coord = False
            if occ:
                # 遮挡格：整理本字与库首位须同在一个折叠组里才归组（整理本字只判归组，不定字，见 `fold_occluded`）
                cand0 = (list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [(None, 0.0)]))[0]
                top = cand0[0]
                lax = p.fold_occluded_lib_max_cov is not None and float(cand0[1] or 0.0) < p.fold_occluded_lib_max_cov
                gid = next((g for g in p.fold_groups if g in FLOW_GROUPS and ref in FLOW_GROUPS[g].members
                            and (lax or top in FLOW_GROUPS[g].members)), None)
                if gid is None:
                    continue
            if p.fold_coord_ref:
                if not ref and coord and coord.get(r.id) not in (None, "", *GAP_CHARS):
                    ref, via_coord = coord[r.id], True
                if gid is None and ref:
                    top = (list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [(None,)]))[0][0]
                    gid = next((g for g in p.fold_groups if g in FLOW_GROUPS and top in FLOW_GROUPS[g].members
                                and ref in FLOW_GROUPS[g].members), None)
            if gid not in p.fold_groups or gid not in FLOW_GROUPS:
                continue
            mem = FLOW_GROUPS[gid].members
            if not no_ref and (not ref or ref not in mem):
                continue
            if p.fold_lib_top_in_group:
                cands = list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [])
                if not cands or cands[0][0] not in mem:
                    continue
            ch, via, extra, veto = None, None, {}, None
            th = p.fold_aspect
            pair = pairs.get(gid)
            ar = None
            if th and pair and pair[0] in mem and pair[1] in mem:
                if wh and r.id in wh:
                    w, h = wh[r.id]
                    ar = w / h if (h and h > 0 and w) else None
            if ar is not None:
                if ar >= th[1]:
                    ch = pair[1]
                elif ar <= th[0]:
                    ch = pair[0]
                if ch is not None:
                    via, extra = "aspect", {"aspect": round(ar, 3)}
                    if p.fold_aspect_ctx_veto is not None:
                        other = pair[0] if ch == pair[1] else pair[1]
                        pr = dict(getattr((dmap or {}).get(r.id), "ranked", None) or []).get(other, 0.0)
                        g_ev = (r.evidence or {}).get("group") or {}
                        gt = next((t for t in g_ev.get("solvers") or [] if t.get("solver") == "ctx"), None) if g_ev.get("id") == gid else None
                        # 组内文意：L1 规则不算（殿本 H01 37 格错 15、史記 06:46「李奇曰」ry-ext-r1 误给日，SJ 11-08）；带概率的（L2）要到阈值
                        g_other = bool(gt and gt.get("char") == other and str(gt.get("why", "")).startswith("agree")
                                       and str(gt.get("via") or "ctx").split(":")[-1] != "ctx_l1"
                                       and (gt.get("p") is None or float(gt["p"]) >= p.fold_aspect_ctx_veto))
                        if pr >= p.fold_aspect_ctx_veto or g_other:
                            # 上下文排名或字组文意解法给了另一个字（名单页「日講官」没有 context_decide 排名，组内文意给日，SJ 11-08）
                            veto = {"aspect": round(ar, 3), "char": ch, "ctx": other, "prob": round(pr, 3),
                                    **({"group_ctx": gt.get("via") or "ctx"} if g_other else {})}
                            ch, via, extra = None, None, {}
            if ch is None and (p.fold_ruling_first or no_ref) and r.id in wins and gid in l3:
                v = getattr(store, "get_equiv", store.get)(gid, l3[gid]["ver"], *wins[r.id])
                if v and v.get("char") in mem and v.get("conf") in ("high", "mid") and not v.get("other"):
                    ch, via = v["char"], "ruling"
                    extra = {k: v[k] for k in ("ruling_key", "ruling_ver") if v.get(k)}   # 版本等价命中（GM4／CV4 11-24）
            if ch is None and p.fold_ctx_vias:
                g_ev = (r.evidence or {}).get("group") or {}
                t = next((t for t in g_ev.get("solvers") or [] if t.get("solver") == "ctx"), None) if g_ev.get("id") == gid else None
                if (t and t.get("char") in mem and str(t.get("why", "")).startswith("agree")
                        and str(t.get("via") or "ctx").split(":")[-1] in p.fold_ctx_vias and (t.get("strong") or not p.fold_ctx_strong)):
                    ch, via, extra = t["char"], "ctx", {"ctx": t.get("via") or "ctx", **({"strong": True} if t.get("strong") else {})}
            if ch is None:
                if no_ref:
                    fp = {"group": gid, **({"ctx_veto": veto} if veto else {})}
                    r.evidence = {**(r.evidence or {}), "fold_pending": fp}   # 已归组、字待文意
                    continue
                ch, via = ref, "ref"
            fold = {"group": gid, "ref": ref, "via": via, **extra}
            if via_coord:
                fold["coord"] = True
            r.evidence = {**(r.evidence or {}), "fold": fold,
                          "lifted_from": {"char": r.char, "doubts": list(r.doubts or [])}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, "fold", "match", []
            n += 1
    return n


def _rr_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """入人八 书级刻形判法（`groups.rr_shape`，`SeedAdmitParams.group_flow_rr_shape`）。紧接 group_flow。→ 放行数净增。

    - 待审格（字组 rr 的格，或库首位／整理本是 人入八）：刻形给字 → 放行成该字（channel `rr_shape`），不看整理本；
    - 已放行的 人入八 格：刻形给了组里另一个字 → 改字（`evidence.fixed_from` 留原字）；刻形弃权 → 不动；
    - 人裁格、硬护栏格不碰；刻形弃权（组外字、几何不明、分差小）的待审格照旧送审。
    sheldon 2026-11-02 定「字形说了算，越过整理本」（全唐文；模型按册留出 对 2,445 错 0 弃 24）。"""
    from ..groups import rr_shape
    model = rr_shape.load(p.group_flow_rr_shape)
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            gid = (ev.get("group") or {}).get("id")
            ref = (amap.get(r.id) or (None,))[0]
            if r.admit:
                if r.char not in _RR:
                    continue
            elif not (gid == "rr" or r.char in _RR or ref in _RR):
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("rr_shape")
                continue
            v = rr_shape.judge(img, model)
            trail = {k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "rr_shape": trail}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "rr_shape": trail, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "rr_shape"
                continue
            r.evidence = {**ev, "rr_shape": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "rr_shape", "match", []
            delta += 1
    return delta


_WU = frozenset("嗚鳴")


def _wu_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """嗚鳴 书级刻形判法（`groups.wu_shape`，`SeedAdmitParams.group_flow_wu_shape`）。紧接 rr_shape。→ 放行数净增。

    同 `_rr_shape_pass`：刻形说了算、越过整理本与文意（sheldon 11-13「嗚/鳴 归形近不同义组，拆部件 100% 自动区分」，
    11-14 嗚鳴17格按刻形点）。只判本格字（库首位）是 嗚鳴 的格：待审格刻形给字 → 放行（channel `wu_shape`）；
    整理本／字组／库前几名里有 嗚鳴 都不算（总览 11-14 审：对不齐时格里可能是别的字；全唐文 t1 实测库前 3 名放进来的 21 格
    全是 鴨鵝鳩塢鴟 这类右边也是 鳥／烏 的字，网只看右半、照样给 p≈1，3 格错放成 鳴）；
    已放行的 嗚鳴 格刻形给了另一个字 → 改字（`evidence.fixed_from`）；弃权不动；人裁格、硬护栏格不碰。"""
    from ..groups import wu_shape
    model = wu_shape.load(p.group_flow_wu_shape)
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            if r.char not in _WU:
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("wu_shape")
                continue
            v = wu_shape.judge(img, model)
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "wu_shape": v}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "wu_shape": v, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "wu_shape"
                continue
            r.evidence = {**ev, "wu_shape": v, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "wu_shape", "match", []
            delta += 1
    return delta


_HOU = frozenset("候𠋫")


def _hou_shape_pass(p, out: list, ctx=None, page: int = 0, patch_missing: dict | None = None,
                    only_unjudged: bool = False) -> int:
    """候𠋫 书级刻形判法（`groups.hou_shape`，`SeedAdmitParams.group_flow_hou_shape`）。紧接 wu_shape。→ 0（只改字、不改放行）。

    全唐文书级码位 候→𠋫（照刻形），可书里也刻真 候（033 册起居多；sheldon 11-19 点选 182 格定标签）。
    只碰**已放行**、字是 候／𠋫 的非人裁格：刻形给了字就照录（`evidence.hou_shape`），给 候 的格到最后码位归一那步不归 𠋫
    （`_codepoint_exempt`），改了字记 `evidence.fixed_from`。待审格不补放：库首位是 候𠋫 的待审格可能其实是 侯（亻右边也只一短笔），
    几何量分不开 侯／候，补放留给原通道与人审。弃权（量在中间）不动。"""
    from ..groups import hou_shape
    model = hou_shape.load(p.group_flow_hou_shape)
    miss = patch_missing if patch_missing is not None else {}
    for c in out:
        for r in c.chars or []:
            if not r.admit or r.char not in _HOU or r.provenance == "human" or r.channel == "human":
                continue
            if only_unjudged and "hou_shape" in (r.evidence or {}):
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("hou_shape")
                continue
            v = hou_shape.judge(img, model)
            ev = r.evidence or {}
            if v["char"] is None:
                r.evidence = {**ev, "hou_shape": v}
                continue
            if v["char"] != r.char:
                ev = {**ev, "fixed_from": {"channel": r.channel, "char": r.char}}
                r.char = v["char"]
            r.evidence = {**ev, "hou_shape": v}
    return 0


def _part_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """书级部件刻形判法（`groups.part_shape`，`SeedAdmitParams.group_flow_part_shape`）。紧接 wu_shape。→ 放行数净增。

    语义同 `_wu_shape_pass`（刻形说了算、只判本格字＝库首位落在某一对里的格、整理本／字组／库前几名不作数）：
    待审格刻形给字 → 放行（channel `part_shape`）；已放行格刻形给了这一对里的另一个字 → 改字（`evidence.fixed_from`）；
    弃权不动；人裁格、硬护栏格不碰。一个模型挂多对，按本格字找对。"""
    from ..groups import part_shape
    model = part_shape.load(p.group_flow_part_shape)
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            if r.char not in model["_chars"]:
                continue
            pair = part_shape.pair_of(model, r.char)
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("part_shape")
                continue
            v = part_shape.judge(img, pair)
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "part_shape": v}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "part_shape": v, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "part_shape"
                continue
            r.evidence = {**ev, "part_shape": v, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "part_shape", "match", []
            delta += 1
    return delta


def _pair_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None,
                     coord: dict | None = None, model_path: str | None = None, veto: bool = False,
                     nm_5b: dict | None = None) -> int:
    """书级两字刻形二选一（`groups.pair_shape`，`SeedAdmitParams.group_flow_pair_shape`）。紧接 rr_shape。→ 放行数净增。

    只补放待审格：库首位或整理本字是模型两个字之一；模型给的字必须＝整理本字或＝库首位（不引入第三个字、不单凭整理本）。
    整理本（或坐标对位）是这两字以外的第三个字时不判（全唐文 r16：库首位王、整理本三，被王玉模型放成王）。
    已放行格不动，人裁格、硬护栏格不碰；模型弃权（组外、字块怪、分值低）的格照旧送审。通道 `pair_shape`，
    `evidence.pair_shape` 留 nn／score。

    `model_path`：多对模型（`group_flow_pair_shapes`）逐对调用时给；缺省读 `group_flow_pair_shape`。
    `veto`：已放行（非人裁）且放行字是这两字之一的格，模型（带 `veto_thr`）以 |分值|≥veto_thr 判成另一字、组外判别也过 →
    降回待审，doubt `pair_shape_veto`（全唐文 r15：库＋整理本一起把「荆山之玉」「衞伯玉」放成王）。→ 放行数净增（降的算负）。
    `nm_5b`：{字位: 5-b 首位}（`group_flow_pair_shape_nm_5b` 开时给）。护栏 never_match 的格 5-b 首位落在这一对里也判，
    `evidence.pair_shape.nm_5b` 留 5-b 首位；None＝never_match 格照旧不碰。"""
    from ..groups import pair_shape
    model = pair_shape.load(model_path or p.group_flow_pair_shape)
    pair = frozenset(model["chars"])
    miss = patch_missing if patch_missing is not None else {}
    veto_thr = model.get("veto_thr") if veto else None
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.provenance == "human" or r.channel == "human":
                continue
            if r.admit:
                if not veto_thr or r.char not in pair:
                    continue
                try:
                    img = _page_patch(ctx, page, c.col, r.slot, r.sub)
                except PatchUnavailable:
                    if p.patch_missing != "skip":
                        raise
                    miss.setdefault(r.id, []).append("pair_shape")
                    continue
                v = pair_shape.judge(img, model)
                if v["char"] and v["char"] != r.char and abs(v.get("score") or 0.0) >= veto_thr:
                    _demote(r, "pair_shape_veto")
                    r.evidence = {**(r.evidence or {}), "pair_shape": {k: v[k] for k in ("char", "why", "score", "other", "margin", "top") if k in v}}
                    r.admit, r.channel, r.provenance = False, None, ""
                    r.doubts = list(r.doubts or []) + ["pair_shape_veto"]
                    delta -= 1
                continue
            ev = r.evidence or {}
            ds = list(r.doubts or [])
            # 形近护栏 conflict（库首位与整理本两字相冲）正是本解法要判的格，放开；never_match／timeout 及其他硬疑问不碰
            # （`nm_5b` 给了且 5-b 首位落在这一对里时 never_match 也判）
            nm = nm_5b is not None and ev.get("guard") == "never_match" and nm_5b.get(r.id) in pair
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") and d != "护栏:conflict"
                   and not (nm and d == "护栏:never_match") for d in ds) \
                    or (ev.get("guard") in ("never_match", "timeout") and not nm):
                continue
            if "human_unbound" in ev or "human_unbound" in ds:      # 人裁绑丢的格不碰（人裁与对位的冲突交人审）
                continue
            ref = (amap.get(r.id) or (None,))[0] or (coord or {}).get(r.id)     # 现役对位缺这一格时用坐标对位字
            if r.char not in pair and ref not in pair:
                continue
            if ref and ref not in pair:                               # 整理本是第三个字（三/王）：争的不是这两字，不判
                continue
            gp = (ev.get("group") or {}).get("pick")                  # 字组流程已给了别的字（解算有分歧）：不越过
            if gp and gp in pair:
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("pair_shape")
                continue
            v = pair_shape.judge(img, model)
            trail = {k: v[k] for k in ("char", "why", "nn", "score", "other", "margin", "top") if k in v}
            if nm:
                trail["nm_5b"] = nm_5b.get(r.id)
            if v["char"] is None or v["char"] not in (ref, r.char):
                r.evidence = {**ev, "pair_shape": trail}
                continue
            r.evidence = {**ev, "pair_shape": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "pair_shape", "match", []
            delta += 1
    return delta


def _resolve_data_path(v: str) -> str:
    """书级模型路径：绝对路径照用；相对路径先找数据目录（随中心库走），再找工作区。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    q = Path(v).expanduser()
    if q.is_absolute():
        return str(q)
    droot = data_root()
    if droot is not None and (droot / q).exists():
        return str(droot / q)
    return str((workspace_root() or REPO_ROOT) / q)


@lru_cache(maxsize=8)
def _shape_variant_pairs(path: str, fp: str = "") -> frozenset:
    """归属表里刻形且同字异形的对（`attr: shape`、`variant: true`）→ {frozenset({a, b})}。"""
    from ..groups import pair_attr
    return frozenset(frozenset(k) for k, v in pair_attr.load(path).items() if v.get("attr") == "shape" and v.get("variant"))


def _shape_first_ok(p, m, a, b, form) -> bool:
    """`lane_shape_first` 的闸：(a, b) 是表里刻形同字异形，且第 5 步 5a.3 对这一对有终判档（tier ≥3）的证据、倾向正是要放的刻形 `form`。
    库首位覆盖度分不开极近的对（奥奧：020 册 cov 0.99 仍错 2/6），只有分类器证明分得开的对才放。"""
    if not p.lane_shape_first or frozenset((a, b)) not in _shape_variant_pairs(p.lane_shape_first, p.lane_shape_first_fingerprint):
        return False
    rows = (getattr(m, "stage", None) or {}).get("pair") or []
    return any(set(r.get("pair") or "") == {a, b} and (r.get("tier") or 0) >= 3 and r.get("lean") == form for r in rows)


def _shape_first_lib(p, m, lib, ref):
    """`lane_shape_first` 的 lib_variant 放宽：(库首位, 整理本字) 过 `_shape_first_ok`、库首位覆盖度 ≥ `lane_lib_veto` → 返回覆盖度，否则 None。"""
    if not (p.lane_shape_first and p.lane_lib_veto and lib and ref and lib != ref):
        return None
    top = (m.candidates[0] if m and m.candidates else None)
    if top and top[0] == lib and float(top[1]) >= p.lane_lib_veto and _shape_first_ok(p, m, lib, ref, lib):
        return round(float(top[1]), 4)
    return None


def _pair_form_pass(p, out: list, mmap: dict, ctx=None) -> int:
    """放行字按刻形改（`SeedAdmitParams.pair_form`，`groups.pair_clf` 的证据 `glyph_match.stage.pair`）。→ 改字的格数。

    只改字，不改 admit／通道／provenance。读第 5 步 5a.3 的证据行 `{pair, tier, p, lean, char?, cand, rank}`：`char` 只在把握过该对的
    门槛（档 ≥2）时才有。条件见参数说明；同一格里含放行字的几对给了不同的字就都不动（宁缺不错）。"""
    from ..groups import pair_attr
    table = {} if p.pair_form == "-" else pair_attr.load(p.pair_form)
    canon = ctx.book.canonical_char if (ctx is not None and getattr(ctx.book, "codepoints", None)) else None
    n = 0
    for col in out:
        for rec in col.chars or []:
            if not rec.admit or not rec.char or rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            rows = ((getattr(m, "stage", None) or {}).get("pair") or []) if m is not None else []
            want: dict[str, dict] = {}
            for r in rows:
                pr, ch = r.get("pair"), r.get("char")
                if not ch or len(pr or "") != 2 or rec.char not in pr or ch == rec.char or ch not in pr:
                    continue
                if pair_attr.attr_of(table, pr[0], pr[1]) != "shape":
                    continue
                want[ch] = r
            if len(want) != 1:
                continue
            new, row = next(iter(want.items()))
            if canon is not None and canon(new) != new:
                continue
            if p.pair_form != "-" and not (table.get(pair_attr.pair_key(*row["pair"])) or {}).get("variant"):
                # 异字对（表里没标 variant: true）：字形与放行字相反只记证据进复审，不自动改（Sheldon 11-18 同意）
                rec.evidence = {**(rec.evidence or {}), "pair_form_review": {"from": rec.char, "to": new, "pair": row["pair"], "p": row.get("p")}}
                continue
            rec.evidence = {**(rec.evidence or {}),
                            "pair_form": {"from": rec.char, "to": new, "pair": row["pair"], "tier": row.get("tier"),
                                          "p": row.get("p"), "rank": row.get("rank")}}
            rec.char = new
            n += 1
    return n


def _stroke_veto_pass(p, out: list, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """笔画反向护栏（`SeedAdmitParams.stroke_veto`，`groups.stroke_veto`）。→ 降回待审的格数。

    已放行、非人裁、放行字在模型某组里的格：笔画判给了类且≠放行字的类 → 降审，doubt `stroke_veto`。
    笔画弃权不动；字块读不到按 `patch_missing` 处理（skip 时记进 patch_missing、不动）。"""
    from ..groups import stroke_veto as sv
    model = sv.load(p.stroke_veto)
    miss = patch_missing if patch_missing is not None else {}
    n = 0
    for c in out:
        for r in c.chars or []:
            if not r.admit or r.provenance == "human" or r.channel == "human":
                continue
            gid, gm = sv.group_of(model, r.char or "")
            if gm is None or (gm.get("channels") and r.channel not in gm["channels"]):
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("stroke_veto")
                continue
            v = sv.judge(img, gm)
            if v["cls"] is None or v["cls"] == gm["classes"][r.char]:
                continue
            _demote(r, "stroke_veto")
            r.evidence = {**(r.evidence or {}), "stroke_veto": {"group": gid, "cls": v["cls"], "llr": v.get("llr"), "x": v.get("x")}}
            r.admit, r.channel, r.provenance = False, None, ""
            r.doubts = list(r.doubts or []) + ["stroke_veto"]
            n += 1
    return n


def _book_knn_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """字组书级刻形近邻判法（`groups.book_knn`，`SeedAdmitParams.group_flow_book_knn`）。紧接 group_flow。→ 新放行格数。

    只看有库的组里仍待审的格：A 档（近邻票多、距离比够小）给字放行；B 档（票、比稍松）须整理本对位字同字才放（两证）。
    已放行格不动；人裁格、硬护栏格不碰（同 `_rr_shape_pass`）。通道 `book_knn`，`evidence.book_knn` 留票数、距离比与档。"""
    from ..groups import book_knn
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.admit or r.provenance == "human" or r.channel == "human":
                continue
            ev = r.evidence or {}
            gid = (ev.get("group") or {}).get("id")
            if gid not in p.group_flow_book_knn:
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("book_knn")
                continue
            ref = (amap.get(r.id) or (None,))[0]
            v = book_knn.judge(img, book_knn.load(p.group_flow_book_knn[gid]), ref)
            trail = {k: v[k] for k in ("char", "why", "tier", "pick", "votes", "ratio", "nn") if k in v}
            if v["char"] is None:
                r.evidence = {**ev, "book_knn": trail}
                continue
            r.evidence = {**ev, "book_knn": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "book_knn", "match", []
            delta += 1
    return delta


_NEAR_CODES = frozenset({"near_form", "solo_confusable", "iron_confusable_ref"})


def _near_knn_pass(p, out: list, amap: dict, mmap: dict, ctx=None, page: int = 0,
                   patch_missing: dict | None = None, stage: str = "near") -> int:
    """形近护栏格的书级刻形近邻（`groups.near_knn`，`SeedAdmitParams.group_flow_near_knn`）。紧接 book_knn。→ 新放行格数。

    只补放待审格：形近护栏（guard conflict／never_match、疑问 near_form 等）或字组未定的格。候选＝本格字、整理本对位字、
    库首位（不引入第三个字）；候选里有模型 `skip_chars`（己已巳）、或两候选互为异体（码位线管）、或字组在 `skip_groups`、
    或字组已给了别的字 → 不碰。人裁格、硬疑问格不碰。通道 `near_knn`，`evidence.near_knn` 留票数、距离比、全库近邻。
    `near_knn_gap` 开时另收「库没把握、库首位≠整理本」的格（见该参数说明，出口闸＝等于整理本或同码位／异体组）。
    `stage`：`near`（紧接 book_knn，只判护栏格／字组格）；`gap`（各补放通道之后，只判 near_knn_gap 的格——
    排在前面会把 rare_ref／witness3 等本就会放、字也相同的两万多格抢成 near_knn 通道，全唐文 r10，11-05 挪后）。"""
    from ..groups import near_knn
    from ..groups.edge_pairs import _exclude as _edge_exclude
    model = near_knn.load(p.group_flow_near_knn)
    miss = patch_missing if patch_missing is not None else {}
    canon = ctx.book.canonical_char if (p.near_knn_gap and ctx is not None and ctx.book.codepoints) else None
    top3: list = []
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.admit or r.provenance == "human" or r.channel == "human":
                continue
            ev = r.evidence or {}
            ds = list(r.doubts or [])
            if "human_unbound" in ev or "human_unbound" in ds:
                continue
            if any(d in _RR_SHAPE_HARD for d in ds) or ev.get("guard") == "timeout":
                continue
            grp = ev.get("group") or {}
            near = ev.get("guard") in ("conflict", "never_match") or bool(_NEAR_CODES & set(ds))
            ref = (amap.get(r.id) or (None,))[0]
            m = mmap.get(r.id)
            gap = False
            if not (near or grp.get("id")):
                top3 = [c for c, _ in (getattr(m, "candidates", None) or [])[:3]] if stage == "gap" else []
                if not (ref and top3 and top3[0] != ref):
                    continue
                gap = True
            elif stage == "gap":
                continue
            if grp.get("id") in model["skip_groups"] or grp.get("pick"):
                continue
            cands = [x for x in dict.fromkeys((r.char, ref, *(top3 if gap else (getattr(m, "char", None),)))) if x]
            if len(cands) < 2 or model["skip_chars"] & set(cands):
                continue
            if not gap and any(_direct_variant_edge(a, b) and frozenset((a, b)) not in _edge_exclude()
                               for i, a in enumerate(cands) for b in cands[i + 1:]):   # 只认真异体边：只当形近／通假的边（NEVER_SOURCES，如 寵/龍）不挡字形判
                continue
            try:
                img = _page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("near_knn")
                continue
            v = near_knn.judge(img, model, cands)
            trail = {k: v[k] for k in ("char", "why", "pick", "votes", "ratio", "full", "full_votes", "nn") if k in v}
            if gap:
                trail["via"] = "near_gap"
                if v["char"] is not None and not (v["char"] == ref
                                                  or (_direct_variant_edge(v["char"], ref) and frozenset((v["char"], ref)) not in _edge_exclude())
                                                  or (canon is not None and canon(v["char"]) == canon(ref))):
                    trail["why"], v = "abstain:ref_gate", {**v, "char": None}
                    trail["char"] = None
            if v["char"] is None:
                r.evidence = {**ev, "near_knn": trail}
                continue
            r.evidence = {**ev, "near_knn": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "near_knn", "match", []
            delta += 1
    return delta


def _group_flow_pass(p, out: list, amap: dict, mmap: dict, ctx=None, page: int = 0,
                     patch_missing: dict | None = None) -> int:
    """字组统一流程（`SeedAdmitParams.group_flow`）：见 `groups/flow.py`。→ 放行数净增（补放减降级）。"""
    from ..groups.context import WIDTH
    from ..groups.flow import FlowConfig, group_flow_pass
    from ..groups.freq import load as _load_freq, load_vols as _load_vols
    from ..groups.registry import FLOW_GROUPS as GROUPS
    from ..utils.jiazhu_order import sort_by_reading
    # 读序展平，剔除排除名单格（与建 L2 表的 `research/m7/ctx/l2_make_book.py` 同一取法，表键才对得上）
    seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
           if not (r.doubts and "excluded" in r.doubts)]
    # 2026-10-31（A24 查 ctx_l2 没挂上）：本进程记一次文意各层的挂载情况（L2 小头、L3 在线、密钥有无），
    # 日志里一眼看得出 L2 小头／L3 在线有没有进来
    if not _FLOW_MOUNT_LOGGED:
        _FLOW_MOUNT_LOGGED.append(True)
        import os
        _log.warning("文意挂载：L2 小头 %s；L3 在线 %s；GUJI_ANTHROPIC_API_KEY %s", sorted(p.group_flow_models) or "无",
                     sorted(_l3_online(p)) or "无", "已设" if os.environ.get("GUJI_ANTHROPIC_API_KEY") else "未设")
    cfg = FlowConfig(groups=tuple(p.group_flow), delta=p.group_flow_delta, min_cov=p.group_flow_min_cov,
                     top1_cov=p.group_flow_top1_cov, freq_major=p.group_flow_freq_major,
                     freq_vols=_load_vols(p.group_flow_freq) if p.group_flow_freq else {},
                     freq_min_vols=p.group_flow_freq_min_vols,
                     freq_table=_load_freq(p.group_flow_freq) if p.group_flow_freq else {},
                     l2_tables=dict(p.group_flow_tables), l2_models=dict(p.group_flow_models), l2_drift=p.group_flow_l2_drift, joint=True,
                     tolerate_extra={g: str(v) for g, v in p.group_flow_tolerate_extra.items()},
                     lift_shape_ref=p._rt_lift_shape_ref(),
                     ref_alias=dict(p.group_flow_ref_alias),
                     ref_free_groups=frozenset(p.group_flow_ref_free),
                     dissent_keep_form=True, same_writing_keep=frozenset(p.group_flow_same_writing_keep), review_fix_agree=frozenset(p.group_flow_review_fix_agree),
                     dissent_keep=frozenset(p.group_flow_dissent_keep), dissent_margin=p.group_flow_dissent_margin, dissent_l1=frozenset(p.group_flow_dissent_l1), ctx_agree=frozenset(p.group_flow_ctx_agree),
                     ref_pair=frozenset(p.group_flow_ref_pair), ref_pair_margin=p.group_flow_ref_pair_margin, ref_pair_coord=p.group_flow_ref_pair_coord,
                     lift_ref_veto=frozenset(p.group_flow_lift_ref_veto),
                     abstain_ref_ok=p._rt_abstain_ref_ok(),
                     shape_ref_ok=p._rt_shape_ref_ok(),
                     l3_online=_l3_online(p), l3_model=p.group_flow_llm_model, l3_effort=p.group_flow_llm_effort,
                     l3_skip_half=p.group_flow_llm_skip_half, ruling_first=frozenset(p.group_flow_ruling_first), l3_panel=tuple(p.group_flow_llm_panel), l3_panel_groups=tuple(p.group_flow_llm_panel_groups),
                     vis_model=(p.group_flow_llm_model if p.group_flow_vis and p.group_flow_llm_model else None),
                     vis_cache=_vis_cache(),
                     lift_ref_guard=True, provisional=p.group_flow_provisional,
                     coord_outside_skip=True,
                     provisional_to=dict(p.group_flow_provisional_to),
                     pv_ref_gap=p.group_flow_pv_ref_gap, pv_ref_cov=p.group_flow_pv_ref_cov,
                     # 文意 L2 表的键按码位归一再比：邻格放行字／整理本字只差书级码位时不算上下文变了
                     canon=(ctx.book.canonical_char if (ctx is not None and ctx.book.codepoints) else None))

    def blocked(r) -> bool:
        m = mmap.get(r.id)
        guard = getattr(m, "guard", None)
        # 形近护栏（匹配器 `never_match`／`conflict`、疑问 `near_form`）说的正是「几个字形近、字形定不了」——
        # 落在字组里的格本来就该归字组判，不当硬护栏（补放时 `flow.entry` 仍要求紧咬的候选都在组里）。
        if guard in _GROUP_FLOW_OWN_GUARDS:
            guard = None
        ds = [d for d in (r.doubts or []) if isinstance(d, str) and d not in _GROUP_FLOW_OWN_DOUBTS]
        # 异体形近规则先于印章：遮挡不当硬护栏（放行后核对见下）；写法待定（Z06）交给组的刻形解法定形，定不了仍留 form_open
        ds = [d for d in ds if d not in ("occluded", "form_open")]
        return _hard_blocked(ds, guard) or any(d in _GROUP_FLOW_HARD for d in ds)

    def cands_of(cid: str):
        m = mmap.get(cid)
        return list(m.candidates or []) if m is not None else []
    patch_fn = None
    if any(GROUPS[g].flow.needs_patch for g in p.group_flow):
        slots = {r.id: (c.col, r.slot, r.sub) for c in out for r in c.chars or []}
        recs = {r.id: r for c in out for r in c.chars or []}
        miss = patch_missing if patch_missing is not None else {}

        def patch_fn(cid: str):
            col, slot, sub = slots[cid]
            try:
                return _page_patch(ctx, page, col, slot, sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(cid, []).append("group_flow")
                recs[cid].evidence = {**(recs[cid].evidence or {}), "patch_missing": list(miss[cid])}
                return None
    canon = ctx.book.canonical_char if ctx is not None else (lambda c: c)
    # 遮挡格先留底：字组流程放行的字不等于默认字（整理本字）时退回（印章底下字形类解法不可靠）
    occ_snap = ({r.id: (r, r.admit, r.channel, r.provenance, r.char, list(r.doubts or []), dict(r.evidence or {}))
                 for r in seq if (r.evidence or {}).get("occluded") and not r.admit})
    res = group_flow_pass(seq, amap, cands_of, blocked, cfg,
                          ctx_fn=lambda s, i, step: _clf_ctx(s, amap, i, step, WIDTH),
                          patch_fn=patch_fn, canon=canon,
                          veto_refs=_coord_refs(ctx, page, {}) if ctx is not None else None)
    net = res.lifted - res.demoted
    for rid, (r, admit0, ch0, pv0, char0, doubts0, ev0) in occ_snap.items():
        if not r.admit:                       # 没放成：原样退回，免得字组的复核疑问（`_LANE_HARD`）拦掉后面的 R5
            r.doubts, r.evidence = doubts0, ev0
            continue
        if r.char == char0:
            r.evidence = {**(r.evidence or {}), "occluded_variant_first": "group_flow"}
            continue
        r.admit, r.channel, r.provenance, r.char, r.doubts, r.evidence = admit0, ch0, pv0, char0, doubts0, ev0
        net -= 1
    return net


@lru_cache(maxsize=4)
def _human_relabeled_at(db_path: str) -> dict[str, str]:
    """库内审阅改标（`glyph_audit relabel`）重进的人裁刻例 → 入库时刻。`{裸 id: admitted_at}`。

    给 `bindings.rebind_library_shapes` 判「作废之后又改标重进」用：只认 `evidence.via == "glyph_audit"`，
    旧 confirm 事件重放进库的不算（那是被作废的旧裁决）。"""
    import json
    import sqlite3
    from pathlib import Path
    if not Path(db_path).exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute("SELECT instance_id, evidence, admitted_at FROM admissions "
                            "WHERE provenance='human' AND instance_id LIKE 'v2:%' "
                            "AND evidence LIKE '%glyph_audit%'").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    out: dict[str, str] = {}
    for iid, ev, at in rows:
        try:
            via = (json.loads(ev) or {}).get("via") if ev else None
        except (TypeError, ValueError):
            via = None
        if via == "glyph_audit" and at:
            out[iid[3:]] = str(at)
    return out


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
        from ..clustering.glyph_fp import HUMAN_SQL      # 与 human_fingerprint 同一条查询
        rows = conn.execute(HUMAN_SQL).fetchall()
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


#: alt_cut 准入后定列（`AlignRefParams.alt_select="admit"`，2026-11-04，A22 评审过）
ALT_ADMIT_MIN_GAIN = 2        # 备选那遍这一列待审格至少少这么多
ALT_CV_MIN_CELLS = 6          # 正文整字格不到这么多的列不比墨高一致性
ALT_CV_RATIO = 1.2            # 备选那份墨高变异系数 ≤ 主切法 × 这个
ALT_CV_MAX = 0.35             # 且 ≤ 这个
#: 换列要不要求「有字形背书的放行格不比主切法少」。125 页 A/B（11-04）：要求时待审 740→734，不要求 740→695；
#: 不要求时多放的 55 格看图 51 对（多走 coord_fallback/witnesses_coord，半色调、褪色页为主）。
#: 用户 11-04 定要求（B）：换列不让整理本当主证据。
ALT_REQUIRE_BACKED = True
#: 首格切坏守卫（只拦、不放）：备选那份首个正文整字格墨高 > 本列其余正文整字格墨高中位数 × 这个，就不换（03:65:7 一类）
ALT_FIRST_CELL_MAX = 1.6
#: 有字形背书的放行通道（只凭整理本＋证人的 witnesses_coord、follow_ref 不算）
_BACKED = frozenset({"match_ref", "match_solo", "match_solo_ocr", "match_solo_5b", "match_num_run", "match_solo_adapt", "match_solo_cal", "match_lead_5b", "iron", "seal", "group_flow", "ref_lib_coord"})
#: 选列那两遍准入不跑 `p_ref`（换列不让整理本当主证据）：p_ref 在后面几条跟整理本的通道之前把待审格取整理本字，
#: 两遍放得不对称，选列就跟着变（史記 r19 离线开 p_ref：06:26:1 主切法一格两字「陳索」、备选格网切对，开 p_ref 后不换；
#: 1.77 把 p_ref 格按待审算又多换了几列，因为这些格不开 p_ref 时由后面的通道放）。SJ 11-08。
_NO_P_REF: "ContextVar[bool]" = ContextVar("seed_admit_no_p_ref", default=False)


def _opt_product(ctx, kind: str, page: int):
    try:
        return ctx.product(kind, page)
    except Exception:                          # noqa: BLE001
        return None


def _col_stats(adm: PageAdmit, col: int, ref) -> tuple[int, int, int]:
    """一列的（待审格数、有字形背书的放行格数、与坐标字冲突的放行格数）。"""
    c = adm.column(col)
    coord = {(r.slot, r.sub or ""): r.ref_char for r in (getattr(ref, "coord", None) or []) if r.col == col}
    review = backed = conflict = 0
    for r in (c.chars if c else []):
        if r.admit:
            via = (r.evidence.get("lane") or {}).get("via") if isinstance(r.evidence.get("lane"), dict) else None
            if r.channel in _BACKED or (r.channel == "coord_fallback" and via == "lib_coord_primary"):
                backed += 1
            rc = coord.get((r.slot, r.sub or ""))
            if rc and r.char and r.char != rc:
                conflict += 1
        elif "excluded" not in r.evidence:
            review += 1
    return review, backed, conflict


def _ink_cv(chars, col: int) -> tuple[float | None, int]:
    """一列正文整字格（不含夹注半格、抬头格、空格）的墨高变异系数与格数。"""
    import statistics
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    hs = [r.bbox_page[3] - r.bbox_page[1] for r in (cc.chars if cc else [])
          if not getattr(r, "sub", None) and getattr(r, "slot", 0) >= 1 and getattr(r, "patch_key", None)
          and getattr(r, "bbox_page", None)]
    if len(hs) < ALT_CV_MIN_CELLS:
        return None, len(hs)
    m = statistics.fmean(hs)
    return (statistics.pstdev(hs) / m if m else None), len(hs)


def _first_cell_tall(chars, col: int) -> bool:
    """备选那份这一列首个正文整字格墨高是否超过其余正文整字格中位数的 `ALT_FIRST_CELL_MAX` 倍（其余不到 3 格不判）。"""
    import statistics
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    rs = sorted((r for r in (cc.chars if cc else [])
                 if not getattr(r, "sub", None) and getattr(r, "slot", 0) >= 1 and getattr(r, "patch_key", None)
                 and getattr(r, "bbox_page", None)), key=lambda r: r.slot)
    if len(rs) < 4:
        return False
    hs = [r.bbox_page[3] - r.bbox_page[1] for r in rs]
    med = statistics.median(hs[1:])
    return med > 0 and hs[0] > ALT_FIRST_CELL_MAX * med


def _unmatched(adm: PageAdmit, col: int, ref) -> int:
    """一列里没有坐标对位字的格数（不含排除格）：坐标对位字在 `ref.coord` 里按格 id 查。"""
    have = {r.id for r in (getattr(ref, "coord", None) or []) if r.col == col}
    c = adm.column(col)
    return sum(1 for r in (c.chars if c else []) if r.id not in have and "excluded" not in r.evidence)


ALT_TEXT_EQ_GAIN = 2         # 不分行参照页：备选那份这一列与参照文字 equal 的字至少多这么多
ALT_TEXT_RATE_SLACK = 0.05   # 不分行参照页：备选那份这一列放行率比主切法低这么多以内


def _admit_rate(adm: PageAdmit, col: int) -> float:
    """一列放行格占非排除格的比例。"""
    c = adm.column(col)
    rs = [r for r in (c.chars if c else []) if "excluded" not in r.evidence]
    return sum(1 for r in rs if r.admit) / len(rs) if rs else 0.0


def _eq_count(ref, col: int) -> int:
    """一列里对齐到参照文字、且是 equal 段的字数（`align_ref.chars`）。"""
    return sum(1 for r in (getattr(ref, "chars", None) or []) if r.col == col and r.align_op == "equal")


def _note_spans(chars, col: int) -> list[tuple[float, float]]:
    """一列雙行小注格（有 sub 的格）的页内 y 范围，按格号并成一段段。"""
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    ys = sorted((r.bbox_page[1], r.bbox_page[3]) for r in (cc.chars if cc else [])
                if getattr(r, "sub", None) and getattr(r, "bbox_page", None))
    out: list[list[float]] = []
    for y0, y1 in ys:
        if out and y0 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], y1)
        else:
            out.append([y0, y1])
    return [(a, b) for a, b in out]


def _note_region_ok(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, chars_main, chars_alt) -> bool:
    """`alt_note_region`：备选有小注格、主切法在小注范围里放行的字备选也放行，小注范围外待审不多、冲突不多。"""
    spans = _note_spans(chars_alt, col)
    if not spans:
        return False

    def inside(chars, rec_ok):
        cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
        keys = set()
        for r in (cc.chars if cc else []):
            bb = getattr(r, "bbox_page", None)
            if bb and rec_ok(r) and any(a <= (bb[1] + bb[3]) / 2 <= b for a, b in spans):
                keys.add((r.slot, getattr(r, "sub", None) or ""))
        return keys
    in_main = inside(chars_main, lambda r: True)
    if any(sub for _s, sub in in_main):  # 主切法在这里已认出小注：不是「并成大字」那种错，照常比
        return False
    in_alt = inside(chars_alt, lambda r: getattr(r, "sub", None))
    cm, ca = main.column(col), alt.column(col)
    if not in_main or cm is None or ca is None:
        return False
    from collections import Counter
    got_m = Counter(r.char for r in cm.chars if r.admit and (r.slot, r.sub or "") in in_main)
    got_a = Counter(r.char for r in ca.chars if r.admit and (r.slot, r.sub or "") in in_alt)
    if got_m - got_a:                    # 主切法在小注范围里放出的字，备选那份也得放出来
        return False

    return _outside_not_worse(main, alt, col, ref_main, ref_alt, in_main, in_alt)


def _outside_not_worse(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, in_main, in_alt) -> bool:
    """两遍各去掉换切的那段格，其余格备选那遍待审不多、与坐标字冲突不多。"""
    def outside(adm, ref, skip):
        coord = {(r.slot, r.sub or ""): r.ref_char for r in (getattr(ref, "coord", None) or []) if r.col == col}
        rv = cf = 0
        for r in adm.column(col).chars:
            if (r.slot, r.sub or "") in skip or "excluded" in r.evidence:
                continue
            if not r.admit:
                rv += 1
            elif coord.get((r.slot, r.sub or "")) and r.char != coord[(r.slot, r.sub or "")]:
                cf += 1
        return rv, cf
    rm, km = outside(main, ref_main, in_main)
    ra, ka = outside(alt, ref_alt, in_alt)
    return ra <= rm and ka <= km


def _big_region_ok(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, chars_main, chars_alt) -> bool:
    """`alt_note_region` 反方向：主切法把一个大字劈成了 a/b 小注（左右结构的「脉」劈成「永」「月」，两半常常也是字、照样放行），
    备选同一处是一个大字格。备选那些大字格全放行、其余格不更差，就换（脉经 01 41:1、39:6）。"""
    def cols(chars):
        return next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    cm_, ca_ = cols(chars_main), cols(chars_alt)
    cm, ca = main.column(col), alt.column(col)
    if cm_ is None or ca_ is None or cm is None or ca is None:
        return False
    pairs: dict[int, list] = {}
    for r in cm_.chars:
        if getattr(r, "sub", None) and getattr(r, "bbox_page", None):
            pairs.setdefault(r.slot, []).append(r)
    bigs = [r for r in ca_.chars if not getattr(r, "sub", None) and getattr(r, "bbox_page", None) and r.slot >= 1]
    in_main, in_alt = set(), set()
    for slot, rs in pairs.items():
        if {getattr(r, "sub", None) for r in rs} != {"a", "b"}:
            continue
        y0, y1 = min(r.bbox_page[1] for r in rs), max(r.bbox_page[3] for r in rs)
        for b in bigs:
            ov = min(y1, b.bbox_page[3]) - max(y0, b.bbox_page[1])
            if ov > 0.7 * (y1 - y0) and ov > 0.7 * (b.bbox_page[3] - b.bbox_page[1]):
                in_main |= {(slot, r.sub) for r in rs}
                in_alt.add((b.slot, ""))
    if not in_alt:
        return False
    if not all(r.admit for r in ca.chars if (r.slot, r.sub or "") in in_alt):
        return False
    return _outside_not_worse(main, alt, col, ref_main, ref_alt, in_main, in_alt)


def _pick_alt_cols(cand, main: PageAdmit, alt: PageAdmit, ref_main, ref_alt, chars_main, chars_alt,
                   require_matched: bool = False, backed_gain: int = 0, note_region: bool = False) -> list[int]:
    """逐列比两遍准入（错格闸已在 align_ref 剔过候选）：待审少 ≥ `ALT_ADMIT_MIN_GAIN`；与坐标字冲突的放行格不多；
    正文整字格墨高一致（够 `ALT_CV_MIN_CELLS` 格才比）；`ALT_REQUIRE_BACKED` 时有字形背书的放行格也不能少；
    备选首格不能过高（`ALT_FIRST_CELL_MAX`）。"""
    out = []
    for col in cand:
        if note_region and (_note_region_ok(main, alt, col, ref_main, ref_alt, chars_main, chars_alt)
                            or _big_region_ok(main, alt, col, ref_main, ref_alt, chars_main, chars_alt)):
            out.append(col)
            continue
        rm, bm, km = _col_stats(main, col, ref_main)
        ra, ba, ka = _col_stats(alt, col, ref_alt)
        cv_a, _ = _ink_cv(chars_alt, col)
        cv_m, _ = _ink_cv(chars_main, col)
        by_text = False
        if getattr(ref_main, "ref_kind", None) == "text":
            # 不分行参照页（没有坐标字）：放行率不能降（02 24:2 整列真小注换成大字格，格少了待审也少，放行率 13/40→0/20）；
            # 备选那份这一列与参照文字逐字相合（equal）的多出 ALT_TEXT_EQ_GAIN、待审不多，也换——大字被劈成小注时半字
            # 常常也是字、照样放行（「肺」→「月」「巿」），只比待审数挑不出来（脉经 02 31:3 待审 3→2）
            if _admit_rate(alt, col) < _admit_rate(main, col) - ALT_TEXT_RATE_SLACK:
                continue
            em, ea = _eq_count(ref_main, col), _eq_count(ref_alt, col)
            by_text = ea >= em + ALT_TEXT_EQ_GAIN and ra <= rm and ka <= km
        # 待审只少 1 格时，字形背书多出 backed_gain 也换（缺省 0 关）
        by_backed = backed_gain > 0 and ra <= rm - 1 and ba >= bm + backed_gain and ka <= km
        if not by_text and not by_backed and not (
                ra <= rm - ALT_ADMIT_MIN_GAIN and (ba >= bm or not ALT_REQUIRE_BACKED) and ka <= km):
            continue
        if cv_a is not None and cv_m is not None and (cv_a > cv_m * ALT_CV_RATIO or cv_a > ALT_CV_MAX):
            continue
        if _first_cell_tall(chars_alt, col):
            continue
        if require_matched and _unmatched(alt, col, ref_alt) > _unmatched(main, col, ref_main):
            continue
        out.append(col)
    return out


def _merge_admit(main: PageAdmit, alt: PageAdmit, chosen) -> PageAdmit:
    """主切法那遍为底，`chosen` 列换成备选那遍的；页计数按列差补。"""
    if not chosen:
        return main
    ch = set(chosen)

    def cnt(adm, col):
        c = adm.column(col)
        rs = c.chars if c else []
        ex = sum(1 for r in rs if "excluded" in r.evidence)
        au = sum(1 for r in rs if r.admit)
        return au, len(rs) - au - ex, ex
    n_auto, n_review, n_ex = main.n_auto, main.n_review, main.n_excluded
    for col in ch:
        a1, r1, e1 = cnt(main, col)
        a2, r2, e2 = cnt(alt, col)
        n_auto += a2 - a1
        n_review += r2 - r1
        n_ex += e2 - e1
    cols = [alt.column(c.col) if c.col in ch and alt.column(c.col) is not None else c for c in main.columns]
    return PageAdmit(page=main.page, n_auto=n_auto, n_review=n_review, n_excluded=n_ex,
                     columns=cols, alt_cols=sorted(ch))


#: seed_admit 跑一页时（且这一页有换备选切法的列）：(册 id, AltView)；`_page_patch` 按册 id 取图时用
_ALT_SCOPE: "ContextVar[tuple[str, object] | None]" = ContextVar("seed_admit_alt_scope", default=None)


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
    if not hasattr(src, "image"):
        # 按册 id 取图（组内检索、铁证尺度等）：本页换过备选切法的列要换键（`products.alt_view`）
        scope = _ALT_SCOPE.get()
        if scope is not None and scope[0] == src:
            from ..products.alt_view import alt_patch_key
            key = alt_patch_key(key, scope[1].alt_cols(page))
        elif scope is None:                 # 离线审计脚本：读产物仓里的 align_ref
            from ..products.alt_view import resolve_patch_key
            key = resolve_patch_key(src, key)
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


@lru_cache(maxsize=4)
def _store_conn(db_path: str):
    import sqlite3
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)


def _store_ex_raw(db_path: str, cid: str):
    """`iron_ex_from_store`：人裁刻例 `cid`（`_iron_context.human_ids` 里去了 `v2:` 前缀的 id）在字形库里的图，
    裁回 canonical 图里原裁切那一块（背景是纯 255，原裁切区域里不全是 255）。库里没有 → None。"""
    import cv2
    import numpy as np
    row = _store_conn(db_path).execute(
        "SELECT patch_png FROM instances WHERE instance_id IN (?, ?) ORDER BY instance_id = ? DESC LIMIT 1",
        (f"v2:{cid}", cid, f"v2:{cid}")).fetchone()
    if row is None or row[0] is None:
        return None
    img = cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise PatchUnavailable(f"字形库刻例图解不出来: {cid}")
    ys, xs = np.nonzero(img != 255)
    if len(ys) == 0:
        return None
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _iron_decide(book, page: int, col: int, r, iron_ctx, scale: float,
                 norm_stroke: int | None, missing: list | None = None,
                 store_db: str | None = None) -> str | None:
    """这一格铁证放行的字，放不了返回 None。`r` 是 `glyph_match` 产物里的逐格记录
    （`.id/.slot/.sub/.candidates/.verdict/.char/.cov`），候选集重算方式与
    `iron_shadow.py` 的批处理壳完全一致——两边现在都读同一个 `iron_with_disc`。
    `store_db`（`iron_ex_from_store`）：刻例图从这个字形库取，不读缓存。"""
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
        if cid not in raw_cache and store_db is not None:
            raw_cache[cid] = x = _store_ex_raw(store_db, cid)
            if x is None and missing is not None:
                missing.append(cid)
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
            if pth is None and missing is not None:
                missing.append(cid)
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


_SOLO_COORD_NUMS = frozenset("一二三四五六七八九十廿卅")


def _solo_coord_dissented(r, vmap, coord: dict) -> bool:
    """`solo_coord_dissent`：坐标对位给了实字、与 match_solo 放行字语义不同 → True（要拦）。
    放行字＝库 same 取库字，否则库候选 top1（同 `_pick_char` 对 solo 通道的取法）。豁免见参数说明：
    坐标字非汉字（私用码／占位）、两边都是数字（坐标对位在数字处常漂）、语义同字（异体）。"""
    cr = coord.get(r.id)
    if cr in (None, "", *GAP_CHARS) or len(cr) != 1 or not _ruling_han(cr):
        return False
    cands = list(r.candidates or [])
    ch = r.char if r.verdict == "same" and r.char else (max(cands, key=lambda t: t[1])[0] if cands else None)
    if not ch or vmap.semantic(cr) == vmap.semantic(ch):
        return False
    return not (cr in _SOLO_COORD_NUMS and ch in _SOLO_COORD_NUMS)


def _lib_cov(cands, ch: str) -> float | None:
    return max((v for c, v in cands if c == ch), default=None)


def _context_variant_tie(dec, cands, vmap, ratio: float, lib_gap: float, canon=None) -> bool:
    """`context_variant_form_guard`：context 放行字在 ranked 里有语义同字、字面不同的对手（概率 ≥ ratio × 放行字概率），
    库形又分不开它俩 → True（context 不该在异体里选形）。"""
    ranked = getattr(dec, "ranked", None) or []
    ch = dec.char
    p1 = next((v for c, v in ranked if c == ch), None)
    if not p1:
        return False
    norm = canon or (lambda c: c)
    sem = vmap.semantic(ch)
    c1 = _lib_cov(cands or [], ch)
    for c, v in ranked:
        if c == ch or norm(c) == norm(ch) or vmap.semantic(c) != sem or v < ratio * p1:
            continue
        c2 = _lib_cov(cands or [], c)
        if c2 is None:
            continue                      # 对手不在库候选里：库形分得开
        if c1 is None or c1 - c2 < lib_gap:
            return True
    return False


def _context_lib_dissent(ch: str, cands, vmap, gap: float, absent_cov: float) -> bool:
    """`context_lib_dissent_gap`：库 top1 与 context 字语义不同，context 字（含同义异体）在库里落后 ≥ gap，
    或不在库候选里而 top1 cov ≥ absent_cov。没有库候选 = 不拦。"""
    if not cands:
        return False
    c1, v1 = max(cands, key=lambda t: t[1])
    sem = vmap.semantic(ch)
    if vmap.semantic(c1) == sem:
        return False
    vc = max((v for c, v in cands if vmap.semantic(c) == sem), default=None)
    return v1 >= absent_cov if vc is None else v1 - vc >= gap


def _iron_ctx_dissent(iron_char: str, dec, cands, vmap, prob: float, gap: float) -> bool:
    """`iron_ctx_guard`：上下文第一名与铁证字语义不同、概率 ≥ prob，且在库里与铁证字近平手。"""
    ranked = getattr(dec, "ranked", None) or []
    if not ranked:
        return False
    top, p = ranked[0]
    if p < prob or vmap.semantic(top) == vmap.semantic(iron_char):
        return False
    ci, ct = _lib_cov(cands or [], iron_char), _lib_cov(cands or [], top)
    return ci is not None and ct is not None and ci - ct < gap


#: match_solo 系：只靠库形状（± OCR/CNN 背书）放行、没有整理本的通道（`solo_ctx_veto` 等用；`solo_confusable_guard` 已于 W2 删）
_SOLO_CHANNELS = frozenset({"match_solo", "match_solo_ocr", "match_solo_5b", "match_num_run", "match_solo_adapt",
                            "match_solo_cal", "match_lead_5b"})

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


def _is_consensus_same(r) -> bool:
    return r.verdict == "same" and str(getattr(r, "via", None) or "").startswith("consensus")


def _consensus_fallback(match: PageMatch, amap: dict) -> PageMatch:
    """`consensus_fallback`：库字 ≠ 对位整理本字（或没有整理本字）的共识升档 same 退回 unsure（升档前的样子）。

    其余格对象原样不动（`is` 相同），没有要退的格时返回原 `match`。"""
    def back(r):
        if not _is_consensus_same(r):
            return r
        al = amap.get(r.id)
        if al is not None and al[0] and al[0] == r.char:
            return r
        return r.model_copy(update={"verdict": "unsure", "char": None, "matched_id": None, "via": None})

    cols, changed = [], False
    for cc in match.columns:
        if not cc.ok:
            cols.append(cc)
            continue
        chars = [back(r) for r in cc.chars]
        if any(a is not b for a, b in zip(chars, cc.chars)):
            changed = True
            cc = cc.model_copy(update={"chars": chars})
        cols.append(cc)
    return match.model_copy(update={"columns": cols}) if changed else match


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
    past = set()
    if ref is not None:
        from .align_ref_coord import COORD_PAST_LEAF
        past = {int(k) for k, v in ref.coord_fallback.items() if v == COORD_PAST_LEAF}
    if p.occluded_ref_empty_blank and ref is not None:
        past |= {int(k) for k, v in ref.coord_fallback.items() if v == "整理本行为空"}
    manual = _manual_seal_cells(ctx, page) if p.occluded_manual_seal_blank else set()
    out: dict[str, tuple[float, str | None, str]] = {}
    for cc in match.columns:
        # 整理本这半叶没有这一列、现役对位也没给这一列任何字 → 整理本说这儿没字
        # （`occluded_seal_align_yield`：印纹上被现役对位硬配的字不算）
        blank_col = cc.col in past and not any(
            r.id in amap and not (p.occluded_seal_align_yield and (cc.col, r.slot, r.sub or "") in hit)
            for r in cc.chars)
        for r in cc.chars:
            dens = hit.get((cc.col, r.slot, r.sub or ""))
            if dens is None:
                continue
            seal_blank = (r.id not in coord
                          and ((blank_col and p.occluded_seal_align_yield)
                               or (cc.col, r.slot, r.sub or "") in manual)
                          and not _lib_reads_char(r, p.occluded_seal_keep_cov))
            if seal_blank:
                # 整理本说这儿没字／人定印框：印纹上的现役对位字不作默认字
                out[r.id] = (dens, None, "coord_blank")
            elif r.id in coord and is_gap(coord[r.id]):
                # 逐列本里没有码表的 PUA 生僻字占位：知道这儿有字、不知道是哪个
                out[r.id] = (dens, None, "coord_pua")
            elif r.id in coord:
                ch = coord[r.id]
                out[r.id] = (dens, ch or None, "coord" if ch else "coord_blank")
            elif r.id in amap:
                out[r.id] = (dens, amap[r.id][0], "align")
            elif blank_col:
                out[r.id] = (dens, None, "coord_blank")
            else:
                out[r.id] = (dens, None, "none")
    return out


def _lib_reads_char(r, keep_cov: float) -> bool:
    """库认得出这一格（判 same，或判 unsure 且首位相似度 ≥ `keep_cov`）：印压真字，不按印纹判空。"""
    if r.verdict == "same":
        return True
    top = max((float(c[1]) for c in (r.candidates or [])), default=float(r.cov or 0.0))
    return r.verdict == "unsure" and top >= keep_cov


def _manual_seal_cells(ctx: RunContext, page: int) -> set[tuple[int, int, str]]:
    """人定印框（`seals` 产物里 `source="manual"` 的印）压着的格 {(col, slot, sub)}；重叠门槛同遮挡判据
    （大印 `OCC_SEAL_OVERLAP`、小印 `OCC_CRISP_OVERLAP`）。没有 `seals` 产物或 Step3 字格就是空集。"""
    from .occlusion import OCC_CRISP_OVERLAP, OCC_SEAL_OVERLAP, seal_overlap_cells
    has = getattr(ctx, "has_product", None)
    if has is None or not has("seals", page):
        return set()
    seals = [s for s in ctx.product("seals", page).seals if s.source == "manual"]
    cells = _opt(ctx, "cells", page) if seals else None
    if cells is None:
        return set()
    return (set(seal_overlap_cells(cells, seals, "stain", OCC_SEAL_OVERLAP))
            | set(seal_overlap_cells(cells, seals, "crisp", OCC_CRISP_OVERLAP)))


_FOLLOW_REF_HOOKS = "open_guji_cv.impl.keben.follow_ref_hooks"


def _follow_ref_rival_hook(ctx: RunContext):
    """书级钩子 `impl/keben/follow_ref_hooks.rival_skip`（书仓 `code/` 覆盖才有；缺省 None）。"""
    import importlib
    from ..core.seg_set import resolve
    return getattr(importlib.import_module(resolve(ctx.book, _FOLLOW_REF_HOOKS)), "rival_skip", None)


def _lane_variant_hook(ctx: RunContext, name: str = "variant_norm"):
    """书级钩子 `impl/keben/follow_ref_hooks.<name>`（`variant_norm`／`variant_rank`；书仓 `code/` 覆盖才有；缺省 None）。
    书仓模块没写这个名字也当 None（11-13 前写的覆盖模块只有 rival_skip，11-16 前的没有 variant_rank）。"""
    import importlib
    from ..core.seg_set import resolve
    return getattr(importlib.import_module(resolve(ctx.book, _FOLLOW_REF_HOOKS)), name, None)


def _lane_variant_rank(hook, lane: str, char: str, cur: str | None, m, topk: int, variant_pair,
                       lib: str | None) -> tuple[str, list] | None:
    """调书级钩子 `variant_rank`：把 `char` 的异体在现字（名次 0）与库前 `topk` 名（名次 1…）里各排第几告诉它。
    → (放行字, [[名次, 异体, cov|None], …])；钩子不放 → None。"""
    cands = [(c, round(float(v), 4)) for c, v in ((m.candidates or [])[:max(topk, 0)] if m else [])]
    forms = ([[0, cur, None]] if cur and variant_pair(cur, char) else []) + [
        [i, c, v] for i, (c, v) in enumerate(cands, 1) if variant_pair(c, char)]
    if not forms:
        return None
    vr = hook(lane=lane, char=char, forms=tuple(tuple(f) for f in forms), cur=cur, cands=tuple(cands), lib=lib)
    return (vr, forms) if vr else None


def _edge_pair_excluded(a: str, b: str) -> bool:
    """`a`／`b` 这一对在本书假边表 `edge_pair_exclude.tsv` 里（`replace_form_edge_exclude`）。"""
    from ..groups.edge_pairs import _exclude
    return frozenset((a, b)) in _exclude()


def _coord_refs(ctx: RunContext, page: int, cache: dict) -> dict[str, str]:
    """本页 `align_ref.coord` → {字位 id: 整理本字（空串 = 坐标对位说是空格位）}；页内缓存。"""
    if "coord" not in cache:
        ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
        cache["coord"] = {c.id: _ref_placeholder_norm(c.ref_char) for c in (ref.coord if ref else [])}
    return cache["coord"]


def _ref_placeholder_norm(ch: str | None) -> str | None:
    """整理本「以图代字」的缅甸字母占位（U+1000–109F，史記整理本直接留着）当缺字〓看：
    不然 `ctx_guard_ref` 会把占位符当整理本字设成默认字，出单、导出露出 ခ（A24 R01 深挖，
    史記 03:114:2:20、08:122:2:16、10:3:6:7b；sheldon 11-07 同意）。"""
    if ch and len(ch) == 1 and 0x1000 <= ord(ch) <= 0x109F:
        return GAP_IMAGE
    return ch


def _context_guard(p: "SeedAdmitParams", r, ctx_char: str, coord: dict[str, str],
                   vmap) -> tuple[str, str | None] | None:
    """context 通道放行前的最后一道闸（overview#333，G1 道）。命中返回 `(doubt, 默认字|None)`，
    不命中 None。三条各有开关（`context_guard_*`），依次判，先中先返回；缺信号一律弃权：
    没有坐标对位就不看整理本。

    - `ctx_guard_diff`：库判 diff 且 cov < `context_guard_cov`；
    - `ctx_guard_ref_blank`：坐标对位说此位是空格、库又不是 same → 字块不是字；
    - `ctx_guard_ref`：坐标对位的整理本字与 context 字语义不同、库不是 same → 默认字取整理本。
    """
    if p.context_guard_diff and r.verdict == "diff" and r.cov < p.context_guard_cov:
        return "ctx_guard_diff", None
    ref = coord.get(r.id)
    if ref is not None and r.verdict != "same" and not is_gap(ref):
        if ref == "":
            if p.context_guard_ref_blank:
                return "ctx_guard_ref_blank", None
        elif p.context_guard_ref_prefer and vmap.semantic(ref) != vmap.semantic(ctx_char):
            return "ctx_guard_ref", ref
    return None


def _rare_cp(ch: str | None) -> bool:
    """码位不在 CJK 基本区（U+4E00–9FFF）：扩展区、部首、兼容区都算罕用。"""
    return bool(ch) and not ("一" <= ch <= "鿿")


def _garble_guard(p: "SeedAdmitParams", r, ctx_char: str, witnesses, vmap) -> str | None:
    """context 通道放行乱码的护栏（`context_garble_guard`，overview#427）。命中返回 doubt 名。

    `witnesses`：整理本对齐字、坐标对位字、OCR 候选（None/空串/〓 不算证人）。有一个与
    context 字语义相同就是有背书，不拦；其余按 shape → rare 依次判（原 run 一条 2026-10-21 起缺省关、无书开，2026-11-23 删）。"""
    sem = vmap.semantic(ctx_char)
    if any(w and not is_gap(w) and vmap.semantic(w) == sem for w in witnesses):
        return None
    if r.cov < p.context_garble_cov:
        return "ctx_garble_shape"
    if _rare_cp(ctx_char) and r.cov < p.context_garble_rare_cov:
        return "ctx_garble_rare"
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


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：缺了就 None，不炸——OCR 要引擎、上下文要语料，都可能没有。"""
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


class _CodepointMap:
    """VariantMap 的包装：书级 `codepoints:` 声明过的码位先归到册指定的码位再查语义
    （巻→卷 后 semantic(巻)==semantic(卷)）。没声明的字原样查。"""

    def __init__(self, base, book):
        self._base, self._book = base, book

    def semantic(self, char: str) -> str:
        return self._base.semantic(self._book.canonical_char(char))

    def __getattr__(self, name):
        return getattr(self._base, name)


def _parse_semantic_extra(spec: str) -> dict[str, str]:
    """`semantic_extra`「异体=正字,…」→ {异体: 正字}；两边都要是单字，写错直接报错（书配置写错别悄悄不生效）。"""
    out: dict[str, str] = {}
    for item in (x.strip() for x in spec.split(",")):
        if not item:
            continue
        a, sep, b = item.partition("=")
        a, b = a.strip(), b.strip()
        if not sep or len(a) != 1 or len(b) != 1 or a == b:
            raise ValueError(f"semantic_extra 写法不对：{item!r}（要「异体=正字」，两边各一个字）")
        out[a] = b
    return out


class _ExtraSemanticMap:
    """VariantMap 的包装：书级 `semantic_extra` 补的对先换到正字再查语义（圗→圖 后 semantic(圗)==semantic(圖)）。
    只管语义层，字形层（候选、放行字）照旧是刻形。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._base.semantic(self._extra.get(char, char))

    def __getattr__(self, name):
        return getattr(self._base, name)


class _PairAwareMap:
    """VariantMap 的一次性包装：额外把几个形映到指定语义（本书人确认过的 T2 转换对）。
    只给 `admission_decision` 这一次调用用，不改全局语义表。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._extra.get(char) or self._base.semantic(char)

    def __getattr__(self, name):
        return getattr(self._base, name)


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
    """这个字在不在任何一张形近表里（按字，不看对手是否在候选里）。"""
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
        if w and not is_gap(w) and w in near and vmap.semantic(w) != vmap.semantic(iron_char):
            return w
    return None


def _iron_coord_dissent(iron_char: str, ref: str | None, vmap) -> bool:
    """`iron_coord_guard` 用：坐标对位字与铁证字语义不同、也没有直接异体边。空串（空格位）、`〓`、None 不算证人。"""
    if not ref or is_gap(ref) or ref == iron_char:
        return False
    if vmap.semantic(ref) == vmap.semantic(iron_char):
        return False
    return not _direct_variant_edge(iron_char, ref)


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
