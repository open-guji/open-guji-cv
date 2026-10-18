# M7 分块 A：共用底座（GUJI-563，Emerson）

> 总设计：[M7-形近字优化算法-总设计.md](M7-形近字优化算法-总设计.md)。状态：A1–A4 全部完成。

| 步 | 内容 | 输入标准 | 验收标准 | 状态 |
|---|---|---|---|---|
| A1 标注总表 | `research/m7/gold_inventory.py` 把 jys／ry／rr 的 char-groups 与 yi_560 的 42 格三段标注合成 `gold_all.jsonl` | dataset `char-groups`、分支 `claude/Evan-1011` 的 `user_parts_labels.jsonl` | 打印表：jys A186/B40/C31、ry A81/B10/C1508、rr A81/B2/C2264、yi_560 A42 | ✓ 已跑 |
| A2 IDS 展开 | `groups/ids.py`＋`config/groups/yi_560/ids_override.tsv`（停止点、别名）；递归展开到停止点并同向压平 | `config/ids/ids_lv1.txt`（yi-bai/ids） | `pytest tests/test_groups_ids.py`：六字全部展开为 `⿳X⿰米Y Z`，彝＝`⿳彑⿰米糸廾`、彜＝`⿳彑⿰米分廾`；三个位置的可选部件＝{彑,彐}／{⿰米糸,⿰米分}／{廾,大} | ✓ 4 条测试过 |
| A3 注册表加 `kind`／`solvers`／`config_dir` | 只加字段、旧字段不动 | A2 | `tests/test_groups_registry.py` 与 `test_architecture.py` 仍过；19 步 `code_hash` 不变 | ✓ 已做 |
| A4 上下文窗口 `groups/context.py` | 前后各 20 字，**不按段截断**（用户 10-17 改：2 代版遇段界即停，作废）；对位缺字用占位符不跳过；`ctx_ver: 3` | A3；整理本分段规则 | 单测造数据覆盖：页中、全文首尾、跨段不停、对位缺字；char-groups 用 `ctx_ver: 3` 重建后条数与旧版相同 | ✓ 已做（`groups/context.py`，6 条测试） |

## 发现与待确认
- 原表里 彜＝`⿱彑𪪷`、𢑱＝`⿱𫜹𡙢`／`⿱彑𡙢`、彛＝`⿱彐𪪷`：展开后六字**全是** `⿳上⿰米X下`，与用户的上中下读法一致。
- 上段：原表用 𫜹（`⿼コ一`）表示「⺕」形，按别名并入 彐；用户标注里的 ⺕（U+2E95）与 彐（U+5F50）用户 10-17 已确认是同一部件。
- 用户的 42 格标注里「中」写作 `糸` 或 `米+分`，对应 IDS 的 `⿰米糸`／`⿰米分`。

## C2 折线页（已出，给用户点；用户 10-17 要求折线）
`research/m7/build_cutline_page.py` 用 skill `review-artifact` 的壳建页；卡 id 冻在 `research/m7/cutline_cards.jsonl`（42 格）。
每张卡画两条**分界折线**（红＝上/中，蓝＝中/下），每条≥2 个点、点可拖、可撤销；两端自动延伸到图左右边缘。
裁决值 `poly:[[[x,y],..],[[x,y],..]]`（0–1 比例，左上原点），`idk` 看不清，`bad` 图不对。旧直线版（key v1）作废，已有的 2 条直线预填成两点折线（`--prefill`），用户碰过才算数。
URL：https://claude.ai/artifact/TV1gPAJwyoNWpfLMgjwpPX 。收回：`Artifact(action="read")` → `harvest_verdicts.py`。
本机 playwright 实测：逐点添加、拖点、撤销、预填、计数均正常。
