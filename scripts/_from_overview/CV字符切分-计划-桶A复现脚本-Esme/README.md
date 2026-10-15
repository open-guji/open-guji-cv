GUJI-75 回执（GUJI-208gy，Esme）：桶 A 只读复现脚本＋README 已写（`repro_coord_column.py`，给定一册一页一列＋整理本这一行，逐个候选起点报「被哪条闸拒」及数值，再调真实 `coord_column` 对照）。已在本机用 cv main `4eed859` 试跑：vol04 p130 第 5 列与 vol07 p2 第 4 列都能跑，自测过；**但整理本真行文本本机没有（daizhige 逐列本不在仓里），所以两列的「真因」仍是待证据**，脚本能给的是：喂什么行形，哪条闸拒。顺带更正：208go 里 A2 把 vol07 p2 第 4 列 slot 16–20 误读成「奇数夹注半格」，实为 5 个 blank 格，「一列对多行」推断撤回，已改该页并标注。只读、没改 cv、没碰 products。

# 桶 A 只读复现（Esme，2026-10-14 洛杉矶）

## 1. 它做什么、不做什么
- 做：读某一页某一列的 Step3 cells（和有的话 glyph_match），造出 `coord_column` 要的格单元，对每个候选起点打印：类型是否对得上、斜率、残差（行）、段外格最近距离（行）、是否通过；末尾调真实 `coord_column` 看结论。
- 不做：不写任何产物，不改 cv，不看人裁，不碰 yaml。
- 需要 cv 代码可 import：`PYTHONPATH=<cv 工作副本>`，cv 取 main `4eed859`（Eden 沙箱同版）。

## 2. 参数
`--products <products 根> --book volNN --page N --col K`，整理本行三选一：`--ref-file` / `--ref-text`（光盘版写法，夹注用 `<右行|左行>`）/ `--ref-pattern`（占位，如 `7c3n`＝7 正文＋3 夹注单元；只能诊断类型与几何，载体吻合恒为 0）。
`--cells-only`：没有 glyph_match 时，用 cells 近似造单元（去掉 blank 格，载体为空）。`--selftest`：自测。

## 3. 两条命令（Eden 沙箱）
products 根示例：`<guji-workspace main 检出>/96mid1ogzk-欽定四庫全書總目武英殿刻本/products`（沙箱里换成沙箱产物根）。

**A1：vol04 p130 第 5 列**（main 上有全套产物）
```
PYTHONPATH=<cv 4eed859> python3 -I repro_coord_column.py --products <根> --book vol04 --page 130 --col 5 --ref-file <该列整理本行.txt>
```
没有真行文本时先用占位看闸：`--ref-pattern 5c3n11c`（类型对→几何通过，残差≈0.12）；`--ref-pattern 19c`（纯正文）→ 三个起点全被「类型」闸拒。真行文本到手后换 `--ref-file`，才能看到载体吻合与「错位／歧义」闸。

**A2：vol07 p2 第 4 列**（main 上只有 border_detect 与 row_segment，没有 glyph_match／align_ref）
- 先在沙箱对 vol07 跑 Step1–4 到 `row_segment`／`glyph_match`（`guji step … -w <沙箱工作区>`，原图在 guji-workspace main 该册 `images/`；具体 `guji` 子命令按 runbook `doc/runbook/整理一册书.md`——**命令待 Ethan 补**）。
- 产物到位后：
```
PYTHONPATH=<cv 4eed859> python3 -I repro_coord_column.py --products <沙箱根> --book vol07 --page 2 --col 4 --ref-file <该列整理本行.txt>
```
- 产物未到位时的近似：`--cells-only --ref-pattern 7c3n`（几何通过）／`10c`（类型闸拒）。注意去掉 blank 后单元约 16 个，真实 glyph_match 的单元数可能不同。

## 4. 读结果
每个起点一行：`类型`（第几位格与整理本类型不同）、`斜率`、`残差`、`段外`（多出的格离字位 ≤0.5 行）、`通过`。末尾「拒因计数」。真实 `coord_column` 的返回与上面哪几条闸对得上，即该列的拒因。

## 5. A3 需要 Ethan 提供的产物（一句话，请 Mila 转）
请 Ethan 把 vol08 p2 与 vol09 p70 的 `row_segment`、`align_ref`、`seed_admit` 产物（每页各几个文件，沙箱重算即可）放到 guji-workspace 的沙箱分支或共享位置，供复现脚本读；这两册 main 上现在只有 border_detect。

## 6. 窗口甲骨架（208gj）里「命令待 Ethan 补」的空位清单
| 骨架节 | 哪一格 | 缺什么命令 |
|---|---|---|
| §3 收紧栏（放行→待审），逐规则 | 「命令」栏，第 54 行 | `set(admit_X) − set(admit_A)` 与 `set(admit_A) − set(admit_X)` 的逐册行数，每臂贴册数与行数 |
| §6 按格号绑定的人裁 | 「命令」栏，第 90 行（Ethan／Eden） | 各册「按格号绑定的人裁放行／事件」条数的统计命令 |
| §8 W1／W2／W5 并入后的 diff | 「命令」栏，第 118 行 | 并入前后同一臂、同一缓存的逐页 sha256 比对命令；W2 另需读十册 `seed_admit` 的 `code_hash`／`params_hash` 是否变 |

## 7. 待证据
| 项 | 缺什么 | 谁取 |
|---|---|---|
| 两列整理本真行文本 | daizhige 逐列本（Lucian 208gv 第二部分） | Lucian |
| vol07 glyph_match／align_ref 产物 | 沙箱跑 Step1–4 | Ethan／Eden |
| vol08 p2、vol09 p70 产物 | 同 §5 | Ethan |
| `lane_coord` 各册 yaml 是否开 | 册 yaml | Ethan |

> 10-14 注：Lucian 208gv 已定位 A1＝夹注类型误判、A2＝尾 5 格段外假格，本脚本降为可选工具（决定页 §二十三）。
