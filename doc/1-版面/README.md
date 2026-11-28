# 1 版面（layout）

原九步的 Step0–1。输入原图，只管**认位置、判类型**：每页的版框、界行、抬头框、页型和印章，交给 [2 切字](../2-切字/README.md)。
单列拉直（射影、缩放）、字与版框界行的分离 2026-11-22 起归 2 切字（用户定）。

| 小步 | 步骤 id | 输入 | 产出 |
|---|---|---|---|
| 1a 页面预检 | `page_survey`、`invert_detect` | 原图 | 异常页名单、反色带候选（只送审，不自动修） |
| 1b 版框界行 | 刻本 `border_detect`／现代 `line_detect`／自由版式 `block_detect` | 原图、册配置的实测先验（`frame_height`、`outer_shift` 等）、页型表 | `borders`（版框、界行折线、抬头框）；闸 `border_detect_gate` 判页型 |
| 1c 印章 | `seal_detect`（刻本链） | 原图、`borders` | `seals`（每方印的类别与外框） |

不做：不拉直、不抹线、不切字（2026-11-22 起归 2 切字）。版面开关 2026-11-25 起五个缺省开（`outer_bar`、`vline_track`、`inner_pull`、`head_raise_fit`、`no_frame_skip`，cv #1892），个别书要关的见 [已知问题.md](已知问题.md)（如史記关 `vline_track`＋`outer_bar`）。验收按 [../验收标准.md](../验收标准.md)，benchmark 登记见 [../bench登记表.md](../bench登记表.md)。

- 各步的输入输出、闸的判据、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 本大步的工具命令：`guji-cv layout survey｜preclean｜split｜locate-gutter｜calibrate｜binarize`（`--help` 看参数）。
- 1b 的实现由版式（`impl/keben|modern|free`）和书仓 `code/` 提供，见 [../参考/切分代码结构.md](../参考/切分代码结构.md)。
- 人定切分（某页某列按人说的切）：[../2-切字/切分覆盖.md](../2-切字/切分覆盖.md)。
- 相关设计：[列宽均匀约束](../design/列宽均匀约束.md)、[彩图墨层与二值体检](../design/彩图墨层与二值体检.md)、[图片格与插图](../design/图片格与插图-处理流程.md)、[印章遮挡格](../design/印章遮挡格-判据与放行.md)、[现代排印链](../参考/modern_print_pipeline.md)、[自由版式](../design/自由版式切分-游学鳌头.md)。
- 评测：版面 benchmark（线／边框／列数行数／页型）：`python -m open_guji_cv.eval.layout_bench`，指标口径见 `open_guji_cv/eval/layout_metrics.py` 模块头，金标格式与标注方法见 open-guji-dataset `layout/README.md`。
