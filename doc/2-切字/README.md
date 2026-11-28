# 2 切字（cut）

原九步的 Step2–4。输入原图和 [1 版面](../1-版面/README.md) 认出的版框、界行、印章，先把每列拉直（射影、缩放）、把字和版框界行分开，再切成带类型的字格（字、空格、夹注、印章、插图…），再把每格收成紧框，交给 [3 识字](../3-识字/README.md)。

| 小步 | 步骤 id | 输入 | 产出 |
|---|---|---|---|
| 2a 拉直 | 刻本 `column_warp`／现代 `column_crop`／自由版式 `column_trace`（＋可选 `line_ocr`） | 原图、`borders`、版面闸 | `column_windows`、列图 `column_raw` |
| 2b 字带左右边 | `column_band`（刻本） | `column_raw`、`column_windows` | `column_bands`、列图 `column_banded`（界行抹白） |
| 2c 列端字 | `column_end`（刻本） | `column_banded`、`column_bands`、`column_windows`、`borders` | `column_ends`、列图 `column_image`（上下端抹框） |
| 列几何 | `column_geometry`（刻本） | 2a–2c 产物 | 文字带、格线范围、页级字距；结构性不切的列（页型 skip、非正文列位、表格列） |
| 2d 字间切分 | 刻本 `row_segment`／现代 `row_segment_runs`／自由版式 `cell_cut` | `column_image`、`column_bands`、`column_ends`、版式先验、人定切分 | `cells`（字格＋类型＋读序） |
| 2e 字框压缩 | `cell_shrink` | `cells`、`column_image`、`column_bands` | `char_index`（紧框＋flags）、`char_patch`（字块图） |
| 出口闸 | `cut_gate`（挂 `cell_shrink`，刻本）；现代 `column_gate` | 2a–2e 全部产物 | `gate_manifest`、`row_segment_gate_manifest`；只出裁决，不挡中间步 |

2a–2e 已是独立 Step（cv #1869、#1872，2026-11-25）。每小步的做什么／不做什么、与旧代码的对应：[五小步.md](五小步.md)。

- 单列拉直 2026-11-22 起从 1 版面移来（用户定：1 版面只认位置、判类型；射影、缩放、字与框线分离整个归切字）。步骤 id、产物、指纹不变。
- 各步的输入输出、闸、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 人定切分（15 种，优先级）：[切分覆盖.md](切分覆盖.md)。
- 切分多备选（候选切线、段分、挑中的路）的 schema：[切分多备选.md](切分多备选.md)。
- 字间界线判官（`row_segment.boundary_net`，看字挪低分切线、格数不变；模型、借用或单独训、验收）：[字间判官.md](字间判官.md)。
- 折线（格的 `seam_top`／`seam_bottom`、切点候选 `y`）：内存里每 x 一个 y（从 `content_x[0]` 起），产物 JSON 里存游程 `{"n", "runs": [[x, y], …]}`（2026-11-27 起，无损；旧产物的逐 x 表照读），直接读 JSON 用 `products.kinds.cells.seam_ys()` 展开。
- 切分代码分层（`seg/` 原语、`impl/` 版式、书仓 `code/`）：[../参考/切分代码结构.md](../参考/切分代码结构.md)。
- 相关设计：[row_boundaries_design](../design/row_boundaries_design.md)、[step3_touching_and_jiazhu](../design/step3_touching_and_jiazhu.md)、[peak_line_search](../design/peak_line_search.md)、[YOLO 列字数先验](../design/19-yolo-release列字数先验与全书评测-总设计.md)。
- 研发过程与负结果：[../经验/切分四步-研发记录.md](../经验/切分四步-研发记录.md)。

## 出口闸（2026-11-25）
刻本链的出口闸只有一道 `cut_gate`，挂在 `cell_shrink` 出口、永远最后调用，读 2a–2e 全部产物，只出裁决（`gate_manifest`、`row_segment_gate_manifest`），不挡中间步。几何量与结构性不切（页型 skip、非正文列位、表格列、页周期估不出）由前面的 `column_geometry` 算；`row_segment` 读它。现代链仍用 `column_crop`＋`column_gate`，与此独立。
