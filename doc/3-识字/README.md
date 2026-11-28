# 3 识字（read）

原九步的 Step5-a、5-b。**只从字块图取证**：两路各自给每格证据，互不投票，交给 [4 定字](../4-定字/README.md) 裁决。整理本对位（原 5-d `align_ref`）不读字块图，2026-11-22 起归 4 定字（Sheldon 定）。

| 小步 | 步骤 id | 产出 |
|---|---|---|
| 3a 字形库匹配 | `glyph_match` | 每格在本书字形库里的 same／unsure／diff 三档判决与逐实例证据（指纹带库版本） |
| 3b 生僻字候选 | `rare_candidates` | 字体模板＋CNN 的融合候选（要模型；没下游在读时自动跳过） |
| 3d 字块图其他特征 | `cell_traits` | 每格 cut／border／residue／stain／merged／blank 原始分（未校准，缺省关；判法见 `clustering/cell_traits.py` 模块头）；收尾 `glyph_analyzer` 放进 `traits` |
| 3e 看图大模型（条件） | `glyph_vis` | 3a／3b 不够好的少数格只看字块图问大模型「刻形像哪个候选」（缺省关；`model` 空只读缓存、没命中出 ask）；缓存 `<feedback>/vis_glyph/`（kind `vis_glyph`，不是人裁、不算钉）；结论进收尾 `vis`／`evidence.v`，不出 p。触发、参数、缓存键见 `steps/glyph_vis.py` 模块头 |

- 各步的输入输出、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 形近字组登记表（六处来源合一的 `near_groups/2`、schema、读口）：[形近字组登记表.md](形近字组登记表.md)。
- 本大步的工具命令：`guji-cv read rare`（生僻字单查、批量）；现代排印本播种用 `calibrate-font`、`witness-align`、`witness-align-stream`、`seed-witness`。
- 字形库、语料、模型的版本钉法：[../design/字形库按版本钉-细设计.md](../design/字形库按版本钉-细设计.md)、[../design/语料库分层版本.md](../design/语料库分层版本.md)、[../design/模型系统.md](../design/模型系统.md)。
- 相关设计：[glyph_match_stack](../design/glyph_match_stack.md)、[5b-库字档](../design/5b-库字档.md)、[5b-笔画证据](../design/5b-笔画证据.md)、[特殊符号进字符候选集](../design/特殊符号进字符候选集-设计.md)、[Step5-7 操作一览](../design/Step5-7-操作一览.md)。
