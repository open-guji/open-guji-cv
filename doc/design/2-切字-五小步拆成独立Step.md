# 2 切字：五小步拆成独立 Step（设计，待评审）

2026-11-25 用户定：2a–2e 直接拆成独立 Step，不怕指纹变；顺序为 2a 拉直、2b 定字带左右边、2c 列端字（先切收尾与版框连接处）、2d 字间切分、2e 字框压缩。分组与输入输出的说明见 [五小步.md](../2-切字/五小步.md)。本文是**拆代码的方案**，只覆盖刻本链 `keben_body_v2`。2026-11-25 用户补充三条：①**出口闸只在最后调用**，有自己的接口，不挂在任何中间 Step 上；②**现代印刷链逻辑完全不同，和刻本链彻底独立**（`column_crop` 与刻本不再共用 `ColumnWindowRec`、闸、产物类型）；③本方案由 CV2 自己实施，不请别的项目改（书级开关沿用旧名，见第三节）。

## 一、现状

`column_warp` 一个 Step 里做了 2a、2b、2c 三件事（`_images`：`warp_column` → `denoise_column` → `clean_column`，`clean_column` 里先 `column_text_band`＋`strip_column_rules`，再 `column_border_trim`）。产物 `column_windows` 一条记录里混着三步的字段，`column_gate` 挂在它上面，一并读。`row_segment`、`cell_shrink`、评测与审阅台读 `column_windows`、`column_image`。

## 二、拆后的 Step 与产物

| 小步 | Step id | 消费 | 产出（numeric） | 产出（列图缓存） |
|---|---|---|---|---|
| 2a | `column_warp`（保留 id） | `raw_page`、`borders`、`border_detect_gate_manifest` | `column_windows`：窗口、上下界、`border_*_in_column`、`warped_size`、`ruled`、`side_floor`、`stamp_noise` | `column_raw`（拉直＋去噪） |
| 2b | `column_band`（新） | `column_raw`、`column_windows` | `column_bands`：`band`、`side_class`（原 triage 里的侧向部分）、找带所用档位（贴边／内缩）与书级开关 | `column_banded`（界行抹白，尺寸不变） |
| 2c | `column_end`（新） | `column_banded`、`column_bands`、`column_windows`、`borders`（内框线） | `column_ends`：`trim_top`、`trim_bottom`、`frame_residue_*`、`top_class`／`bot_class`／`pad_*` | `column_image`（上下端抹框，**名字保留**，下游照读） |
| 2d | `row_segment` | `column_image`、`column_bands`、`column_ends`、版式先验、人定切分 | `cells`（不变） | — |
| 2e | `cell_shrink` | `cells`、`column_image`、`column_bands` | `char_index`、`char_patch`（不变） | — |

要点：
- 三步的算法**不改**，只是把 `clean_column` 切成两段：`column_text_band`＋`strip_column_rules` 归 2b，`column_border_trim`（含 `inner_bottom` 双线逻辑）归 2c。2c 必须在 2d 之前，与现在先抹框后切缝的顺序一致，切字结果应逐字节相同，只有 Step 指纹与产物目录变。
- 2c 的边距证据（`margin_profile`）现在在抹界行**之前**的图上算，拆开后 2c 要同时读 `column_raw` 与 `column_banded`；所以 2c 的消费里要加 `column_raw`。
- 2b 的新输出（用户想法：在文字带内取稍往里缩、墨量最小的点，作为列的字带左右端，供 2c、2d、2e 共用）作为 `column_bands` 里的**新增字段**，缺省不启用，分两步做：先纯拆分、逐字节等价；再加新字段并单独评测。

## 三、要改动的地方

1. 新产物类型：`column_bands`、`column_ends`；`column_windows` 去掉 `band`、`trim_*`、`frame_residue_*`、`triage`（刻本链）。老产物不迁移，重算。
2. 新 Step：`column_band.py`、`column_end.py`；`column_warp.py` 只留 2a；`render`（再生列图）三个 Step 各管各的缓存，`StaleRenderError` 的尺寸检查留在 2a。
3. **闸与「交接清单」分家**（本方案的核心改动）。`column_gate` 现在是 Step，挂在 `column_warp` 后自动跑，产物 `gate_manifest` 里**混了两种东西**：
   - 计算量：页级 `period`（纵向字距，含 `period_prior` 兜底）、`ref_w`、`median_width`、`column_widths`；列级 `content_x`、`border_top/bottom`、`top_slack`、`n_raised_hint`、`raised`、`head_raise_inner_y`、`band_width`。`row_segment` 读的正是这些（`period`、`ref_w`、`gc.content_x`、`gc.border_*`、`gc.col`）。
   - 裁决：`admitted`、`reject`、`flags`、`tier`；`row_segment` 靠 `only_admitted` 拿它**挡列**。
   拆法：
   - 计算量搬出来，做成 2c 之后的纯计算 Step `column_geometry`（产物 `column_geometry`，无任何判定），归入 cut 大步；算法原样搬，不改。
   - 「结构性不切」（`L0c` 非正文列位、`L0t` 表格列、页型 `skip`）不是质量问题，是版式事实，改为 `column_geometry` 里每列一个 `cuttable`＋原因；`row_segment` 只看它，不再看质量裁决。
   - 质量判据（L1 列数、L1c／L1n 列宽、L2 `side_ink`、L2b `stamp_noise`、L4e `frame_residue` 等）全部移到**最后**的出口闸 `cut_gate`：它是独立接口，读 2a–2e 全部产物，只产出裁决（`admitted`／`reject`／`flags`）；不 block 任何中间步，只在 2e 之后调用一次。`row_segment_gate` 的判据（DP 有解、格数、碎格等）并入同一道闸。
   - 行为变化（要评估）：原来被 `column_gate` 质量判据拦下的列（`block` 级）现在会照切，之后由出口闸标出；`flag` 级判据不受影响。下游（识字、定字）原本靠 `admitted` 跳过的列，改读 `cut_gate`。**要先量一下有多少列受影响**（拆前各册 `admitted=False` 且非结构性的列数）。
4. 读 `column_windows.band`／`trim_*` 的下游改读新产物：`row_segment`、`cell_shrink`、`seg_screen_run`、`colgeom`、`manager_api`、`feedback/anchor`、`pins_check` 等（用 `grep` 列全，改完 `tests/test_architecture.py` 守着）。
5. 骨架 `_skeleton.yaml`：`columns` 槽位里刻本链放三步；`stages.cut` 不变（槽位整体归 cut）；`bootstrap` 的 `BOOTSTRAP_STEPS` 补两步。
6. `code_deps`／`book_deps`：`frame_layers`、`outer_gap` 归 2c；`tight_rule_band`、`inner_bar_span` 归 2b；`ruled_warp`、`det_warp` 留 2a。**书级开关不请别的项目迁移**：册配置里写在 `column_warp:` 下的 `tight_rule_band`、`inner_bar_span` 由引擎按字段名自动分派给 2b（加载册配置时的一层别名，旧名继续有效），`params_hash` 不依赖旧名。
7. 文档：`步骤与产物.md` 由 `gen_stage_docs.py` 重生成；README 改成五步表；Wiki 同步。

## 四、不动与风险

- 现代链（`column_crop`、`row_segment_runs`）与刻本链彻底独立：把它们用到的 `ColumnWindowRec` 字段、`column_gate`、`gate_manifest` 复制成现代链自己的产物类型和闸（`modern_*`），刻本链改完不影响它；现代链自己的重构以后另开。
- 所有刻本书（殿本、史記、全唐文、脉经）的列图类产物、`cells`、`char_index` 起全部过期，需要整册重跑；按「代码等价登记」办不到（产物目录和指纹都变），要走一次全量重算。**重算前先用 cut-bench 在拆分前后各跑一遍，`cells`、`char_index` 逐字节比，不等价就是拆错了。**
- 人钉、人裁绑在 `cells`／格号上，不绑 `column_windows` 字段；`manual-cells` 的列图坐标换算用 `ColumnMapper`（读 `ruled`、窗口、`warped_size`），都留在 2a，不受影响。

## 五、顺序

1. 先量影响：拆前各册被 column_gate 质量判据拦下的非结构性列数。
2. 2a/2b/2c 拆分（逐字节等价）→ cut-bench 对比 → 合 dev。
3. `column_geometry` 与出口闸 `cut_gate` 拆出（行为有变，单独 PR、单独评审）。
4. 2b 新字段（字带左右端）单独做，评测后再决定是否让 2c、2d、2e 用。
5. 骨架、文档、Wiki。
