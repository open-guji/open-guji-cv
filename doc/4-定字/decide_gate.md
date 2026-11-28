# 4 定字出口 gate `decide_gate`（只检测，不判断）

2026-11-28 Sheldon 定：**gate 是用来检测的，不是用来判断的**。判断（定字、放行或送审、送审原因）都在收尾步（今天的 `seed_admit`，以后的 `char_decide`）；gate 读第四步全部产物，出一份检测清单。

- 挂在 `seed_admit` 出口（`attach_gate`），永远最后跑，照 `cut_gate` 的样子；不出现在 pipeline yaml 的 `steps:` 里。
- 输入：`seed_admit`（必需）；可选 `align_ref`、`glyph_match`、`context_decision`、`char_index`（缺了对应检测项不做，页级 `metrics.missing` 记下）。
- 输出：产物 `decide_gate`（一页一份，schema `PageDecideGate`）：`passed`（无 fail）、`checks[{name, level: fail|flag, unit: page|col|cell, key, reason, metrics}]`、`metrics{n_cells, n_admit, admit_rate, missing}`。
- 纪律：①不改任何格（字、放行、通道都不动）；②没有任何 Step 读它，也没有 Step 把它列进 `consumes`／`code_deps`，所以别的步骤的指纹不变（`tests/test_decide_gate.py` 守着）；③检测出的问题由人和下游决定怎么办，某类检测稳定后要拦，改收尾步的规则，不在这里拦。
- 谁读：guji-manager 体检（`fail` 汇总）、decide-bench 报告（`ai-team domain/CV/A24/decide-bench/gate_bench.py`）、各书 Project。

## 检测项（首批）

| 级别 | 单位 | 名字 | 看什么 |
|---|---|---|---|
| fail | 列 | `step_error` | 第四步某列报错（整列没出结果） |
| fail | 列 | `ref_shift` | 连续 ≥k（`shift_run_min`，缺省 3）个放行字恰好等于参校本错开一位（±1）的字、而不是本位的字 |
| fail | 格 | `char_not_in_evidence` | 放行字不在候选、参校本字、上下文、证据（字组、刻形、通道留痕）、人裁任何一处出现过 |
| fail | 格 | `admit_blank_cell` | 放行格在切分里是空白（`char_index` 的 `cell_type=empty`／`step3_kind=blank`）；4c `cell_state` 独立后换成它的状态 |
| flag | 页 | `no_align_ref` | 参校本对位产物缺席 |
| flag | 页 | `unanchored_ref_admit` | 参校本没锚上、也没坐标对位，却有 ≥3 格靠参校本／上下文通道放行 |
| flag | 页 | `upstream_error` | 识字或上下文有列报错 |
| flag | 列 | `col_coord_fallback` | 整列坐标对位退回（附原因） |
| flag | 列 | `col_alt_cut` | 这列准入后改用备选切法 |
| flag | 格 | `rare_codepoint` | 放行字≠参校本字，放行字是罕用码位（`form_freq.tsv` 字频 <5），参校本字是它的常用异体形（≥20；边表 variant 或 variants 图） |
| flag | 格 | `human_unbound`／`human_conflict` | 有人裁没绑到这格；绑丢的人裁字与放行字不同 |
| flag | 格 | `group_without_4d` | 放行字在本书启用的字组（`seed_admit.group_flow`）里，证据里却没有字组判定 |

人裁格（通道 `human`）不做 `ref_shift`、`char_not_in_evidence`、`admit_blank_cell`、`rare_codepoint`、`group_without_4d`。阈值全在 `DecideGateParams`。

## 量法

`decide-bench/gate_bench.py`：对放错字的检出率（被 fail 或 fail／flag 标出的比例）、对放对格的误报率；按书、按检测项。结果与口径见 ai-team `domain/CV/A24/decide-bench/gate-bench-2026-11-28.md`。
