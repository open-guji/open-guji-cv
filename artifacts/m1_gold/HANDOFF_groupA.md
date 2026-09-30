# A 道交接（column_warp / frame_strip / side_rule / text_band / page_crop）2026-09-30

通用：环境 `source /home/user/sandbox/env.sh`。数字范围=沙箱：vol01/vol02 金标页产物在 `/home/user/sandbox/A_products`（我自己的目录，Step1→Step4 按需补跑），
text_band / page_crop 基线读主沙箱 `products`（vol01 108 页全、vol02 border_detect 全、vol02 row_segment 未跑完）。
五个评测经 `python -m open_guji_cv eval --from-raw --timeout 3000 run column_warp frame_strip side_rule text_band page_crop`（GUJI_PRODUCTS_DIR=A_products）全部「通过 5 / 失败 0 / 跑不起来 0」。
共同改动：脚本默认读 v2 产物（`--source v2`，`--source v1` 保留旧读法）；registry 里 side_rule/text_band/page_crop 的 needs 去掉 `v1_output`；
**评测现场先过「人当时看的图还在不在」闸，金标文件本身没改**（数据集仓只新增 `text-band/expected_v2.json`、`page-crop/expected_v2.json`，已拷入本目录）。
新增脚本：`scripts/column_warp_v2.py`、`scripts/patch_identity.py`、`scripts/migrate_m1_column_warp.py`（各评测目录有副本）。

## column_warp
- 空跑原因：评测读 `output/<册>/step2_columns/*.png`（`regen_step2_columns.py` 预导、v1 时代落点），云端没有；`border_class` 那一半——metadata 写 64 条，但本克隆 samples/items 里 **0 条**（bxgb 31 条类别无指纹/无图）。
- 迁移结果：115 列 → 迁入 86（指纹 5 / 曲线同一 71 / 零墨补救 10），失效 29（宽变+曲线变 18、仅曲线变 10、仅宽变 1；含 2 条 mixed）。border_class 0 迁。见 `column_warp/MIGRATION.md`。
- 新基线：`python scripts/eval_column_warp.py ../open-guji-dataset/char-segmentation/column-warp`（A_products）：86 列/66 页；文字带命中走廊 **137/172 条界**；吃进字身 **21/86 列**（均 0.3px，最大 5px）；clean 组残墨 0.002（最大 0.017）；
  附加（非原口径）容差 1px 内命中 165/172。严格口径（不含补救档）76 列：121/152，吃字 19/76。border_class：无金标，不报。
- 与 doc 上次值对照（column-warp/README.md「当前状态与跑分」）：现行口径 32 列/13 页 命中 58/64、吃字 1 列 1px、border_class 一致 60/63；legacy 43/50。
  同页面子集（vol01 按原 5 类选列标签、能迁的 18 列）：命中 27/36、吃字 4 列。**差异主因是口径/图变**：走廊宽 0 的列（human=canonical）v2 窗口纵向变了后带边界差 1px 就计吃/欠，容差 1px 后 165/172（96%）；
  **真变化**：vol02/11 c1 左界预测 10 vs 人标 5（吃 5px）、vol01/14 c3 欠 4px，是值得看的两列。
- 仍跑不了：border_class（金标缺）；vol01 原 32 列里 29 条失效的要重标才能恢复样本量。

## frame_strip
- 空跑原因：金标格位指向 v1 `phase4_chars/patches`，退役；脚本原报「0 个样本（65 个格位已消失）」，不是解析器问题。
- 迁移结果：65 → 迁入 8（带框 3 / 干净 5），失效 57（无存图 47、图对不上 10）。判据=instances/patches 存的人裁图块 vs v2 字块 NCC≥0.90+位移≤4+尺寸差≤12。见 `frame_strip/MIGRATION.md`。
- 新基线：`python scripts/eval_frame_strip.py ../open-guji-dataset/char-segmentation/frame-strip`：n=8；残余率 **0/3**；误剥率 **0/5**；字保全 **3/8**（墨量≥main_ink 基线；5 条低 0.2~2.8%，最差比值 0.972；对位后旧有新无/新有旧无像素同量级＝重采样，附加指标容差 3% 为 8/8）。
- 与 doc 对照（frame-strip/README.md）：原目标 残余率→0、误剥 0、字保全红线 100%；README 历史「残余率 19% 是天花板」「2026-08-25 重冻 11 条」。v2 的 0/3 残余无法与 19% 比（样本 3 条）；
  字保全 3/8 是**口径变化**（v1 main_ink 基线对不上 v2 重采样），不是切字——但建议你抽 22:7:20（2178<2240）肉眼确认。
- 仍跑不了：57 条无图，需在 v2 上重标。

## side_rule
- 空跑原因：读 v1 `phase3_char_grid`/`phase4_chars`；且金标是算法挖的（正样本=有出带细高连通体），无逐格人裁证据。
- 迁移结果：264 有效 → 迁入 2（均负样本），失效 262（无存图 252、图对不上 10）；**25 条正样本全部失效**。
- 新基线：`PYTHONPATH=. python scripts/eval_side_rule.py ../open-guji-dataset/char-segmentation`：计分 2；残余率 0/0（无正样本，不可量）；误剥率 2/2（vol01/18:2:20 keep_ink 591<605、vol02/144:2:5 340<341）；字保全 1/2（vol01/18:2:20 1197<1239）。**n 太小，不能当基线，仅证明管线通了。**
- 与 doc 对照（side-rule/README.md）：残余率 25/25→2/25、误剥 1/240、字保全 262/262。v2 无可比口径（样本几乎全失效），不是退步也不是进步。
- 仍跑不了：需要在 v2 图块上重新挖正样本（`build_side_rule_shard.py` 仍按 v1 产物挖，未改）。

## text_band
- 空跑原因：读 v1 `phase2_layout.inner_frame`+`phase3_char_grid`，云端无 → 「字格 47431→0」假回归。金标是算法快照非人裁。
- 迁移结果：不迁，重冻 v2 基线 `text_band/expected_v2.json`（窗口高=borders 上下内框@页中线；格高=全书 row_segment period 中位 115.0；每列 21 字；字格=kind==char）。
- 新基线：`python scripts/eval_text_band.py ../open-guji-dataset/char-segmentation --update`（主沙箱 products）：正文 **109 页**（vol01 108 + vol02 1）/ 字格 **17231** / 窗口偏短 **0 页**；比值最小 0.952（vol01/87）、中位 1.016。
  回归只比页交集（A_products 上交集 53 页通过）。**vol02 186 页 row_segment 沙箱没跑完，未入基线**——跑完后 `--update` 重冻。
- 与 doc 对照（text-band/expected.json、README）：294 页/47431 格/偏短 2 页（vol01/50=0.863、vol01/88=0.898）。v2：vol01/50=1.096、vol01/88=0.967 → 偏短 2→0，**真变化**（v2 Step1 内框比 v1 phase2 准）；
  格数不可直接比（页数不同；每页均值 v1 161 vs v2 158）。
- 仍跑不了：无豁免机制对应（`band_widened/checked` 在 v2 无）。

## page_crop
- 空跑原因：读 v1 `phase3_char_grid` 的 cell_left/right_x；金标是算法快照。病根（s3 预处理裁窄）在 v2 链不存在（直接读原图）。
- 迁移结果：不迁，冻 v2 基线 `page_crop/expected_v2.json`（最外两条竖线 vs 页宽，阈值 8px 不变）。
- 新基线：`python scripts/eval_page_crop.py ../open-guji-dataset/char-segmentation --update`：扫 **318 页**（vol01 109/vol02 186/bxgb 23），越界 **0 页**；最外线离页边最小余量 右 255px/左 245px（bxgb），vol01/02 ≥300px。
- 与 doc 对照（page-crop/README.md）：6 页/387（vol01/167 左10.9、178 右12.3、18 右20.8、vol02/136 8.6、64 9.9、70 12.3）。v2：18/136/64/70 均未越界；167/178 非正文页 v2 无产物，未验。**真变化**（口径与对象都换了：v1 是裁窄后的网格窗，v2 是原图上的界行）。
- 仍跑不了：无。
