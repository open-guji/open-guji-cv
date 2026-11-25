# 2 切字：五小步拆成独立 Step（设计，待评审）

2026-11-25 用户定：2a–2e 直接拆成独立 Step，不怕指纹变；顺序为 2a 拉直、2b 定字带左右边、2c 列端字（先切收尾与版框连接处）、2d 字间切分、2e 字框压缩。分组与输入输出的说明见 [五小步.md](../2-切字/五小步.md)。本文是**拆代码的方案**，只覆盖刻本链 `keben_body_v2`；现代 `modern_body`、自由版式 `keben_free` 本轮不动（`column_crop` 与 `ColumnWindowRec` 共用，见第四节）。

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
3. `column_gate`：现在挂 `column_warp`，读全部字段。拆后按字段归属拆成三段挂到 2a／2b／2c（L1 列数、列宽、L2b `stamp_noise` 在 2a；L2 `side_ink` 在 2b；L4e `frame_residue`、版框分诊在 2c），出口闸挂在 2c，`row_segment` 的 `gate_manifest` 取三处的合并结果。**这是本方案里改动最大的一块，要单独评审。**
4. 读 `column_windows.band`／`trim_*` 的下游改读新产物：`row_segment`、`cell_shrink`、`seg_screen_run`、`colgeom`、`manager_api`、`feedback/anchor`、`pins_check` 等（用 `grep` 列全，改完 `tests/test_architecture.py` 守着）。
5. 骨架 `_skeleton.yaml`：`columns` 槽位里刻本链放三步；`stages.cut` 不变（槽位整体归 cut）；`bootstrap` 的 `BOOTSTRAP_STEPS` 补两步。
6. `code_deps`／`book_deps`：`frame_layers`、`outer_gap` 现在挂在 `column_warp`，应归 2c；`tight_rule_band`、`inner_bar_span` 归 2b；`ruled_warp`、`det_warp` 留 2a。书级 `params` 里写在 `column_warp:` 下的这几个开关要迁到新 Step 名下（`book_defaults` 迁移脚本，GM2）。
7. 文档：`步骤与产物.md` 由 `gen_stage_docs.py` 重生成；README 改成五步表；Wiki 同步。

## 四、不动与风险

- `column_crop`（现代）与 `ColumnWindowRec` 共用：本轮把 `band`／`trim_*` 等字段在模型里**保留为可选**，刻本链不再写，现代链照旧写，等现代链也拆时再删。
- 所有刻本书（殿本、史記、全唐文、脉经）的列图类产物、`cells`、`char_index` 起全部过期，需要整册重跑；按「代码等价登记」办不到（产物目录和指纹都变），要走一次全量重算。**重算前先用 cut-bench 在拆分前后各跑一遍，`cells`、`char_index` 逐字节比，不等价就是拆错了。**
- 人钉、人裁绑在 `cells`／格号上，不绑 `column_windows` 字段；`manual-cells` 的列图坐标换算用 `ColumnMapper`（读 `ruled`、窗口、`warped_size`），都留在 2a，不受影响。

## 五、顺序

1. 2a/2b/2c 拆分（逐字节等价）→ cut-bench 对比 → 合 dev。
2. 闸拆分（可与 1 同一个 PR，也可紧随其后）。
3. 2b 新字段（字带左右端）单独做，评测后再决定是否让 2c、2d、2e 用。
4. 骨架、文档、Wiki、`book_defaults` 迁移。
