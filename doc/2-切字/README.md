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

## benchmark（2026-11-28，四大步验收 S11、S12）
脚本都在 `open_guji_cv/eval/`，只读产物、不动指纹；金标在 open-guji-dataset `char-segmentation/`。登记见 [../bench登记表.md](../bench登记表.md)，按书基线见 [基线-2026-11-28.md](基线-2026-11-28.md)。

| 小步 | 命令 | 测试集 | 主指标 | 护栏（必须为 0／不增） |
|---|---|---|---|---|
| 2a、2d、整步 | `python -m open_guji_cv.eval.cut_bench run／score` | cut-bench（四书 155 页）、cut-lattice | 列全对、字数全对、格 F1 | `--against` 的「对→错」翻转列 |
| 出口闸 | `python -m open_guji_cv.eval.cut_bench gate` | cut-bench | 检出率、误报率（拦／拦或旗两档，按判据分报） | — |
| 2b | `python -m open_guji_cv.eval.cut_ink band` | band-ink（史記、全唐文） | 字带余量 | 抹墨格 |
| 2c、2e 列端 | `python -m open_guji_cv.eval.cut_frame --items cut-frame/items.jsonl` | cut-frame（史記、全唐文） | IoU@0.9 | 切笔、新带渣 |
| 2e 列中 | `python -m open_guji_cv.eval.cut_frame --items shrink-ink/items.jsonl --junk-tol 6` | shrink-ink（史記、全唐文） | IoU@0.9 | 切笔 |

冻结输入（原图、第一步产物、册配置、书仓 code/）用 `cut_bench freeze --gold-from <dataset>/char-segmentation/cut-bench/<书>` 从工作区与产物包取，做法见 `eval/cut_bench.py` 模块头；
改切字算法前后各 `run` 一次，`score／gate／cut_frame／cut_ink band` 都带 `--against` 出翻转清单。

