# 1 版面（layout）

原九步的 Step0–2。输入原图，输出每页的版框、界行、印章和拉直后的单列图，交给 [2 切字](../2-切字/README.md)。

| 小步 | 步骤 id | 产出 |
|---|---|---|
| 1a 页面预检 | `page_survey`、`invert_detect` | 异常页名单、反色带候选（只送审） |
| 1b 版框界行 | 刻本 `border_detect`／现代 `line_detect`／自由版式 `block_detect` | `borders`（版框、界行折线、抬头框）；闸 `border_detect_gate` 判页型 |
| 1c 印章 | `seal_detect`（只有刻本链） | `seals` |
| 1d 单列拉直 | 刻本 `column_warp`／现代 `column_crop`／自由版式 `column_trace`、`line_ocr` | `column_windows`、`column_image`；闸 `column_gate` 判每列能不能切 |

- 各步的输入输出、闸的判据、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 本大步的工具命令：`guji pipeline survey｜preclean｜split｜locate-gutter｜calibrate｜binarize`（`--help` 看参数）。
- 1b、1d 的实现由版式（`impl/keben|modern|free`）和书仓 `code/` 提供，见 [../参考/切分代码结构.md](../参考/切分代码结构.md)。
- 人定切分（某页某列按人说的切）：[../2-切字/切分覆盖.md](../2-切字/切分覆盖.md)。
- 相关设计：[列宽均匀约束](../design/列宽均匀约束.md)、[彩图墨层与二值体检](../design/彩图墨层与二值体检.md)、[图片格与插图](../design/图片格与插图-处理流程.md)、[印章遮挡格](../design/印章遮挡格-判据与放行.md)、[现代排印链](../参考/modern_print_pipeline.md)、[自由版式](../design/自由版式切分-游学鳌头.md)。
