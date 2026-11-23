# 3 识字（read）

原九步的 Step5。三路各自给每格取证，互不投票，交给 [4 定字](../4-定字/README.md) 裁决。

| 小步 | 步骤 id | 产出 |
|---|---|---|
| 3a 字形库匹配 | `glyph_match` | 每格在本书字形库里的 same／unsure／diff 三档判决与逐实例证据（指纹带库版本） |
| 3b 生僻字候选 | `rare_candidates` | 字体模板＋CNN 的融合候选（要模型；没下游在读时自动跳过） |
| 3c 整理本对位 | `align_ref` | 整理本（参校文本）与字格逐字对位（要语料） |

- 各步的输入输出、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 本大步的工具命令：`guji-cv read rare`（生僻字单查、批量）；现代排印本播种用 `calibrate-font`、`witness-align`、`witness-align-stream`、`seed-witness`。
- 字形库、语料、模型的版本钉法：[../design/字形库按版本钉-细设计.md](../design/字形库按版本钉-细设计.md)、[../design/语料库分层版本.md](../design/语料库分层版本.md)、[../design/模型系统.md](../design/模型系统.md)。
- 相关设计：[glyph_match_stack](../design/glyph_match_stack.md)、[5b-库字档](../design/5b-库字档.md)、[5b-笔画证据](../design/5b-笔画证据.md)、[特殊符号进字符候选集](../design/特殊符号进字符候选集-设计.md)、[Step5-7 操作一览](../design/Step5-7-操作一览.md)。
