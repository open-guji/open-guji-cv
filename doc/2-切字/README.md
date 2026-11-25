# 2 切字（cut）

原九步的 Step2–4。输入原图和 [1 版面](../1-版面/README.md) 认出的版框、界行、印章，先把每列拉直（射影、缩放）、把字和版框界行分开，再切成带类型的字格（字、空格、夹注、印章、插图…），再把每格收成紧框，交给 [3 识字](../3-识字/README.md)。

| 小步（旧分组） | 步骤 id | 产出 |
|---|---|---|
| 2a 单列拉直 | 刻本 `column_warp`／现代 `column_crop`／自由版式 `column_trace`、`line_ocr` | `column_windows`、`column_image`；闸 `column_gate` 判每列能不能切 |
| 2b 逐字切分 | 刻本 `row_segment`／现代 `row_segment_runs`／自由版式 `cell_cut` | `cells`（字格＋读序）；闸 `row_segment_gate` |
| 2c 字框收缩 | `cell_shrink` | `char_index`（紧框＋flags）、`char_patch`（字块图） |

- 单列拉直 2026-11-22 起从 1 版面移来（用户定：1 版面只认位置、判类型；射影、缩放、字与框线分离整个归切字）。步骤 id、产物、指纹不变。
- 各步的输入输出、闸、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 人定切分（15 种，优先级）：[切分覆盖.md](切分覆盖.md)。
- 切分代码分层（`seg/` 原语、`impl/` 版式、书仓 `code/`）：[../参考/切分代码结构.md](../参考/切分代码结构.md)。
- 相关设计：[row_boundaries_design](../design/row_boundaries_design.md)、[step3_touching_and_jiazhu](../design/step3_touching_and_jiazhu.md)、[peak_line_search](../design/peak_line_search.md)、[YOLO 列字数先验](../design/19-yolo-release列字数先验与全书评测-总设计.md)。
- 研发过程与负结果：[../经验/切分四步-研发记录.md](../经验/切分四步-研发记录.md)。
- **2026-11-25 起分析用五小步 2a–2e（拉直、定字带左右边、字间切分、列端字、字框压缩）**，每步的输入输出与现有代码的对应见 [五小步.md](五小步.md)；上表是步骤 id 的分组，不变。
