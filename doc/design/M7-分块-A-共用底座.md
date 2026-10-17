# M7 分块 A：共用底座（GUJI-563，Emerson）

> 总设计：[M7-形近字优化算法-总设计.md](M7-形近字优化算法-总设计.md)。状态：A1、A2 已做（本 PR），A3、A4 待做。

| 步 | 内容 | 输入标准 | 验收标准 | 状态 |
|---|---|---|---|---|
| A1 标注总表 | `research/m7/gold_inventory.py` 把 jys／ry／rr 的 char-groups 与 yi_560 的 42 格三段标注合成 `gold_all.jsonl` | dataset `char-groups`、分支 `claude/Evan-1011` 的 `user_parts_labels.jsonl` | 打印表：jys A186/B40/C31、ry A81/B10/C1508、rr A81/B2/C2264、yi_560 A42 | ✓ 已跑 |
| A2 IDS 展开 | `groups/ids.py`＋`config/groups/yi_560/ids_override.tsv`（停止点、别名）；递归展开到停止点并同向压平 | `config/ids/ids_lv1.txt`（yi-bai/ids） | `pytest tests/test_groups_ids.py`：六字全部展开为 `⿳X⿰米Y Z`，彝＝`⿳彑⿰米糸廾`、彜＝`⿳彑⿰米分廾`；三个位置的可选部件＝{彑,彐}／{⿰米糸,⿰米分}／{廾,大} | ✓ 4 条测试过 |
| A3 注册表加 `kind`／`solvers`／`config_dir` | 只加字段、旧字段不动 | A2 | `tests/test_groups_registry.py` 与 `test_architecture.py` 仍过；19 步 `code_hash` 不变 | 待做 |
| A4 上下文窗口 `groups/context.py` | 前后各 20 字，遇段首段尾停；段判法复用 `render/reflow_text.py` 规则；邻字取整理本对位字 | A3；整理本分段规则 | 单测造数据覆盖：页中、段首、段尾、跨页、对位缺字；char-groups 用 `ctx_ver: 2` 重建后条数与旧版相同 | 待做 |

## 发现与待确认
- 原表里 彜＝`⿱彑𪪷`、𢑱＝`⿱𫜹𡙢`／`⿱彑𡙢`、彛＝`⿱彐𪪷`：展开后六字**全是** `⿳上⿰米X下`，与用户的上中下读法一致。
- 上段：原表用 𫜹（`⿼コ一`）表示「⺕」形，按别名并入 彐；用户标注里的 ⺕（U+2E95）与 彐（U+5F50）**待用户确认是同一部件**。
- 用户的 42 格标注里「中」写作 `糸` 或 `米+分`，对应 IDS 的 `⿰米糸`／`⿰米分`。
