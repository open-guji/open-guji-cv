# HANDOFF E 道：云端评测基线（2026-09-30）

分支 `claude/E-eval-baseline-0930`。环境/命令/坑见 `doc/cloud_eval.md`。

## ⚠ 未完成的交付（被权限拦住，需你处理）
`add_repo open-guji-core/overview` 被权限分类器拒绝，所以：**没读到 #305/#300 原文**、**没写 overview 仓的
基线 md、没在 #305 发评论**。下面的基线表就是要放进
`项目进展/图片初步数字化/进度/云端评测基线.md` 的内容（初版，可直接拷过去），给权限后我可代推。

## 评测层修复（本分支，均不改算法）
1. `eval/runner.py`：`--from-raw` 遇到本工作区没有定义的册（金标混了 bxgb）整批崩 → 只让该评测 failed 并写原因。
2. `scripts/eval_unsupported_layout.py`：金标路径不再写死 `D:\workspace\…`，默认 `../open-guji-dataset/page-type/expected.json`，加 `--gold`。
3. `eval/registry.py`：新增前提 `v1_output`，10 个读 v1 链产物 `./output/<册>/phase3_char_grid` 的评测（char_drop / seam / truncation / page_crop / jiazhu_tail / left_cut / right_cut / side_rule / text_band / geometry，外加 instance_quality 读 v1 phase4_chars）在没有该目录时标 skipped，**不再静默扫 0 页印假通过/假回归**（云端原先 seam/truncation/char_drop/page_crop 的「✓ 0%/通过」和 text_band「回归门失败」全是假象）。
4. `scripts/regen_step2_columns.py`：原图回退加入 `GUJI_WORKSPACE/data_full/...`（原先只认仓内 data_full，云端不存在）——使 column_warp 可跑。
5. 不改代码的办法：overlay 工作区（软链四庫 books+原图 与 bxgb books+原图），见 doc/cloud_eval.md §2，解决 touching_cuts 的「parse_metrics 0 条」——根因是缺 bxgb 产物，不是解析器。
- `rare_char` 的 `../open-guji-dataset` 相对路径：cwd=引擎仓、数据集仓同级即可，无需改（软链 /home/user/open-guji-dataset）。
- `bottom_offset` 只需 GUJI_WORKSPACE，已跑通。

## 基线表（云端，vol01/vol02/bxgb 金标；「上次值」doc 对照**未做**，留空）
| 评测 | Step | 金标 n | 当前 | doc 上次值 | 跑法 | 耗时 |
|---|---|---|---|---|---|---|
| bottom_offset_gold | 1 边框 | 374 | mean 14.58px | — | eval run bottom_offset_gold | 38s |
| bottom_offset_oneside | 1 边框 | 187 | ok 152/187=81.3% | — | 同上 | 220s |
| column_warp | 2 列矫正 | 242 点/115 列 | 命中 62.81%；吃到字身的列 40%（46/115） | — | 需先 regen_step2_columns（bxgb 10 页未出列图） | 1.2s |
| row_boundaries | 3 格线 | — | **failed**：vol01/33 等「对齐相关只有 -2.00」（此前一轮 ≤3px 30.3% / ≤5px 48% / ≤10px 67.7%，n=198）——待查 | — | | 1s |
| touching_cuts | 3 粘连 | 727 | 像素误差 mean 7.4 / median 1 / p90 23 | — | 需 overlay | 9–27s |
| recrop | 4 | 40 | 格位消失 40（金标全过期，空跑） | — | | 0.2s |
| layout | 版式 | — | >6 列 0.1% | — | | 0.2s |
| normalize | 归一化 | 31 | 回归门 90.32%（28/31） | — | | 0.6s |
| rare_char | 生僻字 | 6 | 现状 33.3% / 字体模板 0% / 并集 33.3% | — | | 0.4s |
| llm_context | 上下文 | 150 | llm_acc 3.3%（mock 默认） | — | | 0.2s |
| pagetype | 页型 | — | n=0 空跑 | — | | 0.2s |
| unsupported_layout | 页型闸 | 294 body | 红线 body 误判 0 ✅；漏判 10 页（方向安全） | — | `scripts/eval_unsupported_layout.py`（registry 解析不出指标，假 failed） | ~60s |
| frame_strip | 2 | 0 | 「0 个样本（65 个格位已消失）」空跑，金标全过期 | — | | |

skipped（v1 产物缺）：char_drop seam truncation page_crop jiazhu_tail left_cut right_cut side_rule text_band geometry instance_quality。
跑不了：OCR/GPU（char_ocr、font_fallback、struct_*）；重活（clustering、db_match、match_*、degradation、oov、zero_shot*、seen_test_single_proto、guard_ceiling）；语料（confusable_lm、context_correction、align_replace_gate）；中间产物（crop_margin）。

## 离目标最远（依据基线数字，粗排）
1. Step2 列矫正：命中 62.8%，40% 的列吃到字身。
2. Step3 格线：±3px 仅 30%（上一轮数），粘连切线 p90 23px。
3. Step1 bottom_offset 81%（下框 oneside）。
4. 生僻字候选并集 33%（n=6，样本极小）。
注：大量评测金标已过期（frame_strip/recrop 全空、pagetype/truncation 空跑），这本身是最大的「量不出来」风险。

## 待你/下一步
- 给 overview 写权限，我推基线 md + #305 评论。
- row_boundaries 新 failed 原因（bxgb/overlay 引入的页？）未查清。
- 「doc 记载的上次指标 / 是否回归」列未对照，需要读各 doc。
