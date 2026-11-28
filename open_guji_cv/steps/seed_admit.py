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

from ..core.decide_names import ADMIT_STEP_ACTIVE
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
from .seed_admit_cell_state import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    SEG_BOX_CRITERIA,
    SEG_BOX_FRAME_H,
    SEG_BOX_FRAME_W,
    SEG_BOX_KIND,
    SEG_BOX_SLIVER,
    SEG_BOX_SPECK,
    SEG_BOX_SPLIT_H,
    SEG_BOX_SPLIT_NB,
    SEG_BOX_SPLIT_SUM,
    SEG_BOX_SPLIT_W,
    SEG_BOX_TALL,
    SPECK_HALF_GAP,
    _JIAZHU_UNEVEN_RE,
    _LIB_CHANNELS,
    _SEAL_STRONG,
    _SRB_FROM_MAX_GAP,
    _blank_ink_pass,
    _g,
    _header_formula_pass,
    _ink_mark_pass,
    _jiazhu_three_agree,
    _jiazhu_uneven_pass,
    _lib_reads_char,
    _manual_seal_cells,
    _occluded,
    _seal_blank_flip,
    _seg_box_pass,
    _speck_halves,
    _symbol_ref_blank_pass,
    _symbol_review_pass,
    seg_box_defects,
)
from .seed_admit_groups import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    _FLOW_MOUNT_LOGGED,
    _FOLD_ASPECT_PAIRS,
    _GROUP_FLOW_HARD,
    _GROUP_FLOW_OWN_DOUBTS,
    _GROUP_FLOW_OWN_GUARDS,
    _L3_ONLINE,
    _RULING_SPECS,
    _VIS_CACHE,
    _VIS_HALF_BAD,
    _VIS_RULING_GROUP,
    _VIS_RULING_SPECS,
    _VIS_RULING_SUBCLASSES,
    _VIS_RULING_VER,
    _anchor_cand_ok,
    _anchor_cells_sha,
    _cell_book,
    _clf_ctx,
    _fold_pass,
    _group_flow_pass,
    _group_members,
    _group_variant,
    _human_relabeled_at,
    _human_shapes,
    _l3_fingerprint,
    _l3_groups,
    _l3_online,
    _near_p_map,
    _override_ok,
    _provisional_forms,
    _resolve_data_path,
    _resolve_group_flow_paths,
    _ruling_han,
    _uid_map,
    _vis_cache,
    _vis_ruling_pass,
)
from .seed_admit_pick import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    _ADMIT_LANES,
    _AdmitFacts,
    _CORPUS_CHANNELS,
    _CodepointMap,
    _ExtraSemanticMap,
    _FOLLOW_REF_HOOKS,
    _JUAN_DOUBTS,
    _JUAN_FORMS,
    _KEBEN_COUNTS,
    _NUMERALS,
    _PairAwareMap,
    _SOLO_CHANNELS,
    _SOLO_COORD_NUMS,
    _TRUSTED_COUNTS,
    _admit_lanes_hook,
    _after_number,
    _approx_fingerprint,
    _approx_hit,
    _approx_index,
    _approx_index_cached,
    _codepoint_exempt,
    _confusable_char,
    _consensus_fallback,
    _context_lib_dissent,
    _context_variant_tie,
    _follow_ref_rival_hook,
    _hand_variant_pairs,
    _image_ranks,
    _iron_confusable_witness,
    _iron_context,
    _iron_coord_dissent,
    _iron_ctx_dissent,
    _iron_decide,
    _iron_page_scale,
    _keben_counts,
    _lane_variant_hook,
    _lane_witnesses,
    _lib_cov,
    _parse_semantic_extra,
    _pick_char,
    _pua_code_admit_pass,
    _pua_code_pass,
    _pua_pin,
    _resolve_book_lanes_data,
    _same_column_exemplar,
    _shape_split,
    _solo_coord_dissented,
    _solo_ctx_vetoed,
    _store_conn,
    _store_ex_raw,
    _trusted_keben_counts,
    _trusted_variant_edge,
    _variant_indirect,
)
from .seed_admit_veto import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    _SHADOW_GATES,
    _follow_ref_veto,
    _shadow_gate,
    _shadow_model_path,
    _shadow_veto_pass,
    _witness3_knn_veto_fn,
)
from .seed_admit_altcut import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    ALT_ADMIT_MIN_GAIN,
    ALT_CV_MAX,
    ALT_CV_MIN_CELLS,
    ALT_CV_RATIO,
    ALT_FIRST_CELL_MAX,
    ALT_REQUIRE_BACKED,
    ALT_TEXT_EQ_GAIN,
    ALT_TEXT_RATE_SLACK,
    _BACKED,
    _NO_P_REF,
    _admit_rate,
    _big_region_ok,
    _col_stats,
    _eq_count,
    _first_cell_tall,
    _ink_cv,
    _merge_admit,
    _note_region_ok,
    _note_spans,
    _opt_product,
    _outside_not_worse,
    _pick_alt_cols,
    _unmatched,
)
from .seed_admit_reasons import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    _context_guard,
    _doubts,
    _garble_guard,
    _rare_cp,
)
from .seed_admit_page_params import (  # noqa: F401  CV4 整理 P1a（2026-11-28）搬出去的，这里 re-export
    _no_ref_page,
    accuracy_page_params,
    book_trust_params,
    derive_trust,
    no_ref_page_params,
    ref_accuracy_summary,
)
from .decide import _opt, _ref_placeholder_norm, coord_refs as _coord_refs_of, text_refs as _text_refs_of  # noqa: F401  `_opt` 等搬到 decide；本模块的 _align／_coord_refs 仍经本模块的 `_opt` 取产物（测试换它）
from . import seed_admit_common as _C
from .seed_admit_common import _edge_pair_excluded, _page_patch  # noqa: F401  只供 import；本模块经 _C 调用，测试换它要 setattr(seed_admit_common, …)


@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id=ADMIT_STEP_ACTIVE, title="收尾 char_decide 定字（旧名 seed_admit）", version="1.82", unit="cell",   # 1.82：规则 A（rare_ref／rare_ref_sparse）不在折叠组待文意格（evidence.fold_pending）里拿整理本字定组内字（殿本 vol41:55:4:19「六日僧道」被放成日，r7 殿本影响 2 格，A24 11-08）；（#1277 的 1.82 撤回为 1.81：group_flow_llm_half_groups 缺省空时逐字节不变，改用 code_equiv 登记，免得各书 seed_admit 全量过期；A31 11-08）（solo_5b 刻例门槛改读可信刻例数 trusted_keben_counts、放行格带 evidence.no_glyph_lib、solo_5b_borrow_db 同族借库：同样不升版本号，缺省关、逐字节不变、code_equiv 登记，A24 11-08）1.82：group_flow_llm_half_groups 这几组的夹注半格不受 llm_skip_half 限制、照样记 L3 问（书级，缺省空、不进参数 dump；SJ 史記 H01 半格写不了裁定键，A24 11-08）；（solo_5b 不升版本号：缺省关、逐字节不变、code_equiv 登记，免得各书 seed_admit 全量过期）solo_5b_cov 无参照格「库首位＋5-b 作证」放行通道 match_solo_5b（书级，缺省关、关时不进参数 dump；全唐文 001–003 总目／韵编，形近字线 11-08，A24 定口径）；1.81：fold_aspect_ctx_veto 的组内文意一支不认 L1 规则、带概率的要到阈值（SJ 史記 06:46「李奇曰」被 ry-ext-r1 误否决，A24 11-08）；1.80：fold_aspect_ink 折叠宽高改量墨迹主体（字组 ry_shape ratio），书级缺省关、不进参数 dump（SJ 史記看图框比字宽，A24 11-08）；1.79：alt_select="admit" 开 p_ref 时选列另跑两遍不带 p_ref 的准入来比（撤 1.77 的「p_ref 格按待审算」：那些格不开 p_ref 时多由后面的通道放，按待审算多换了列；史記 r19 06:26 回放，SJ 11-08）；1.78：fold_aspect_ctx_veto 也认字组文意解法给的另一个字（开着时；SJ 史記 01:45「日講官」宽高比 1.15 判曰没挡住，A24 11-08）；1.77：alt_select="admit" 换列比较时 p_ref 放的格按待审算（开 p_ref 后主切法错位列不再换备选、坏格被整理本字盖住；史記 r19 06:26:1、03:88:4，SJ 11-08）；1.76：p_ref_min_cov（缺省 0.8 开，缺省值不进参数 dump；p_ref 不取库里认不出［diff 档、cov<0.8］的格，挡住切分坏格被整理本字盖住；史記 r19 离线重跑 7 格，SJ 11-08，A24）；1.75：follow_ref_seen_conflict follow_ref_seen 也接「护栏 conflict」格（候选前两名恰是 ref 与 seen 对里另一形；书级，缺省关、关时不进参数 dump；A24 N01 第 7 轮复查 11-08，殿本 七／𠤎 字形相同 28 格按整理本）；1.74：lane_group_img_veto 补放三通道不放字组图像判官（rr_img）反对的字（书级，缺省关、关时不进参数 dump；A23 Z02 r7 人入 2 格，11-08）；1.73：group_flow_ref_pair／ref_pair_coord 不把共字组搭档的码位解法（`组:codepoint`，只回报码位归一目标、无图像证据）当反对票（只对开了这两项的书生效；A24 Z02 r7，殿本 sy 山由出 4 格看图全是山）；1.72：fold_occluded_lib_max_cov 遮挡格库首位无把握（cov<阈值）时仍按整理本字归组（书级，缺省关、关时不进参数 dump；殿本 r7 D01 己已巳 19 格，A24 11-08）；1.71：p_ref_irregular_gap（书级，缺省关、关时不进参数 dump；整理本字是异体写法［槪寳囘竒厯］且字族 cov 贴近机器字时取整理本字、不受 p_ref_max_cov 约束；殿本 r7 P01 异体被库认成形近字 83 格＋同类，A24 11-08）；1.70：暂归一兜底放宽 group_flow_pv_ref_gap（缺省 0.01 开、缺省值不进参数 dump；整理本与库首位都是某组暂归一写法、首位 cov≥0.95、领先组外最好候选≥0.01 时，分差内有组外形近字也进组兜底；A24 V01 第 7 轮 11-08，殿本 𨽻→𨽾 被 諫據綠裁 紧咬拦下 20 格）；1.69：group_flow_dissent_keep_form（dissent_keep 认 ids 弃权票刻形＝放行字，缺省开；A24 Z03 11-08，r7 殿本一二 19 格）；1.68：fold_ctx_vias／fold_ctx_strong 折叠组认字组文意路已给的字（书级，缺省空、不进参数 dump；A24 H01 第 7 轮复盘 11-08，殿本 L3 strong 68 格盲读全同）；1.67：pua_code_admit 族里是别的码表字的字不算互证（F1001 族 乖垂埀 是形近异字合码，乖是 EA36 的表字；第 7 轮 3 格垂放成乖；A24 11-08）；1.66：私用码表的殆知阁码本身也登记（pua_v2_codes），格→码事件可写殆知阁码（新图源文本层对不上、按整理本窗口回查的格；A24 R01 第 7 轮 38 格）；1.65：pair_shape 整理本／坐标对位是两字以外的第三个字时不补放（全唐文 r16 三→王，库首位王、整理本三，QTW 11-07）；1.64：alt_require_matched 备选格网比主切法多出没有坐标字的格就不换列（书级，缺省关、关时不进参数 dump；史記 r18 02:106:7，A24）；1.63：group_flow_lift_shape_ratio(_jiazhu) 给 lift_shape_ref 加宽高门、reference_trust_skip 让 reference_trust 自动并入的各项可单独关（书级，缺省空、不进参数 dump；SJ 史記 r18 日曰 71 格，A24 11-07）；1.62：lane_coord_blind_guard 坐标对位兜底「靠证人同意参校字」一支，参校字在库里刻例≥N却不在库候选、库首位 cov≥0.98 → 留审（书级，缺省关、关时不进参数 dump；Z04 殿本错放 餘／三，A23 建议，A24）；1.61：group_flow_same_writing_keep／group_flow_review_fix_agree（A24 Z03 11-07，见 1.59）；1.60：group_flow_ctx_agree 书级（缺省关）dissent_keep／ref_pair 的组还要本组文意同意放行字；1.59：坐标对位的缅甸字母占位（整理本以图代字，史記）当〓看，机器字不再取占位符（A24 R01 深挖 11-07，sheldon 同意）；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.58：字组入口认暂归一的另一写法作整理本字（li 𨽻、sui 𡻕：第 6 轮 align_ref 对上整理本后入口不接，殿本 V01 多 219 格；第 5 轮这些格按坐标对位进组暂归一放行，A24 V01 按新码重统计 11-07）；1.57：group_flow_pair_shapes 多对两字刻形模型（pair_shape/2 墨量图＋组外判别）与 group_flow_pair_shape_veto 刻形强烈反对已放行字降审（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.57：group_flow_dissent_l1 书级（缺省关）复核时 L1 规则孤证＋整理本×ids 同意放行字不降审（A24 Z02 11-07）；1.56：pua_code_admit 未放行格按私用码表＋库首位互证放行（书级，缺省关、关时不进参数 dump；A24 R01 深挖 11-07，殿本 r6 R01 668 格中 408 格，人裁留出 416/422 同字、6 格录法）；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸；1.55：group_flow_ref_pair_coord 联合判搭档没表态时认坐标对位字（书级，缺省关、关时不进参数 dump；A24 Z07 11-07）；1.54：卿𨜊 组暂归一兜底认整理本〓（registry PROVISIONAL qing gap，A24 Z 类梳理 11-07，sheldon 同意；殿本 Z04 里 235 格坐标对位〓被当组外字拦下，抽 30 格看图全是卿）；1.53：共识升档 same 退回原档 consensus_fallback（书级，缺省关、关时不进参数 dump；库字≠对位整理本字的共识 same 按 unsure 走原通道，A23，全唐文 r15 回退 46 格，QTW 看图 11-06）；1.52：整理本空格位上有墨、库认不出的格判非字放行 blank_ink_nonchar（书级，缺省关、关时不进参数 dump；配 align_ref coord_blank_ink；A22 S02 深挖 11-06，Sheldon 定）；1.51：group_flow_form_open 字组流程接写法待定（form_open，Z06）格（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）；1.50：p_ref_coord_max_cov／p_ref_coord_adjacent P02 坐标对位格自己的 cov 上限和相邻开关，不再与 P01 共用（书级，缺省 None／关、关时不进参数 dump；A24 P02，殿本 P01 开相邻会放进 P02 的切分错位格）；1.49：p_ref_skip_variant 机器字与整理本字有直接异体边的格不取整理本字（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06，殿本 L01 抽 30 格 14 格是异体对）；1.48：p_ref_coord P02 取坐标对位的整理本字（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）；1.47：字组复核／补放两个书级旋钮 group_flow_dissent_keep（整理本＝放行字、只有弱图像票反对不降审）、group_flow_ref_pair（整理本字＝本组解法给的字、反对只有图像路则取它），缺省全关、关时不进参数 dump；同批收窄 7 条 L1 规则 zh-曾經 yh-遺文 yh-還朝 yt-圓 yt-圖 rm-日 js-申-l1（全册审计冲突 1187→1119，A24 Z02 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸 ；1.46：p_ref_max_cov／p_ref_adjacent／p_ref_jiazhu P 类取整理本字的三个书级旋钮（缺省全关、关时不进参数 dump；A24 P01 深挖 11-06，殿本只开 p_ref_admit 放 126 格看图 13 格机器字对，加 cov<0.93 放 31 零错）；1.45：rare_ref_coord_group_top 坐标支放宽库首位在字组里（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）；1.44：follow_ref_variants_gap／follow_ref_variants_cov 按参校本取异体单独放宽领先（书级，缺省 None 不变、不进 dump；A24 V01 深挖 11-06，史記夹注半格 10 格看图都对）；1.43：edge_pair 补字组缝 edge_pair_group_seam（缺省开，A24 V01 深挖 11-06，第 7 轮：纯异体强边但有一字是字组成员、字组又没接的格；涉及形近组领先≥0.03）；1.42：pua_code_table 书级旋钮 pua_code_keep_channels／pua_code_family_demote、多字码族（缺省行为不变、不进 dump；A24 11-06 X01 参数化）；1.41：折叠组书级参数化 fold_aspect_pairs／fold_jiazhu／fold_aspect_jiazhu／fold_aspect_ctx_veto（缺省全关、关时不进参数 dump；A24 H01 深挖 11-06，框架见 doc/字组/折叠组.md）；1.40：规则 A 少刻例支 rare_ref_sparse（书级，缺省关、关时不进参数 dump；5-b 参校字组居首且领先同来源组外最好候选 ≥0.02、参校字刻例 ≤2 时放，A23 L02 深挖，sheldon 11-06 同意）；1.39：match_ref 不放库判 diff 的格 match_ref_diff_guard（书级，缺省关、关时不进参数 dump；A24 11-06，vol05:66:9:15）；1.38：字组入口不拉坐标对位说是组外字的格 group_flow_coord_outside_skip（缺省开，A24 Z01 深挖 11-06，殿本 r5 Z01 −106）；1.37：pua_code_table 按私用码表改放字、族豁免、每页 n_code_fix／n_code_mismatch（缺省关，殿本开，A24 11-06，A31 X01）；1.36：R5 题列套语容错 lane_seal_title_tolerance（书级，缺省关；前 8 字差 ≤N 字仍放、不一致的字位留审，A32 D01 深挖 11-06，vol77 p119）；1.35：src_code_conflict 降审计入页头 n_auto/n_review（v0.6.2 漏减，pending_list 校验格数不符，A32 11-04 vol35 vol48）；1.34：R4 坐标对位兜底放过本书 codepoints 已归一的异体对 lane_coord_codepoint_variant（缺省关，全唐文码位线 11-04，r8 114 格）；1.33：src-1 裁定加子类 GB（乱码闸/影子闸拦下的格，新图源文本层与整理本同字，A24 11-04，r3 62 格）；1.32：已放行格命中 src-1 code_conflict 裁定（私用码唯一字≠现字，非人裁）→ 降审 doubt src_code_conflict（A24 11-03，25 格）；1.31：R5 库否决只在默认字库里刻例 ≥2 时才算 lane_seal_lib_veto_min_n（A32 11-02，r1 遮挡格）；1.30：context 通道不放高宽比＞2.5 的字块 context_max_aspect（A24 11-01，A32 报错放 vol39:176:3:1 印文碎块）；1.29：遮挡格所在列过了整理本半叶末行 → 默认字来源 coord_blank occluded_past_leaf_blank（A32 11-01，r1 卷末印页）；1.28：异体边表自动暂归一 edge_pair（A24 10-31，r5 V 类单格长尾）；1.27：R5 库否决放过默认字＝库第二名 lane_seal_lib_veto_second、异体护栏放过本书已定归一的异体对 lane_seal_codepoint_variant（A32，vol20–99 r3 遮挡格）；1.26：印框内背景干净的格不算遮挡 occluded_seal_min_noise（A31 sheldon 10-28 定）；1.25：异体形近规则先于印章遮挡 occluded_variant_first（R5 默认字＝库首位不受异体护栏、follow_ref 与 group_flow 不再把遮挡当硬护栏；A31 sheldon 10-28 定）；1.24：R5 印章区题列套语放行、via 加 align、库否决 lane_seal_lib_veto、整页错位护栏 lane_seal_shift_guard（A32 印章格研究，sheldon 10-26 定）；1.23：铁证与坐标对位字互证 iron_coord_guard（缺省开）、ref_lib_diff 进 _LANE_HARD；同批 #528 的 ref_lib_diff_guard 与 ref_prefer／rare_ref／symbol_review／shadow_veto 缺省开（A31 v0.5.12 错放样例）；1.22：删准入三闸 runt_cell_review、oversplit_gate、nonchar_gate（现行切分上 0 格，doc/exp/准入三闸-vol05-vol09-报告.md）；1.21：seal_blank_page、lane_seal 缺省开；1.20：遮挡格加小印压着的字（与小印框重叠 ≥ 0.3、不是盖章空栏），默认整理本字、不进字形库；1.19：遮挡格与盖章空栏候选改读印章定位 `seals`（大印框、小印框＋笔画覆盖区），修正旧判据格框与原图左右镜像；1.18：人裁绑丢闸 human_unbound_review（缺省开，绑定后不采信的人裁不许被新放行悄悄顶掉，GUJI-697）；1.17：字组统一流程 group_flow 覆盖全部字组，旧字组开关 ji_yi_si_*／ry_group／rr_clf／m7_*／variant_tie* 与 _resolve_ji_yi_si 删除（2026-10-18 S6）；1.16：矮格转人审 runt_cell_review（任意 slot，缺省关，overview#554）；1.15：入人八字形分类器 rr_clf／罕用码位×context 落审 rare_cp_ctx_review（缺省关，overview#437）；日曰 v2 答案表 ry_group（缺省关，overview#441）；1.14：己已巳词组分类器 ji_yi_si_clf／ji_yi_si_clf_llm（缺省关，overview#443）；1.13：待审补放三通道 lane_witness3/lane_coord/lane_seal（缺省关，overview#433）；1.12：己已巳上下文表规则 ji_yi_si_ctx_rule（缺省关，overview#428）；1.11：排除名单格人已给字挂 evidence.human_char（overview#403 缺口 B）；1.10：异体等价放行拦间接路径（variant_indirect_guard）；1.6：context 通道加整理本互证；1.7：事件侧人裁定字（不入库也算）；1.8：context 通道加空白字块弃权闸；1.9：己已巳 resolve() 改 use_ref=all + 三方一致闸
        consumes=("glyph_match", "context_decision", "align_ref", "char_index"),
        optional_consumes=("rare_candidates", "glyph_candidate", "seals", "glyph_analyzer", "cell_state", "glyph_near", "group_decision"),
        optional_consumes_when=(("rare_candidates", "rare_ref_5b"), ("rare_candidates", "symbol_review_5b"), ("glyph_candidate", "cand_3c_on"), ("rare_candidates", "rare_ref_sparse"),
                                ("rare_candidates", "solo_5b_cov"), ("rare_candidates", "book_lanes"),
                                ("rare_candidates", "ref_lib_5b_veto"), ("glyph_analyzer", "group_flow_near_p"),
                                ("glyph_near", "group_flow_near_from_3b"), ("glyph_analyzer", "vis3_shadow")),
        produces=(ADMIT_STEP_ACTIVE,),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.steps.seed_admit_params",   # 参数类与参数表（2026-11-23 从本模块搬出，SPLITS 合回）
                   "open_guji_cv.steps.seed_admit_common",   # 共用工具／放行通道与护栏／字形判官（2026-11-26 CV4 PR3c 从本模块搬出，SPLITS 合回）
                   "open_guji_cv.steps.seed_admit_lanes",
                   "open_guji_cv.steps.seed_admit_shapes",
                   # 2026-11-28 CV4 P1a：本模块与 lanes 再拆出下面八块（纯搬家），SPLITS 合回原来的 seed_admit／seed_admit_lanes 两项
                   "open_guji_cv.steps.seed_admit_vis3",         # 影子读口 vis3（缺省关；2026-11-28 P1）
                   "open_guji_cv.steps.seed_admit_cell_state",   # 4c 格况（探测器；2026-11-28 P3b 起另有 steps/cell_state 出产物，收尾读它）
                   "open_guji_cv.steps.seed_admit_groups",       # 4d 字组流程（2026-11-28 P3c 起另有 steps/group_decision 出原料，收尾读它）
                   "open_guji_cv.steps.seed_admit_pick",         # 定字：选刻形／铁证／独证／钩子取数
                   "open_guji_cv.steps.seed_admit_veto",         # 否决
                   "open_guji_cv.steps.seed_admit_altcut",       # 备选切法挑列
                   "open_guji_cv.steps.seed_admit_reasons",      # 疑问码与护栏
                   "open_guji_cv.steps.seed_admit_page_params",  # 按页换参数
                   "open_guji_cv.steps.char_decide_reasons",     # 收尾直接写送审原因（P3a-2，判法搬自 manager reasons.py）
                   "open_guji_cv.steps.decide",                  # 第四步公共读口（ref_of、_opt）
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

    def book_params(self, p: "SeedAdmitParams", ctx: RunContext) -> "SeedAdmitParams":
        """参校本四维 → 信任字段（`reference_trust` 等，册里写的旧键不采用）；段上压低准确度的摘要进 `ref_accuracy`。"""
        return book_trust_params(p, ctx.book)

    def parallel_warm(self, ctx: RunContext) -> None:
        """页级并行 fork 前在主进程预建两份大缓存（`core/parallel.warm`）：三份证人的 8-gram 索引
        （复核通道才用，懒加载，第一页常碰不到）与铁证人裁匹配器。键与 run_page 里一致。只管提速。"""
        p: SeedAdmitParams = ctx.params_for(self)  # type: ignore[assignment]
        if p.lane_witness3 or p.lane_coord or p.lane_seal:
            _lane_witnesses(ctx.book, p)
        if ctx.book.iron_gate:
            _iron_context(p.db_path, getattr(ctx.book, "norm_stroke", None))

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        out = self._run_page_alt(ctx, page)
        # P3a-2（2026-11-28）收尾直接写送审原因与选形来源：只读本页产物、不改放行（见 char_decide_reasons 模块头）
        from .char_decide_reasons import stamp_page
        try:
            stamp_page(ctx, page, out[ADMIT_STEP_ACTIVE], glyph_db=str(ctx.params_for(self).db_path))   # 与放行用同一个字形库
        except Exception as e:      # noqa: BLE001 —— 写不出原因不拦放行；留 None，manager 回退反推
            ctx.log(f"seed_admit p{page}: pending_reason 没写出（{type(e).__name__}: {e}）")
        return out

    def _run_page_alt(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
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
                        runs.append(self._run_page(av if cols else ctx, page)[ADMIT_STEP_ACTIVE])
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
        return {ADMIT_STEP_ACTIVE: _merge_admit(main, alt, chosen)}

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
        p = accuracy_page_params(p, page, ctx.book)
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
            from .align_ref import topk_src_map
            rtop = topk_src_map(ctx, page, 1, getattr(p, "read_3c", False))
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
        # 4c 格况（P3b）：`cell_state` 步开了就读它存的探测原值（同一批探测器、同一份参数，逐格不变），没开就在这里现算
        # `cell_state_read` 关（缺省）：一律现算，不看产物在不在；开：读产物，产物里没有的探测器现算并计数（A1）
        cstate = _opt(ctx, "cell_state", page) if p.cell_state_read else None
        _cs_ran = frozenset(cstate.ran) if cstate is not None else frozenset()
        if p.cell_state_read:
            _cs_need = {n for n, on in (("occluded", p.occluded_gate), ("seal_blank", p.seal_blank_page and p.lane_seal),
                                        ("seg_box", bool(p.seg_box_check)), ("ink", p.ink_marks), ("jiazhu_uneven", True),
                                        ("header_formula", p.lane_header_formula)) if on}
            ctx.log(f"char_decide p{page}: cell_state 读产物 {len(_cs_need & _cs_ran)} 个探测器"
                    f"、本地现算 {len(_cs_need - _cs_ran)} 个{sorted(_cs_need - _cs_ran) or ''}")
        occ = ((cstate.occluded_map() if "occluded" in _cs_ran else _occluded(ctx, page, match, p, amap))
               if p.occluded_gate else {})
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
                elif (ok and p.solo_self_exemplar and channel in _SOLO_CHANNELS
                      and _same_column_exemplar(r.id, getattr(r, "matched_id", None))):
                    ok, channel = False, None
                    doubts.append("solo_self_exemplar")
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
                # note_lexicon 只定「读法」（哪个字），形（刻本刻的是异体里的哪一个）看库：库首位与短语字同义、字面不同时，
                # 取库首位的形（异体看刻形，Sheldon 11-24 复核殿本 𨽾→𨽻 6 格：库首位 𨽾 cov 0.97，短语写的是 𨽻）
                if (ok and channel == "note_lexicon" and p.note_lexicon_lib_form and r.candidates and char
                        and r.candidates[0][0] != char and r.candidates[0][0] not in NEAR_FORM_CHARS
                        and vm_here.semantic(r.candidates[0][0]) == vm_here.semantic(char)):
                    char = r.candidates[0][0]
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
                if not ok and iron_ctx is not None and "solo_self_exemplar" not in doubts:
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
                from .align_ref import topk_src_map
                _nm5 = {k: v[0] for k, v in topk_src_map(ctx, page, 1, getattr(p, "read_3c", False)).items() if v}
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
                # 保留内联回退（C2 查过，不删）：group_decision 缺省关，配了 fold_groups 没开 4d 的书靠 char_index 现算宽高，
                # 删了日曰宽高判断会悄悄失效（Sheldon：宽高判断按书决定）。要删须先定「4d 缺省开」。
                _gd = _opt(ctx, "group_decision", page)          # 4d（P3c）：字框宽高存在产物里就读它，没有就从 char_index 现算
                _ci = _opt(ctx, "char_index", page) if (p.fold_aspect and not (_gd is not None and "wh" in _gd.ran)) else None
                d_fd = _fold_pass(p, out, amap, mmap,
                                  coord=_coord_refs(ctx, page, coord_cache) if p.fold_coord_ref else None,
                                  wh=(_gd.wh_map() if (p.fold_aspect and _gd is not None and "wh" in _gd.ran) else
                                      {c.id: (c.width, c.height) for col in (_ci.columns if _ci else []) for c in col.chars}
                                      if _ci else None),
                                  aspect=({c.id: c.aspect for c in _gd.cells} if (p.fold_aspect and _gd is not None and "wh" in _gd.ran) else None),
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
            d_seal = _seal_blank_flip(out, cstate.seal_blank_map() if "seal_blank" in _cs_ran else page_seal_blank(ctx, page, p),
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
            d_hf = _header_formula_pass(ctx, page, p, out, cstate.header_line_map() if "header_formula" in _cs_ran else None)
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
        d_ju = _jiazhu_uneven_pass(ctx, page, out, mmap, amap, _coord_refs(ctx, page, coord_cache),
                                   cstate.uneven_spans() if "jiazhu_uneven" in _cs_ran else None)
        n_auto -= d_ju
        n_review += d_ju
        if p.seg_box_check:
            # 字框几何闸（降，CV2 11-27，缺省关、按书开）：碎格／框线扁条／墨点／一字劈两框／过高框送审，归 seg_defect
            d_sb = _seg_box_pass(ctx, page, out, p.seg_box_check, cstate.seg_box if "seg_box" in _cs_ran else None)
            n_auto -= d_sb
            n_review += d_sb
        if p.ink_marks:
            # 格级墨迹记号（升降都有，CV2 11-28，缺省关、按书开）：印、墨点对位无字判非字放行，对位有字送审
            d_im = _ink_mark_pass(ctx, page, out, amap, cstate.ink_facts() if "ink" in _cs_ran else None)
            n_auto += d_im
            n_review -= d_im
        if ctx.book.codepoints:
            # 放行字落到册指定码位。放在所有后处理遍之后：`group_flow` 的文意 L2 表键是按整理本原字
            # 建的（`_clf_ctx` 取邻格放行字），提前改邻格字会让键对不上、组内格被误降。
            for col in out:
                for rec in col.chars or []:
                    if rec.admit and rec.char and not _codepoint_exempt(rec, ctx.book, p.codepoint_no_exempt):
                        rec.char = ctx.book.canonical_char(rec.char)
        if p.vis3_shadow:
            # 影子（只记录）：3e glyph_vis 的看图结论与现行 vis_llm 逐格对比，写 evidence.vis3_shadow，不动放行
            from .seed_admit_vis3 import vis3_shadow_pass
            _v3 = vis3_shadow_pass(_opt(ctx, "glyph_analyzer", page), out)
            ctx.log(f"seed_admit p{page}: vis3 影子 {dict(sorted(_v3.items()))}")
        if patch_missing:
            lanes: dict[str, int] = {}
            for v in patch_missing.values():
                for k in v:
                    lanes[k] = lanes.get(k, 0) + 1
            ctx.log(f"seed_admit p{page}: patch_missing=skip，{len(patch_missing)} 格读不到字块、"
                    f"跳过 {lanes}（见各格 evidence.patch_missing）")
        return {ADMIT_STEP_ACTIVE: PageAdmit(page=page, n_auto=n_auto, n_excluded=n_excluded,
                                        n_review=n_review, columns=out,
                                        n_code_fix=n_code_fix, n_code_mismatch=n_code_mismatch)}


def _align(ctx: RunContext, page: int) -> dict[str, tuple[str, str]]:
    """`align_ref` 的产物 → {字位: (整理本字, equal|replace)}。

    Step5-d 已经把 8-gram 锚定 + difflib 挪成正式 Step（`steps/align_ref.py`）：
    这里只读它的产物，不再自己 import `gold.v2_align` 的私有函数现算一遍——
    那是任务书点名的"绕道读金标"，对齐这个动作因此在两处各算一遍、互相漂移。
    产物缺失或未锚定就返回空表，所有整理本通道自动失效，退回改动之前的行为，
    不会把错的/缺的对齐硬塞进准入。这是「拿不准就保持基线」在这一层的落法。
    """
    return _text_refs_of(_opt(ctx, "align_ref", page))   # 解析在 steps/decide.py（读口 ref_of 同一处）


def _coord_refs(ctx: RunContext, page: int, cache: dict) -> dict[str, str]:
    """本页 `align_ref.coord` → {字位 id: 整理本字（空串 = 坐标对位说是空格位）}；页内缓存。"""
    if "coord" not in cache:
        cache["coord"] = _coord_refs_of(_opt(ctx, "align_ref", page))   # 解析在 steps/decide.py
    return cache["coord"]
