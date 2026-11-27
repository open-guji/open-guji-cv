"""seed_admit 的参数（`SeedAdmitParams`）、退役／恒开参数表与参数指纹的去键规则。

2026-11-23 CV4 整理 seed_admit 时从 `steps/seed_admit.py` 原样搬出（纯搬家，代码一字未改；`seed_admit` 照旧
re-export 这里的名字，外面 `from open_guji_cv.steps.seed_admit import SeedAdmitParams` 不用改）。
本模块在 `seed_admit` 的 `code_deps` 里，改了照常让各书 seed_admit 过期。
"""

from __future__ import annotations

import copy
import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_serializer, model_validator

_log = logging.getLogger("open_guji_cv.steps.seed_admit")

REFERENCE_TRUST_SHAPE_GROUPS = ("guang", "yh", "fc", "em", "weiw", "lv", "qik", "lih", "jue", "jiao", "weim", "zh")
REFERENCE_TRUST_ABSTAIN_GROUPS = ("jys", "zh")
REFERENCE_TRUST_LIFT_SHAPE_GROUPS = ("ry",)
FOLLOW_REF_VARIANTS_REV = 1


_RARE_REF_COORD_MIN_COV = 0.90
"""坐标对位那支的库首位覆盖度下限：殿本 vol04–10 回放里库首位 cov < 0.90 的格多落在页末（9:21）、版心外（-1），
库判 diff、字块本身可疑，坐标对位在这些位置也最容易错位，一律留人审。"""


def _flow_groups():
    from ..groups.registry import FLOW_GROUPS
    return FLOW_GROUPS


def _default_flow_groups() -> tuple:
    from ..groups.registry import generic_flow_names
    return generic_flow_names()


#: `group_flow_same_writing_keep` 缺省名单（A24 Z03 深挖 2026-11-07：三书 Z03 里实有同写法格的组；旨㫖 等按刻形复核的组不在内）
_SAME_WRITING_KEEP = ("xu", "feng", "yi_560", "guan", "guang", "jiao", "jue")


#: 已退役的参数（CV4 2026-11-23 整理，方案见 ai-team `domain/CV/A24/seed_admit整理/`）：没有任何书开过、缺省关／空＝整条分支不走，
#: 代码已删。值是退役前的缺省值。书配置里还写着、且值＝这里的值 → 照旧忽略；写了别的值 → 报错（说明那本书真在用，不能悄悄失效）。
_RETIRED: dict = {
    "context_verdicts": "", "context_single_stroke_review": False,
    "group_flow_llm_need_l2_agree": False, "group_flow_llm_half_groups": [],
    "group_flow_lift_shape_ratio": {}, "group_flow_lift_shape_ratio_jiazhu": None,
    "witness3_no_diff": False,
    "textlayer_ref_gap": "", "textlayer_ref_area_min": 0.8, "textlayer_ref_page_min": 0.8, "textlayer_ref_min_pairs": 20,
    "textlayer_ref_near_guard": True, "textlayer_ref_allow_pua": False, "textlayer_ref_gap_fingerprint": "",
    "p_ref_coord": False, "p_ref_coord_max_cov": None, "p_ref_coord_adjacent": False,
    "fold_aspect_pairs": None, "fold_jiazhu": False, "fold_aspect_jiazhu": None, "fold_aspect_ink": False,
    "pua_code_keep_channels": "", "off_channels": "",
    "match_tie_guard": False, "match_tie_gap": 0.003,
    "solo_5b_borrow_db": None, "solo_5b_char_ok": None, "solo_5b_human_min": 1,
    "occluded_rescue_ink": 0.0, "approx_gate": False, "context_garble_run": 0,
    "lane_coord_codepoint_skip": "", "seal_lib_agree": False, "seal_lib_cov": 0.9, "lane_witnesses": "",
    "reference_trust_skip": [], "lane_coord_few_stroke": [],
    "follow_ref_variants_gap": None, "follow_ref_variants_cov": 0.93,
}
#: 搬进书仓的通道参数（2026-11-24 CV4，Sheldon 定「搬进全唐文书仓」）：只有全唐文 001–003 用的四条无参照补放通道
#: solo_adapt／num_run／solo_cal／lead_5b 搬进全唐文书仓 `code/admit_lanes.py`（k13），取值改写进 `book_lanes`。
#: 值是搬家前的缺省值：书配置写的＝这里的值 → 忽略；写了别的值 → 报错，提示改写进 `book_lanes`。
_MOVED_TO_BOOK: dict = {
    "solo_adapt_pct": None, "solo_adapt_floor": 0.94, "solo_adapt_gap": 0.01, "solo_adapt_min_n": 5,
    "solo_adapt_window": 0.05, "solo_adapt_profile": "", "solo_adapt_fingerprint": "", "solo_adapt_risk_gap": None,
    "solo_adapt_abstain_ok": False, "solo_adapt_abstain_skip": "", "solo_adapt_near_slack": None,
    "solo_adapt_near_gap": 0.03, "solo_adapt_nf_ok": False,
    "num_run_cov": None, "num_run_gap": 0.01, "num_run_juan_cov": None, "num_run_cov_5b": None, "num_run_gap_5b": 0.02,
    "solo_cal": False, "solo_cal_tiers": "0.98:0.03,0.95:0.05", "solo_cal_skip": "己已巳于干曰日代伐遣遺真",
    "solo_cal_5b_cov": None, "solo_cal_allow": "", "solo_cal_5b_canon": False,
    "lead_5b": False, "lead_5b_gap_out": 0.023, "lead_5b_gap_in": 0.015, "lead_5b_lib_min": 0.935,
}
#: 退役参数里原先**缺省就进 dump** 的几个：dump 里照旧补上退役前的值，`params_hash` 与退役前逐位相同、各书产物不过期。
#: 补在 `_drop_off_rare` 最前面，后面按条件去掉的规则（group_flow 全关去 `group_flow_*`、三通道全关去 `lane_*`）照常生效。
_RETIRED_IN_DUMP: dict = {k: _RETIRED[k] for k in
                          ("context_verdicts", "group_flow_llm_need_l2_agree", "off_channels", "context_garble_run", "lane_witnesses",
                           "lane_coord_codepoint_skip")}
#: R5 印章格「异体形近规则先行」（`occluded_variant_first`）认库首位＝默认字的 cov 下限（原 `seal_lib_cov` 参数，无书改过）
_SEAL_LIB_COV = 0.9

#: 恒开的护栏／通道（2026-11-23 CV4 整理 PR2：缺省开、397 册没有一册关过）：不再是参数，代码里无条件执行。
#: 老配置写 `true` 照读（同 `_RETIRED`），写 `false` 报错。原先进参数指纹的照原值补回 dump（有的随别的开关条件
#: 再被 `_drop_off_rare` 去掉，口径与退役前一样），各册 params_hash 不变。
_ALWAYS_ON: tuple[str, ...] = (
    "use_exclusions", "use_note_lexicon", "human_unbound_review", "evict_review", "iron_ref_guard",
    "iron_confusable_guard", "iron_coord_guard", "iron_ex_missing_guard", "iron_ex_from_store", "context_blank_gate",
    "relax_split_ref", "group_flow_dissent_keep_form", "group_flow_joint", "group_flow_form_open",
    "group_flow_coord_outside_skip", "group_flow_lift_ref_guard", "vis_rulings", "pua_code_family_demote",
    "relax_ref_agree", "ref_lib_diff_guard", "ref_lib_variant_guard", "variant_indirect_guard",
    "context_variant_form_guard", "iron_ctx_guard", "rare_ref_coord", "rare_ref_nf",
    "rare_ref_sparse_variant", "occluded_past_leaf_blank", "lane_seal_lib_veto_second",
    "lane_seal_codepoint_variant", "lane_seal_shift_guard", "occluded_variant_first", "lane_variant_keep_rare",
    "lane_keep_ref_review", "edge_pair", "codepoint_semantic",
)
_ALWAYS_ON_IN_DUMP: dict = {k: True for k in _ALWAYS_ON if k not in (
    "vis_rulings", "pua_code_family_demote", "group_flow_form_open", "codepoint_semantic",
    "group_flow_dissent_keep_form", "edge_pair", "occluded_variant_first",
)}
_RETIRED.update({k: True for k in _ALWAYS_ON})

#: 收成常量的门槛（2026-11-24 CV4 整理 PR4，Sheldon 11-24 定）：397 册没有一册改过，不再是参数，代码照旧读 `p.<名>`
#: （`SeedAdmitParams` 上的只读属性）。老配置写这个值照读（同 `_RETIRED`），写别的值报错。原先进参数指纹的照原值补回 dump
#: （再按 `_DUMP_DROP` 去键，口径不变），各册 params_hash 不变。各项含义见类里同名注释。测试要换值用 `monkeypatch.setitem(_CONSTANTS, …)`。
_CONSTANTS: dict = {
    'solo_cov': 0.99,
    'context_margin': 0.7,
    'always_review': '己已巳',
    'exclusion_origins': 'human,gate,pipeline',
    'note_min_sim': 0.7,
    'context_min_ink': 0.05,
    'context_max_aspect': 2.5,
    'group_flow_freq_major': 10,
    'group_flow_freq_min_vols': 2,
    'group_flow_llm_effort': 'low',
    'group_flow_llm_panel': ('claude-opus-5-5:high', 'claude-fable-5-1:high'),
    'group_flow_delta': 0.03,
    'group_flow_min_cov': 0.85,
    'group_flow_top1_cov': 0.97,
    'group_flow_same_writing_keep': ['xu', 'feng', 'yi_560', 'guan', 'guang', 'jiao', 'jue'],
    'group_flow_review_fix_agree': ['yr'],
    'group_flow_dissent_margin': 1.0,
    'group_flow_ref_pair_margin': 1.5,
    'group_flow_pv_ref_gap': 0.01,
    'group_flow_pv_ref_cov': 0.95,
    'group_flow_l2_drift': 2,
    'symbol_ref_gap_cov': 0.97,
    'symbol_ref_gap_min_col': 3,
    'p_ref_min_cov': 0.8,
    'blank_ink_max_cov': 0.9,
    'blank_ink_col_min_agree': 3,
    'blank_ink_col_min_frac': 0.5,
    'pua_code_admit_cov': 0.85,
    'context_variant_ratio': 0.25,
    'context_variant_lib_gap': 0.02,
    'context_lib_dissent_gap': 0.03,
    'context_lib_dissent_cov': 0.93,
    'iron_ctx_prob': 0.5,
    'iron_ctx_gap': 0.005,
    'rare_ref_nf_max_n': 2,
    'rare_ref_nf_cov': 0.96,
    'rare_ref_sparse_max_n': 2,
    'rare_ref_sparse_lead': 0.02,
    'solo_5b_gap': 0.01,
    'occluded_min_density': 4.0,
    'occluded_min_cells': 12,
    'occluded_min_cols': 3,
    'occluded_min_peak': 8.0,
    'occluded_min_contrast': 2.5,
    'occluded_seal_min_noise': 4.0,
    'occluded_seal_keep_cov': 0.93,
    'seal_blank_thr': 0.35,
    'seal_blank_overlap': 0.5,
    'seal_blank_ink_out': 0.005,
    'context_guard_cov': 0.8,
    'context_garble_cov': 0.9,
    'context_garble_rare_cov': 0.95,
    'lane_coord_codepoint_gap': 0.005,
    'lane_seal_via': 'coord,align',
    'lane_seal_title_norm': '巻卷',
    'lane_seal_lib_veto': 0.95,
    'lane_seal_lib_veto_min_n': 2,
    'pua_rule_cov': 0.85,
    'lane_coord_blind_min_n': 3,
    'lane_coord_blind_lib_cov': 0.98,
    'lane_coord_blind_gap': 0.05,
    'ref_lib_coord_cov': 0.96,
    'ref_lib_coord_gap': 0.01,
    'follow_ref_cov': 0.92,
    'follow_ref_gap': 0.005,
    'edge_pair_cov': 0.92,
    'edge_pair_gap': 0.005,
    'edge_pair_group_seam_nf_gap': 0.03,
}
_RETIRED.update(_CONSTANTS)


#: 参数指纹的去键规则（`SeedAdmitParams._drop_off_rare`，2026-11-23 CV4 整理 PR3 由一百多段 if 改成表，规则逐条不变）：
#: 每行（条件, 键）：条件为真就把这些键从 dump 里去掉。通用口径是「书级开关关着时、或参数取缺省值时不进 dump」，
#: 这样没开某开关的书 `params_hash` 与加字段前逐位相同、产物不过期。新加书级参数照这个口径加一行。
#: 缺省开的开关（symbol_review、rare_ref、shadow_veto、context_guard_*）关着时开关本身留在 dump 里（显式 False），
#: 只去附属字段——否则 dump 再读回来会变回缺省的开。条件只看参数本身，行与行之间没有先后依赖。
#: 2026-11-25 CV4 改了缺省的 5 个参数（Sheldon 11-24 定：缺省改成三本主力书都设的值）：参数指纹仍按**旧缺省**去键，
#: 写了旧缺省值的册（殿本、全唐文写死照旧）与没改缺省前逐位相同。只在算指纹时去（`params_hash`／`param_parts` 传
#: `context={"hash": True}`）；普通 dump 保留这几个键——`step.py` 等处用 `type(p)(**p.model_dump(), …)` 重建参数，
#: 去了键会落回新缺省，写死的旧值就丢了。
_DUMP_DROP_HASH: tuple = (
    (lambda p: not p.consensus_fallback, ("consensus_fallback",)),
    (lambda p: not p.note_lexicon_lib_form, ("note_lexicon_lib_form",)),
    (lambda p: not p.ref_lib_coord_dissent, ("ref_lib_coord_dissent",)),
    (lambda p: not p.solo_coord_dissent, ("solo_coord_dissent",)),
    (lambda p: not p.human_unbound_shift_ok, ("human_unbound_shift_ok",)),
    (lambda p: not p.group_flow_ctx_agree, ("group_flow_ctx_agree",)),
    (lambda p: p.edge_pair_group_seam, ("edge_pair_group_seam",)),
)

_DUMP_DROP: tuple = (
    (lambda p: not p.solo_self_exemplar, ("solo_self_exemplar",)),
    (lambda p: not p.seg_box_check, ("seg_box_check",)),
    (lambda p: not p.book_lanes, ("book_lanes", "book_lanes_fingerprint")),
    (lambda p: not p.symbol_review, ("symbol_min_human",)),
    (lambda p: p.rare_ref_coord_min_cov == _RARE_REF_COORD_MIN_COV, ("rare_ref_coord_min_cov",)),
    (lambda p: not p.occluded_ref_empty_blank, ("occluded_ref_empty_blank",)),
    (lambda p: not p.occluded_manual_seal_blank, ("occluded_manual_seal_blank",)),
    (lambda p: not p.occluded_seal_align_yield, ("occluded_seal_align_yield",)),
    (lambda p: not (p.occluded_manual_seal_blank or p.occluded_seal_align_yield), ("occluded_seal_keep_cov",)),
    (lambda p: not p.pua_code_table, ("pua_code_table",)),
    (lambda p: not p.pua_table_digest, ("pua_table_digest",)),
    (lambda p: not p.pua_code_admit, ("pua_code_admit", "pua_code_admit_cov")),
    (lambda p: not p.group_flow_llm_skip_half, ("group_flow_llm_skip_half",)),
    (lambda p: not p.vis_ruling_half, ("vis_ruling_half",)),
    (lambda p: not p.vis_ruling_ctx_subclasses, ("vis_ruling_ctx_subclasses",)),
    (lambda p: not p.ruling_anchor_loose, ("ruling_anchor_loose",)),
    (lambda p: not p.ruling_by_u, ("ruling_by_u",)),
    (lambda p: not p.codepoint_no_exempt, ("codepoint_no_exempt",)),
    (lambda p: not p.group_flow_ruling_first, ("group_flow_ruling_first",)),
    (lambda p: not p.p_ref_admit, ("p_ref_admit",)),
    (lambda p: (not p.p_ref_admit or p.p_ref_max_cov is None), ("p_ref_max_cov",)),
    (lambda p: (not p.p_ref_admit or not p.p_ref_adjacent), ("p_ref_adjacent",)),
    (lambda p: (not p.p_ref_admit or not p.p_ref_jiazhu), ("p_ref_jiazhu",)),
    (lambda p: (not p.p_ref_admit or not p.p_ref_skip_variant), ("p_ref_skip_variant",)),
    (lambda p: (not p.p_ref_admit or p.p_ref_min_cov == 0.8), ("p_ref_min_cov",)),
    (lambda p: (not p.p_ref_admit or p.p_ref_irregular_gap is None), ("p_ref_irregular_gap",)),
    (lambda p: not p.alt_require_matched, ("alt_require_matched",)),
    (lambda p: not p.alt_note_region, ("alt_note_region",)),
    (lambda p: not p.alt_backed_gain, ("alt_backed_gain",)),
    (lambda p: not p.blank_ink_nonchar,
     ("blank_ink_nonchar", "blank_ink_max_cov", "blank_ink_col_min_agree", "blank_ink_col_min_frac")),
    (lambda p: not p.fold_groups,
     ("fold_groups", "fold_ruling_first", "fold_lib_top_in_group", "fold_coord_ref", "fold_ref_char", "fold_aspect", "fold_occluded", "fold_occluded_lib_max_cov", "fold_aspect_ctx_veto", "fold_ctx_vias", "fold_ctx_strong")),
    (lambda p: not p.fold_ruling_first, ("fold_ruling_first",)),
    (lambda p: not p.fold_lib_top_in_group, ("fold_lib_top_in_group",)),
    (lambda p: not p.fold_coord_ref, ("fold_coord_ref",)),
    (lambda p: not p.fold_occluded, ("fold_occluded",)),
    (lambda p: p.fold_occluded_lib_max_cov is None or not p.fold_occluded, ("fold_occluded_lib_max_cov",)),
    (lambda p: p.fold_ref_char, ("fold_ref_char",)),
    (lambda p: p.fold_aspect is None, ("fold_aspect",)),
    (lambda p: p.fold_aspect_ctx_veto is None, ("fold_aspect_ctx_veto",)),
    (lambda p: not p.fold_ctx_vias, ("fold_ctx_vias",)),
    (lambda p: not p.fold_ctx_strong, ("fold_ctx_strong",)),
    (lambda p: p.ruling_override_groups is None, ("ruling_override_groups",)),
    (lambda p: p.ruling_ref_lead_min_unseen is None, ("ruling_ref_lead_min_unseen",)),
    (lambda p: p.ruling_ref_lead_min_oov is None, ("ruling_ref_lead_min_oov",)),
    (lambda p: p.ruling_glyph_min_score is None and p.ruling_glyph_min_margin is None,
     ("ruling_glyph_min_score", "ruling_glyph_min_margin")),
    (lambda p: not p.symbol_ref_blank, ("symbol_ref_blank", "symbol_ref_blank_cov")),
    (lambda p: not (p.symbol_ref_blank and p.symbol_ref_blank_from), ("symbol_ref_blank_from",)),
    (lambda p: not (p.symbol_ref_blank and p.symbol_ref_gap),
     ("symbol_ref_gap", "symbol_ref_gap_cov", "symbol_ref_gap_min_col")),
    (lambda p: not p.shadow_veto, ("shadow_conf", "shadow_veto_variant_abstain")),
    (lambda p: p.lane_group_img_veto is None, ("lane_group_img_veto",)),
    (lambda p: not p.witness3_knn_veto, ("witness3_knn_veto",)),
    (lambda p: not p.near_knn_gap, ("near_knn_gap",)),
    (lambda p: not p.rare_ref_sparse,
     ("rare_ref_sparse", "rare_ref_sparse_max_n", "rare_ref_sparse_lead", "rare_ref_sparse_variant")),
    (lambda p: p.solo_5b_cov is None, ("solo_5b_cov", "solo_5b_gap", "solo_5b_min_n")),
    (lambda p: not p.no_ref_pages, ("no_ref_pages",)),
    (lambda p: not p.no_ref_params, ("no_ref_params",)),
    (lambda p: not p.trust_from_accuracy, ("trust_from_accuracy",)),
    (lambda p: not p.ref_accuracy, ("ref_accuracy",)),
    (lambda p: not p.ref_variants_off, ("ref_variants_off",)),
    (lambda p: p.consensus_lib_cov is None, ("consensus_lib_cov",)),
    (lambda p: p.ref_lib_5b_veto is None, ("ref_lib_5b_veto", "ref_lib_5b_veto_lead")),
    (lambda p: p.solo_5b_same_cov is None, ("solo_5b_same_cov",)),
    (lambda p: p.solo_5b_scope == "any", ("solo_5b_scope",)),
    (lambda p: not p.replace_form_edge_exclude, ("replace_form_edge_exclude",)),
    (lambda p: not p.lane_coord_blind_guard,
     ("lane_coord_blind_guard", "lane_coord_blind_min_n", "lane_coord_blind_lib_cov", "lane_coord_blind_gap")),
    (lambda p: not p.rare_ref, ("rare_ref_coord", "rare_ref_coord_min_cov")),
    (lambda p: not (p.rare_ref and p.rare_ref_coord_group_top), ("rare_ref_coord_group_top",)),
    (lambda p: not p.rare_ref, ("rare_ref_nf", "rare_ref_nf_max_n", "rare_ref_nf_cov")),
    (lambda p: not p.shadow_veto, ("shadow_model", "shadow_model_fingerprint")),
    (lambda p: not p.approx_fingerprint, ("approx_fingerprint",)),
    (lambda p: not p.solo_ctx_veto, ("solo_ctx_veto",)),
    (lambda p: not p.seal_blank_page, ("seal_blank_page", "seal_blank_thr", "seal_blank_overlap", "seal_blank_ink_out")),
    (lambda p: not p.lane_coord_codepoint_variant,
     ("lane_coord_codepoint_variant", "lane_coord_codepoint_gap", "lane_coord_codepoint_skip")),
    (lambda p: not p.group_flow_lift_ref_veto, ("group_flow_lift_ref_veto",)),
    (lambda p: not p.group_flow_lift_shape_ref, ("group_flow_lift_shape_ref",)),
    (lambda p: not p.group_flow_ref_alias, ("group_flow_ref_alias",)),
    (lambda p: not p.group_flow_near_p, ("group_flow_near_p",)),
    (lambda p: not p.group_flow_hou_shape_late, ("group_flow_hou_shape_late",)),
    (lambda p: p.reference_trust == 'none', ("reference_trust",)),
    (lambda p: not p.ref_topk_follow, ("ref_topk_follow",)),
    (lambda p: not p.ref_lib_coord, ("ref_lib_coord", "ref_lib_coord_cov", "ref_lib_coord_gap")),
    (lambda p: not p.group_flow_abstain_ref_ok, ("group_flow_abstain_ref_ok",)),
    (lambda p: not p.group_flow_ref_free, ("group_flow_ref_free",)),
    (lambda p: not p.group_flow_exclude, ("group_flow_exclude",)),
    (lambda p: p.group_flow_same_writing_keep == list(_SAME_WRITING_KEEP), ("group_flow_same_writing_keep",)),
    (lambda p: p.group_flow_review_fix_agree == ['yr'], ("group_flow_review_fix_agree",)),
    (lambda p: not p.group_flow_dissent_keep, ("group_flow_dissent_keep", "group_flow_dissent_margin")),
    (lambda p: not (p.group_flow_dissent_keep and p.group_flow_dissent_l1), ("group_flow_dissent_l1",)),
    (lambda p: not p.group_flow_ref_pair, ("group_flow_ref_pair", "group_flow_ref_pair_margin")),
    (lambda p: not p.group_flow_ref_pair_coord, ("group_flow_ref_pair_coord",)),
    (lambda p: not p.group_flow_tolerate_extra, ("group_flow_tolerate_extra",)),
    (lambda p: not p.group_flow_provisional_to, ("group_flow_provisional_to",)),
    (lambda p: p.group_flow_pv_ref_gap == 0.01 and p.group_flow_pv_ref_cov == 0.95,
     ("group_flow_pv_ref_gap", "group_flow_pv_ref_cov")),
    (lambda p: not p.group_flow_pair_shape, ("group_flow_pair_shape",)),
    (lambda p: not p.group_flow_pair_shapes, ("group_flow_pair_shapes",)),
    (lambda p: not p.group_flow_pair_shape_veto, ("group_flow_pair_shape_veto",)),
    (lambda p: not p.group_flow_pair_shape_nm_5b, ("group_flow_pair_shape_nm_5b",)),
    (lambda p: not p.group_flow_near_knn, ("group_flow_near_knn",)),
    (lambda p: not p.pair_form, ("pair_form", "pair_form_fingerprint")),
    (lambda p: not p.lane_shape_first, ("lane_shape_first", "lane_shape_first_fingerprint")),
    (lambda p: not p.stroke_veto, ("stroke_veto", "stroke_veto_fingerprint")),
    (lambda p: not p.match_ref_diff_guard, ("match_ref_diff_guard",)),
    (lambda p: not p.lane_seal_title_tolerance, ("lane_seal_title_tolerance", "lane_seal_title_prefix")),
    (lambda p: not p.juan_rule, ("juan_rule", "juan_cov")),
    (lambda p: p.patch_missing == 'error', ("patch_missing",)),
    (lambda p: not (p.lane_witness3 or p.lane_coord or p.lane_seal),
     ("lane_witness3", "lane_coord", "lane_seal", "lane_witnesses", "lane_seal_via", "lane_seal_title_marks", "lane_seal_title_formula", "lane_seal_title_norm", "lane_seal_lib_veto", "lane_seal_shift_guard", "lane_seal_lib_veto_second", "lane_seal_lib_veto_min_n", "lane_seal_codepoint_variant", "lane_witness_fingerprint", "lane_variant_guard", "lane_variant_topk", "lane_variant_keep_rare")),
    (lambda p: not p.lane_lib_veto, ("lane_lib_veto",)),
    (lambda p: not (p.lane_lib_veto and p.lane_lib_veto_pairs), ("lane_lib_veto_pairs",)),
    (lambda p: not (p.lane_witness3 or p.lane_coord or p.lane_seal or p.rare_ref), ("lane_keep_ref_review",)),
    (lambda p: not p.lane_header_formula, ("lane_header_formula", "lane_header_formula_re")),
    (lambda p: not p.pua_rules, ("pua_rules", "pua_rule_cov")),
    (lambda p: not p.semantic_extra, ("semantic_extra",)),
    (lambda p: not p.follow_ref_variants, ("follow_ref_variants",)),
    (lambda p: not p.follow_ref_seen, ("follow_ref_seen",)),
    (lambda p: not (p.follow_ref_seen and p.follow_ref_seen_conflict), ("follow_ref_seen_conflict",)),
    (lambda p: not p.follow_ref and not p.follow_ref_variants and not p.follow_ref_seen,
     ("follow_ref", "follow_ref_cov", "follow_ref_gap")),
    (lambda p: not p.context_lib_dissent_gap, ("context_lib_dissent_gap", "context_lib_dissent_cov")),
    (lambda p: not p.context_page_end_review, ("context_page_end_review",)),
    (lambda p: not p._context_guard_on(), ("context_guard_cov",)),
    (lambda p: p.edge_pair_to == "freq", ("edge_pair_to",)),
    (lambda p: p.edge_pair_cov == 0.92, ("edge_pair_cov",)),
    (lambda p: p.edge_pair_gap == 0.005, ("edge_pair_gap",)),
    (lambda p: p.edge_pair_group_seam_nf_gap == 0.03 or not p.edge_pair_group_seam, ("edge_pair_group_seam_nf_gap",)),
)

class SeedAdmitParams(BaseModel):
    variants: str = ""                  # 异体表；空 = VariantMap 默认
    semantic_extra: str = ""            # 书级补语义对「异体=正字,…」，叠在 VariantMap 之上（如史記 圗=圖：语义同、字形层照刻形）；空＝不补、不进 dump（A22 11-16）
    # ── `solo_cov` = 0.99（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    match_solo 的 cov 闸，实测拐点
    use_context: bool = True            # 把 Step6 的定字当第三路证据
    # ── `context_margin` = 0.7（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    用它时的 margin 门槛（生产值）
    # ── `always_review` = '己已巳'（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    这些字不采信字形/OCR 通道的判决（用户 2026-09-04 定，2026-09-11 改口不再是
    #    「永远人审」）：命中时先清空 `admission_decision` 给的通道，只看 `relax_split_ref`
    #    （整理本给字）与下面的 context 通道（Step6 上下文判定）能不能定下来；两条都没有
    #    结果才落人审。
    #    2026-10-18（S6）起本族「哪个字」只由字组统一流程定：`group_flow` 点名 `jys` 时，这里放进来的格（`split_ref`／
    #    `context`）在页末按文意复核——文意给了别的字就改字，没有文意证据就降审。**没点名 `jys` 的书，`split_ref` 放行的
    #    就是整理本字、不再有任何复核**（旧的 `_resolve_ji_yi_si` 已删）。缺省值不改：vol04 A/B 上它＋`group_flow` 比旧路
    #    放行多 8 格（强真值 40/0 → 48/0）。
    edition: str = "wuyingdian_zongmu"  # 本书用字账（variant_ledger）的键
    # 整理本通道原来在这里配 corpus/corpus_fingerprint，2026-09-09 挪去了
    # `align_ref`（Step5-d，正式 Step，产物带自己的语料指纹）——本步只消费
    # 它的产物，通道开不开看 `align_ref` 锚没锚上，不用再在这里配一份。
    # ── `use_exclusions`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）：查 config/crop_exclusions.jsonl（切坏的图块不进库不出卡）
    exclusions: str = ""                # 名单路径；空 = exclusions.py 默认
    # ── `exclusion_origins` = 'human,gate,pipeline'（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    采信名单里的哪几档来源（逗号分隔）。
    #    **按证据强度分级，别一刀切**（`exclusions.py` 模块头的纪律）：`human` 是人眼实锤；
    #    `gate` / `pipeline` 是管线确定层旗标；`pipeline-suspect` 那 216 条**实测只有约 27%
    #    是真有问题**——全采信会误伤约 150 个好格子（58 页上实测命中 68 条）。所以默认不含它，
    #    要复核时显式打开，或等重扫后逐条判。
    # ── `use_note_lexicon`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）：版本注闭集通道（段级，只作用于夹注格）
    note_lexicon: str = ""              # 词表路径；空 = note_lexicon.py 默认
    # ── `note_min_sim` = 0.7（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    段相似度下限（见 note_lexicon.MIN_SIM）
    note_fingerprint: str = ""          # 自动填：词表变了产物过期
    use_human_verdicts: bool = True     # 人裁过的位直接采信人裁字形（最高优先级）
    # ── `human_unbound_review`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 人裁绑丢闸（2026-10-20，GUJI-697，Sheldon 定：**人裁永远是最高优先级，新放行不许顶掉旧人裁**）。
    #
    # 重切之后，人裁要经绑定表（`feedback/bindings.py`）找回现在对应的格；切开／合并／格没了／锚补不出来的，
    # 绑定表判「不采信」，人裁就从 `_human_shapes`／`human_chars` 里消失了——原来的设计说「回待审」，
    # 但本步并没有把那一格拦下，后面的自动通道照常放行，**人裁被机器悄悄顶掉、没有任何报错**
    # （册2 在 cv dev 上重跑实测：22:6:7 人裁「戕」→ 放行「成」，64:9:21「止」→「什」）。
    #
    # 开着（缺省）时：原编号上有绑丢的人裁、而这一格最后放行的字与人裁的字**不一样** → 退回待审
    # （`doubts` 记 `human_unbound`，`evidence.human_unbound = {char, status, event}`，日志 warning）；
    # 放行的字与人裁一致的照常放行，只在 evidence 上挂标记。只降级、不改字、不放行。放在所有遍之后。
    # 格是不是还是当年那一格不知道（正因为绑不上），所以交给人看图，不拿旧字直接顶上。
    # ── `evict_review`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 撤库重审闸（Sheldon 2026-11-09）：人在库内刻例审阅卡上「撤库」（带 `review` 的 `glyph_audit evict` 事件，
    # 见 `feedback/lookup.evict_review_cells`）的格，多半切坏、看不出是哪个字，**文本撤下来、重新人审**：
    # 这一格机器放行的一律退回待审（`doubts` 记 `evict_review`，待审原因归 seg_defect），之后人再裁的照常采信。
    # 只降级、不改字、不放行，放在所有遍之后。没有这类事件的书产物不变。
    human_unbound_shift_ok: bool = True
    """人裁绑丢闸的顺移豁免（缺省开（2026-11-25 CV4 起缺省改成三本主力书都设的值，Sheldon 11-24 定；参数 dump 仍按旧缺省去键，设了旧值或没设而用新缺省的册指纹分别照旧／改变）；史記 2026-11-01 实测）。

    早期快审的人裁是在旧切分上做的，重切后同列多/少了一格，旧编号上现在是另一个字；补锚档
    （`feedback/anchor_backfill.py`）同列旁证不够时锚不上，人裁按原编号挂到现格上，现格机器放行的字
    （与整理本一致）跟旧人裁不同 → 被闸退回待审。史記册 01–03 这样退回的 401 格里约 360 格是这种。

    开着时，绑丢的人裁只在下面三条**同时**成立时不降级（evidence 照挂 `human_unbound`，另挂 `shift_ok`）：
    绑定状态是 `unanchored`（没有几何，只是编号对不上）；本格放行的字＝整理本在本格的字；
    旧人裁的字＝整理本在同列同半行 ±2 格内某一格的字（即旧编号顺移到了邻格）。只免降级，不改字、不放行。
    「整理本在本格／邻格的字」先看现役对位，缺格的用坐标对位字补（`coord_fallback` 放行的格没有现役对位；2026-11-03，史記第 2 轮 49 格里 32 格因此没被豁免）。"""
    db_path: str = ""    # 读人裁记录用；与 glyph_match 同一个库。留空 = 按 workspace 解析
    human_fingerprint: str = ""         # 自动填：人裁进库了本步要重跑
    iron_config_fingerprint: str = ""
    """自动填：`config/iron_extra_confusable.json`（铁证闸的追加形近/形不可分表）
    变了本步要重跑。开不开铁证闸看册配置 `iron_gate:`（`StepSpec.book_deps`
    已经把这个字段收进指纹了，这里只管配置文件内容本身）。"""
    # ── `iron_ref_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 铁证放行前与整理本互证（2026-09-27 整理 Z7 实测）：铁证定的字与 `align_ref`
    # 对齐字**语义不同**就不放行、落人审（同 `context_conflicts_ref`）。vol03 铁证放行
    # 11 格错 3（曰/白、夬/夫、而/面），三格 align_ref 都标了 replace——库里够像的刻例
    # 是形近字，整理本早就说了不是它。没有对齐字的格不拦。
    # ── `iron_confusable_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 铁证首选与证人（整理本）是**已知形近对**、字又不同就不放行、落人审（overview#426，
    # doubt `iron_confusable_ref`）。证人取现役对位字和坐标对位字（`align_ref.coord`）两路——
    # vol04 铁证放行 20 格错 3（曰/日×2、人/八），三格现役对位都被库分歧过滤掉了
    # （`n_lib_dropped`），`iron_ref_guard` 看不到证人，坐标对位里证人是对的。形近对只认现成表：
    # `confusable.partners()`（手工核过 + 人裁确认 + 字体 τ≥0.988）与铁证补充表
    # `iron_extra_confusable.json`。语义同字（异体、码位）不拦。
    # ── `iron_coord_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 铁证放行前与坐标对位字互证（A20 2026-10-24，A31 vol07:30:4:8 水→木 引出）：现役对位字被库分歧过滤掉
    # （`n_lib_dropped`，`align_char` 为空）时，`iron_ref_guard` 看不到证人，`iron_confusable_guard` 又只认形近表；
    # 坐标对位（`align_ref.coord`）还给得出整理本字，它与铁证字语义不同、两字之间也没有直接异体边
    # （`_direct_variant_edge`，挡住 會/㑹 这类整理本异体写法）→ 不放行，doubt `iron_vs_coord`。现役对位字在时不看坐标对位
    # （归 `iron_ref_guard`）；空格位与 `〓` 不算证人。殿本 17 册 main 包回放命中 14 格（宫/官 ×10、子/予、人/代、木/本、
    # 木/水），看图 13 格是错放、木/本 1 格难分，没有拦下看得出是对的格（cv#522）。戌/戊 有直接异体边（关系层 T1），漏 1 格。
    # ── `iron_ex_missing_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 铁证判别器取候选字的人裁刻例原图做成对复核（每字最多 8 例，`_iron_decide.ex_raws`），
    # 原图在缓存（`GUJI_CACHE_DIR`）里别册别页的 `char_patch`；缓存没有那一例就静默跳过——
    # 同输入、同代码、同 yaml，**只因缓存里有没有别册的字块**，放行结果就会变（overview#554，
    # vol01:90:1:17a／91:1:15 复现：只有 vol01 缓存 vs vol01–07 全在，结果不同）。
    # 开着：铁证本要放行、但判别时有刻例原图缺失（缓存里没有），**不放行**，转待审并记 doubt
    # `iron_ex_missing`，`evidence.iron_ex_missing` 记缺的例数。只会收紧，缓存齐全时与关着逐格一致。
    # v1 旧坐标等「本来就认不出的形状」不算缺（与缓存无关，各环境一样）。
    # ── `iron_ex_from_store`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 铁证判别器的人裁刻例原图改从**字形库**取（A20 2026-11-05，用户「可以修」）：缺省（关）从缓存里
    # 别册别页的 `char_patch` 取，执行机缓存里有哪些册全看它跑过什么——同代码同输入，`iron_ex_missing`
    # 随机器变（史記 01 任务库 #459/#460：8 页只差这一项，两边各缺各的）。开着：刻例图取字形库
    # `instances.patch_png`（与人裁匹配器同一份，册钉了字形库就各机一样），裁到 canonical 图里原裁切
    # 那一块（canonical 只平移不放大，字的像素尺寸不变），缓存一概不读。字形库里人裁实例都有图，
    # `iron_ex_missing` 基本不再出现。会改放行（多出原先缺图转待审的格、刻例图与缓存版本不同的格判别距离变），
    # 2026-11-05 用户定缺省开（史記 01 A/B 见 doc/开关登记表.md）；关着就是老口径（读缓存）。

    # ── `context_blank_gate`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 上下文通道对近空白字块弃权（2026-09-27 D 铁证复核：`vol03:9:9:21` 字块几乎
    # 是空白，`context` 通道仍把它放行成「今」——上下文判定只看文意，不看这一格
    # 到底有没有墨）。字块（`char_index` 的 `ink_ratio`）低于 `context_min_ink`
    # 时不走 context 通道，落人审（`context_blank_cell`）。只挡 context 这一条
    # 通道——`match_solo`/`iron` 等字形通道本身就要求库里能验出「像」，空白格
    # verify 不出 same，链路里已经挡住了，不需要重复设闸。
    # ── `context_min_ink` = 0.05（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `context_blank_gate` 的墨量闸。bxgb + vol03 两书全书 `char_index.ink_ratio`
    #    分布实测（`scripts/measure_context_ink_gate.py`）＋逐格看图定的界：vol03 全
    #    书 `channel=context` 的 262 格里最低 4 格（0.0415~0.0493，含 `vol03:9:9:21`
    #    ink=0.0493、`vol03:67:9:21` ink=0.0415）图上看**都是空白**（碎墨点/划痕，
    #    非字）；再往上第一个「像样」的格是 `vol03:33:2:1`（一，ink=0.0677）——
    #    「一」只有一横，天然低墨，图上确认是真字；中间 0.0604（莫）图上零散不
    #    确定，落在闸的"不拦"一侧（新闸第一版，拿不准就不拦，比错拦一个真字更
    #    安全）。取 **0.05**：压在「确认空白」（≤0.0493）与「确认真字」（0.0677）
    #    之间。bxgb 全书 `channel=context` 134 格最低也有 0.1093（臣），阈值对它
    #    是纯保险栓、不会误伤。
    # ── `context_max_aspect` = 2.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `context_blank_gate` 的姊妹闸（A24 11-01，A32 报错放 vol39:176:3:1）：正文字块（不是夹注）高宽比大于它时不走 context 通道，
    #    落人审（`context_tall_cell`）。高宽比 ≥2.5 的字块是印章边框碎块／粘连切多了的残片，字形库「像」只因为十、卜、丨 这类
    #    竖笔字太容易匹配，context 又只看文意。r5 全 93 册 context 通道放行里只有 3 格（vol39:176:3:1 十 3.3、vol82:191:4:4 十 3.9、
    #    vol96:95:9:2 卜 4.0）；字形通道（match_ref 等，库验过 same）不受影响。0＝关。只收紧。
    # ── `relax_split_ref`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 己/已/巳：整理本给了字就放行——文意取整理本，字形取库 top1（用户 2026-09-06：
    # 「没必要每次都单独让我选文意，根据上下文或整理本直接选；字形选哪个都行」）。
    # 实测 41 条人裁：文意对 39、字形对 40。关掉不等于「永远人审」——下面的 context
    # 通道（2026-09-11 起对己已巳不再排除）仍可能在没有整理本时单独放行。放进来的字由 `group_flow`（jys 组）复核，
    # 见 `always_review`。
    group_flow: tuple[str, ...] = Field(default_factory=_default_flow_groups)   # 缺省开通用字组（11-04 起不含码位组 cp_*，它们是殿本的码位结论；2026-10-23 原先缺省开全部）
    """字组统一流程（新 variant-tie，2026-10-18 sheldon 定；2026-10-23 起缺省＝注册表里全部声明了 flow 的字组，书 yaml 写 `[]` 才关）：点名注册表里声明了 `flow` 的字组 id
    （七个异体组 `mn dian can chen li shen zhi`，六个形近组 `jys ry rr ts wm wxs`）。紧接主循环、在其余后处理遍之前。
    2026-10-18 起它是字组的唯一一条路：旧开关 `ji_yi_si_*`、`ry_group`、`rr_clf`、`m7_*`、`variant_tie*` 已并进来删掉。

    - **补放**：没放行、没撞硬护栏的格，库 top1 cov ≥ `group_flow_min_cov`，与 top1 分差 < `group_flow_delta` 的候选
      ＋整理本字（按书级 `codepoints` 归一后）全落在同一组 → 按组声明的解法（字频 `freq`、IDS、库形最近 `top1`、
      文意 `ctx`、量横、入人八字形分类器）给字放行（通道 `group_flow`），给不出就留人审（`group_flow_abstain`／`_conflict`）；
    - **复核**：组声明了 `review`（己已巳、入人八），已放行字在组里的格也过一遍，解法给了别的字（或解法互相冲突）就降为
      人审（`group_flow_disagree`）；己已巳另有 `review_fix`（文意给了别的字就改字）与 `review_abstain`（文意弃权就降审）。
    - 形近护栏（`never_match`／`conflict`／`near_form`）不挡字组：这些格正该由字组判。

    证据写 `evidence.group`（组、入口、每个解法的给字与理由、结论）。见 `groups/flow.py`、
    doc/design/M7-字组统一流程-variant-tie改造方案.md。关着不进参数 dump（`params_hash` 不变）。"""
    group_flow_exclude: list[str] = Field(default_factory=list)
    """书级减法（A22 11-16，史記 勢𫝑 不可分）：从 `group_flow`（缺省＝注册表全部 flow 组）里去掉这几组，免得书配置抄全名单、
    以后新增组跟不上。写法 `[shi]`；组 id 照 `registry.RENAMED` 换新名，不认识的组报错。空＝不减（不进参数 dump）；
    减后的 `group_flow` 照常进 dump，产物随之过期。"""
    group_flow_freq: str = ""               # 字频表（`python -m open_guji_cv.groups.freq <工作区>` 冻结），空＝字频解法弃权
    # ── `group_flow_freq_major` = 10（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    主形人裁数下限；其余成员须为 0（2026-10-20 sheldon 定 20→10）
    # ── `group_flow_freq_min_vols` = 2（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    主形人裁须来自至少这么多册（表里有册数才查；0＝不查）
    group_flow_tables: dict[str, str] = Field(default_factory=dict)   # 组 id → 文意 L3 大模型答案表（ctx_ver 3；目录沿用旧名 l2/）
    group_flow_models: dict[str, str] = Field(default_factory=dict)   # 组 id → 文意 L2 模型小头（`ctx_model/1`，缺省找 config/groups/l2model/<组>.json）
    group_flow_book_knn: dict[str, str] = Field(default_factory=dict)   # 组 id → 书级刻形近邻库（`groups.book_knn`，缺省找 config/groups/book_knn/<组>.json；没有＝不跑，行为不变）
    group_flow_rr_shape: str = ""            # 入人八 书级刻形判法模型（`groups.rr_shape`，缺省找 config/groups/rr_shape.json；没有＝不跑，行为不变）。
    group_flow_wu_shape: str = ""            # 嗚鳴 书级刻形判法模型（`groups.wu_shape`，缺省找 config/groups/wu_shape.json；没有＝不跑，行为不变；全唐文 11-14）。
    group_flow_hou_shape: str = ""           # 候𠋫 书级刻形判法（`groups.hou_shape`，几何量判 亻 右边第二竖长短；缺省找 config/groups/hou_shape.json；没有＝不跑，行为不变；全唐文 11-20）。
    group_flow_part_shape: str = ""          # 书级部件刻形判法模型（`groups.part_shape`，剌刺／疎踈 等差在一块部件的字对，一份文件挂多对；缺省空＝不跑，不自动找文件；全唐文 11-15）。
    group_flow_near_knn: str = ""            # 形近护栏格书级刻形近邻库（`groups.near_knn`，缺省找 config/groups/near_knn.json；没有＝不跑，行为不变）。
                                              # 只补放待审格，候选限 本格字／整理本／库首位，全书刻例近邻也须同意（全唐文形近字线 2026-11-04）
    group_flow_pair_shape: str = ""          # 书级「两字」刻形二选一模型（`groups.pair_shape`，史记之矣；2026-11-03）。空＝不跑，行为不变。
                                              # 只补放：待审格库首位或整理本是这两字之一，模型给的字＝整理本字或库首位才放（不引入第三个字），
                                              # 人裁格、硬护栏格不碰；图上证据（HOG＋逻辑回归，按册留出 对1899 错0（4 个错放格剔除后）），整理本只作第二证据。
                                             # 有模型的书：刻形说了算，可越过整理本补放、改字（全唐文 sheldon 2026-11-02 定）
    group_flow_pair_shapes: dict[str, str] = Field(default_factory=dict)   # 两字 → 书级刻形二选一模型，可挂多对（`pair_shape/2` 墨量图＋组外判别；
                                              # 全唐文 大太／王玉／還遺 2026-11-07）。补放规则同 group_flow_pair_shape；空＝不跑、不进参数 dump，行为不变
    group_flow_pair_shape_veto: bool = False  # 已放行格（非人裁）刻形强烈反对放行字（模型 veto_thr，分值＋组外判别都过）→ 降回待审，doubt pair_shape_veto。
                                              # 只看 group_flow_pair_shapes 里带 veto_thr 的模型；缺省关、关时不进参数 dump
    group_flow_pair_shape_nm_5b: bool = False  # 匹配器护栏 never_match 的待审格，5-b 首位落在这一对里时也交两字刻形判（原先一律不碰）。
                                              # 全唐文 001–003 目录页 王 50 格（无整理本对位）：离线判 50 对 0 错；5-b 首位是土的那格挡掉（形近字线 11-10）。
                                              # 缺省关、关时不进参数 dump、行为不变
    group_flow_llm_model: str = "claude-opus-5-5"   # 文意 L3 在线（`groups/ctx_llm`）用的模型；空＝不问。密钥只从环境变量 GUJI_ANTHROPIC_API_KEY 读，没有就弃权
    group_flow_llm_groups: tuple[str, ...] = ("ry", "rm", "mz", "jys", "zy", "yz", "xz", "rr", "guan", "men", "wj", "chuo", "yh", "kgc", "tsh",
                                               "yr", "ly", "dt", "mb", "fc", "ts", "zh", "yt", "em", "wm", "sb", "feng", "liang", "wxs", "hou", "js")   # 哪些组问 L3 在线（要有 config/groups/<组>/prompt.md）
    # ── `group_flow_llm_effort` = 'low'（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `group_flow_llm_panel` = ('claude-opus-5-5:high', 'claude-fable-5-1:high')（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    group_flow_llm_panel_groups: tuple[str, ...] = ("ry", "rm", "mz", "jys", "yr", "ly", "dt", "mb", "fc", "ts", "zh", "yt", "em", "wm", "sb", "feng", "liang", "wxs", "hou", "js")   # 用二审小组的组（别的组的 strong 语义没验过，先不开）
    """L3 二审小组（A24 2026-11-01）：首问不是「组内字、high」、或首问的字与整理本不同时，再让这几个模型（`"模型:effort"`）各自高 effort 独立读：
    全部同字（置信 ≥ mid）→ 给字且记 strong；全部说「其他」→ 共字组接手；其余照首问。空＝不开。见 `groups/ctx_llm.panel_verdict`。"""
    group_flow_vis: bool = True             # 字块图像＋文意 L4（`groups/vis_llm`，FlowSpec.vis 的组才问；用 group_flow_llm_model；没密钥＝不问）
    group_flow_llm_skip_half: bool = False
    """夹注 a/b 半格不走 L3（`Llm` 答案表、`CtxOnline` 在线、二审小组；A24 第 5 轮，SJ 史記 L3 放行核对 14 格错 1 格是 men 组 06:12:5:12a）。
    半格窄、字块切分不稳，文意读出的字常错；A31 11-04 定殿本半格归 S 档不由终审判。缺省关（不进 dump，`params_hash` 不变）。
    只管 L3 与终审裁定放行（`vis_ruling` 通道）；规则层（`CtxRule`）、L2 模型、字形解法不受影响。"""
    vis_ruling_half: bool = False
    """`group_flow_llm_skip_half` 开着时，仍让**有看图裁定事件**（`vis_ruling` 通道，两路对话盲读 high、与整理本对位字同格）的夹注半格按裁定放行；
    没有裁定的半格照旧受保护（本就不放行）。书级，缺省关、关时不进参数 dump、行为不变（SJ 史記 11-12：必 04:26:1:13b、解 03:46:1:4a、遲 等半格裁定放不出，半格是形近待审大头）。
    放行条件（A22 评估 11-12）：裁定记的 cell＝当前格号、裁定字＝整理本字（不走白名单）、本格无 clipped／frame_residue／jiazhu_*／split_* 疑点；放行格 evidence.half=True。
    起因的错放（men 组 06:12:5:12a）是旧在线 L3，不是现在的对话双路裁定；放行前须金标验证 0 错。"""
    vis_ruling_ctx_subclasses: str = ""
    """文意终审裁定（`ctx-m1`，group=O）在 Z（字组）、N（形近护栏）之外再收哪些子类，逗号分隔（书级，缺省空、空时不进参数 dump、行为不变）。
    粗校第 4 层「AI 处理文意」：没有字组问的待审格（参校本缺字、复审、库缺例等）由两路独立对话盲判，同字且都 high、字在候选内才写
    `admit_ok`，子类按写入方定（全唐文形近字线 11-18 用 `A`）。其余放行条件与 Z/N 相同：整理本对位字须与裁定记的一致、越过整理本要在白名单。
    开之前须用人裁金标量这一类两路判读 0 错（Sheldon 11-18：形近字文意可以用 AI 判断，属第 4 层固定步骤）。"""
    ruling_anchor_loose: bool = False
    """格锚点后备键的宽松档（GM4 合并方案，GM3／CV0 确认 11-24；书级，缺省关、关时不进参数 dump、行为不变；开的册 seed_admit 起往下过期）。
    关：锚点照 #1832——版本＝本问版本或其等价版本，窗口与裁定记的编辑距离 ≤3。
    开（`RulingStore._anchor_loose`）：同格同 cells_sha 同 ref 下，本组 `validate` 认的任意版本（减 `ver_equiv.yaml` 的 `void`，O 组仍按目标版本）、
    多条取最新、字不一致记 `ruling_conflict` 不放行；只收 high（fold 遍也是）；窗口改为前后 2 字至少一侧相同。
    窗口键、版本等价表照旧先查；在线问前查缓存（`RulingCache`）仍按精确键。开之前须 20 册强制锚点回放人裁真错 0。"""
    codepoint_no_exempt: tuple = ()
    """书级，缺省空、关时不进参数 dump、行为不变（史記 sui/guanm/yinv/can 统一归一，Sheldon 11-26）。列出的拆判字组 id：册 `codepoints:` 归一时
    不再留「人裁／该组判出的刻形照录」的例外，各出口（match_ref／match_replace／human／字组）放行字都落到册指定码位。"""
    ruling_by_u: bool = False
    """裁定按字格永久编号 u 查（CV0 T3 2026-11-24，执行方案 https://claude.ai/artifact/NksDge9ZxaEyebAgnS8s8Q；书级，缺省关、关时不进参数 dump、行为不变；
    开的册 seed_admit 起往下过期，L1）。开：`_vis_ruling_pass` 与 fold 遍在窗口键、版本等价、格锚点都没中之后再查一档——
    本格的 u 从本册字格身份账（`<feedback>/uid/<册>.jsonl`，`feedback.rulings.UidLedger`）按本页当前 cells_sha 取，
    同组同册同 u 的裁定按格锚点宽松档口径取（`RulingStore.get_by_u`：validate 认的版本减 void、多条取最新、字不一致记 `ruling_conflict` 不放行、
    只收 high、前后 2 字至少一侧相同），且裁定字在库候选或＝整理本对位字；看图判通道其余护栏（ref 一致、子类白名单、越过整理本白名单）照旧。
    账里查不到本页这次切分就当没有 u（不回退格号）。账与裁定数据不进指纹，变了要 force 重放。开之前须试点册回放放行集合不变小、人裁真错 0。"""
    group_flow_ruling_first: list[str] = Field(default_factory=list)
    """这几组的文意解法先查裁定库（对话裁定，`feedback.rulings`），命中就照裁定给字，不再看 L1 规则、L2 表／小头（书级，缺省空、不进参数 dump、行为不变）。
    没命中照旧走 L1 → L2 → L3。复核时（`review_fix` 的组，如己已巳）已放行格的上下文有裁定、字不同 → 改成裁定字。
    全唐文 11-13 Sheldon 定：己已巳 刻形分不开、按文意＋AI 判；L2 小头放错的格（001–030 按文意核 23 格），对话裁定排在小头后面改不动。"""
    # ── `group_flow_delta` = 0.03（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `group_flow_min_cov` = 0.85（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `group_flow_top1_cov` = 0.97（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    group_flow_tolerate_extra: dict[str, str] = Field(default_factory=dict)
    """书级追加的字组陪衬字（组 id → 字串，叠在注册表 `FlowSpec.tolerate` 上；2026-11-01 史記文淵閣本）：写本里
    曰 与借来的殿本库形 田／四／囬／臼 紧咬（分差内），格进不了日曰组、文意小头无从判，01–10 册约 900 格因此送审。
    只放宽进入，给字仍全凭解法；组声明了 `tolerate_ref_agree`（日曰有）时，陪衬带进的格还须与整理本同字。空＝不追加（不进参数 dump）。"""
    group_flow_lift_ref_veto: list[str] = Field(default_factory=list)
    """书级：这几组补放（lift）时，整理本对位字（现役对位缺格时用坐标对位字）是组里另一个字、与组给的字不同 → 不放，留人审
    （`group_flow_ref_dissent`；只降不放）。起因（2026-11-03 史記文淵閣本）：山由出 sy 整字 HOG 的模板来自殿本，史記写本山常被判成出
    （标签山的格里判出 143、判山 27），第 6 轮 06:93:4:1a、alt_cut 02:20:6:2b 山被放成出。空＝不启用（不进参数 dump）。"""
    group_flow_near_p: dict[str, float | dict[str, float]] = Field(default_factory=dict)
    """书级（Sheldon 2026-11-26）：形近含义不同的字组读第三步收尾（`glyph_analyzer`）给的组内各字校准概率 p，`{"guan": 0.98}`＝组内最高 p ≥ 0.98
    才由字形放行（也可按字给：`{"guan": {"宫": 0.955, "官": 0.999}}`，没列的字不放；官宫的校准表只标定宫、官 p＝1−p宫，官样本多、门槛要高），不够高的照旧交文意（`groups.methods.NearP`；组的方法数组里有 `near_p` 的才用，现在只有 官宫宮 guan）。方法与文意都有答案且不同 → 送审；
    复核时放行字与它的字不同 → 降审（只降不改字）。门槛按人核格定，不用现行文本当真值。空＝不启用（缺省，不进参数 dump、不读 `glyph_analyzer`）。"""
    group_flow_ref_alias: dict[str, str] = Field(default_factory=dict)
    """书级（全唐文 11-20，sheldon「整理本作 間 的格不再挡本书刻的 閒」）：字组流程里整理本字（及坐标对位字）先按这张表换掉再判，
    `{"間": "閒"}`＝本书只刻 閒、整理本的 間 来自殿本模板，不当 ref_dissent。只影响字组流程（`groups.flow`），不改对位产物与其他通道。
    空＝不换（缺省，不进参数 dump）。"""
    group_flow_hou_shape_late: bool = False
    """书级（全唐文 11-21）：5c vis_ruling 放行之后对 候／𠋫 格再跑一遍 `_hou_shape_pass`，只判还没有 `evidence.hou_shape` 的格。
    hou_shape 那一遍排在字组流程里、5c 之前，5c 补放的 候 格没被刻形判过，到最后码位归一（候→𠋫）一律落成 𠋫
    （ve1 053:23:9:6、053:34:2:9、044:66:8:7）。要 `group_flow_hou_shape` 有模型才生效。缺省关（不进参数 dump）。"""
    group_flow_lift_shape_ref: list[str] = Field(default_factory=list)
    """书级：这几组补放时，`lift_needs`（如日曰要文意给字）没满足、但字形路给的字＝整理本字（现役对位缺格时用坐标对位字），
    且没有任何解法给出别的字（文意只是弃权）→ 照样补放（2026-11-01 史記文淵閣本：写本 曰 在小注里文意 L2 常 low_p 弃权，
    字形宽高比路判 曰、坐标对位也是 曰，01–10 约 100 格因此送审）。空＝不放宽（不进参数 dump）。"""
    group_flow_ref_free: list[str] = Field(default_factory=list)
    """书级「完全不看整理本」的字组（sheldon 2026-11-06：日曰同己已巳，殿本数据：整理本约 7% 错、文意约 90% 读得定）：这几组按 `ref_free` 走——
    入口不看整理本、判法拿不到它、补放与复核都不拿它当证人／兜底（`ref_enter`、`lift_ref_agree`、`tolerate_ref_agree`、`review_ref_agree`、
    `lift_shape_ref`、`abstain_ref_ok`、`lift_ref_guard` 全部失效）。写法 `[ry]`。空＝照注册表（缺省，不进 dump）。"""
    group_flow_dissent_keep: list[str] = Field(default_factory=list)
    """书级（A24 Z02 深挖 2026-11-06，缺省空＝关、不进参数 dump）：这几组复核已放行格时，**已放行字＝整理本字**（现役对位）、至少一路解法给了放行字、
    给别字的解法**全是弱图像票**（`ids` 等记了 margin 的 < `group_flow_dissent_margin`；`yr_bars`、`bars` 这类量笔画的算弱票）→ 不降审（`flow._dissent_keep`，
    留痕 `dissent_keep`）。文意或码位给了别字照旧降审。殿本目视 36 格（遺還、圓圖、面而、傳傅、諭論、甲申、間問、曾會、一二）放行字全对。
    写法 `[em, fc, ly, wj, yh, yt, js, zh, yr]`；入人八 rr 与 日曰 ry 文意不独立，别开（见 doc/字组/判法打架.md）。"""
    group_flow_ctx_agree: list[str] = Field(default_factory=lambda: ['rr'])
    """书级（A24 Z02 11-07 sheldon 定；缺省 `[rr]`（2026-11-25 CV4 起缺省改成三本主力书都设的值，Sheldon 11-24 定；参数 dump 仍按旧缺省去键，设了旧值或没设而用新缺省的册指纹分别照旧／改变）；写 `[]`＝关、不进参数 dump）：`group_flow_dissent_keep`／`group_flow_ref_pair` 里再列入这里的组，
    放行字（复核）或整理本字（补放／联合判）还要**本组文意（ctx，不含共字组搭档）同意**才生效。入人八 rr：整理本 24 对 3 错、
    文意 10 对 10 错，「整理本＝文意」9 格 8 对 0 错。写法 `[rr]`。"""
    group_flow_dissent_l1: list[str] = Field(default_factory=list)
    """书级（A24 Z02 11-07，缺省空＝关、不进参数 dump；只对 `group_flow_dissent_keep` 里的组有效）：复核时已放行字＝整理本字，
    唯一反对的是文意 L1 规则（`ctx:ctx_l1`，二字组合规则，全册审计冲突率约 1–2%），而本组 ids 等非文意解法同意放行字 → 不降审，
    留痕 `dissent_keep`。殿本 B2／B2x 9 格（曾會、遺還、圓圖，规则收窄后仍命中的）放行字全对。写法 `[zh, yh, yt, js]`。"""
    # ── `group_flow_same_writing_keep` = ['xu', 'feng', 'yi_560', 'guan', 'guang', 'jiao', 'jue']（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    书级（A24 Z03 深挖 2026-11-07，缺省 `[xu, feng, yi_560, guan, guang, jiao, jue]`＝Z03 里实有这类格的组、缺省值不进参数 dump；写 `[]` 关）：这几组复核已放行格时，给了别字的解法给的**全是放行字的另一写法**（`registry.PROVISIONAL` 同组，
    #    外加宫宮）→ 不降审（`flow._same_writing`，留痕 `same_writing`）。殿本／史記 21 格（宮宫、賓賔、敘叙、敎教、絶絕）。
    # ── `group_flow_review_fix_agree` = ['yr']（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    书级（A24 Z03 深挖 2026-11-07，缺省 `[yr]`、缺省值不进参数 dump；写 `[]` 关）：这几组复核时 ≥2 路不同的图像解法（`yr_bars`＋`ids` 等）给了同一个别的组员字、
    #    没人（文意、码位）反对 → 改成那个字（`flow._agree_fix`，通道 `group_flow`）而不是降审。一二：殿本／史記 35 格，目视 24 格 yr_bars 数横画全对。
    #    例外（CV4 2026-11-25）：整理本（或坐标对位字）＝已放行字时不改、照常降审（`flow._ref_backs`）——两路图像吃同一张字块，字块裁偏时一起错（殿本 replay-1125 二→一 37 格）。
    # ── `group_flow_dissent_keep_form`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 书级（A24 Z03 11-08，缺省开、缺省值不进参数 dump）：`group_flow_dissent_keep` 的「至少一路解法给了放行字」也认 ids 弃权票（margin < `group_flow_dissent_margin`）的刻形＝放行字
    # （`flow._dissent_keep(form_support)`）。r7 殿本一二 27 格里 19 格是这样：ids 低 margin 弃权、刻形＝放行字＝整理本，只有 yr_bars 数横反对（目视多为单横，横上方是邻字残笔）。
    # ── `group_flow_dissent_margin` = 1.0（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `group_flow_dissent_keep` 里 `ids` 反对票算弱票的 margin 上限（缺省 1.0；仅 `group_flow_dissent_keep` 非空时进参数 dump）。
    group_flow_ref_pair: list[str] = Field(default_factory=list)
    """书级（A24 Z02 深挖 2026-11-06，缺省空＝关、不进参数 dump）：这几组补放／联合判卡在「字形与文意冲突」或「共字组搭档没裁定」时，若**整理本字（现役对位）＝
    本组解法给的字**、反对的全是图像路（margin < `group_flow_ref_pair_margin`；没有文意支持时须比支持的 ids 弱）→ 取这个字（`flow._ref_pair_pick`，留痕 `ref_pair`）。
    文意、码位、搭档文意给了别字不取。殿本 ★main 全册 309 格已被别的通道放行的，字全与它一致（0 异）；目视 Z02 待审 32 格全对。
    写法 `[men, chuo, zy, yr, wm, zh, ts, sy, rr, rm]`。"""
    # ── `group_flow_ref_pair_margin` = 1.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `group_flow_ref_pair` 里图像路反对票的 margin 上限（缺省 1.5；仅 `group_flow_ref_pair` 非空时进参数 dump）。
    group_flow_ref_pair_coord: bool = False
    """书级（A24 Z07 差一路确认 11-07，缺省关、关时不进参数 dump）：`group_flow_ref_pair` 里的组联合判卡在「共字组搭档没表态」、
    现役对位缺这一格时，**坐标对位字＝本组解法给的字、没有任何解法（含搭档）给别字** → 取它（`flow._ref_pair_coord_pick`，留痕 `ref_pair_coord`）。
    夹注半格、〓 不认。殿本＋全唐文 ★main Z07 里 41 格（zy 32、wm 5、men 2…）看图全对。"""
    group_flow_abstain_ref_ok: list[str] = Field(default_factory=list)
    """书级：这几组复核已放行格时，解法全弃权（`group_flow_abstain`）、没有任何解法给出别的字、已放行字＝整理本字
    （现役对位缺格时用坐标对位字）→ 不降审（2026-11-01 史記文淵閣本，用户定「按整理本走」：己已巳文意 L2 首选同字但 low_p、
    曾會㑹 L1 弃权，01–10 正文约 170 格因此送审）。
    同义异体组（`kind=variant`，如 別别）的补放一支：字组判出组内另一写法、与整理本字不一（`ref_dissent`）→ 取整理本形，
    证据 `ref_dissent_follow`（2026-11-02）；同组没有解法给字（弃权）、整理本字在组内（库首位可以不是它）时同样取整理本形，证据 `abstain_ref_follow`；
    不同义的形近组、整理本在组外、文意明说「其他」的弃权都不适用。空＝不放宽（不进参数 dump）。"""
    # ── `group_flow_joint`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 共字组联合补放（2026-10-22）：分差内候选哪一组都装不下、但装得下「组＋它在点名里的共字组」（日曰目三字紧咬：ry＋rm）时也进流程，
    # 先由该组定字，共字组须同意（字也是它的成员）或明说「其他」（L2 表 abstain:other 且 high），否则留人审（`group_flow_joint`）。
    # 见 `groups.flow.decide_joint`。False＝这类格不进流程（2026-10-22 前的行为）。
    # ── `group_flow_form_open`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 字组流程接「写法待定」格（A24 2026-11-06，Z06 深挖，sheldon 11-07 定缺省开；缺省值不进参数 dump）：准入时用字账里 ≥2 个写法的组、形定不了（`form_open`，
    # 原因码 Z06）的格，过去一律被字组流程当硬护栏挡在门外，哪怕这组本来就有按刻形拆判的解法（li 隸𨽾、sui 歲嵗、yi_560 彝彛彞 整字 HOG／三段 IDS）。
    # 开：`form_open` 不再算字组流程的硬护栏，由组的解法定形：给字且与整理本字互证才补放（放行后 doubts 清空）；弃权、与整理本不一的仍留 `form_open`（Z06）。
    # 殿本 ★main 99 册现算 Z06 共 5 格（彛 1、隸 2、歲／嵗 2），离线用组解法试判全部给字、4 格会放行、目视可判 3 格全对。
    # ── `group_flow_coord_outside_skip`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 字组补放入口（A24 2026-11-06，Z01 深挖）：现役对位缺这一格、坐标对位的整理本字既不是该组成员也不是陪衬字
    # （〓、空格位除外）→ 不进该组。组只会在组员里挑字，这类格进组只会弃权（`group_flow_abstain`，原因码 Z01），
    # 不进组后原因落回 L01／P02。殿本第5轮 Z01 527 格里 394 格现役对位缺位。只改原因、不放行；已放行格不受影响
    # （放行侧本有 `coord_dissent` 闸）。False＝旧行为。
    # ── `group_flow_lift_ref_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 字组补放（lift）与整理本互证（A24 2026-10-23，vol15 118:4:15 面→而：文意 L1 规则 em-而-l1 给 而，整理本对位 面，
    # 字形第二路倾向 面 但分差 0.33 不到 0.4 弃权，lift 仍放 而；图是 面）：整理本字是本组成员、与组给的字不同，且组里
    # 没有任何非文意解法（字频、字形、IDS…）给出同一个字 → 不补放，留人审（`group_flow_ref_dissent`）。
    # 共字组联合判（joint，日曰目）不受此限：sheldon 10-22 定日曰文意高置信可改整理本。
    # 现役对位没有这一格、只有坐标对位（`align_ref.coord`）时，坐标对位字不是本组成员且与补放字不同 → 同样不补放
    # （`group_flow_coord_dissent`；vol18 107:6:7 叔→叙、vol16 109:6:21 樊→彝。坐标对位字只用来拦，不参与组内判字）。
    group_flow_provisional: bool = True
    group_flow_provisional_to: dict[str, str] = Field(default_factory=dict)
    #: 暂归一兜底放宽（A24 V01 第 7 轮 11-08）：整理本字（现役对位）与库首位都是某组暂归一的写法、首位 cov ≥ `group_flow_pv_ref_cov`、
    #: 领先最好的组外候选 ≥ 这个数时，分差内有组外形近字也进组兜底（殿本 𨽻→𨽾 被 諫 據 綠 裁 紧咬拦下的 20 格）。None＝关。缺省值不进参数 dump。
    # ── `group_flow_pv_ref_gap` = 0.01（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `group_flow_pv_ref_cov` = 0.95（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    书级暂归一字形：组 id → 字（须是 `registry.PROVISIONAL` 该组 forms 里的字，否则不理），压过表里的 `to`（缺省关；空时不进 dump，
    #    `params_hash` 不变）。全唐文 彝组 yi_560：表里 `to`＝𢑱（殿本放行最多的形），本书刻的是 彝（Sheldon 11-05 同轮人裁 3 格），
    #    r11 复核时 ids 读出 彝（彑米糸廾）而上段 margin 不够改字，兜底就放成了 𢑱（8 格）。
    """同义字组暂归一兜底（sheldon 2026-10-27，见 `groups.flow._provisional`、`groups.registry.PROVISIONAL`）：字组方法拆不开写法、
    与整理本说法不一而留人审／降审的格，只要库形、整理本（或已放行字）都认是这个字，就放成这组最常见的字形，
    `evidence.group.decision` 记 `provisional`。False＝照旧留人审（2026-10-27 前的行为）。"""
    # ── `group_flow_l2_drift` = 2（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    文意 L2 答案表的键（建表时的前后各 20 字）与本次窗口对不上时，若目标字两侧各 3 字内逐字相同、只远处差至多这么多个字位，
    #    仍用表里的答案（证据 `ctx_drift`）；0＝逐字相同才用（2026-10-22 前的行为）。建表后重跑，邻格放行字会变（□→曰、徵→徴），
    #    vol04–10 己已巳／日曰约 40 格因此整条对不上而送审。
    group_flow_fingerprint: str = ""        # 自动填（开关开时）：字频表、规则文件、答案表内容哈希
    witness3_knn_veto: bool = False
    """witness3 本书刻例近邻否决（缺省关；关时不进 dump，`params_hash` 不变；全唐文形近字线 2026-11-04）：`lane_witness3`
    本要放行的格，用 `group_flow_near_knn` 那份本书刻例库在 {库首位, 整理本字} 里判，近邻 ≥ votes_min−1 票指向**库首位**、
    全库近邻多数也是库首位、离库不远 → **不放**，留待审并记 `doubts: witness3_knn_veto`、`evidence.lane_skip = {lane: witness3,
    why: knn_veto}`。异体对（已由 lib_variant 跳过）、模型 `skip_chars`、两字同在 `skip_groups` 某组里（王玉、大太…）不否决；
    没有模型、取不到字块时照旧放（fail-open）。全唐文 r9b：witness3 3,395 格，约 37 格退回，挡掉约 20 格错放（洽→治、有→月…）。"""
    near_knn_gap: bool = False
    """near_knn 入口放宽（缺省关；关时不进 dump，`params_hash` 不变；全唐文形近字线 2026-11-04，A24 审过）：`group_flow_near_knn`
    除形近护栏格、字组未定格外，也收「库没把握、库首位≠整理本」的待审格（不在形近护栏、不在字组里；全唐文 r9b 多归 variant_pair）。
    候选＝本格字、整理本、库前三（`glyph_match` candidates）；不因候选互为异体跳过，改为**出口闸**：给出的字须等于整理本字，
    或与整理本字同属本书码位表／异体表一组，否则留审。判法、门槛、`skip_chars`／`skip_groups` 不变；`evidence.near_knn.via = near_gap`。
    全唐文 r9b variant_pair 164 格：给字 63，看图错 2（元←无、尸←戶，都被出口闸拦下），放 61 错 0。"""
    seg_box_check: list[str] = []
    """字框几何闸（CV2，2026-11-27，朱楓林集 MBJ 报 3:4:7 碎格被放成「一」进了发布文本）：按格高、列宽判字框，命中的一律退回待审，
    doubt 码 `seg_defect`（待审原因 seg_defect）。写要开的判据：`sliver`（Step3 格高 <0.35 格）、`frame_line`（框线扁条）、`speck`（墨点）、
    `split_pair`（一字劈两框，与邻框合起来 <1.25 格）、`tall`（过高框 >1.6 格）；`[all]`＝全开。判据与阈值见
    `seed_admit_lanes.seg_box_defects`。**按书开、按书挑判据**：殿本「一」本来就扁（frame_line 误中），史記卷首大字题会中 tall。
    缺省空＝关，关时不进参数 dump。"""

    @field_validator("seg_box_check", mode="before")
    @classmethod
    def _seg_box_kinds(cls, v):
        from .seed_admit_lanes import SEG_BOX_CRITERIA
        if v in (None, False):
            return []
        if v is True:
            v = ["all"]
        v = [str(x) for x in ([v] if isinstance(v, str) else v)]
        if "all" in v:
            return list(SEG_BOX_CRITERIA)
        bad = [x for x in v if x not in SEG_BOX_CRITERIA]
        if bad:
            raise ValueError(f"seed_admit.seg_box_check 不认 {bad}，可写 {list(SEG_BOX_CRITERIA)} 或 all")
        return [x for x in SEG_BOX_CRITERIA if x in v]

    symbol_review: bool = True    # 2026-10-24 sheldon 定缺省开（殿本 vol04–20 原本逐册开着）
    """特殊符号送审（`doc/design/特殊符号进字符候选集-设计.md` S3，2026-10-24 起缺省开；关时 `symbol_review`／`symbol_min_human`
    不进 dump，`params_hash` 不变）。与册配置 `font.charset.symbols`（5-b 字表收符号）配套开。

    符号形状简单，墨团、残字容易被配成 ●／○，所以第一版：
    - 放行字是符号（`hanzi.symbols`）→ 退回待审，除非走的是库匹配通道（`match_*`／`dual`／`iron`）且本书库里
      同一符号的人裁 ≥ `symbol_min_human` 条；
    - 库 top1 或 5-b top1 是符号、却由上下文通道（`context*`）放行成别的字 → 退回待审（上下文对符号不投票）；
    - 没放行的格，只要放行字／库 top1／5-b top1 有符号，`doubts` 记 `symbol`（网站原因「可能是符号」）。
    人裁位不动。"""
    symbol_min_human: int = 3
    symbol_ref_blank: str = ""
    """书级：这些符号（如 `○`，一串字符，每字一个符号）的字块，整理本（坐标对位）在这一位是**空格**、字形库首位就是这个符号
    且 cov ≥ `symbol_ref_blank_cov` → 放行为该符号，通道 `symbol_ref_blank`。
    起因（Sheldon 2026-11-01，史記文淵閣本）：写本篇末／段末的圈号 ○ 整理本不录，对位说这一位是空格、图上是清清楚楚的圆圈；
    `symbol_review` 因本书库里没有 ≥ `symbol_min_human` 条人裁的 ○ 而一律送审（01–10 册约 480 格）。
    只收符号；遮挡（印章）格、排除名单格、人裁格不动；对位没说空格（整理本这一位有字）的不放。空＝关（不进 dump）。"""
    symbol_ref_blank_cov: float = 0.97
    """`symbol_ref_blank` 的库 cov 下限（库对这个符号的匹配度；本书圈号实测 0.977–0.999）。"""
    symbol_ref_blank_from: str = ""
    """书级，缺省空（关，不进参数 dump，行为不变）。`symbol_ref_blank` 再放宽一档：本格字（`rec.char`）在这串字里（如 `口囗□日四`，圈号 ○ 的图被误判成它们）、
    库首位也在这串字里、库前三名里有 `symbol_ref_blank` 的符号且 cov ≥ 门槛、与库首位 cov 差 ≤ 0.03、整理本此位空（或 `symbol_ref_gap` 放宽后无对位）→ 放行为该符号。
    起因：史記 17/40/41 册约 14 格 ○ 被判口（GUJI-777，SJ 11-27）。遮挡、人裁、排除名单照旧不动；证据 lane 记 `from`。**没做单圈形状检测**（本通道拿不到字块图），
    靠「整理本此位空＋库前三含○＋cov 近」收口；日／目误报风险由这三条挡。需 `symbol_ref_blank` 非空才生效。"""
    symbol_ref_gap: bool = False
    """`symbol_ref_blank` 放宽到「整理本这里没字」（坐标对位没有这一位的条目，`coord.get(id) is None`，不是空格 `""`；
    A24 第 5 轮，长期计划线程转 SJ 史記 r9：ref_gap 里 17 格库首位是 ○、cov 0.92–0.999）。需 `symbol_ref_blank` 非空才生效。
    护栏：同一列里至少 `symbol_ref_gap_min_col` 个字位有坐标对位条目（防整页没对位、切分错）；cov 用 `symbol_ref_gap_cov`；
    遮挡、人裁、排除名单照旧不动；证据 lane 记 `via=gap`。缺省关（不进 dump）。"""
    # ── `symbol_ref_gap_cov` = 0.97（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `symbol_ref_gap_min_col` = 3（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    stroke_veto: str = ""
    """笔画反向护栏（`groups.stroke_veto`，A23 笔画识别 cv #1474）：书级模型路径（相对路径先找数据目录，模型随中心库走，
    如 `config/groups/stroke_veto.json`，再找工作区）。已放行、非人裁、放行字落在模型某组里（己／已／巳、千／干）的格，
    笔画判给了类、且与放行字的类不同（判 己 而放行 已／巳，判 已巳 而放行 己；千、干 互反）→ 降回待审，
    doubt `stroke_veto`，`evidence.stroke_veto` 留判出的类、似然比领先量与特征。笔画弃权（似然比不够、离群、贴坏）不动。
    排在各补放通道之后、人裁绑丢降审之前，各通道放的格都看。全唐文 001–030 扩组2 已放行格里 24 格放行错，
    笔画判全对（形近字线 11-13）。空＝关（缺省，不进参数 dump，行为不变）。"""
    stroke_veto_fingerprint: str = ""
    """笔画护栏模型文件指纹，由校验器填，进 params_hash（模型换了产物判过期）。"""
    pair_form: str = ""
    """放行字按刻形改（2026-11-19，形近字线，第 5／7 步统一方案第 3 步，缺省关）：形近字对归属表路径（相对路径先找数据目录，
    如 `config/groups/pair_attribution.yaml`；写 `-` ＝不用表、所有对都按刻形）。已放行、非人裁的格，第 5 步 5a.3 在
    `glyph_match.stage.pair` 里给了字（`pair.unsure` 开着时 unsure 格也有；把握过该对的门槛，档 ≥2），该字与放行字是同一对里的两个字，
    且这对在表里归刻形（缺省）→ **改放那个字**（通道、provenance 不变，`evidence.pair_form` 留 {from, to, pair, p, tier, rank}）。
    不改：人裁；归文意／暂归一的对；同一格里同含放行字的几对给了不同的字；改成的字被册 `codepoints:` 归一走（簡→𥳑、候→𠋫）；
    库没有那个字。解决 `witness3`／`match_ref` 照整理本放行字、库改了也不变的格（全唐文 020 册 41 个目标格 13 格如此）。
    空＝关（不进参数 dump，行为不变）。"""
    pair_form_fingerprint: str = ""
    """归属表文件指纹，由校验器填，进 params_hash。"""
    lane_shape_first: str = ""
    """witness3／coord_fallback 照刻形（2026-11-20，形近字线，缺省关）：形近字对归属表路径（同 `pair_form`，相对路径先找数据目录）。
    表里 `attr: shape` 且 `variant: true` 的对（同字异形，如 寇𡨥、奧奥）：①库否决（`lane_lib_veto`）要否的格，要放的字与库首位恰是这样一对 →
    改放库首位的形（同 `lane_lib_veto_pairs`，名单由表生成，两处取并集；同样要 5a.3 终判档证据倾向库形）；②witness3 的 `lib_variant` 跳过（库首位与整理本字是已知异体对，一律送审）
    改成：这一对在表里是刻形同字异形、第 5 步 5a.3 对这一对有终判档（tier ≥3）证据且倾向库首位的形、库首位覆盖度 ≥ `lane_lib_veto`（要开着、非 0）→ 放库首位的形（`evidence.lane.lib_form`），
    其余仍送审。只降「送审」为放行、放的是库形（刻本原字），不放整理本字。空＝关（不进参数 dump，行为不变）。"""
    lane_shape_first_fingerprint: str = ""
    """同上，归属表指纹，由校验器填。"""
    ruling_override_groups: tuple[str, ...] | None = None
    """越过参校本的白名单（书级；A20 对照表第 4 条，A24 第 5 轮）：`ctx-m1` 终审裁定的字≠整理本对位字时，管线再核一遍——
    这个字与整理本字须同属白名单里的某个字组（`groups.registry.FLOW_GROUPS` 成员），否则不放行、留审。
    判读脚本写 `admit_ok` 时已按组判过；这里把白名单放进书级配置（进 `params_hash`、可查），金标证据附在册 yaml 注释。
    `None`＝不核（旧行为，不进 dump）；`()`＝一律不许越过整理本。"""
    ruling_glyph_min_score: float | None = None
    ruling_glyph_min_margin: float | None = None
    """终审（`final-review`／`finalize`，guji-manager）判「字形证人」的书级口径（A31 11-05，A23 标定见 ai-team
    `domain/CV/字形领域/L2图一致证人标定-2026-11-05.md`）：该字是 `candidates` **首位**、得分 ≥ `ruling_glyph_min_score`、
    比次优的异体字高 ≥ `ruling_glyph_min_margin`。两项都 `None`＝旧口径（该字在前五且 ≥ 0.95）。
    只放进 `params_hash`（册 yaml 可查），本步放行逻辑不读它；殿本 0.98／0.02，史記、全唐文 0.95／0.02。"""
    ruling_ref_lead_min_unseen: float | None = None
    ruling_ref_lead_min_oov: float | None = None
    """5b「验证整理本字」证人的书级阈值（A31／A23 11-05，评测见 ai-team `domain/CV/字形领域/5b验证整理本字评测-2026-11-05.md`）：
    整理本字 X 是 emb **首位**，且领先次优异字（不同折叠组）≥ 阈值。`unseen`＝本书人裁 ≤2 例的字，`oov`＝不在 CNN 类表里的字，
    两层各一个阈值（建议 unseen 0.01、oov 0.02）。**只与 L2 图一致证人（`ruling_glyph_min_*`）同时成立才放行，绝不单独放行。**
    只放进 `params_hash`（册 yaml 可查），本步放行逻辑不读它，由终审（guji-manager）判；证据记 `via=ref_lead`（带层与领先量）。
    `None`＝关（缺省，不进 dump）。"""
    fold_groups: tuple[str, ...] = ()
    """折叠组（书级；A24 第 6 轮，用户 11-05 定「己已巳、日曰折叠，组内任一字算对」，A31 同意管线侧同口径）：字组在名单里、
    字组流程没放行的待审格，整理本对位字就在这个组里 → 直接放整理本字（通道 `fold`，`evidence.fold = {group, ref}`），不再送审。
    整理本字在组外（真异文）、没有整理本对位、遮挡／排除／人裁格、夹注 a/b 半格不动。空＝关（缺省，不进 dump）。"""
    p_ref_admit: bool = False
    """P 类「机器字≠整理本」取整理本字放行（书级，缺省关；A24 第 6 轮，轮次主线转 R/P 小试点结论 11-04）：待审格的机器字≠整理本对位字，
    两字都不在任何字组里（字组自己判）、不是夹注 a/b 半格、没有遮挡／排除／硬疑问、不是人裁格，且同列相邻格（slot±1）不也是这类格
    （成片＝切分错位的征兆，归 S）→ 放整理本字（通道 `p_ref`，`evidence.p_ref`）。
    依据（r3 小试点，Sheldon 标）：这类格整理本字对 6/6（去掉成片格后），机器字 0 次对；样本小，上线前要抽检未标格。
    **三个书级旋钮（A24 P01 深挖 11-06，缺省全关、关时不进参数 dump；框架与 benchmark 见 guji-manager `待审原因/ref_ocr_diff/`）**：
    `p_ref_max_cov`（机器字的库覆盖率 `evidence.cov` 须**低于**它才放；缺 cov 的格不放；`None`＝不核）、`p_ref_adjacent`（放开「同列相邻格也是
    这类格就不放」）、`p_ref_jiazhu`（放开夹注 a/b 半格）。依据：殿本线上 P01 里只开 `p_ref_admit`（旧口径）放 126 格，看图其中机器字对的 13 格全是库覆盖率
    ≥0.94 的格（库认得机器字、整理本是别的版本）；加 `p_ref_max_cov=0.93` 后放 31 格零错，再放开相邻＋夹注放 52 格（看图 48 对 0 错 4 看不清）。史記 `p_ref_max_cov=0.97`＋
    相邻＋夹注放 87／142 格（看图 62 对、24 图糊按文意、0 错）。全唐文整理本是 Kanripo 另一底本，机器字对的多（20/29），**不要开**。"""
    p_ref_max_cov: float | None = None
    p_ref_adjacent: bool = False
    p_ref_jiazhu: bool = False
    p_ref_skip_variant: bool = False
    """`p_ref_admit` 的旋钮（A24 P01 深挖 11-06，缺省关、关时不进参数 dump；要同时开 `p_ref_admit`）：机器字与整理本字在关系层有**直接异体边**（`_direct_variant_edge`）的格不取整理本字，
    留给异体对流程按刻形定（殿本不按参校本取异体，`follow_ref_variants` 不适用）。依据：放开相邻／夹注、cov<0.95 后 p_ref 也会碰 L01（库认不出）格，殿本这类格抽 30 格 14 格
    是异体对（羨羡、諫諌、緣縁、奥奧、舟丹…），整理本字都对但会盖掉刻形；其余 16 格整理本对 15（1 格黑条）。"""
    # ── `p_ref_min_cov` = 0.8（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `p_ref_admit` 的下限闸（A24 P01，2026-11-08，**缺省 0.8 开**，缺省值不进参数 dump，`None`＝关；要同时开 `p_ref_admit`）：库里认不出机器字的格不放——
    #    库判 `diff`（doubt「库里没有这个字」，多是切分坏格：一格两字、残块、墨块）或机器字库覆盖率 `evidence.cov` < 该值。依据：史記 r19 离线重跑 p_ref 新放约 112 格，118 格看图
    #    0 认错字，但 7 格是切分坏格（01:127:8:1、03:88:4:21b、06:26:1:15、06:26:2:-1/1a/1b、06:29:1:10），多为库认不出或 cov<0.8，放了整理本字会盖住切分错（SJ 11-08）。
    #    P01 本身的格必是 unsure 档（cov≥0.85），这条只挡 p_ref 碰到的 L04／切分类格。
    p_ref_irregular_gap: float | None = None
    """`p_ref_admit` 的旋钮（A24 P01 第 8 轮 11-08，缺省 `None`＝关、关时不进参数 dump；要同时开 `p_ref_admit`）：**整理本字是异体写法**（教育部异体字表 twedu／本地表 local:keben 指认它是某正字的异体：
    槪→概、寳→寶、囘→回、竒→奇、厯→歷…）、机器字与它没有直接异体边，且库候选里「整理本字及其正字」的最高 cov 与机器字 cov 的差 ≤ 该值 → 取整理本字，**不受 `p_ref_max_cov` 约束**
    （相邻／夹注旋钮照旧管）。依据：整理本誊抄者不会凭空造冷僻异体，而机器字把冷僻异体判成常见形近字是库样本少的必然（槪 6 例对慨 62 例、寳 1 例；整理本字不在库里时用它的正字 cov 代，
    正字与异体在库里是并列候选）；这类格机器字 cov 多在 0.97 以上，被 `p_ref_max_cov` 挡住。殿本第 7 轮 P01 275 格中按此口径放 113 格（gap 0.03；cov≥0.95 的 99 格是 `p_ref_max_cov` 0.95 放不了的，整理本字在字组里的 46 格，相邻 18、夹注 1），Claude 看图初判放行格及其近邻共 156 格整理本字对为主，非金标；史記 r6 同口径 23 格看图全对，全唐文 0 格。
    **整理本是另一底本的书（全唐文）不要开**。"""
    alt_require_matched: bool = False
    """`align_ref.alt_select="admit"` 换列的护栏（书级，缺省关、关时不进参数 dump；A24 史記 r18 02:106:7 深挖 11-07）：备选格网这一列里**没有坐标对位字的格**
    （备选那份 `align_ref.coord` 查不到这格 id）比主切法那一遍多，就不换。备选格网多出一格（如 `-1` 抬头格、一个多切的大字格）时坐标对位整列后移一格，
    后面夹注逐格错一位，而 coord_fallback 放的字天然等于坐标字，`与坐标字冲突` 一项恒为 0，只剩「待审少 ≥2」撑着换列。02:106 第 7 列：
    主切法 31 格全有坐标字、待审 3，备选 31 格有 1 格没有坐标字（7:5「畤」）、待审 1，刚好差 2 被换。真换对的列（02:100:5、02:108:6／8）
    备选没坐标字的格都比主切法少（4→1、4→0、13→0）。"""
    alt_backed_gain: int = 0
    """`align_ref.alt_select="admit"` 换列再开一条路（书级，缺省 0 关、关时不进参数 dump；脉经 01 10:2 MJ 11-19）：备选那遍这一列
    待审只少 1 格（够不上 `ALT_ADMIT_MIN_GAIN`），但有字形背书的放行格多出 ≥ 这么多、与坐标字冲突的不多，也换。01 10:2 序页句末「則可」
    主切法劈成「貝丁口」，备选两字整格，待审 4→3、背书 2→3；卷一只多换这一列、卷二不变。"""
    alt_note_region: bool = False
    """`align_ref.alt_select="admit"` 换列再开一条路（书级，缺省关、关时不进参数 dump；脉经 01 MJ 11-20）：备选这一列有雙行小注格
    （如 `row_segment.alt_cuts` 的整列 cells 把「一作某」小注劈对了），而主切法落在这些小注范围里放行的字备选那份也都放行时，
    小注范围外两遍比：待审不多、与坐标字冲突不多，就换。参照本没有小注，劈对了格多、待审反而多，按原规矩永远换不过来
    （01 29:10「得一／作」主切法并成一格、19:12、65:9 同）；主切法在小注范围里本来也放不出字，换了不丢东西。
    反方向也认：主切法把大字劈成 a/b 小注、备选同处是一个放行的大字格（`_big_region_ok`，01 41:1「脉」劈成「永」「月」照样放行）。"""
    consensus_fallback: bool = True
    """共识升档的 same 退回原档（A23，全唐文 r15 回退 46 格，QTW 看图 11-06；第 7 轮；缺省开（2026-11-25 CV4 起缺省改成三本主力书都设的值，Sheldon 11-24 定；参数 dump 仍按旧缺省去键，设了旧值或没设而用新缺省的册指纹分别照旧／改变），关时不进参数 dump）。
    5a 共识升档（`glyph_match.consensus_*`，`via="consensus:<n>"`）把 unsure 升成 same 后，准入对 same 档另有防线：
    库 same 字 ≠ 对位整理本字（含整理本缺字）时 rare_ref／rare_sparse／整理本诸通道都不放，doubt「库 same 但准入被拦」，
    而升档前它是 unsure、本来走 context／match_ref／coord_fallback 等通道放行。开了以后：来自共识升档的 same、
    库字与对位整理本字不同（或这一位没有整理本字）时，本步把它按升档前的样子看（`verdict=unsure`、`char`／`via` 空，
    与没开共识时逐字节相同），走原通道；库字与整理本字相同的共识 same 照旧。全唐文 r15 这类 46 格 r14 原放行字
    看图全对，其中 35 格共识字与原放行字相同。"""
    consensus_lib_cov: float | None = None
    """共识升档 same 的库字放行（全唐文 f4 字形线，2026-11-11；书级，缺省关，`None`＝关、关时逐字节不变、不进 dump）。
    5a 共识升档（`via="consensus:<n>"`，多条刻例同意）判 same 的格，若库字与整理本对位字不同（或没有对位），
    `consensus_fallback` 会把它退回 unsure，常落进待审。本支只看**仍待审**、非人裁的格：退档前记录是共识 same、
    判的字就是库首位、cov ≥ 本值、无护栏、无硬疑问（`_hard_blocked`）、字不是 己已巳／〓／非汉字 → 放库字，
    通道 `consensus_lib`，evidence `consensus_lib`（cov、via、整理本字）；不入字形库（C4）。只升不降。
    依据：f4 016–030 待审里这类 88 格，cov≥0.97 的 78 格（𥳑19 刺8 珏8 𠋫6…，其中 35 格整理本是另一个字如 剌）
    逐格看图 0 错、存疑 1；同一门槛下普通库 unsure（非共识）错率 35%，故只认共识升档。"""
    blank_ink_nonchar: bool = False
    """整理本空格位上有墨、库又认不出的格判非字放行（A22 S02 深挖 11-06，Sheldon 定「这几列没有必要完全挡住」；
    缺省关、关时不进参数 dump；配 align_ref `coord_blank_ink`）。条件：坐标对位说这一位是空格（`ref_char=""`）、
    不是坐标冲突格、库不是 same 且首位 cov < `blank_ink_max_cov`、同列有整理本字的格里库首位与整理本字一致的
    至少 `blank_ink_col_min_agree` 格且占比 ≥ `blank_ink_col_min_frac`（这一列的格位对得上）。放法同印章空栏
    （`admit=True`、`char=None`、通道 `blank_ink`）——随整理本不出字。库有把握是汉字（same 或 cov 够高）的留审：
    可能是整理本漏字。起因：vol19 满文字母、vol10 p86 大印漏认的印文、碎笔格。遮挡格（`occluded`）归 R5，不碰。"""
    # ── `blank_ink_max_cov` = 0.9（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `blank_ink_col_min_agree` = 3（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `blank_ink_col_min_frac` = 0.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    fold_ref_char: bool = True
    """`fold_groups` 的落字来源（sheldon 11-05 澄清：己已巳「匹配到其中任一个就归入这组，之后按文意定是哪一个，完全不能参考整理本」）：
    `True`＝旧行为（整理本字在组内就放整理本字，`fold.via=ref`；裁定优先护栏另算）；`False`＝**不取整理本字**，只放文意裁定（`fold.via=ruling`，
    需本组 L3 提示词的裁定）或字形宽高判据（`fold_aspect`，`via=aspect`），都没有就留审，`evidence.fold_pending={group}` 记「已归组、字待文意」。
    缺省 True（不进 dump）。"""
    fold_aspect: tuple[float, float] | None = None
    """日曰组（`ry`）的字形宽高判据（sheldon 11-05：长宽差别大时直接按字形判，居中归组按文意）：字块外框宽/高 ≥ hi 判曰、≤ lo 判日、中间不判。
    写 `(0.85, 1.0)`＝宽高比 ≥1.0 曰、≤0.85 日。只对 `fold_groups` 里的 ry 格、且无人裁无遮挡无半格的待审格；量的是切分后字块框的宽高（`char_index` 的 `width`／`height`），不是字形主体。
    `None`＝关（缺省，不进 dump）。证据 `fold = {group, via: aspect, aspect: 宽高比}`。"""
    fold_aspect_ctx_veto: float | None = None
    """宽高判据的文意否决（书级，缺省关，不进 dump；A24 H01 深挖 11-06：史記 03:43:2:19b「孔安國曰」切分框不准，宽高比 0.68，单靠宽高会判成日）：
    `context_decide` 的 ranked 里组内**另一个字**的概率 ≥ 这个数时，宽高结论作废，改等文意裁定／留审。证据记 `fold.ctx_veto`（只在作废时写进 `fold_pending`）。
    建议 0.5。开着时字组文意解法（`evidence.group` 里 solver `ctx` agree）给了另一个字也作废（记 `group_ctx`；L1 规则不算、带概率的要到这个数；A24 11-08，SJ 史記 01:45 名单页「日講官」没有 context_decide 排名、组内文意给日）。"""
    fold_ctx_vias: list[str] = Field(default_factory=list)
    """折叠组认字组流程里文意路已给的字（书级，缺省空、不进 dump；A24 H01 第 7 轮复盘 11-08）：本格 `evidence.group` 是同一折叠组、
    文意路（solver `ctx`）`agree` 给了组内字、来源层在名单里（`ctx_l1`／`ctx_l2`／`ctx_l3`／`ctx_llm`，取 via 冒号后一段）→ 按这个字放（`fold.via=ctx`）。
    次序：宽高 → 文意裁定库 → 本条 → 整理本字（旧口径）／留审。这些格在字组流程里是被日目搭档没表态（joint）或殿本宽高比路唱反调（conflict）挡下的，
    文意本身已有答案。殿本第 7 轮 H01：L3 答案表 strong 的 68 格与干净会话盲读 high 全同；L3 非 strong 28 格错 1、L2 19 格错 1、L1 37 格错 15（规则 ry-ext-l1／排比曰 在书名「日錄／日志」上误判），
    所以 **L1 不要进名单**。建议殿本 `[ctx_l3]` 配 `fold_ctx_strong: true`。"""
    fold_ctx_strong: bool = False
    """`fold_ctx_vias` 只认 strong 的文意答案（缺省关、不进 dump）。"""
    fold_occluded: bool = False
    """`fold_groups` 对遮挡格也折叠（缺省关，不进 dump；A32 D01 深挖：殿本 28 格己已巳在遮挡格上没折叠）：遮挡格（`occluded` 疑问／证据）平时不碰，
    开了之后只在**整理本字与库首位（`glyph_match` candidates[0]）都在同一折叠组里**时才归组、再按 `fold_ref_char` 的口径落字——
    `fold_ref_char: false` 时整理本字只用来判归组，字仍由文意裁定／字形判据定，没有就留审（记 `fold_pending`）；
    `fold_ref_char: true`（旧口径）才会放整理本字，己已巳不要这样开。排除、glyph_timeout 格照旧不碰。"""
    fold_occluded_lib_max_cov: float | None = None
    """`fold_occluded` 的放宽（书级，缺省 None＝关，不进 dump；A24 D01 深挖 11-08，殿本第 7 轮 D01 里整理本字是己已巳的 19 格：看图 19/19 图上就是这一族的字，
    库首位却是印泥下的噪声——唐、臯、包、道、卑…，只有 4 格首位在组内，其余 15 格被「库首位也得在组里」挡在折叠之外）：遮挡格库首位不在组里时，
    只要**库首位覆盖度 < 此值**（没有一个有把握的别字反对）、整理本字（现役或坐标对位）在组里，就仍然归组。建议 0.9。
    只管归组，字仍由文意裁定／宽高判据定（`fold_ref_char: false` 时不取整理本字），没有就记 `fold_pending` 留审、不放行；库首位覆盖度 ≥ 此值（有把握的别字）照旧不碰。
    需同开 `fold_occluded`。"""
    fold_ruling_first: bool = False
    """`fold_groups` 的护栏一（缺省关；全唐文 QTW 要求）：裁定库里有这格本组的文意裁定（高／中把握、字在组内，键＝本组 L3 提示词版本＋前后文窗口）时，
    先用裁定字，不放整理本字；没有裁定才放整理本字。"""
    fold_lib_top_in_group: bool = False
    """`fold_groups` 的护栏二（缺省关）：库首位字（`glyph_match` candidates[0]）也必须在本组里才放；首位在组外或没有候选的格留审。"""
    fold_coord_ref: bool = False
    """`fold_groups` 的扩展（缺省关，只在 fold_groups 非空且开时进 dump；全唐文形近字线 11-05）：
    ① 现役对位缺这一格时用坐标对位字（不取空、〓）当整理本字，`evidence.fold.coord = true`（全唐文日曰格现役对位全空、坐标对位都在）；
    ② 没进字组流程的格（没有 `evidence.group`，如库候选分差内有组外字 田 挡了 曰 的入口），库首位与整理本字同在某个折叠组里，
       就按那个组折。②要求库首位在组内，所以开它最好同开 `fold_lib_top_in_group`（①对已入组的格也生效）。"""
    # ── `vis_rulings`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 看图判裁定（无组入口，A24 2026-11-03）：待审格的前后文窗口命中裁定库里「看图＋文意」的 `ctx_ruling`
    # （`group=O`、`prompt_ver=vis-o1`，payload.admit_ok、conf=high、有字）→ 放行成那个字，通道 `vis_ruling`。
    # 只收 A24 名下的子类（A68 库有样本机器字≠整理本、B99 整理本漏字、D130 补判）；整理本对位字须与裁定记的一致；
    # 人裁、遮挡、排除、超时格不动。缓存里没有就什么也不做（不调大模型）。关着（False）才进参数 dump。
    pua_code_table: bool = False
    """按私用码表放字（缺省关，殿本开；A24 2026-11-06，A31 X01 派单）：格在新图源文本层里有私用码（离线算好，裁定库 `src-2` 按**格号**取，
    `RulingStore.cell_codes`；每条带当时的整理本对位字 `ref`，对位字变了不认）、码表（`utils/pua_v2_codes`）定了字、
    **非人裁**放行的字≠码表字 → **改放码表字**（通道 `code_table`，`evidence.code_table` 记原字与原通道），不降审。
    一码多字的码（`families`，如 F1001 乖垂埀）：放行字在族内就认，不按码改；落到族外 → 降审 `src_code_conflict`。
    人裁格不动。这一遍在 `vis_rulings` 之前，所以旧的窗口键降审（src-1 code_conflict）对已改字的格不再触发，也不靠窗口命中。
    每页统计：`PageAdmit.n_code_fix`（改字格数）、`n_code_mismatch`（这一遍之后放行字仍≠码表字的格数，如人裁与码表冲突；族内字不算）。"""
    pua_table_digest: str = ""
    """册钉了 `pua_table_pin`（PUA 码表共享层版本）时由 `core/pua_table_pin.with_pua_table_pin` 填的码表内容指纹（`pua-v<N>-<sha 前 16 位>`）；
    没钉为空、空时不进参数 dump（没钉的书指纹不变）。不是书级旋钮，别手写。"""
    # ── `pua_code_family_demote`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # `pua_code_table` 的书级旋钮（缺省开、开时不进参数 dump）：一码多字的码、放行字落到族外 → 降审 `src_code_conflict`；
    # 关则只计入 `n_code_mismatch`、不动格。
    pua_code_admit: bool = False
    """`pua_code_table` 的书级旋钮（缺省关、关时不进参数 dump；A24 R01 深挖 11-07）：**未放行**、非人裁的格，格有私用码（`src-2`，
    对位字核对同上）、码表定了字（或一码多字的族），且库首位＝码表字（或族内字）、cov ≥ `pua_code_admit_cov`、库没判 diff、无护栏、
    无硬疑问 → 放行成库首位字（通道 `code_table`，`evidence.code_table.admit=True`）。码表字是人定的，库首位独立给出同一个字，两路互证。
    殿本 r6 ★main：R01 668 格里 408 格命中（卿 271）；留出核对：人裁 422 格命中，字 416 格同人裁，6 格是录法（勅敕、埀垂、㸃點），无认错字。"""
    # ── `pua_code_admit_cov` = 0.85（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `pua_code_admit` 的库首位 cov 下限（同 `pua_rule_cov`）。

    # ── `relax_ref_agree`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 整理本字 ≡ 库 top1（语义同字）或 == 上下文定字 时直接放行（用户 2026-09-06：
    # 「很多都是在整理本存在时非常明显的选择，能不能放松要求」）。形取库 top1（刻本形），
    # 文意取整理本。两册人审位实测 整理本≡库top1 10/10、==上下文 4/4，全部 1,1xx 条
    # 人裁真值上反例 0。同时让「义定形未定」的位在库 top1 属组内形时直接取它当形
    # （evidence.form.state=guess，判据 E 会把它算进抽审分母）。
    match_ref_diff_guard: bool = False
    """match_ref 通道不放库判 diff 的格（A24 2026-11-06，书级开关，缺省关；sheldon 点头后殿本开）。match_ref 的 equal 层
    只要「现役对位字＝库首位候选」就放，不看库分与 verdict；对位滑格时库只拿整理本字去比、判了 diff 也照放
    （vol05:66:9:15 冻结包：列格数 18＜整理本 19 走 coord_fallback，现役对位给「字」，库 字 0.73 diff，图上是「不」）。
    开了：match_ref 遇库 verdict=diff 不放，doubt `match_ref_diff`（进 `_LANE_HARD`，补放通道不按整理本字放回）。
    70 册 ★main 包里这类放行 177 格（殿本 155、史記 19、全唐文 3），看图 60 格大多是断笔、字对，开了约每册多 2 格人审。"""
    # ── `ref_lib_diff_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # `relax_ref_agree` 的 `ref_lib` 分支在库判 `diff` 时不放行（A24 2026-10-24，殿本 vol06 v0.5.12 重跑）：
    # 149:3:3 图是「也」，框带版框竖线，整理本对位与库 top1 都给「十」，库判 diff（cov 0.83），照旧被
    # `ref_lib` 放成「十」。库已明说「不像」，整理本与 top1 一致不能证明刻的是这个字；记 doubt
    # `ref_lib_diff`、退回人审。vol06 新包 ref_lib 放行 13 格里只有这 1 格库判 diff，vol04–10 旧包 0 格。
    # ── `ref_lib_variant_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # `ref_lib` 通道变体放行加闸（2026-09-27，R 形近溯源实测 `bxgb:52:11:15` 冶→治
    # 揪出，做法参照 `iron_ref_guard`，参数缺省开）：`relax_ref_agree` 里「库候选与整理本字
    # 语义相同（`vmap.semantic` 归一）」这条，此前只要语义相同就放行，完全不看两者字面是否
    # 一致、也不看 Step6 margin——`variants.auto.tsv` 的 `graph` 来源多数是词典单向登记
    # （twedu 那条 冶→治 就是：`directed['冶']={'治':['twedu']}`，没有反向 `directed['治']`），
    # 不代表刻本场景下两字真同义（`open_guji_cv/variants.py` 模块头「来源分级只是先验」）。
    # 加闸后：库候选与整理本字**字面相同**（`_top == align_char`）不受影响，照放；**字面不同**
    # （变体放行）只有满足以下任一条件才放行，否则记 doubt `ref_lib_variant`、退回人审（不改
    # `char`，不采信这条判决）——
    # - **可信边**：变体关系在关系层双向确认（`open_guji_cv.variants.regulars_of` 两个方向都
    # 收，即两个来源都认对方是自己的正字，不是单向词典登记）；或人工审查确认表
    # `config/dicts/variants.tsv` 登记过这一对（该表本就是人工确认，不要求关系层双向）；
    # 或本书用字账人裁过这一对（`BookLedger.pair_confirmed`，双向都查）；或本书
    # `codepoints` 配置把两个码位统一成同一个（`BookSpec.codepoint_equal`，书级实证，
    # 比字典更硬）——见 `_trusted_variant_edge` 的完整判据；
    # - **Step6 margin 过线**：复用 `context_margin`（0.70，同一把已经在生产用的尺子，不另开
    # 一个阈值）——`context_decision` 给这一位的 margin ≥ 它，即便变体边本身单薄也放行。
    # 三书（bxgb dev_set+p52、vol03 107 页快照、vol01 206 页快照）实测 `ref_lib` 通道共 5 格
    # 变体放行、0 格字面相同：`躭→耽`（vol01，双向可信）、`彝→彞`×3（vol03，双向可信）margin
    # 0.12~0.24 全部远低于 0.70；`冶→治`（bxgb，唯一不可信）margin 0.024。加闸后前四格不变，
    # 冶→治 落人审——详见 done 单。
    # ── `variant_indirect_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 异体等价放行拦**间接路径**（2026-09-28，overview#178，缺省开）。
    #
    # `vmap.semantic` 归一只说明两个字挂到了同一个语义正字，不说明它们之间有边：
    # `𢑴→彝`（hydzd）与 `彞→彝`（twedu）各自挂到「彝」，`𢑴`/`彞` 就被判成同义，
    # 关系层里两者却**没有直接边**，是经第三个字间接连起来的（H #62 `vol04:28:3:18a`：
    # 刻「彝」形，库 top1 `𢑴`、整理本 `彞`，按 `ref_lib` 把 `𢑴` 放行、margin 0.0036）。
    # 开着时，库形与整理本字字面不同、语义相同、但关系层（`variants.json`，除
    # kSpoofingVariant/通假）**没有直接边**的——
    # - `match_ref`/`match_replace`/`match_margin`（`admission_decision` 里那几条拿
    # `vmap.semantic` 比库形与整理本的通道）撤回放行，记 doubt `variant_indirect`；
    # - `ref_lib`：不再能靠 Step6 margin 过闸（直接边的 margin 分支照旧），记
    # `ref_lib_variant` + `variant_indirect`。
    # 例外与 `_trusted_variant_edge` 同口径：人工表 `variants.tsv`、本书用字账人裁、
    # 书级 `codepoints` 认过这一对的照放。**直接边（双向、单向）行为一概不变**。
    # 实测（四庫 vol01–04 快照 + 全唐文 v006–v010 快照，见 #178 评论）：靠异体等价放行的
    # 1,321 格里间接路径 2 格，都是 `𢑴`→`彝`→`彞`，1 格存形错；其余全是直接边。
    solo_ctx_veto: float = 0.0
    """match_solo 系的上下文否决（2026-10-09，overview#450）：`context_decide.ranked` 第一名与
    放行字**语义不同**（异体码点差不算），且第一名概率 ≥ 此值，就不单独放行，记 doubt
    `solo_ctx_veto`、落人审。起因：vol05 `147:9:9` 金标士，库候选 土 0.9955／士 0.9813（纯形状），
    而 context_decide 的 ranked 是 士 0.6327／土 0.2218——系统里已有对的答案，match_solo 这条路
    不看。vol05 377 格 match_solo 里 ranked[0] 与放行字不同仅 27 格。0 = 关（旧行为，不进 dump）。"""
    # ── `context_variant_form_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # context 通道不在异体里选形（A24 2026-10-23，殿本 vol11/14/15 用 v0.5.9 重跑后逐格核）：Step6 的 margin 按语义合并算
    # （`semantic_margin`，为的是 珎/珍 不摊薄），于是 參㕘叅 三形各约 0.33、簒/篡 各 0.46 也报 margin 1.0，context 在异体里抓阄
    # （vol14 235:7:4 两版一次 㕘 一次 叅）。放行字的 `ranked` 里有另一个**语义同字、字面不同**的候选，概率 ≥
    # `context_variant_ratio` × 放行字的概率，而库形分不开它俩（放行字的库 cov 领先不到 `context_variant_lib_gap`；
    # 那个候选不在库候选里 = 分得开）→ 不放行，doubt `context_variant_form`，落人审（异体看刻形）。书级码位归一后同字的不算。
    # ── `context_variant_ratio` = 0.25（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `context_variant_lib_gap` = 0.02（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `context_lib_dissent_gap` = 0.03（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    context 通道与库形互证（A24 2026-10-23）：库 top1 与 context 字语义不同，而 context 字在库候选里落后 top1 至少这么多
    #    （或根本不在库候选里、且 top1 cov ≥ `context_lib_dissent_cov`）→ 不放行，doubt `context_lib_dissent`。
    #    `context_guard_diff` 只拦库判 diff 且 cov<0.8；vol14 的错放库判都是 unsure、cov 0.93–0.98（𣏌→相：库 𣏌 0.984／相 0.948；
    #    㳫→書：杳 0.975／書 0.933；牽→事：奉 0.937、事 不在候选）。0 = 关。
    # ── `context_lib_dissent_cov` = 0.93（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    context_page_end_review: bool = True
    """每页读序最后一格不走 context 通道（A24 2026-10-23）：Step5-d 对位只收两头被 equal 夹住的 replace 段，页末那一格
    没有后一段，库字与整理本不一致时就拿不到对位字，只剩 context 猜。殿本 v0.5.9 vol12／vol14：页末格放行字变率
    1.9%／1.7%，其余格 0.07%／0.05%（vol12 布→補、葬→非、戴→裁，vol14 牽→事、睦→時 都在 9:21）。命中 → doubt
    `context_page_end`，落人审（每册约 2–5 格）。根治在对位侧，另查。"""
    # ── `iron_ctx_prob` = 0.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `iron_ctx_gap` = 0.005（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    replace_form: str = "align"
    """`match_replace` 放行时字形（码位）取谁（2026-09-28，overview#155）：
    - `align`（缺省，旧行为）：库没下 same 断言时取整理本字；
    - `lib`：整理本字与库 top1 语义同、字面不同时，取**库 top1**（刻本字形；这条通道要求
      top1 cov ≥ 0.95，形状证据站得住）；
    - `review`：字面不同就不放行，记 doubt `replace_form`、落人审。
    起因：全唐文 v006 `match_replace` 放行「嚐」，图上是「嘗」——整理本（维基）用了
    异体，码位跟着整理本走了。只在 variant_form（本书用字账组内定形）没接手时生效。"""
    replace_form_edge_exclude: bool = False
    """`replace_form: lib` 换库形时，若库首位与整理本字这一对在本书假边表 `config/variants/edge_pair_exclude.tsv`
    里（不是异体，只是语义表连上了），不换、照整理本字（全唐文码位线 11-05：r12 试 `lib` 估约 11 格把「往」记成
    「住」等，往/住 早已在假边表）。缺省关（关时逐字节不变，不进 dump）。"""
    ref_lib_coord_dissent: bool = True
    """`ref_lib` 放行前看坐标对位：坐标对位给了实字、与现役对位字语义不同时，不放行，记 doubt
    `ref_lib_coord_dissent`（硬疑问，补放通道不再按现役字放回）、落人审（全唐文 r11 11-05：去借库后本书库缺
    麒／褚／俘 刻例，库首位落到 麟／諸／俾，现役对位跟着错位成 equal，ref_lib 照放；坐标对位是对的。r11 ref_lib
    226 格里有坐标对位的 14 格、两边不一致 9 格，看图 7 格坐标对、2 格现役对）。缺省开（2026-11-25 CV4 起缺省改成三本主力书都设的值，Sheldon 11-24 定；参数 dump 仍按旧缺省去键，设了旧值或没设而用新缺省的册指纹分别照旧／改变）；关时逐字节同旧行为、不进 dump。"""
    solo_coord_dissent: bool = True
    """match_solo 系放行前看坐标对位（同 `ref_lib_coord_dissent` 的判据，GUJI-750）：坐标对位给了实字、与放行字
    （库 same 取库字，否则库候选 top1）语义不同，不单独放行，记 doubt `solo_coord_dissent`（硬疑问，补放通道不再放回）、
    落人审。缺省开（2026-11-27 CV4：殿本 large 基线 撫→廵、鶴→號 两格放错字，开后拦入人审；关时逐字节同旧行为）。起因：史记 r49 十册 match_solo 系放行 68 格里，坐标对位字≠放行字 16 格，看图 6 格坐标对（槨→以、陪→倍、
    毒→毐 ×2、理→里、旱→早）、4 格放行对（二→三 ×2、一→二 ×2：数字处坐标对位常漂）、5 格误报（坐标字是私用码／异体）、1 格不确定。
    故豁免：坐标字不是汉字（私用码、占位）、两边都是数字、语义同字（异体）。"""
    note_lexicon_lib_form: bool = True
    """note_lexicon 通道放行的字：库首位与短语字语义同、字面不同时，取库首位的形（刻形），不取短语写的形。
    起因：殿本 large 基线 𨽾→𨽻 6 格（vol02:134、vol04:16/46/48/58/81 的夹注），库首位 𨽾 cov 0.97–0.98，短语表写 𨽻，
    Sheldon 11-24 复核金标是 𨽾。缺省开（2026-11-27 CV4）；关时逐字节同旧行为、不进指纹。"""
    solo_self_exemplar: bool = False
    """match_solo 系放行前看库判 same 的刻例（matched_id）在哪：就在本页本列（册／页／列同、格号不论）→ 不放行，记 doubt
    `solo_self_exemplar` 落人审。起因：殿本 vol01:88:6:9b 管→總、vol02:150:3:14 鶴→號，刻例都在本页本列相邻格。
    **缺省关**（2026-11-27 CV4 评估后没开）：库里不分刻例是不是人裁的，脉经 01 第 11、12 页（目录页，列里人裁刻例很多）
    开了会把 17 个本来放对的格送审，殿本 vol01 多送 1 格；要开须先让它只认非人裁刻例。关时逐字节同旧行为、不进指纹。"""
    ledger_fingerprint: str = ""        # 自动填：账本变了产物过期
    variants_fingerprint: str = ""      # 自动填：语义表（auto + 手工）变了产物过期
    variant_graph_fingerprint: str = ""
    """自动填：关系层 `config/variants/variants.json` 变了本步要重跑——`ref_lib_variant_guard`
    的双向判据直接读它（`open_guji_cv.variants.regulars_of`），此前 `variants_fingerprint`
    只盯 `variants.auto.tsv`/`variants.tsv` 派生表，盯不到关系层本身的改动。"""
    exclusions_fingerprint: str = ""    # 自动填：名单变了产物过期
    rare_ref: bool = True    # 2026-10-24 sheldon 定缺省开（殿本 vol02–20 原本逐册开着）
    """规则 A「5-b × 整理本」放行通道 `rare_ref`（2026-10-02，D3 道 overview#349），2026-10-24 起缺省开。

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
    # ── `rare_ref_coord`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 规则 A 补坐标对位（2026-10-21，M7「无把握与无对位格」，缺省开；只在 `rare_ref` 开着时起作用）。
    #
    # 现役对位（`align_ref.chars`）里**没有**这一格时（difflib 没配上，或被库证据闸 `lib_gate` 拿掉），
    # 用坐标对位字（`align_ref.coord`）当整理本字再走一遍规则 A：5-b 首位逐字等于坐标对位字 → 放行，
    # 字 = 坐标对位字，evidence `rare_ref.via = "coord"`。殿本 vol04–10（cv0.5.4、语料 12）送审 1,255 格里
    # 约 600 格没有现役对位，其中约 30 格（过完下面的护栏）坐标对位字与 5-b 首位一致却没有任何通道接（多是库里没有的字：
    # 䕶、謫、褣、闕…，库首位只是长得像的常用字）。离线对照：同一规则落在已由别的通道放行的格上，
    # 与放行字一致 311/319，不一致的 8 格全是 `context` 通道放的。排在审路（`_review_lanes_pass`）
    # 之后跑，`coord_fallback` 已接走的格（回放里 179 格，字全同）不改通道。
    #
    # 比现役对位那支多四道护栏（坐标对位比 difflib 对位粗）：坐标对位字是 〓（逐列本的生僻字占位）或空格不放；
    # 库首位覆盖度 < 0.90 不放（`_RARE_REF_COORD_MIN_COV`）；
    # 坐标对位字或库首位落在任一字组（`groups.registry`）里不放（归字组流程判）；库前
    # `lane_variant_topk` 名候选里有坐标对位字的异体不放（同 `lane_variant_guard`，免得把刻本异体改成通用字）。
    # 整页没锚上（现役对位整页为空）时不用坐标对位。关着（或 `rare_ref` 关着）时不进参数哈希。
    rare_ref_coord_min_cov: float = 0.90
    """`rare_ref_coord` 那支的库首位覆盖度下限（原模块常量 `_RARE_REF_COORD_MIN_COV`，2026-11-06 A24 改书级参数）。
    缺省 0.90＝老行为，不进 dump，产物指纹不变；各书自己试（L01 深挖：殿本 5b 首位命中的格里 cov 0.85–0.90 的约 18 格被它挡下，
    放低前先做金标、留出 0 错）。"""
    rare_ref_coord_group_top: bool = False
    """规则 A 坐标对位那支：库首位是字组成员、坐标对位字**不在**任何字组时也放（2026-11-06 A24 L05 深挖，书级，缺省关、关时不进参数 dump）。
    缺省行为「坐标对位字或库首位落在任一字组里都不放」把一类格一起拦了：糊墨格库首位是 刪／冊／衛／王… 这类吸引子字
    （它们是字组成员），而整理本字（坐标对位字）与 5-b 首位一致、不在组里。组里的字之间要分的是组员，这时整理本字不是组员，
    字组流程没有可判的事。开了只放宽库首位在组里这一条，**坐标对位字在组里仍不放**。放前先做金标、留出 0 错（殿本 L05 17 格里 15 格库首位在组、整理本字不在，看图全对）。"""
    # ── `rare_ref_nf`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 规则 A 坐标对位那支放宽 `near_form` 疑问（2026-10-28，A24「复盘形近护栏 N 类」，缺省开；只在 `rare_ref_coord` 开着时起作用）。
    #
    # `near_form` 只是「库前三名候选里有形近家族的字」，整理本字在库里没有（或只有 ≤2 条刻例）时，那几个候选只是
    # 库里最像的邻居、不是真对手，却把 5-b 首位＝坐标对位字的格整个拦下（N 类 536 格里 174 格如此）。
    # 放宽的条件（缺一不放）：坐标对位字是 BMP 字（扩展 B 以上稀有字 5-b 不可靠，金标里错放的几乎全是它们）；
    # 坐标对位字在库里的刻例数 ≤ `rare_ref_nf_max_n`（库对这个字没有判力）；库候选里除该字外**没有** cov ≥ `rare_ref_nf_cov`
    # 的对手（强对手说明库有把握认成别的字）；候选里 cov ≥ 0.80 的字不是它的异体（`are_variants`）。
    # 护栏 `never_match`／`conflict`、`occluded`／`excluded` 等其余硬条件照旧。金标（5,980 条人裁格）回放：
    # 坐标对位×BMP 字×本规则 83 格 0 错。关着时不进参数哈希。
    # ── `rare_ref_nf_max_n` = 2（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `rare_ref_nf_cov` = 0.96（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    rare_ref_sparse: bool = False
    """规则 A 少刻例支「5-b 当证人」（2026-11-06，A23 L02 深挖，sheldon 11-06 同意；缺省关，关时逐字节不变、不进 dump）。

    待审单 L02「刻例太少·不一致」的格几乎都是整理本字对、机器字错：整理本字在本书库里只有 0～2 个刻例，库首位只能在
    库里有的字里乱挑（殿本 11-06 ★main 361 格，线上单 286 格逐格看图 274 格整理本字与图一致；ai-team
    `domain/CV/质检/待审原因深挖/L02-刻例太少不一致.md`）。规则 A 两支都放不了它们：现役对位那支要 replace 段，
    坐标对位那支要整页有锚、库首位 cov ≥ 0.90（库里没这个字时 cov 本来就低）。这一支给**仍待审**的格再补一次：

    整理本字（现役对位，没有就用坐标对位）在本书库里刻例 ≤ `rare_ref_sparse_max_n`；5-b 首位是整理本字
    （`rare_ref_sparse_variant` 开时，整理本字是扩展 B 以上罕用码位、5-b 首位是它的异体也算——文淵閣本用罕用码位记的
    异体，字体里常只有通行字，如 𮪍／騎）；5-b 首位领先「同来源、组外」最好候选 ≥ `rare_ref_sparse_lead`
    （分数只跟同一来源比，不同来源量纲不同）→ 放行，字＝整理本字，`channel`＝`rare_ref`，evidence
    `rare_ref.via = "sparse"`、带 `lead`、`n_lib`。护栏同规则 A：硬疑问（`_hard_blocked`）、库 same 认成别的字、
    整理本字或库首位在字组里、己已巳、〓 占位、非汉字都不放；人裁位不碰。只升不降。"""
    # ── `rare_ref_sparse_max_n` = 2（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `rare_ref_sparse_lead` = 0.02（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `rare_ref_sparse_variant`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    solo_5b_cov: float | None = None
    """无参照页「库首位＋5-b 作证」放行（2026-11-08，全唐文总目／姓氏韵编 001/002，形近字线与 A24 定口径；书级，缺省关，
    `None`＝关、关时逐字节不变、三个键都不进 dump）。

    没有整理本可对的页（总目、韵编多是人名，文意帮不上），`match_solo` 只认 cov ≥ `solo_cov`（0.99），0.98～0.99 的格
    全进待审。这一支给**仍待审**、整格**没有任何整理本对位**（现役与坐标都没有）的格再补一次：库首位 cov ≥ `solo_5b_cov`；
    领先「语义不同」（不是同字也不是直接异体）的最好候选 ≥ `solo_5b_gap`；库首位在本书库里刻例 ≥ `solo_5b_min_n`；
    5-b 首位就是库首位（或其直接异体）→ 放库首位，`channel`＝`match_solo_5b`，evidence `solo_5b`（cov、gap、n_lib、5-b 首位）。
    护栏：硬疑问（`_hard_blocked`，含 near_form／护栏:*）、guard 非空、库首位或第二名属手工形近表、库首位在任一字组里、
    己已巳、〓、非汉字都不放；人裁位不碰。只升不降。
    依据（front1 包 001/002，cov≥0.98 去形近／护栏／字组后 4,026 格，看图 Paddle 不同意 93＋同意随机 350＋5-b 不同意 18）：
    只看 cov 错 36（丸 34＝刻「九」、库 丸 仅 2 例；主→王 1；古→右 1），加 5-b 作证后 0；
    0.98／0.01／3 档 001 放约 2,700 格。"""
    # ── `solo_5b_gap` = 0.01（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    solo_5b_min_n: int = 3
    """库首位在本书库里刻例下限（`solo_5b_cov` 开时用）。PR4 收常量后 11-24 恢复成参数：脉经序页、牒文页经 `no_ref_params` 要设 1（刻例少）。"""
    solo_5b_same_cov: float | None = None
    """`solo_5b_cov` 开着时，库匹配已判 same（`verdict="same"`、判的字就是库首位，多为 consensus 多刻例同意）的格，
    cov 门槛降到这个值（2026-11-08，全唐文 002／003 姓氏韻編，形近字线；书级，缺省关，`None`＝关、不进 dump）。
    其余条件（5-b 作证、领先、可信刻例数、形近表／字组／硬疑问）照 `solo_5b_cov`。依据：front4 002／003 待审里
    cov 0.95–0.98、库判 same、5-b 同意、过其余条件的 1,703 格（张劉德崔孫鄭…442 种字）按字排图看，未见错放（1 格 費 存疑）。"""
    solo_5b_scope: Literal["any", "no_ref"] = "any"
    """`solo_5b_cov` 开着时放哪些格（2026-11-26，Sheldon 定参校本属性：无参照放行只在无参照页，CV0）。

    - `any`（缺省，旧行为）：整格没有任何整理本对位的格都算，不管在哪一页；
    - `no_ref`：只放①无参照页上的格——册配置 `reference_profile` 声明 `kind: none` 的页，或 `page_kinds.no_ref`
      （`no_ref_pages`）的页；②有参校本的页上，坐标对位说参校本这一位是缺字（〓、图位，`GAP_CHARS`）的格。
      有参校本的页上「一个对位字都没拿到」的格多是对位或切分出了事，只靠字形库放更险，留待审。
      全唐文 main 包 8 册实数：none 页 7,513 格不变；有参校本页上 94 格（约 0.06%）改回待审（其中参校本标缺字的仍放）。
    缺省 `any` 不进参数 dump，`params_hash` 不变。"""
    no_ref_pages: list[int | str] = []
    """无参校本页（册配置用 `page_kinds: {no_ref: [...]}` 写，不直接写这里）：参校本里本来就没有这段文字的页
    （脉经 01 林億序、06 牒文，2026-11-19 用户定）。这些页对不上参校本是常态、不是切分坏，按 `no_ref_params`
    换一套放行参数。写法同页号（整数或 "5-7"）。空＝没有这类页（不进 dump）。"""
    no_ref_params: dict = {}
    """无参照页上换用的 seed_admit 参数（书级），如 `{solo_5b_cov: 0.95, solo_5b_min_n: 1}`：只在这些页
    叠在本步参数上，别的页不变。无参照页＝`no_ref_pages`（`page_kinds.no_ref`）或册配置 `reference_profile` 声明
    `kind: none` 的页（11-27 起两种写法同一口径）。键须是本步参数名（不许再嵌 `no_ref_*`）。空＝不换（不进 dump）。"""
    trust_from_accuracy: bool = False
    """按参校本准确度分档推信任档（书级，2026-11-27 CV0，Sheldon「四维＋准确度分档」；缺省关、关时不进 dump，行为逐字节不变）。
    开了以后每页看这页参照的 `accuracy`（册配置 `references[].accuracy`，`reference_profile` 段上可压低）：

    - `very_high` → `reference_trust: very_high`；`high` → `reference_trust: high`；`mid` → `ref_lib_coord: true`；
      `low`／未标／无参照页 → 不动（照册里写的）。
    - 只往上推不往下拉：册里已写了更高的 `reference_trust`／`ref_lib_coord` 就照旧（要压低就把 `accuracy` 标低）。
    - 参校本 `script: trad|simp`（异体已归一、码位不跟刻本）的页：关 `follow_ref_variants`（含 `reference_trust` 带的那一项）、
      `edge_pair_to: ref` 退回 `freq`——这种参校本的码位不能照录。
    门槛（very_high ≥ 99.9%、high ≥ 99.5%、mid ≥ 98%，与最终定字一致率）与实测见 `doc/design/参校本四维与准确度分档.md`。"""
    ref_accuracy: str = ""
    """自动填（`trust_from_accuracy` 开时）：本册 `references[]` 的 accuracy/script 与段上压低的摘要，进指纹——标改了本步过期。"""
    ref_variants_off: bool = False
    """逐页派生（`trust_from_accuracy` 开、本页参校本 `script: trad|simp`）：关掉照录参校本异体。册里别直接写（不进 dump 时等于关）。"""
    book_lanes: dict = {}
    """书级无参照补放通道的取值（2026-11-24 CV4，Sheldon 定）：交给书仓 `code/` 覆盖的钩子 `impl/keben/admit_lanes.noref_lanes`，
    cv 不解释其中的键，原样进参数指纹；`data`（路径表，相对数据目录）是通道要读的数据文件，内容哈希进 `book_lanes_fingerprint`。
    全唐文 001–003 原来的 solo_adapt_*／num_run_*／solo_cal_*／lead_5b_* 28 个参数搬进全唐文书仓 k13 后写在这里。
    空＝不调钩子（不进 dump）；写了而书仓没覆盖钩子 → 拒跑。"""
    book_lanes_fingerprint: str = ""          # 自动填：book_lanes.data 的文件内容哈希
    ref_lib_5b_veto: float | None = None
    """「整理本＝库首位」放行（通道 `ref_lib`）的 5-b 否决（A23 2026-11-23，殿本 5a A/B；缺省 None＝关、关时不进 dump）。
    `ref_lib` 不看库分数：整理本字与 5a 库首位字面相同就放。整理本把生僻字规范成常用字（靃→霍）而库里没有这个生僻字时，
    5a 首位恰好落到常用字上，两条弱证据一致就放错了。开着时：`ref_lib` 放行的格，5-b 首位是别的汉字、5-b 分 ≥ 这个值、
    且领先 5-b 其余候选 ≥ `ref_lib_5b_veto_lead` → 不放，记 `ref_lib_5b_veto` 送人审。
    依据：殿本 vol20／vol44 现行产物 ref_lib 放行 42 格，0.95／0.02 拦下 7 格：靃→霍 4 格（现行算法已放错）、
    載（应为戴）1 格、竄／𥨥、涉／渉 各 1 格存疑；新相似度（底座＋平均分）下 vol20 的 8 格 靃→霍 全拦。"""
    ref_lib_5b_veto_lead: float = 0.02
    occluded_gate: bool = True
    """印章／大片污损遮挡的格直接拒（2026-09-28，D 道 overview#195，缺省开）。

    检测见 `steps/occlusion.py`（整页中等墨点密度 + 成块，vol03 全册标定只命中 p3 印章）。
    命中的格：**不进任何放行通道**（`admit=False`、`doubts=["occluded"]`）——太脏，字形
    一律不进字形库（用户原话「这些格太脏，全都不能入库」）；`char` = 默认字：整理本的字，
    先取 `align_ref` 的坐标对位（`PageAlignRef.coord`），没有才取现役对位字，都没有为 None；
    坐标对位说这一位是**空格**（印章切出来的假格）的，`char=None` 并记
    `evidence.occluded.ref_blank=True`（文本层当非字跳过，人审卡默认点「非字」）。
    人裁位照旧一票定案，不受这道闸影响。只会把格从放行挪到待审，不会反过来。"""
    # ── `occluded_min_density` = 4.0（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    热格密度门槛（每万像素中等墨点数），标定见 `steps/occlusion.py` 模块头。
    # ── `occluded_min_cells` = 12（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    热格连通块至少多少格才算遮挡。
    # ── `occluded_min_cols` = 3（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    热格连通块至少横跨几列。
    # ── `occluded_min_peak` = 8.0（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    块内最高密度门槛（真印章 9.2~20.2，vol05 p68 碎笔画误报 6.1）。
    # ── `occluded_min_contrast` = 2.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    块内密度中位 / 本页其余格中位 的下限（真印章 ≥3.1 倍，碎笔画 1.9 倍）。
    # ── `occluded_seal_min_noise` = 4.0（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    大印框内的格，格内背景噪点密度（每万像素中等墨点数）< 此值且整格墨占比 < 0.5 的不算遮挡（sheldon 10-28 定「印章范围内＋
    #    背景有大量噪点」才算；20–99 册抽样约 14% 遮挡格背景干净）。0＝关。缺省开，进参数哈希。
    occluded_ref_empty_blank: bool = False
    """书级（缺省关，不进 dump）：遮挡格所在列整理本这一行是**空的**（坐标对位退回原因 `整理本行为空`，页已按页钉定位）、
    且这一列没有现役对位字 → 默认字来源记 `coord_blank`，由 R5 判非字（同 `occluded_past_leaf_blank`）。
    起因：卷首页小印盖在整理本空列上（史記 05:85、08:119 等，卷首只有题名、印下几列没有字），印下的格机器认成印纹，
    默认字 None、`via=none`，只能人审。需配合 `seal_detect.overrides` 点名印位（模板按原扫描尺度，这几页的印小一圈没测出）。"""
    occluded_manual_seal_blank: bool = False
    """书级（缺省关，不进 dump）：**人定印框**（`seal_detect.overrides` 写的印，`source="manual"`）压着的遮挡格，
    坐标对位没给字（没有坐标对位记录；原先 `via=none`，或印纹上被现役对位硬配了字、`via=align`）→ 默认字来源记
    `coord_blank`，由 R5 判非字。人点名这儿是印、参校本又没字，就不再送人审（全唐文 046–060 层 1 一批 37 格，QTW 11-21）。
    坐标对位给了字的格照旧（印压真字）；库认得出的格（判 same，或判 unsure 且首位相似度 ≥ `occluded_seal_keep_cov`）
    也照旧——印压真字时现役对位常给对字（056:77:1:10 三 0.969、054:89:1:9 五 0.965、051:3:1:10 十 0.944），
    印纹硬配的字库都判 diff 或首位偏低（052:91:2:19 一 0.913）。算法认的印（`frame`／`density`／`template`）不受影响。"""
    # ── `occluded_seal_keep_cov` = 0.93（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `occluded_manual_seal_blank`／`occluded_seal_align_yield` 的「印压真字」保险：库判 unsure 时首位相似度 ≥ 此值不判空。
    #    两个开关都关时不进 dump。全唐文 046–060 人定印框下无坐标字的 120 格里，判空的 117 格首位最高 0.913，保下的 3 格真字 ≥ 0.944。
    occluded_seal_align_yield: bool = False
    """书级（缺省关，不进 dump）：`occluded_past_leaf_blank`／`occluded_ref_empty_blank` 判「整理本说这一列没字」时，
    **落在遮挡格里的现役对位字不算**，这些遮挡格的 `align` 默认字也让位给 `coord_blank`。起因：全唐文 057 p90 列 8、9
    过了半叶末行，印纹上被现役对位硬配了「一」（8:19、9:21），整列就不算空列，其余印下格 `via=none` 进待审，
    那两格还被 R5 按 `via=align` 放成了「一」（A22 11-21 查）。遮挡格外有现役对位字的列照旧不算空列。"""
    # ── `occluded_past_leaf_blank`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 遮挡格所在列过了整理本这半叶的最后一行（align_ref 退回原因 `COORD_PAST_LEAF`，只在按半叶头定位的页上有），
    # 且这一列没有现役对位字 → 默认字来源记 `coord_blank`（整理本说这儿没字），由 R5 判非字（1.29，A32 11-01）。
    # 卷末页整理本只到「…皆附存目」，后面几列是「乾隆御覽之寶」压着的空栏；原先 `via=none` 只能人审。
    # vol20–99 r1 只有 5 页命中（vol21 p225、vol30 p140、vol37 p71、vol39 p176、vol44 p65）。缺省开，进参数哈希。
    seal_blank_page: bool = True
    """盖章空栏判空（2026-10-09，道 B 规格 overview#493；需同开 `lane_seal`；2026-10-22 起缺省开，殿本十册原先逐册开）。

    固定印「乾隆御覽之寶」（`config/seal_templates/`）NCC 命中、印框与格重叠 ≥ `seal_blank_overlap`
    的格，若同时满足：坐标对位无字、且未被强通道（match_ref／match_solo／witness3／match_margin／iron）
    放行、不是人裁格 → 挪成「遮挡待审、默认字 None」，再由 `lane_seal` 的 coord_blank 分支判非字
    （admit=True、char=None、文本层跳过）。context 通道**不算**强通道。只按格判，绝不按列判：印压真字的页
    框内有字的格不动。关着时不进参数哈希，产物逐字节不变。书 yaml `params: {seed_admit: {seal_blank_page: true}}`。"""
    # ── `seal_blank_thr` = 0.35（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    印框 NCC 门槛（留一法 5/5 召回，非印页最高 0.282，阈值两侧余量 ≥0.07）。
    # ── `seal_blank_overlap` = 0.5（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    格与印框重叠面积 ÷ 格面积 的下限。
    # ── `seal_blank_ink_out` = 0.005（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    第四条保险：格内「模板外墨」＝格框内 <128 且落在本页命中模板覆盖区（二值化＋5px 膨胀）外的像素 ÷ 格面积；
    #    ≥ 此值的格不算空（退出候选，仍待审）。只收窄。道 A 量法（overview#493）：真字页 vol02 p188 的 4 格真字
    #    模板外墨 ≥ 0.045，阈值 0.005 与之有 9 倍空档；不是已校准的阈值，只是已知真字都在它外面。

    shadow_veto: bool = True    # 2026-10-24 sheldon 定缺省开（殿本 vol05–20 原本逐册开着，门槛都是 0.8）
    """影子放行闸（overview#305 第一阶段，2026-10-24 起缺省开）：对**现行规则已放行**的格再算一次影子预测，
    影子很有把握选了**不同的字**（`shadow_conf`）就降回待审、evidence 记 `shadow_veto`、doubts 加
    `shadow_veto`。**只降级不升级**；人裁通道不动；信号缺失／本格自身在字形库里／异常 → 弃权。
    关着时下面四个字段都不进 dump：没开的书 `params_hash` 与加字段前逐位相同。"""
    shadow_model: str = ""              # 模型文件；空 = models/shadow_admit/shadow_gate_v1.joblib。路径不进指纹（path_params）
    shadow_conf: float = 0.8           # 影子把握度门槛：殿本 vol05–20 册配置一律 0.8（2026-10-24 收成缺省）；原缺省 0.97 是 vol03 标签上影子 top1 错误率 ≤1% 的最低把握度，见 doc/shadow_gate.md
    shadow_veto_variant_abstain: bool = True
    """影子选的字与现放行字**语义同字**（`vmap.semantic` 相同，即异体／简繁）时影子弃权、不降级
    （overview#431）：vol04 影子拦 61 格只 5 格真错，56 格是放行字＝证人字＝图上字形的刻本异体
    （㫖/旨、旣/既、尙、郞、刋…），影子 pick 的是通用正字——那是标签口径差，不是认错字。
    例外：放行字是罕用码位（不在 U+4E00–9FFF，同 `context_garble_guard` 口径）时不弃权、照常降级——
    vol04 弃权放回的 5 格真错（𠮓→變、𣼣→漏…）都是这一型；代价是 㫖、㓂 这类罕用区刻本异体也会照常降级。
    只在 `shadow_veto` 开着时进 dump。"""
    shadow_model_fingerprint: str = ""  # 自动填：模型文件内容戳——换模型本步要过期
    approx_fingerprint: str = ""
    """自动填：近似字侧表的内容戳（`approx_labels` 条数 + 内容哈希）。表空 = ""。"""

    context_guard_diff: bool = True   # 2026-10-23 sheldon 定缺省开（20 册全开）
    """context 通道放行前，库判 `diff` 且 `cov < context_guard_cov` 就不放行（doubt
    `ctx_guard_diff`，overview#333 建议 1 前半）。库已经明确说「不像」，上下文单凭文意不该
    把它抬成字。缺省关；四个 `context_guard_*` 全是缺省值时都不进 dump，产物逐字节不变。"""
    # ── `context_guard_cov` = 0.8（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `context_guard_diff` 的 cov 门槛。
    context_guard_ref_blank: bool = True   # 2026-10-23 sheldon 定缺省开（20 册全开）
    """坐标对位（`align_ref.coord`）说这一位是**空格**（`ref_char == ''`）、而库判不是 `same`
    时，context 通道不放字（doubt `ctx_guard_ref_blank`，`char=None`，卡片默认非字；建议 2）。"""
    context_guard_ref_prefer: bool = True    # 2026-10-24 sheldon 定缺省开（殿本 vol04/05、11–20 原本逐册开着，06–10 漏开致 vol06 商→而 错放）
    """坐标对位给出整理本字、与 context 定字语义不同、库判又不是 `same` 时，不放行 context 字，
    落人审、默认字取整理本字（doubt `ctx_guard_ref`；建议 3）。不直接放行整理本字：这条路没有
    独立形状证据，放不放留给标定结果。"""
    context_garble_guard: bool = True
    """context 通道放行乱码的护栏（overview#427，C1 道，缺省开）。列切窄、卷末印章被切成字格时，
    字块只剩笔画边缘或印文，库判 diff/低 cov、整理本对不上，Step6 仍可能给 margin 1.0——
    vol04 这样放行了 93 格乱码（`𬑹小𢍺箵㫖是𠳋訁…`）。**没有证人背书**（整理本对齐字、
    坐标对位字、OCR 候选里没有一个与 context 字语义相同；全空也算）时，两条判据任一命中就
    不放行、落人审（字照旧，只是 admit=False）：

    - `ctx_garble_shape`：库 top 相似度 `cov < context_garble_cov`——字块不像任何一个刻例；
    - `ctx_garble_rare`：码位不在 U+4E00–9FFF、且 `cov < context_garble_rare_cov`——
      㫖/㕘/𢑴 这类本书常刻的扩展区字 cov 都在 0.96 以上，不拦；
    （原第三条 `ctx_garble_run`「本列罕用码位成串」2026-10-21 缺省关：vol04–10 只命中 1 格、还是误伤；
    无书再开，2026-11-23 CV4 删。）

    vol04（快照 20261006T0716）：乱码列 context 放行 93 格拦 89；其余 339 格拦 43，看图
    全是错放或非字（版框角、圈号、半字、错位夹注），没有一格是对的。vol03 拦 7/93，同样全是
    错放。数字见 HANDOFF_C1.md（合并后移入 doc/handoffs/），重放脚本 research/garble_guard/replay.py。"""
    # ── `context_garble_cov` = 0.9（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `context_garble_rare_cov` = 0.95（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）

    # ── 待审补放三通道（overview#433，R2 道）。各一个开关，缺省都关，书 yaml 打开 ──────────
    # 接在 iron／ji_yi_si／rare_ref／shadow 之后（页末 `_review_lanes_pass`），只碰仍待审的格：
    # 只升不降、只出文本（`evidence.no_glyph_lib`），人裁位与排除名单不经这里，己/已/巳 一族
    # 一律不走（仍归 `ji_yi_si`）。放行格 `channel`/`provenance` 是通道名，`doubts` 记
    # `lane_<通道名>`，原疑问挪进 `evidence.lane.prev_doubts`。三个开关全关时这一段不进 dump。
    lane_witness3: bool = True   # 2026-10-23 sheldon 定缺省开（20 册全开）
    """R1 三证人一致（通道 `witness3`）：整理本对位来自 `replace` 段、待审类别是 对齐改字层／
    与整理本冲突／形近字（`review.cards.card_class` 同口径），而 `lane_witnesses` 里每家证人
    （逐格读法见 `clustering.witness_cells`）、整理本字、坐标对位字语义全同 → 放行，字 = 整理本字。
    护栏：库首位（刻本原字）与整理本字是已知异体对（语义同、字面不同）→ 不放，照旧送审
    （免得把刻本上的 獘 改成整理本的 弊）。"""
    lane_group_img_veto: float | None = None
    """补放三通道的字组图像判官否决（书级，缺省 None＝关、关时不进参数 dump；A23 11-08，A31 Z02 第 7 轮复查）：
    格进过字组流程、字组没定（`evidence.group`），组里**图像判官**（solver 名以 `_img` 结尾，现只有人入八组 `rr_img`）
    给的字与通道要放的字不同、且自己那个字概率 ≥ 本值 → 不放，记 doubt `lane_group_img`、`evidence.lane_skip.why=group_img`。
    起因：殿本 r7 vol68:160:3:16、vol67:149:9:15 两格图是「入」（舊皆入小說家、咸入版圖），整理本作「人」，
    `rr_img` 判 入 0.77／0.72，字组判待审，`witness3` 照整理本放成 人。r7 殿本 80 册回放：图像判官反对放行字的格只有这 2 格，都拦对。
    字组里别的判官（ids、ry_shape、bars、codepoint、ctx…）反对的 119 格看图几乎全是放行字对，不能一起拦。"""
    lane_coord: bool = True   # 2026-10-23 sheldon 定缺省开（20 册全开）
    """R4 坐标对位兜底（通道 `coord_fallback`）：只碰「其余」类待审格。二选一：库首位 == 坐标
    对位字 == 主证人（`lane_witnesses` 质量最高的那家，四庫即 daizhige 逐列本）→ 字取库首位；
    或每家证人 + 坐标对位字全同、库无护栏 → 字取坐标对位字。库首位与坐标对位字是已知异体对时
    两支都不放（同 R1 的护栏）。"""
    lane_coord_codepoint_variant: bool = False
    """R4 异体护栏放宽（2026-11-04，全唐文码位线，sheldon 定码位表）：库首位与坐标对位字是异体对、但两形在本书
    `codepoints:` 里归一到同一码位（淸/清、兹/茲、勲/勳…）→ 不当「哪个是刻本形说不准」拦下，放归一后的码位
    （`lane.via=lib_coord_codepoint`、`variant_norm=codepoint`）。另要求库候选里归一后不同字的最强对手比首位低
    `lane_coord_codepoint_gap` 以上、首位不是 diff；`lane_coord_codepoint_skip` 列出的字（逗号分隔）不放。
    全唐文 r8 这一类待审 114 格。缺省关，逐书开。"""
    # ── `lane_coord_codepoint_gap` = 0.005（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    lane_seal: bool = True
    """（2026-10-22 起缺省开，殿本十册原先逐册开。）R5 印章区（通道 `seal`）：`occluded_gate` 拦下的格，默认字来源在 `lane_seal_via` 里且有字 →
    放行默认字；坐标对位说这一位是空格（`via=coord_blank`）→ 判非字（`admit=True`、`char=None`、
    `evidence.occluded.ref_blank`，文本层跳过不占位）。护栏：本列坐标对位字连起来含
    `lane_seal_title_marks` 里任一串（卷端／版心题，坐标对位常错位）→ 整列不放。"""
    # ── `lane_seal_via` = 'coord,align'（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    R5 放行哪些来源的默认字（`_occluded` 的 via）：`coord`；加 `align` 连现役对位字也放。
    #    2026-10-26 起缺省 `coord,align`（A32 印章格研究，sheldon 定：印章区 via=align 的 81 格看图未见错字；108 页回放新放 105 格，看图见 1 错：vol43 p2 整理本漏「有」致对位错一格）。
    lane_seal_title_marks: str = "書總目,四庫全書"
    """卷端／版心题列的标记串（本列坐标对位字连起来含任一串 → 整列不走 R5，除非是 `lane_seal_title_formula`
    套语列）。2026-10-26 由「總目,四庫全書」改为「書總目,四庫全書」：正文里的「崇文總目」之类不再连累整列。"""
    lane_seal_title_formula: str = "^欽定四庫全書總目[卷巻][〇一二三四五六七八九十百]+$"
    """R5 题列套语（2026-10-26，A32，sheldon 定）：本列坐标对位字连起来**整串**匹配这个正则 → 这一列的
    印章格按坐标对位字放行，不受 `lane_seal_title_marks` 整列不放、异体护栏、`lane_seal_lib_veto` 的限制
    （套语本身就是第二证据；印泥斑点下字形库几乎读不出）。殿本 47 册 58 列题列逐格看图：56 列与整理本全同，
    另 2 列坐标对位不全或整页错位，本规则或 `lane_seal_shift_guard` 自然不放。空串＝关。"""
    # ── `lane_seal_title_norm` = '巻卷'（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    lane_seal_title_tolerance: int = 0
    """题列套语容错（2026-11-06，A32 D01 深挖，A31 定；书级开关，缺省 0＝关，殿本开 1）：本列坐标字连起来
    **前 8 字**（欽定四庫全書總目）与套语至多差这么多字、其余（卷＋数字）完全符合时，仍按套语放；不一致的那个字位
    本身不放，留人审（vol77 p119 c1 整理本「錠」误字，其余 10 格可放）。差字数超过容错、或尾部不符 → 照旧按题列整列拦。"""
    lane_seal_title_prefix: str = "欽定四庫全書總目"
    """`lane_seal_title_tolerance` 用的套语前缀。"""
    """题列套语放行时的字形归一，两两一对「原字→新字」（sheldon 10-26：題列「巻」一律写「卷」，是本项目的
    新规矩，不必与整理本一致；刻本图上也是「卷」，9 次人裁全取「卷」）。"""
    # ── `lane_seal_lib_veto` = 0.95（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    R5 库否决（2026-10-26，A32）：印章格的字形库首位覆盖度 ≥ 此值、与默认字不同又不是异体对 → 不放，
    #    照旧送审（`lane_skip.why=lib_veto`）。47 册命中 61 格，看图约 12 格默认字是错的（整理本错字
    #    兀/元、新/浙、一/十、門/開，及 vol40 p2 整页错位）。题列套语不受此限。0＝关。
    # ── `lane_seal_lib_veto_second`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    lane_lib_veto: float = 0.0
    """witness3／coord_fallback 两条补放通道的库否决（2026-11-19，全唐文·形近字线；Sheldon 11-19 同意）：要放的字与
    字形库首位不同（语义也不同、不是异体对），而库首位覆盖度 ≥ 此值 → 不放，照旧送审（`lane_skip.why=lib_veto`，
    doubt `lane_lib_veto`）。维基文库 Page 版对比 001–015 发现这两条通道无视库首位放错（位/蝗、刺/殯、戸/吏…）。
    `lib_coord_primary`（放的就是库首位）不受影响。只降不升。0＝关（缺省，不进参数 dump）。"""
    lane_lib_veto_pairs: list[str] = []
    """库否决的照刻形例外（2026-11-19，全唐文·码位线）：每项两个字（如 "寇𡨥"），是同一个词的异体、本书照刻形记。
    库否决要否的这一格若「要放的字」与「库首位」正好是名单里的一对 → 不否决，改放库首位（库形，刻本原字；
    `evidence.lane.lib_form` 记原字与 cov），其余照旧。d2 轮 lane_lib_veto 退回 518 格里约 300 格是这类异体对
    （寇/𡨥 80、奧/奥 49、遙/遥 47、皐/臯 20、冑/胄 17、冊/𠕋 17）。空＝不例外（缺省，不进参数 dump）。"""
    """库否决放宽（2026-10-31，A32）：默认字正是字形库第二名时不否决（印泥压着，近形两字分差常不到 0.01）。
    vol20–99 r3 包里库否决 340 格，看图默认字错的约 10 格，全在「默认字不在库前二」那一档；默认字是第二名的 150 格看图未见错。"""
    # ── `lane_seal_lib_veto_min_n` = 2（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    库否决只在库认得这个字时才算（2026-11-02，A32）：默认字在字形库里的刻例数 < 此值时不否决——库里没有（或只有
    #    一例）这个字，首位必然是别的近形字，「库反对」不是证据。vol20–99 r1 包库否决 177 格里，默认字刻例 ≤1 的 83 格
    #    看图 0 错；刻例 2 的 12 格有 1 错（母/毋），≥10 的 44 格有 6 错。0＝关（旧行为）。
    lane_header_formula: bool = False
    """题列套语放行（史記文淵閣本 2026-11-02，目錄页题列；需同开 `row_segment.header_ref_flag`）：列级旗 `header_ref:<整理本行>`
    整行匹配 `史記卷N` 或 `X第N[上中下][篇名]`（本紀／世家／列傳／表／書），且本列字格数＝整理本行字数 →
    本列还没放行的格按整理本行逐字放行（`lane_header_formula`）；已放行但与整理本行不一致的格（个别近形放错，如一/二）改成整理本字，不一致超过三分之一视为整列错位、整列不动。同「欽定四庫全書總目卷N」套语（sheldon 10-26）：套语本身是第二证据，
    不受字形库、形近护栏限制；字数对不上（切分错了）整列不动。关（缺省）时不进参数 dump。"""
    lane_header_formula_re: str = (r"^(史記卷[一二三四五六七八九十百]+(上|中|下)?"
                                   r"|(本紀|世家|列傳|表|書)第[一二三四五六七八九十百]+(上|中|下)?[^\d]{0,6})$")
    # ── `lane_seal_codepoint_variant`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # R5 异体护栏放宽（2026-10-31，A32）：默认字与库候选是异体对、但两形在本书 `codepoints:` 里归一到同一码位
    # （𩔖→類、巻→卷、别→別…，sheldon 定），或同在 `groups.registry.PROVISIONAL` 暂归一组里 → 不拦，放归一后的字
    # （暂归一组的记 `lane.variant_norm=provisional`）。vol20–99 r3 遮挡格里异体护栏拦下 170 格，这样能放约 155 格。
    # ── `lane_seal_shift_guard`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # R5 整页错位护栏（2026-10-26，A32）：本页印章格里，字形库首位（覆盖度 ≥ 0.9）与「上一格／下一格的
    # 默认字」吻合的格数 ≥ 3 且多过与本格默认字吻合的格数 → 格号整体错了一格，本页印章格一律不放
    # （`lane_skip.why=page_shift`）。47 册只有 vol40 p2 命中（切分漏了列首一行）。
    # ── `occluded_variant_first`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 异体形近规则先于印章遮挡（A31 2026-10-28，sheldon 定：「异体字能处理的就让它处理，处理不了再按印章走」）。
    # 遮挡格原先在主循环里直接拒、并被所有放行通道当硬护栏，结果库首位＝整理本字的格也因「候选里有异体」留在待审
    # （vol20–99 遮挡卡 220 格）。开着时：
    # ① R5：默认字＝库首位且库首位覆盖度 ≥ `seal_lib_cov` 时不受 `lane_variant_guard` 限制（放的就是库形，没有把刻本异体改成通用字的风险）；
    # ② `follow_ref`（登记的异体对）不再把遮挡当硬护栏，条件不变；
    # ③ `group_flow`（字组统一流程）不再把遮挡当硬护栏，但遮挡格只在它给出的字＝默认字（整理本字）时放行，给别的字照旧待审
    # （印章底下字形类解法不可靠，不让它单独改字）。
    # 都不能处理的，仍按 R5 的印章规则走。放行的格字形一律不进库（`no_glyph_lib`）。关着＝回到 1.24 行为。
    lane_variant_guard: bool = True
    """三通道统一的异体护栏（overview#433 vol04 实测）：要放的字与图上字形的线索——现候选字
    `rec.char`、库匹配前 `lane_variant_topk` 名候选——任一是**已知异体对**（语义同、字面不同）时
    不走通道、送审，免得把刻本异体改成通用字（vol04 coord_fallback 把 6 格刻本「㫖」放成「旨」：
    库首位是「旨」，㫖 只在候选里）。只在三通道任一开着时进 dump。"""
    lane_variant_topk: int = 3
    # ── `lane_variant_keep_rare`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # `lane_variant_guard` 的一个例外（A24 2026-10-24，殿本 vol11–20）：坐标对位通道（`lib_coord_primary`）
    # 要放的字＝坐标对位字＝库首位，**三者字面相同、且是少见异体**（语义归一后不是它自己，如 䟦 䘮 𤨏）时不拦。
    # 护栏防的是「把刻本异体改成通用字」；这里放的就是刻本异体本身，整理本照录、库首位同形，两路独立证据对同一字形。
    # vol11–20 有约 50 格因此误送审，看图 䟦 26、䘮 13、𤨏 8 全是整理本对。属任一字组的字（㕘 㸃 䜟 𢑴 㫖 …）不走这条，
    # 由字组按刻形判。只在三通道任一开着时进 dump。
    # ── `lane_keep_ref_review`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 护栏拿整理本字拦下的格不再走待审补放（A24 2026-10-23，vol20 实跑）：`ctx_guard_ref`（ref_prefer）、
    # `group_flow_ref_dissent`／`group_flow_coord_dissent` 降审的格，R1/R4 会拿同一个整理本字、再加文渊阁系证人又放回去。
    # 证人与整理本同源，跟殿本刻字不一致时（其/萁、諸/諧）它们照样一致；vol20 这样放回 23 格里改错 5 格
    # （45:5:18 諸→諧、144:5:20 其→萁、109:5:10 本→木、178:3:16、178:3:19）。开着 = 这些格留人审，默认字仍是整理本字。
    # rare_ref（两遍）同样不碰这些格（A24 10-23 九册核对：vol18:115:6:3 刻「本」由 rare_ref 放成整理本的「木」）。
    # 只在三通道或 rare_ref 开着时进 dump；False＝放回（2026-10-23 前的行为）。
    lane_witness_fingerprint: str = ""
    pua_rules: str = ""
    """整理本缺字特殊规则表（通道 `pua_rule`，A24 2026-10-24 sheldon 定「缺字三层」的第一层）。
    整理本在这一位写 〓（坐标对位或现役对位字是逐列本的 PUA 生僻字占位）、库首位字在表里 → 按表录字。
    表是人看过刻形定下的「这个刻形录哪个码位」，所以只认库首位，不看文意。第二层「库高置信放行」是现有
    `match_solo`（cov ≥ `solo_cov`）；其余照旧送审。格式：逗号分隔，`库首位字` 或 `库首位字=录入字`，
    如 `絃,鉉,確,埀=垂,點=㸃`。表是一套书的数据，写在册 yaml；空 = 关（不进 dump）。
    殿本 vol11–20：sheldon 看图定 9 族 299 格（玄旁缺笔 絃鉉炫弦眩 录正字、確、㽔、邦、鬼、直、垂、㸃、負）。"""
    # ── `pua_rule_cov` = 0.85（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `pua_rules` 的库首位 cov 下限。殿本 9 族 299 格最低 0.89，全是 verdict=unsure、无护栏。
    """自动填（R1/R4 开着时）：`references` 证人文件内容戳，证人改了本步要过期
    （`core.step._with_witness_fingerprint`）。"""
    follow_ref: str = ""
    """照录整理本的异体对（通道 `follow_ref`，A24 2026-10-26「压低组外异体对送审」）。格式：逗号分隔的 `整理本形=库里另一形`，
    如 `㓜=幼,劔=劍,勅=敕,盖=蓋`。登记的是**殿本两种刻法都有、整理本码位就是刻形**的对（看图定，库里少见形没刻例或很少，
    库首位总给常见形）。整理本这一位（坐标对位字，没有时看现役对位字）是表里的整理本形时：
    - 已放行、非人裁、放行字是表里的另一形 → 字改回整理本形（`evidence.follow_ref`）；殿本 vol02–99 看图 21 格全是整理本形；
    - 待审格：库首位是这一对里的一形、cov ≥ `follow_ref_cov`、库没判 diff、无护栏，且首位领先对外最好的候选 ≥ `follow_ref_gap`
      → 放行整理本形。带 `ctx_guard_ref` 的格只在上下文字也是这一对时放。
    不同义的形近对不进这张表。表是一套书的数据，写在册 yaml；空 = 关（不进 dump）。"""
    follow_ref_variants: bool = False
    """书级：`follow_ref` 不限表——整理本字（坐标对位字，没有时看现役对位字）与库首位／已放行字**同义异体**
    （本步异体关系 `vmap.semantic` 相同、字面不同）的对子都照录整理本形，判据同 `follow_ref`（待审格放行、已放行格改回）。
    Sheldon 2026-11-01（史記文淵閣本）：「四库全书有一个置信度非常高的参校本，与其暂归一，不如按参校本取字；
    万一参校本有错，我们还可以回过头来再次整理」——字组拆不开的写法、码位异体（隠𨼆隱、傳𫝊）落整理本码位，
    暂归一放行的格也改回整理本形；证据 `follow_ref.via=variants`／`lane.via=variants` 留痕，方便按参校本错误回查。
    没有参校本的书别开。False＝只认 `follow_ref` 表（不进 dump）。"""
    reference_trust: Literal["none", "high", "very_high"] = "none"
    """书级「参校本可信度」（缺省 `none`＝不额外信任，不进参数 dump；史記文淵閣本 2026-11-02，用户定：把「按参校本走」收成一个有语义的参数）。

    四库系书有一个置信度很高的参校本（同一底本的整理文本）。机器认的字与参校本一致、又没有强反证时，就按参校本走，
    不再因为某个弱解法弃权或反对而送人审。档位逐级叠加：

    - `high`：
      ① 参校字＝库首位＝本格字（含只有坐标对位、没有现役对位的格）、库首位 cov ≥ 0.90、库没判 diff、无护栏、库里没有语义不同的
        对手紧咬（差 < 0.005）→ 放行（通道 `ref_lib_coord`，字形不进库）；人裁绑丢的格只在旧人裁字＝放行字时放；
        日曰目／己已巳／入人八／一二 有专门解法，不碰；
      ② 字组复核：解法全弃权的己已巳、曾會㑹（`abstain_ref_ok`）、字组补放只有字形路给参校字的日曰（`lift_shape_ref`）、
        只有字形路 ids 反对而字＝参校字的廣賔 還遺 衞衛 等（`REFERENCE_TRUST_SHAPE_GROUPS`）→ 不降审、不退人审；
      ③ 异体拆不开的写法取参校本码位并留痕（`follow_ref_variants`）。
    - `very_high`：另加「库认不出」的格——库首位不是参校字、但格带 `ctx_guard_ref`（文意与参校本不同）、库首位 cov < 0.975、
      且本列对位健康（列内已放行格字＝参校字占比 ≥ 0.8、至少 3 格）→ 也按参校本放，evidence `lane.blind=true` 留痕。

    这几项原先是 `group_flow_abstain_ref_ok`／`group_flow_lift_shape_ref`／`follow_ref_variants` 等分散开关，现在由本参数一并导出；
    旧开关仍可单独写（取并集），按书微调用它们。史記 01–10 册 F／G 类看图核对：廣 23、還 12、G 类 89 格几乎全是参校本对。"""
    ref_lib_coord: bool = False
    """只开 `reference_trust: high` 的第 ① 项（整理本字＝库首位＝本格字 → 放行，通道 `ref_lib_coord`），不带 ②③ 与书级其他放宽
    （A24 2026-11-03，第 3 轮 N 类）。殿本整理本不是整本可信（不能开 `reference_trust`），但「整理本坐标对位字、库首位、
    本格字三方一致」只被 `near_form`／上下文 margin 不足挡下的格，看图 28/28 读对（页错位的 vol56 p75 除外，那页带 never_match 护栏）。
    判据同 `ref_lib_coord_decide`，门槛用 `ref_lib_coord_cov`／`ref_lib_coord_gap`（比 reference_trust 的 0.90／0.005 严）。
    `reference_trust` 开着时本开关不起作用（以它的门槛为准）。False＝关（不进 dump）。"""
    lane_coord_blind_guard: bool = False
    """`coord_fallback` 的 `witnesses_coord` 一支（库首位≠参校字、只靠证人同意参校字）的护栏（A23 建议并回放，A24 Z04 深挖 11-07；
    殿本 飲→餘、二→三 图上是库首位）：库首位 cov ≥ `lane_coord_blind_lib_cov`，参校字在库候选里但比库首位低 ≥ `lane_coord_blind_gap`，
    且参校字在本书库里刻例 ≥ `lane_coord_blind_min_n` → 不放，留审（`lane_skip.why=ref_blind`）。参校字不在候选里的不拦
    （r6 回放：不在候选一支 10 格拦对 1 错拦 8）。第 6 轮殿本 80 册 ★main 回放：4051 格里恰拦 2 格，都拦对。缺省关，关时不进参数 dump。"""
    # ── `lane_coord_blind_min_n` = 3（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `lane_coord_blind_lib_cov` = 0.98（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `lane_coord_blind_gap` = 0.05（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `ref_lib_coord_cov` = 0.96（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    # ── `ref_lib_coord_gap` = 0.01（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    只在 `ref_lib_coord` 开着、`reference_trust` 关着时用：库首位 cov 下限，与语义不同的最好对手的领先下限。
    ref_topk_follow: bool = False
    """库前 5 名候选里有整理本字、且与首位 cov 差 ≤ `REFERENCE_TRUST_TOPK_GAP` 时按整理本放（史記文淵閣本 2026-11-03，
    第 2 轮 P 类「机器字≠整理本」90 + 「整理本改字层」71 格看图：161 格里整理本字对的 ≥ 95%，库首位是形近字抢先；
    整理本字在库前 5 名的 59 格逐格看图全是整理本对，整理本字不在前 5 的 102 格里才出现机器对、整理本错的几例）。
    要 `reference_trust: very_high`、本列对位健康（列内已放行格字＝整理本字占比 ≥ 0.8、至少 3 格）、
    无护栏、库没判 diff、无字组解法反对，疑问码只限 `_REF_LIB_COORD_DOUBTS`；日曰目／己已巳／入人八／一二 不碰。
    通道 `ref_lib_coord`，evidence `lane.topk_rank` 留痕，方便按参校本错误回查。False＝关（不进 dump）。"""
    follow_ref_seen: str = ""
    """看图核实过的字对（通道 `follow_ref`，证据 `via=seen`，A24 2026-11-02，全唐文 Z 弃权／N 形近护栏）。格式同 `follow_ref`：
    逗号分隔的 `整理本形=库里另一形`（王=玉,天=大,永=氷 …）。这些对子在本书按字对抽样看图（每对 16 格）整理本形全对、机器读错，
    所以**不限同义异体**：待审格的库首位是这一对里的一形、cov ≥ `follow_ref_cov`、库没判 diff、无硬疑问（遮挡、乱码、护栏冲突、
    字组解法／文意给了别的字）时，放整理本形。与 `follow_ref` 的区别：不拦 `near_form`、`group_flow_abstain` 和文意不足的疑问码
    （这类对子的库首位本来就是形近字护栏拦下的）；只升待审格，不改已放行格。每对要在本书逐对看图后才许写进来。空＝不启用（不进 dump）。"""
    follow_ref_seen_conflict: bool = False
    """`follow_ref_seen` 也接「护栏 conflict」格（书级，缺省关、关时不进 dump；A24 N01 第 7 轮复查 11-08，殿本 七／𠤎 28 格）：库把这一对里的两个字都判 same
    （候选前两名恰是 ref 与 seen 对里的另一形、护栏 `conflict`）——字形本就相同，只有整理本文意能定，放整理本形。只认 `护栏:conflict`，
    `never_match`／`timeout` 和别的 `护栏:*` 照旧拦；候选前两名里混进这一对以外的字也不放。要在本书看图确认这一对字形一样才开。"""
    # ── `follow_ref_cov` = 0.92（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `follow_ref` 待审格的库首位 cov 下限。殿本回放放行 27 格最低 0.939；0.87–0.89 的 2 格是切坏的残字。
    # ── `follow_ref_gap` = 0.005（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `follow_ref` 待审格：库首位领先这一对以外最好候选的下限。
    # ── `edge_pair`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 异体边表自动暂归一（通道 `edge_pair`，A24 2026-10-31，r5 重放 V 类单格长尾约 360 对）：整理本字与库首位互为「自动对」
    # （`edge_pairs.is_auto_pair`：边表 T1 纯异体且 ≥2 个异体来源、不在字组、不在 `config/variants/edge_pair_exclude.tsv`）的待审格，
    # 库首位 cov ≥ `edge_pair_cov`、领先对外最好候选 ≥ `edge_pair_gap`、库没判 diff、无护栏 → 放 `edge_pairs.pair_to`（两形里已放行字频
    # 较高的一形，都罕见放库首位）。同义异体暂归一（sheldon 10-25／10-27 只限同义）：证据 `edge_pair.decision=provisional`，将来按它筛出来再拆。
    # 只升不降、不改已放行格、不碰人裁。r5 回放（vol07–99 产物包）看图 94 格全对。False＝照旧留人审。
    edge_pair_to: str = "freq"
    """`edge_pair` 放哪一形（A24 V01 定案 11-09，sheldon 经 ZM GUJI-756）：
    - `freq`（缺省，旧行为）：`edge_pairs.pair_to`，两形里已放行字频较高的一形（同义异体暂归一）；
    - `lib`：放库首位（刻形证据）——按刻形转写的书（殿本）用，「同字」只表示这格可以不人审、不写暂归一；
    - `ref`：放整理本字——按整理本录的书（史記、全唐文）用。
    缺省 `freq` 逐字节不变、不进参数 dump。"""
    # ── `edge_pair_cov` = 0.92（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `edge_pair` 库首位 cov 下限（同 `follow_ref_cov`）。
    # ── `edge_pair_gap` = 0.005（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    `edge_pair` 库首位领先这一对以外最好候选的下限（同 `follow_ref_gap`）。
    edge_pair_group_seam: bool = False
    """`edge_pair` 补字组缝（A24 V01 深挖 11-06，第 7 轮）：整理本字与库首位是纯异体强边、但有一字是字组成员（`is_auto_pair` 不认），
    且这一格字组没接（evidence 里没有 group）→ 也按 `edge_pair` 判；涉及形近组时领先要 ≥ `edge_pair_group_seam_nf_gap`。
    殿本三书 ★main 包回看 9 格看图字都对（衞衛、隸隷、陰隂、尙尚、歲歳、𩀱雙、呂吕、嘗甞、廹迫）。缺省关（2026-11-25 CV4 起缺省改成三本主力书都设的值，Sheldon 11-24 定；参数 dump 仍按旧缺省去键，设了旧值或没设而用新缺省的册指纹分别照旧／改变）。"""
    # ── `edge_pair_group_seam_nf_gap` = 0.03（门槛，2026-11-24 CV4 起收成常量 `_CONSTANTS`、不再是参数）
    #    字组缝涉及形近组时，库首位领先对外最好候选的下限（同字组入口的 delta）。

    # ── `codepoint_semantic`（护栏／通道，2026-11-23 CV4 起恒开、不再是参数）
    # 书级 `codepoints:` 并进语义判等（缺省开）：册配置声明过的码位对（巻→卷、别→別、岀→出、晩→晚、內→内 …）
    # 在本步所有「语义同字」比较里按同一个字算（`context_vs_ref`、`replace_align`、`relax_ref_agree`、
    # `match_ref` 各通道都读 `vmap.semantic`），放行的字也落到册指定的码位。此前 `codepoints` 只进
    # 可信边判据，`vmap` 不认 巻/卷、别/別 等，于是整理本排异体、刻本与文意都对的格全被 `context_vs_ref`
    # 拦下（殿本 vol04–10 送审里这一类 217 格）。没配 `codepoints` 的册行为不变；关掉回到旧行为。

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

    patch_missing: str = "error"
    """铁证 / CNN 背书 / 组内检索三路读本格字块读不到时怎么办（overview#407，2026-10-05）。

    - `error`（缺省，本地真书）：抛 `PatchUnavailable`，这一页 failed。
    - `skip`（云端快照沙箱：只带 products、不带原图与 cache，字块现算不出来）：这几路**不参与**
      这一格，但不静默——该格 `evidence.patch_missing` 记下跳过了哪几路（`iron_scale`／`iron`／
      `cnn`／`form`），日志汇总一行。真书别开：开了等于回到 10-05 前「没图就悄悄关掉」。

    `glyph_match` 没有这个开关：本格没图就没法判，停页是对的。
    缺省值不进 dump，`params_hash` 与加字段前逐位相同。"""

    def _rt_rank(self) -> int:
        return {"none": 0, "high": 1, "very_high": 2}[self.reference_trust]

    def _rt_on(self, item: str) -> bool:
        """`reference_trust` ≥ high（`item` 只作说明：原 `reference_trust_skip` 逐项豁免无书用，2026-11-23 删）。"""
        return self._rt_rank() >= 1

    def _rt_shape_ref_ok(self) -> frozenset:
        return frozenset(REFERENCE_TRUST_SHAPE_GROUPS) if self._rt_on("shape_ref_ok") else frozenset()

    def _rt_abstain_ref_ok(self) -> frozenset:
        return frozenset(self.group_flow_abstain_ref_ok) | (frozenset(REFERENCE_TRUST_ABSTAIN_GROUPS) if self._rt_on("abstain_ref_ok") else frozenset())

    def _rt_lift_shape_ref(self) -> frozenset:
        return frozenset(self.group_flow_lift_shape_ref) | (frozenset(REFERENCE_TRUST_LIFT_SHAPE_GROUPS) if self._rt_on("lift_shape_ref") else frozenset())

    def _follow_variants(self) -> bool:
        if self.ref_variants_off:
            return False
        return self.follow_ref_variants or self._rt_on("follow_ref_variants")

    @model_serializer(mode="wrap")
    def _drop_off_rare(self, handler, info):
        """参数 dump（进 `params_hash`）：补回退役／恒开参数的固定值，再按 `_DUMP_DROP` 去掉关着的、取缺省值的键；
        算指纹时（`context={"hash": True}`）再按 `_DUMP_DROP_HASH` 去改过缺省的键。"""
        d = handler(self)
        if not isinstance(d, dict):
            return d
        d.update(_RETIRED_IN_DUMP)
        d.update(_ALWAYS_ON_IN_DUMP)
        d.update({k: copy.deepcopy(v) for k, v in _CONSTANTS.items()})
        rules = _DUMP_DROP + _DUMP_DROP_HASH if (info.context or {}).get("hash") else _DUMP_DROP
        for cond, keys in rules:
            if cond(self):
                for k in keys:
                    d.pop(k, None)
        if not self.group_flow:                  # 没开字组流程：group_flow* 一概不进 dump
            for k in [k for k in d if k.startswith("group_flow")]:
                d.pop(k, None)
        if self.follow_ref and self._follow_variants():
            # 表项不再接管 variants 路径（史記 r45 嵗=歳，cv#1438）：只有「表非空且按参校本取异体」的书输出会变，
            # 修订号进 dump 只让它们过期（别的书 dump 不变，代码改动登 code_equiv）。
            d["follow_ref_variants_rev"] = FOLLOW_REF_VARIANTS_REV
        return d

    @model_validator(mode="before")
    @classmethod
    def _retired_keys(cls, data):
        """退役参数（`_RETIRED`）：写的是退役前的缺省值就丢掉；写了别的值报错，免得那本书的开关悄悄失效。"""
        if not isinstance(data, dict):
            return data
        bad = []
        for k in [k for k in data if k in _RETIRED]:
            v = data[k]
            want = _RETIRED[k]
            same = (list(v) == list(want)) if isinstance(v, (list, tuple)) and isinstance(want, (list, tuple)) else v == want
            if not same:
                bad.append(f"{k}={v!r}")
        moved = [f"{k}={data[k]!r}" for k in data if k in _MOVED_TO_BOOK and data[k] != _MOVED_TO_BOOK[k]]
        if moved:
            raise ValueError(f"seed_admit 参数已搬进书仓（2026-11-24 CV4，全唐文书仓 code/admit_lanes.py，k13 起）：{', '.join(moved)}；"
                             "改写进 book_lanes（见书仓 admit_lanes 模块头），并钉 code: 13 以上")
        data = {k: v for k, v in data.items() if k not in _MOVED_TO_BOOK}
        if bad:
            raise ValueError(f"seed_admit 参数已退役（无书改过，2026-11-23／24 CV4 删、改恒开或收常量）：{', '.join(bad)}；"
                             "要用请找 CV4，说明哪本书、为什么")
        return {k: v for k, v in data.items() if k not in _RETIRED}

    @field_validator("patch_missing")
    @classmethod
    def _check_patch_missing(cls, v: str) -> str:
        if v not in ("error", "skip"):
            raise ValueError(f"seed_admit.patch_missing 只能是 error/skip，不是 {v!r}")
        return v

    @field_validator("group_flow")
    @classmethod
    def _rename_groups(cls, v) -> tuple:
        """并掉的组照新 id 读（`registry.RENAMED`：千干 qg → 于千子干 zy，2026-10-24）。"""
        from ..groups.registry import flow_names
        return flow_names(v)

    def _context_guard_on(self) -> bool:
        return (self.context_guard_diff
                or self.context_guard_ref_blank or self.context_guard_ref_prefer)

    def model_post_init(self, _ctx) -> None:
        from .seed_admit import (_approx_fingerprint, _l3_fingerprint, _l3_groups, _resolve_book_lanes_data,  # noqa: 循环引用，用时再取
                                 _resolve_data_path, _resolve_group_flow_paths, _shadow_model_path)
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
        if not self.exclusions_fingerprint:
            from ..clustering.exclusions import default_path as _ex_default
            object.__setattr__(self, "exclusions_fingerprint",
                               corpus_fingerprint([self.exclusions or str(_ex_default())]))
        # 人裁表直接读 glyph.db，这一步自己带库指纹——上游 glyph_match 的指纹只保证
        # 它自己重跑，不会让本步过期（人裁进库时 match 产物可能没变）。
        # 只看 provenance='human' 那部分（2026-09-20）：机器 align 进库、字头改判与本步
        # 的人裁通道无关，用整库指纹会让本步跟着白跑。
        # 2026-10-19 起（GUJI-609，v0.4.0）取人裁通道真正读到的 (实例 id, 字头) 的内容哈希：
        # glyph.db 改成从中心库重建后 rowid 会重排，旧的 (条数, 最大 rowid, 时间戳) 会白白变。
        if self.use_human_verdicts and not self.human_fingerprint:
            from ..clustering.glyph_fp import human_shapes_fingerprint
            object.__setattr__(self, "human_fingerprint",
                               human_shapes_fingerprint(self.db_path))
        # 版本注词表也是派生物（scripts/build_note_lexicon.py），同理
        if not self.note_fingerprint:
            from ..clustering.note_lexicon import DEFAULT_LEXICON
            object.__setattr__(self, "note_fingerprint",
                               corpus_fingerprint([self.note_lexicon or str(DEFAULT_LEXICON)]))
        if self.shadow_veto and not self.shadow_model_fingerprint:
            from ..shadow.model import file_fingerprint
            object.__setattr__(self, "shadow_model_fingerprint",
                               file_fingerprint(_shadow_model_path(self)) or "missing")
        if not self.approx_fingerprint:
            object.__setattr__(self, "approx_fingerprint", _approx_fingerprint(self.db_path))
        if self.book_lanes and not self.book_lanes_fingerprint:
            data = self.book_lanes.get("data") or []
            if isinstance(data, str) or not all(isinstance(x, str) for x in data):
                raise ValueError("seed_admit.book_lanes.data 须是路径表（相对数据目录）")
            paths = [_resolve_book_lanes_data(x) for x in data]
            object.__setattr__(self, "book_lanes_fingerprint",
                               corpus_fingerprint([x for x in paths if x]) + ("" if all(paths) else ":missing")
                               if data else "")
        if self.group_flow_exclude:
            from ..groups.registry import FLOW_GROUPS as _FG, flow_names as _fn
            _ex = _fn(self.group_flow_exclude)
            if bad := [g for g in _ex if g not in _FG]:
                raise ValueError(f"seed_admit.group_flow_exclude 有不认识的组：{bad}")
            object.__setattr__(self, "group_flow_exclude", list(_ex))
            object.__setattr__(self, "group_flow", tuple(g for g in self.group_flow if g not in _ex))
        if self.group_flow:
            from ..groups.flow import check_groups
            check_groups(self.group_flow)
            _resolve_group_flow_paths(self)
            if not self.group_flow_fingerprint:
                from ..groups.freq import fingerprint as _fq_fp
                from ..groups.flow import ctx_fingerprint as _ctx_fp
                from ..utils.rr_clf import model_fingerprint as _rr_fp
                from ..groups.registry import FLOW_GROUPS as _G
                _ctx_groups = tuple(g for g in self.group_flow if "ctx" in _G[g].flow.solvers)
                parts = [_fq_fp(self.group_flow_freq), _ctx_fp(_ctx_groups, self.group_flow_tables)]
                if self.group_flow_models:           # 文意 L2 模型小头（没有小头的书不加，旧指纹不变）
                    from ..groups.ctx_l2 import head_fingerprint as _hd_fp
                    parts.append("m" + "".join(_hd_fp(self.group_flow_models[g]) for g in sorted(self.group_flow_models)))
                if _l3_groups(self):                 # 文意 L3 在线：模型、档位、提示词（没开的书不加，旧指纹不变）
                    parts.append("l" + _l3_fingerprint(self))
                if self.group_flow_vis and self.group_flow_llm_model and any(_G[g].flow.vis for g in self.group_flow):
                    from ..groups import vis_llm as _vis
                    import hashlib as _hl
                    parts.append("v" + _hl.sha256((_vis.VER + _vis.SYSTEM + self.group_flow_llm_model).encode()).hexdigest()[:12])
                if self.group_flow_rr_shape:         # 入人八 书级刻形判法（没有模型的书不加，旧指纹不变）
                    from ..groups.rr_shape import fingerprint as _rs_fp
                    parts.append("rs" + _rs_fp(self.group_flow_rr_shape))
                if self.group_flow_wu_shape:         # 嗚鳴 书级刻形判法（没有模型的书不加，旧指纹不变）
                    from ..groups.wu_shape import fingerprint as _ws_fp
                    parts.append("ws" + _ws_fp(self.group_flow_wu_shape))
                if self.group_flow_hou_shape:        # 候𠋫 书级刻形判法（没有配置的书不加，旧指纹不变）
                    from ..groups.hou_shape import fingerprint as _hs_fp
                    parts.append("hs" + _hs_fp(self.group_flow_hou_shape))
                if self.group_flow_part_shape:       # 书级部件刻形判法（没有模型的书不加，旧指纹不变）
                    from ..groups.part_shape import fingerprint as _pt_fp
                    parts.append("pt" + _pt_fp(self.group_flow_part_shape))
                if self.group_flow_pair_shape:       # 书级两字刻形二选一（没有模型的书不加，旧指纹不变）
                    from ..groups.pair_shape import fingerprint as _ps_fp
                    parts.append("ps" + _ps_fp(self.group_flow_pair_shape))
                if self.group_flow_pair_shapes:      # 多对两字刻形模型（没有的书不加，旧指纹不变）
                    from ..groups.pair_shape import fingerprint as _ps_fp
                    parts.append("pp" + "".join(k + _ps_fp(self.group_flow_pair_shapes[k]) for k in sorted(self.group_flow_pair_shapes)))
                if self.group_flow_book_knn:         # 书级刻形近邻库（没有库的书不加，旧指纹不变）
                    from ..groups.book_knn import fingerprint as _bk_fp
                    parts.append("bk" + "".join(g + _bk_fp(self.group_flow_book_knn[g]) for g in sorted(self.group_flow_book_knn)))
                if self.group_flow_near_knn:         # 形近护栏格书级刻形近邻（没有库的书不加，旧指纹不变）
                    from ..groups.near_knn import fingerprint as _nk_fp
                    parts.append("nk" + _nk_fp(self.group_flow_near_knn))
                if any("rr_img" in _G[g].flow.solvers for g in self.group_flow):
                    parts.append(_rr_fp(None) or "missing")
                from ..groups.ids_online import fingerprint as _ids_fp
                if _ids_fp(self.group_flow):        # IDS 模板库＋判法（方案 S7）；没有在线 IDS 的组不加，旧指纹不变
                    parts.append(_ids_fp(self.group_flow))
                object.__setattr__(self, "group_flow_fingerprint", ":".join(parts))
        if self.pair_form and not self.pair_form_fingerprint:
            from ..groups.pair_attr import fingerprint as _pf_fp
            if self.pair_form != "-":
                object.__setattr__(self, "pair_form", _resolve_data_path(self.pair_form))
            object.__setattr__(self, "pair_form_fingerprint", _pf_fp(self.pair_form) if self.pair_form != "-" else "all-shape")
        if self.lane_shape_first and not self.lane_shape_first_fingerprint:
            from ..groups.pair_attr import fingerprint as _pf_fp
            object.__setattr__(self, "lane_shape_first", _resolve_data_path(self.lane_shape_first))
            object.__setattr__(self, "lane_shape_first_fingerprint", _pf_fp(self.lane_shape_first))
        if self.stroke_veto and not self.stroke_veto_fingerprint:
            from ..groups.stroke_veto import fingerprint as _sv_fp
            object.__setattr__(self, "stroke_veto", _resolve_data_path(self.stroke_veto))
            object.__setattr__(self, "stroke_veto_fingerprint", _sv_fp(self.stroke_veto))
        if not self.iron_config_fingerprint:
            from ..clustering.iron_evidence import _CONFIG as _IRON_CONFIG
            object.__setattr__(self, "iron_config_fingerprint",
                               corpus_fingerprint([str(_IRON_CONFIG)]))


def _const_prop(k: str) -> property:
    return property(lambda self: copy.deepcopy(_CONSTANTS[k]), doc=f"常量 `{k}`（见 `_CONSTANTS`）")


for _k in _CONSTANTS:
    setattr(SeedAdmitParams, _k, _const_prop(_k))
del _k
