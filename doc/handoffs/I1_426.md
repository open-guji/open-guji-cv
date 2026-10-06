# HANDOFF I1：iron 在形近对上推翻证人，加护栏（overview#426）

分支 `claude/I1-iron-confusable-1006`（没合 main，没开 PR）。

## 根因
`iron_ref_guard` 只读现役对位字（`align_ref.chars` → `align_char`）。#426 点名的 3 格
（`vol04:40:2:2`、`60:9:6`、`188:2:20`），现役对位都被库分歧过滤掉了（`n_lib_dropped`），
所以 `align_char=None`，没有对齐字的格是不拦的。证人的字在坐标对位 `align_ref.coord`
里，而且是对的：日、日、八。iron 放行时还会把这几格原有的 `near_form` 疑问一并清空（`doubts = []`）。

## 改动
- `open_guji_cv/steps/seed_admit.py`：
  - 新参数 `iron_confusable_guard: bool = True`；
  - 新函数 `_iron_confusable_witness`；
  - iron 放行处加一个 `elif`：证人取现役对位字和坐标对位字两路，只要有一路与 iron 首选语义不同，
    而两者又在形近表里，就不放行，记 doubt `iron_confusable_ref`。
  - 形近表只用现成的：`confusable.partners()`（手工 `NEVER_MATCH_FAMILIES`、人裁
    `confusable_human.json`、字体表 τ≥0.988）与 `iron_extra_confusable.json`。
    日/曰 出自手工表（vol01:10:9:10 有案底），人/八 出自人裁表。
  - `〓`（PUA 占位）和空串不算证人。语义同字的（异体、码位）不拦。
- `tests/test_seed_admit_iron_confusable_guard.py`：单测，数据都是自己造的。

## 数字
在 scratchpad 沙箱里用 `git archive` 解快照算，没碰正式 products。

| 册 | iron 放行 | 已知错 | 护栏拦下 | 拦下的格里错的 | 多送人审 |
|---|---|---|---|---|---|
| vol04（`snap/.../vol04/20261006T0716`） | 20 | 3 | 3（正是点名的 3 格） | 3 | 3 |
| vol03（0930 seed_admit + 0928-full align_ref） | 7 | 0（5 格有人裁，全对；2 格证人同字） | 0 | — | 0 |

- vol04 加护栏后：iron 放行 20→17，已知错 3→0。码位类的 2 格（宫、別）不拦。
- 已被 `iron_vs_ref` 拦下的格里，护栏也命中的：vol04 有 2 格（圓/圖），本来就在人审里，不算新增。
- **代价上界**：vol03 的 500 个人裁格里，证人与真值不同、两者又是形近对的，只有 24 格（己已巳 22 格 + 日↔曰 2 格）。
  这些格上 iron 就算选对了，护栏也会拦下。己已巳 这一族先走 ji_yi_si 通道；除去这一族，只有 2 格，占 0.4%。
- **建议缺省开**（现已缺省开）。
- 局限：vol03 最新快照没有 align_ref，所以用的是 0928 的。0928 的 `105:8:20` 现役对位字是「有」，
  和 0930 跑出来的结果不一致，不过对这一格护栏判不中，结论不变。vol04 没有人裁，用的是
  #426 逐格看图的结论。

## 影响
`SeedAdmitParams` 多了一个字段，各书的 seed_admit 产物都会判过期，这是预期的。
没开 `iron_gate` 的书，重跑后内容不变。开了的书只会多出待审格，不会改任何已放行格的字。

## 测试
全量：`python -m pytest tests/ -q -s -p no:cacheprovider`（Linux，装了 `.[console,dev]`，没装 torch）：
2589 passed, 30 skipped, 1 failed。挂的那条是 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，
在 main 上不带本改动也挂（本地环境的问题），和这次改动无关。新单测 6 条全过。

## 沙箱里的脚本（没进仓）
scratchpad 下的 `tools/measure.py`（逐格列 iron 格、证人、护栏判定、人裁真值）和
`tools/cost.py`（代价上界）。
