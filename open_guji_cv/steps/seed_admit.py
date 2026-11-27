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



from .seed_admit_common import (  # noqa: F401  CV4 整理 PR3c（2026-11-26）搬出去的，这里 re-export
    PatchUnavailable,
    REFERENCE_TRUST_COV,
    REFERENCE_TRUST_GAP,
    REFERENCE_TRUST_TOPK_GAP,
    _ALT_SCOPE,
    _HOU,
    _IRREGULAR_SOURCES,
    _LANE_CLS_CODES,
    _LANE_GARBLE,
    _LANE_HARD,
    _LANE_R1_CLASSES,
    _LANE_REF_REVIEW,
    _NEAR_CODES,
    _PairFacts,
    _RARE_REF_HARD,
    _REF_LIB_COORD_DOUBTS,
    _REF_LIB_COORD_SKIP,
    _RR,
    _RR_SHAPE_HARD,
    _RivalFacts,
    _SEEN_HARD,
    _VIS_RULING_HARD,
    _WU,
    _blind_ref_behind,
    _coord_codepoint_norm,
    _demote,
    _direct_variant_edge,
    _fold_hold,
    _group_img_dissent,
    _hard_blocked,
    _irregular_ref_gap,
    _is_consensus_same,
    _is_han,
    _is_hanzi,
    _lane_class,
    _lane_variant_rank,
    _log,
    _never_pairs,
    _pair_facts,
    _parse_follow_ref,
    _parse_follow_ref_seen,
    _parse_pua_rules,
    _rare_ref_coord_ok,
    _rare_ref_nf_ok,
    _raw_same_char,
    _ref_regulars,
    _seal_lib_same,
    _seal_page_shifted,
    _seal_variant_norm,
    _shape_first_lib,
    _shape_first_ok,
    _shape_variant_pairs,
    _unbound_shifted,
)
from .seed_admit_lanes import (  # noqa: F401  CV4 整理 PR3c（2026-11-26）搬出去的，这里 re-export
    _blank_ink_pass,
    _consensus_lib_pass,
    _edge_pair_pass,
    _evict_review_pass,
    _follow_ref_pass,
    _human_unbound_pass,
    _p_ref_pass,
    _pair_form_pass,
    _pua_rule_pass,
    _rare_ref_pass,
    _rare_ref_sparse_pass,
    _ref_lib_5b_veto_pass,
    _ref_lib_coord_pass,
    _ref_topk_pass,
    _review_lanes_pass,
    _solo_5b_pass,
    _symbol_ref_blank_pass,
    consensus_lib_decide,
    follow_ref_decide,
    rare_ref_decide,
    rare_sparse_decide,
    ref_lib_5b_veto_decide,
    ref_lib_coord_decide,
    ref_topk_decide,
    seen_pair_decide,
    solo_5b_decide,
)
from .seed_admit_shapes import (  # noqa: F401  CV4 整理 PR3c（2026-11-26）搬出去的，这里 re-export
    _book_knn_pass,
    _hou_shape_pass,
    _near_knn_pass,
    _pair_shape_pass,
    _part_shape_pass,
    _rr_shape_pass,
    _stroke_veto_pass,
    _wu_shape_pass,
)
from . import seed_admit_common as _C
from .seed_admit_common import _edge_pair_excluded, _page_patch  # noqa: F401  只供 import；本模块经 _C 调用，测试换它要 setattr(seed_admit_common, …)


@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id="seed_admit", title="C1 进库准入", version="1.82", unit="cell",   # 1.82：规则 A（rare_ref／rare_ref_sparse）不在折叠组待文意格（evidence.fold_pending）里拿整理本字定组内字（殿本 vol41:55:4:19「六日僧道」被放成日，r7 殿本影响 2 格，A24 11-08）；（#1277 的 1.82 撤回为 1.81：group_flow_llm_half_groups 缺省空时逐字节不变，改用 code_equiv 登记，免得各书 seed_admit 全量过期；A31 11-08）（solo_5b 刻例门槛改读可信刻例数 trusted_keben_counts、放行格带 evidence.no_glyph_lib、solo_5b_borrow_db 同族借库：同样不升版本号，缺省关、逐字节不变、code_equiv 登记，A24 11-08）1.82：group_flow_llm_half_groups 这几组的夹注半格不受 llm_skip_half 限制、照样记 L3 问（书级，缺省空、不进参数 dump；SJ 史記 H01 半格写不了裁定键，A24 11-08）；（solo_5b 不升版本号：缺省关、逐字节不变、code_equiv 登记，免得各书 seed_admit 全量过期）solo_5b_cov 无参照格「库首位＋5-b 作证」放行通道 match_solo_5b（书级，缺省关、关时不进参数 dump；全唐文 001–003 总目／韵编，形近字线 11-08，A24 定口径）；1.81：fold_aspect_ctx_veto 的组内文意一支不认 L1 规则、带概率的要到阈值（SJ 史記 06:46「李奇曰」被 ry-ext-r1 误否决，A24 11-08）；1.80：fold_aspect_ink 折叠宽高改量墨迹主体（字组 ry_shape ratio），书级缺省关、不进参数 dump（SJ 史記看图框比字宽，A24 11-08）；1.79：alt_select="admit" 开 p_ref 时选列另跑两遍不带 p_ref 的准入来比（撤 1.77 的「p_ref 格按待审算」：那些格不开 p_ref 时多由后面的通道放，按待审算多换了列；史記 r19 06:26 回放，SJ 11-08）；1.78：fold_aspect_ctx_veto 也认字组文意解法给的另一个字（开着时；SJ 史記 01:45「日講官」宽高比 1.15 判曰没挡住，A24 11-08）；1.77：alt_select="admit" 换列比较时 p_ref 放的格按待审算（开 p_ref 后主切法错位列不再换备选、坏格被整理本字盖住；史記 r19 06:26:1、03:88:4，SJ 11-08）；1.76：p_ref_min_cov（缺省 0.8 开，缺省值不进参数 dump；p_ref 不取库里认不出［diff 档、cov<0.8］的格，挡住切分坏格被整理本字盖住；史記 r19 离线重跑 7 格，SJ 11-08，A24）；1.75：follow_ref_seen_conflict follow_ref_seen 也接「护栏 conflict」格（候选前两名恰是 ref 与 seen 对里另一形；书级，缺省关、关时不进参数 dump；A24 N01 第 7 轮复查 11-08，殿本 七／𠤎 字形相同 28 格按整理本）；1.74：lane_group_img_veto 补放三通道不放字组图像判官（rr_img）反对的字（书级，缺省关、关时不进参数 dump；A23 Z02 r7 人入 2 格，11-08）；1.73：group_flow_ref_pair／ref_pair_coord 不把共字组搭档的码位解法（`组:codepoint`，只回报码位归一目标、无图像证据）当反对票（只对开了这两项的书生效；A24 Z02 r7，殿本 sy 山由出 4 格看图全是山）；1.72：fold_occluded_lib_max_cov 遮挡格库首位无把握（cov<阈值）时仍按整理本字归组（书级，缺省关、关时不进参数 dump；殿本 r7 D01 己已巳 19 格，A24 11-08）；1.71：p_ref_irregular_gap（书级，缺省关、关时不进参数 dump；整理本字是异体写法［槪寳囘竒厯］且字族 cov 贴近机器字时取整理本字、不受 p_ref_max_cov 约束；殿本 r7 P01 异体被库认成形近字 83 格＋同类，A24 11-08）；1.70：暂归一兜底放宽 group_flow_pv_ref_gap（缺省 0.01 开、缺省值不进参数 dump；整理本与库首位都是某组暂归一写法、首位 cov≥0.95、领先组外最好候选≥0.01 时，分差内有组外形近字也进组兜底；A24 V01 第 7 轮 11-08，殿本 𨽻→𨽾 被 諫據綠裁 紧咬拦下 20 格）；1.69：group_flow_dissent_keep_form（dissent_keep 认 ids 弃权票刻形＝放行字，缺省开；A24 Z03 11-08，r7 殿本一二 19 格）；1.68：fold_ctx_vias／fold_ctx_strong 折叠组认字组文意路已给的字（书级，缺省空、不进参数 dump；A24 H01 第 7 轮复盘 11-08，殿本 L3 strong 68 格盲读全同）；1.67：pua_code_admit 族里是别的码表字的字不算互证（F1001 族 乖垂埀 是形近异字合码，乖是 EA36 的表字；第 7 轮 3 格垂放成乖；A24 11-08）；1.66：私用码表的殆知阁码本身也登记（pua_v2_codes），格→码事件可写殆知阁码（新图源文本层对不上、按整理本窗口回查的格；A24 R01 第 7 轮 38 格）；1.65：pair_shape 整理本／坐标对位是两字以外的第三个字时不补放（全唐文 r16 三→王，库首位王、整理本三，QTW 11-07）；1.64：alt_require_matched 备选格网比主切法多出没有坐标字的格就不换列（书级，缺省关、关时不进参数 dump；史記 r18 02:106:7，A24）；1.63：group_flow_lift_shape_ratio(_jiazhu) 给 lift_shape_ref 加宽高门、reference_trust_skip 让 reference_trust 自动并入的各项可单独关（书级，缺省空、不进参数 dump；SJ 史記 r18 日曰 71 格，A24 11-07）；1.62：lane_coord_blind_guard 坐标对位兜底「靠证人同意参校字」一支，参校字在库里刻例≥N却不在库候选、库首位 cov≥0.98 → 留审（书级，缺省关、关时不进参数 dump；Z04 殿本错放 餘／三，A23 建议，A24）；1.61：group_flow_same_writing_keep／group_flow_review_fix_agree（A24 Z03 11-07，见 1.59）；1.60：group_flow_ctx_agree 书级（缺省关）dissent_keep／ref_pair 的组还要本组文意同意放行字；1.59：坐标对位的缅甸字母占位（整理本以图代字，史記）当〓看，机器字不再取占位符（A24 R01 深挖 11-07，sheldon 同意）；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.57：group_flow_dissent_l1 书级（缺省关）复核时 L1 规则孤证＋整理本×ids 同意放行字不降审（A24 Z02 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸
        consumes=("glyph_match", "context_decision", "align_ref", "char_index"),
        optional_consumes=("rare_candidates", "seals", "glyph_analyzer"),
        optional_consumes_when=(("rare_candidates", "rare_ref"), ("rare_candidates", "symbol_review"), ("rare_candidates", "rare_ref_sparse"),
                                ("rare_candidates", "solo_5b_cov"), ("rare_candidates", "book_lanes"),
                                ("rare_candidates", "ref_lib_5b_veto"), ("glyph_analyzer", "group_flow_near_p")),
        produces=("seed_admit",),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.steps.seed_admit_params",   # 参数类与参数表（2026-11-23 从本模块搬出，SPLITS 合回）
                   "open_guji_cv.steps.seed_admit_common",   # 共用工具／放行通道与护栏／字形判官（2026-11-26 CV4 PR3c 从本模块搬出，SPLITS 合回）
                   "open_guji_cv.steps.seed_admit_lanes",
                   "open_guji_cv.steps.seed_admit_shapes",
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
                   "open_guji_cv.impl.keben.follow_ref_hooks",
                   # 2026-11-24 书级放行通道钩子（缺省 None；全唐文书仓覆盖）。指纹靠 code_equiv.SPLITS 不变
                   "open_guji_cv.impl.keben.admit_lanes"),
        # 册配置 `iron_gate:` 开不开进指纹——同 glyph_match 的 norm_stroke 那条口子，
        # 不然开关翻了、产物没过期（书级布尔量，不是 Params 字段，走这条路）。
        # `codepoints:` 同理（2026-09-27 加，`ref_lib_variant_guard` 的可信边判据读它）。
        book_deps=("iron_gate", "codepoints"),
        # 路径不进指纹（2026-09-29 K238）：db_path 留空填本机绝对路径；其余三个是「显式
        # 给才有值」的文件路径。内容各有指纹把关：human_fingerprint / variants_fingerprint /
        # note_fingerprint / exclusions_fingerprint（都只认文件名 + 内容哈希）。
        path_params=("db_path", "variants", "note_lexicon", "exclusions", "shadow_model",
                     "group_flow_freq", "group_flow_tables", "group_flow_models", "group_flow_rr_shape", "group_flow_wu_shape", "group_flow_hou_shape", "group_flow_part_shape", "group_flow_pair_shape", "group_flow_pair_shapes", "group_flow_book_knn", "group_flow_near_knn",
                     "stroke_veto", "pair_form", "lane_shape_first"),
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
        p = no_ref_page_params(p, page, ctx.book)
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
                            if not (p.replace_form_edge_exclude and _C._edge_pair_excluded(_top, align_char)):
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
            # `ruling_by_u`：字组文意在线问前查缓存时，窗口键没中再按本格 u 查同版本裁定（CV0 T3 11-25）；关时不设、不读账
            _um = _uid_map(p, ctx, page) if getattr(p, "ruling_by_u", False) else None
            if _um:
                from ..feedback.rulings import UMAP_SCOPE
                _tok = UMAP_SCOPE.set(_um)
                try:
                    d_gf = _group_flow_pass(p, out, amap, mmap, ctx, page, patch_missing)
                finally:
                    UMAP_SCOPE.reset(_tok)
            else:
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
                                  dmap=dmap if p.fold_aspect_ctx_veto is not None else None,
                                  cells_sha=_anchor_cells_sha(ctx, page) if (p.fold_ruling_first or not p.fold_ref_char) else None,
                                  umap=_uid_map(p, ctx, page) if (p.fold_ruling_first or not p.fold_ref_char) else None)
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
                                 mmap_raw=mmap_raw,
                                 lacuna_only=p.solo_5b_scope == "no_ref" and not _no_ref_page(ctx.book, p, page))
            n_auto += d_s5
            n_review -= d_s5
        if p.book_lanes:
            # 5b-b 书级无参照补放（升）：书仓 code/ 覆盖 impl/keben/admit_lanes.noref_lanes 才有（全唐文 001–003 的
            # solo_adapt／num_run／solo_cal／lead_5b 四条通道 2026-11-24 搬进书仓，位置同原来）
            d_bl = _admit_lanes_hook(ctx)(out=out, mmap=mmap, amap=amap, rare=_opt(ctx, "rare_candidates", page),
                                          coord=_coord_refs(ctx, page, coord_cache), params=p.book_lanes,
                                          facts=_AdmitFacts(ctx))
            n_auto += d_bl
            n_review -= d_bl
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
        d_vr = _vis_ruling_pass(p, out, amap, cells_sha=_anchor_cells_sha(ctx, page), mmap=mmap, umap=_uid_map(p, ctx, page))
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
                    if rec.admit and rec.char and not _codepoint_exempt(rec, ctx.book, p.codepoint_no_exempt):
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


def _codepoint_exempt(rec, book, no_exempt: tuple = ()) -> bool:
    """放行字落册码位的例外：这对字已有按刻形拆判的字组（`registry.SHAPE_GROUPS`，如 變𠮓 bian），
    码位归一只是兜底（「暂归一」），人裁的刻形、该组判出的刻形照录，不归一。
    vol04:197:7:3 人裁 變 被工作区 變→𠮓 改回 𠮓（A32 10-25 报），bian 组判出的 變 也一样被改回（A24 10-25）。"""
    tgt = book.canonical_char(rec.char)
    if tgt == rec.char:
        return False
    if ((rec.evidence or {}).get("hou_shape") or {}).get("char") == rec.char:
        return True                       # 候𠋫 书级刻形判法判出的 候 照录，不归 𠋫
    gids = _shape_split(rec.char, tgt) - frozenset(no_exempt)     # 书级 `codepoint_no_exempt`：这些拆判组的码位归一不留例外
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


def _no_ref_page(book, p: "SeedAdmitParams", page: int) -> bool:
    """本页是不是无参照页：册配置 `reference_profile` 声明 `kind: none`，或在 `no_ref_pages`（`page_kinds.no_ref`）里。
    `solo_5b_scope: no_ref` 用。"""
    prof = getattr(book, "reference_profile", None)
    if prof is not None and prof.declared and prof.kind_of(page) == "none":
        return True
    from ..core.book import _expand_pages
    return bool(p.no_ref_pages) and page in set(_expand_pages(list(p.no_ref_pages)))


def no_ref_page_params(p: "SeedAdmitParams", page: int, book=None) -> "SeedAdmitParams":
    """无参照页（册配置 `reference_profile` 声明 `kind: none`，或 `no_ref_pages`／`page_kinds.no_ref`）上把 `no_ref_params`
    叠到本步参数上；别的页、或没配，原样返回同一个对象。两种写法同一口径（同 `_no_ref_page`，参校本 bug 修 CV0 11-27）。"""
    if not p.no_ref_params:
        return p
    if not _no_ref_page(book, p, page):
        return p
    bad = [k for k in p.no_ref_params if k not in type(p).model_fields or k.startswith("no_ref_")]
    if bad:
        raise ValueError(f"seed_admit.no_ref_params: 不认的参数 {bad}（须是 seed_admit 的参数名，且不能是 no_ref_*）")
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **p.no_ref_params})



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
            fold_ruled = (getattr(p, "ruling_anchor_loose", False) and rec.channel == "fold"
                          and ((rec.evidence or {}).get("fold") or {}).get("via") == "ruling")
            _demote(rec, "shadow_veto")
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = _doubts(m, None) + list(rec.doubts) + ["shadow_veto"] + (["fold_ruling_vetoed"] if fold_ruled else [])
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



_LIB_CHANNELS = ("match_", "dual", "iron")



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



#: 1：`follow_ref` 表里有整理本形、本格字不是表里那一形时，仍按参校本取异体（cv#1438）。



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
            img = _C._page_patch(ctx, page, col, rec.slot, rec.sub)
        except PatchUnavailable:
            return None
        v = near_knn.judge(img, model, [lib, ref])
        if (v.get("pick") == lib and v["votes"] >= model["votes_min"] - 1 and v["full"] == lib
                and v["full_votes"] >= model["full_votes_min"] and v["nn"] <= model["guard"]):
            return {k: v[k] for k in ("pick", "votes", "ratio", "full", "full_votes", "nn")}
        return None
    return veto



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



#: 看图判裁定（`feedback/rulings`，group=O）：提示词版本、A24 名下的子类、不碰的疑问
from ..feedback.rulings import VIS_RULING_GROUP as _VIS_RULING_GROUP, VIS_RULING_SPECS as _RULING_SPECS   # noqa: E402  写入校验同一份
_VIS_RULING_VER = _RULING_SPECS[0][0]
_VIS_RULING_SUBCLASSES = _RULING_SPECS[0][1]
#: 整理本缺字（〓）按新图源文本层取字／私用码「一码一字」表（`research/a24/pua_src`，A24 2026-11-03），提示词版本 → 收的子类
#: ctx-m1＝只读文意终审（A24 2026-11-04，两路独立会话双 high＋字形分或≥2 来源，按组定越不越过整理本；`admit_ok` 写入时已判），Z＝字组格、N＝形近护栏格
_VIS_RULING_SPECS = _RULING_SPECS
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

def _anchor_cells_sha(ctx, page: int) -> str | None:
    """格锚点后备键用的本页 cells_sha；裁定库里没有带 cells_sha 的裁定就不算（返回 None，行为与没有锚点时完全一样）。"""
    if ctx is None or not _vis_cache().store_.has_anchors():
        return None
    from ..feedback.rulings import page_cells_sha
    return page_cells_sha(ctx.book.id, page, ctx.store)


def _cell_book(cid: str | None) -> str | None:
    """格号的册前缀（`vol31:12:3:4a` → `vol31`）。"""
    return cid.split(":", 1)[0] if cid and ":" in cid else None


def _uid_map(p, ctx, page: int) -> dict | None:
    """`ruling_by_u` 用的本页 {格号: u}（字格身份账按本页当前 cells_sha 查）。开关关、裁定库里没有带 u 的裁定、账里没这一页这次切分
    → None（不读账、不算 sha，行为与开关关时完全一样）。"""
    if not getattr(p, "ruling_by_u", False) or ctx is None:
        return None
    st = _vis_cache().store_
    if not st.has_u():
        return None
    from ..feedback.rulings import page_cells_sha
    sha = page_cells_sha(ctx.book.id, page, ctx.store)
    return st.uid_ledger().lookup(ctx.book.id, page, sha) or None


def _anchor_cand_ok(ch: str, cid: str, ref: str | None, mmap: dict | None) -> bool:
    """格锚点命中的附加条件：裁定字＝整理本对位字，或在这格库候选里。"""
    if ref and ch == ref:
        return True
    m = (mmap or {}).get(cid)
    return bool(m and any(c[0] == ch for c in (m.candidates or [])))


def _vis_ruling_pass(p, out: list, amap: dict, store=None, cells_sha: str | None = None, mmap: dict | None = None,
                     umap: dict | None = None) -> int:
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
    loose = getattr(p, "ruling_anchor_loose", False)
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
        ref_ = (amap.get(r.id) or (None,))[0]
        if hit is None and cells_sha:
            # 格锚点后备键（GM4／CV4 11-24，裁定键长期方案③）：窗口键都没中 → 格号＋写裁定时 cells_sha＋ref 全对，
            # 且裁定字在库候选里或＝整理本字；其余护栏同上
            if loose:
                ancs = [(ver, subs, store.get_anchor(_VIS_RULING_GROUP, ver, r.id, cells_sha, ref_, left, right, loose=True))
                        for ver, subs in specs]
                cf = [x for _, _, x in ancs if x and x.get("ruling_conflict")]
                if cf:
                    r.evidence = {**(r.evidence or {}), "ruling_conflict": cf[0]["rows"]}   # 同格多条裁定字不同：不放行
                    continue
                hit = next(((ver, x) for ver, subs, x in ancs
                            if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                            and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
            else:
                hit = next(((ver, x) for ver, subs in specs
                            for x in [store.get_anchor(_VIS_RULING_GROUP, ver, r.id, cells_sha, ref_, left, right)]
                            if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                            and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
        if hit is None and umap and umap.get(r.id):
            # 按字格永久编号 u 查（书级 `ruling_by_u`，CV0 T3 11-24）：窗口键、等价、锚点都没中 → 同册同 u 的裁定（宽松档口径），
            # 裁定字在库候选或＝整理本字；其余护栏同上，ref 一致等照旧在下面核
            ubs = [(ver, subs, store.get_by_u(_VIS_RULING_GROUP, ver, _cell_book(r.id), umap[r.id], left, right)) for ver, subs in specs]
            cf = [x for _, _, x in ubs if x and x.get("ruling_conflict")]
            if cf:
                r.evidence = {**(r.evidence or {}), "ruling_conflict": cf[0]["rows"]}   # 同 u 多条裁定字不同：不放行
                continue
            hit = next(((ver, x) for ver, subs, x in ubs
                        if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                        and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
        vt, v = hit if hit else (None, None)
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
        # 终审 ref_lead 证人放行：via=ref_lead（层、领先量）；ruling_key／ruling_ver 只在非窗口精确命中时有
        vr.update({k: v[k] for k in ("via", "ref_lead", "ruling_key", "ruling_ver") if v.get(k)})
        if v.get("ruling_key") == "u":
            vr.update({"u": v.get("u"), "win_sides": v.get("win_sides")})   # 按 u 命中：u 与前后 2 字哪侧相同
        elif v.get("ruling_key") == "anchor":
            if v.get("win_sides"):
                vr["win_sides"] = v["win_sides"]     # 宽松档：前后 2 字哪侧相同
            else:
                vr["window_diff"] = v.get("window_diff")
        r.evidence = {**(r.evidence or {}), "vis_ruling": vr,
                      "lifted_from": {"char": r.char, "doubts": ds}}
        if half_ok and is_half:
            r.evidence["half"] = True                # 统计用，字形库可据此排除
        r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "vis_ruling", "match", []
        n += 1
    return n



#: `fold_aspect` 判窄字／宽字的组与字（组 id → (窄字, 宽字)）
_FOLD_ASPECT_PAIRS = {"ry": ("日", "曰")}


def _fold_pass(p, out: list, amap: dict, mmap: dict | None = None, store=None, coord: dict | None = None,
               wh: dict | None = None, dmap: dict | None = None, cells_sha: str | None = None, umap: dict | None = None) -> int:
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
                if v is None and cells_sha:
                    # 格锚点后备键（裁定键长期方案③）：格号＋写裁定时 cells_sha＋整理本对位字全对，裁定字在库候选或＝对位字
                    aref = (amap.get(r.id) or (None,))[0]
                    if p.ruling_anchor_loose:
                        # 宽松档：只收 high（`_anchor_loose` 里筛）；同格多条字不同记 ruling_conflict 不放行
                        a = store.get_anchor(gid, l3[gid]["ver"], r.id, cells_sha, aref, *wins[r.id], loose=True)
                        if a and a.get("ruling_conflict"):
                            r.evidence = {**(r.evidence or {}), "ruling_conflict": a["rows"]}
                            a = None
                    else:
                        a = store.get_anchor(gid, l3[gid]["ver"], r.id, cells_sha, aref, *wins[r.id])
                    if a and a.get("char") and _anchor_cand_ok(a["char"], r.id, aref, mmap):
                        v = a
                if v is None and umap and umap.get(r.id):
                    # 按字格永久编号 u 查（书级 `ruling_by_u`，CV0 T3 11-24）：宽松档口径（只收 high），裁定字在库候选或＝对位字
                    aref = (amap.get(r.id) or (None,))[0]
                    a = store.get_by_u(gid, l3[gid]["ver"], _cell_book(r.id), umap[r.id], *wins[r.id])
                    if a and a.get("ruling_conflict"):
                        r.evidence = {**(r.evidence or {}), "ruling_conflict": a["rows"]}
                        a = None
                    if a and a.get("char") and _anchor_cand_ok(a["char"], r.id, aref, mmap):
                        v = a
                if v and v.get("char") in mem and v.get("conf") in ("high", "mid") and not v.get("other"):
                    ch, via = v["char"], "ruling"
                    extra = {k: v[k] for k in ("ruling_key", "ruling_ver") if v.get(k)}   # 版本等价／格锚点命中（GM4／CV4 11-24）
                    if v.get("ruling_key") == "u":
                        extra.update({"u": v.get("u"), "win_sides": v.get("win_sides")})
                    elif v.get("ruling_key") == "anchor":
                        if v.get("win_sides"):
                            extra["win_sides"] = v["win_sides"]
                        else:
                            extra["window_diff"] = v.get("window_diff")
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



def _near_p_map(p, ctx, page: int) -> dict:
    """第三步收尾 `glyph_analyzer` 的组内校准概率：{格 id: {字: p}}（只收 p 不为 None 的候选）。没开 `group_flow_near_p` 或没产物 → 空。"""
    if not p.group_flow_near_p or ctx is None:
        return {}
    pf = _opt(ctx, "glyph_analyzer", page)
    if pf is None:
        return {}
    return {rec.id: {c.char: c.p for c in rec.cands if c.p is not None}
            for col in pf.columns for rec in col.chars if any(c.p is not None for c in rec.cands)}


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
                     near_p_min={g: ({c: float(x) for c, x in v.items()} if isinstance(v, dict) else float(v)) for g, v in p.group_flow_near_p.items()},
                     near_p=_near_p_map(p, ctx, page),
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
                return _C._page_patch(ctx, page, col, slot, sub)
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
                patches.append(_C._page_patch(book, page, cc.col, r.slot, r.sub))
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
    img = _C._page_patch(book, page, col, r.slot, r.sub)
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


_ADMIT_LANES = "open_guji_cv.impl.keben.admit_lanes"


def _admit_lanes_hook(ctx: RunContext):
    """书级钩子 `impl/keben/admit_lanes.noref_lanes`；写了 `book_lanes` 而书仓 `code/` 没覆盖 → 拒跑（不悄悄当关）。"""
    import importlib
    from ..core.seg_set import resolve
    mod = resolve(ctx.book, _ADMIT_LANES)
    hook = getattr(importlib.import_module(mod), "noref_lanes", None)
    if hook is None:
        raise RuntimeError("seed_admit.book_lanes 写了取值，但本书书仓 code/ 没覆盖 keben.admit_lanes（noref_lanes）；"
                           "这些通道 2026-11-24 起只在书仓里，检查 code.yaml 的 overrides 与册配置 code: 号")
    return hook


class _AdmitFacts:
    """交给书级钩子 `admit_lanes.noref_lanes` 的只读工具（书级代码不许 import cv 内部模块）。见该模块头。"""

    def __init__(self, ctx: RunContext):
        from ..clustering.seeding import NEAR_FORM_CHARS
        from ..groups.registry import GROUPS
        from ..variants import are_variants, look_alike
        self.gap_chars = GAP_CHARS
        self.group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
        self.near_form_chars = NEAR_FORM_CHARS
        self.are_variants = are_variants
        self.look_alike = look_alike
        self.is_gap = is_gap
        self.is_hanzi = _is_hanzi
        self.canonical_char = (ctx.book.canonical_char if ctx is not None and ctx.book.codepoints else None)

    @staticmethod
    def data_path(rel: str) -> str:
        return _resolve_book_lanes_data(rel)


def _resolve_book_lanes_data(rel: str) -> str:
    """`book_lanes.data` 的一项 → 绝对路径：绝对路径照用；相对路径先找数据目录、再找工作区。找不到＝空串。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    q = Path(rel).expanduser()
    cands = [q] if q.is_absolute() else [(data_root() or REPO_ROOT) / q, (workspace_root() or REPO_ROOT) / q]
    return next((str(c) for c in cands if c.exists()), "")



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
    img = _C._page_patch(book, page, col, slot, sub)
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
