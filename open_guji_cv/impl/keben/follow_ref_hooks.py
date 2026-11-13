"""C1 进库准入 `follow_ref`（照录整理本异体对）的书级钩子：缺省实现什么都不做，殿本、全唐文产物不变。

2026-11-13 A22（SJ 请求、A24 定规则）：史記按整理本录字，`follow_ref_variants` 一路算领先差时，同族第三形
（吴／呉／吳、嵗／歳／歲 里的第三个）被当成对手，已判对的格卡在 `follow_ref_gap` 送审。哪些字不当对手是本书的规则，
不进 cv、不加开关：书仓 `code/` 写一个同名模块，在 `code/code.yaml` 的 `overrides` 写
`keben.follow_ref_hooks: <本书模块>`，给出下面的函数就生效，出新 `k`。

- `rival_skip(*, ref, lib, cands, via, facts) -> Iterable[str] | None`

  只对**待审格**（未放行、非人裁、有库候选）、且这一格已认出整理本对子时调（表路 `follow_ref` 与 `follow_ref_variants` 都调，
  `via` 区分）。返回算领先差时不当对手的字；`ref`／`lib` 本来就不算，返回了也忽略。None／空＝照旧。

  - `ref`：整理本字；`lib`：配对的另一形（`follow_ref_variants` 时是库首位）；
  - `cands`：库候选 `[(字, cov), …]`，按 cov 降序，首位就是 `lib` 或 `ref`（否则判据本来就不放）；
  - `via`：`None`＝`follow_ref` 表里的对子，`"variants"`＝`follow_ref_variants`（与整理本同义异体）；
  - `facts`：关系层查询，书级代码不许 import cv 内部模块，事实由 cv 给：
    `facts.semantic(ch)` 同义归并后的字；`facts(a, b)` 一对字的事实（只读），字段：
    `same_semantic`、`tier`（"T1"｜"T2"｜"T3"｜None）、`sources`、`n_bridge`（异体字典来源数）、`never_only`、`is_variant`、
    `never`（never_group.json）、`edge_excluded`（edge_pair_exclude.tsv）、`groups`（两字同在的字组 `((组 id, kind), …)`，
    kind＝"variant"｜"near_form"）。

  被排除且确实在候选里的字记进放行证据 `lane.rival_skip`，方便按参校本错误回查。其余判据（cov 门槛、领先差门槛、
  硬疑问、`diff`）照旧。
"""
from __future__ import annotations

#: None＝不调（缺省）。
rival_skip = None
