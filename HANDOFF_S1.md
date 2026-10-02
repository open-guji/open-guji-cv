# S1 交单：下版框「带内多候选峰选哪条」学习模型（overview#344）

分支 `claude/S1-bottom-peak-1002`，**默认关、不合 main**。

## 结论（先说）

**这版没有提升，不建议开。** 候选排序模型在同页集、同折上与现行规则打平或略差（见下表），没有一种特征组合 / 模型 / 护栏松紧能稳定超过规则；
不升不降的那几档（强护栏）是「几乎不改页」换来的。也**没有能删的常量**——模型挂在现行规则**之后**（救援之后、落墨条下沿之前），不替代任何一级补丁。
按验收口径（降不接受）：只交默认关的代码与报告。

## 做了什么

- `open_guji_cv/bottompeak_model/`：`signals.py`（候选枚举 + 23 个信号，`SIGNAL_VERSION="1"`）、`model.py`（模型文件 `.joblib`+`.json`，内容指纹、信号口径/sklearn 版本校验）、`chooser.py`（选峰回调 + 纯函数硬护栏 `select`）。
- 钩子：`peak_line_search.find_horizontal_border(bottom_chooser=None)`；落墨条下沿的收尾抽成 `finalize_bottom()`（行为不变的重构）；`border_geometry.detect_borders(bottom_model=None)`。
- 开关：`border_detect` 的 `bottom_peak_model`（默认 false）+ `bottom_peak_model_path`（路径不进指纹）+ `bottom_peak_model_fingerprint`（自动填）。
- 脚本：`scripts/experiments/bottom_peak/build_table.py`（展开候选表）、`train_eval.py`（页折 / 按册留出 / 负担保 / 消融 / 存模型）；结果文本在 `results/`。
- 测试：`tests/test_bottompeak_model.py`（6 条，自造数据）。**没有交模型文件**（没有值得交的）。

## 对比（187 页 gold，`find_horizontal_border` 口径，不含 push_bottom_to_bar）

页误差 = 两端点各自 |线−金标| 取大者。单侧：线在金标下方 0~30px 为「过」，在上方为「切字」。

| 方法 | ≤3px | ≤6px | 平均 | p90 | 最坏 | 单侧过 | 切字 | 太低 |
|---|---|---|---|---|---|---|---|---|
| 现行规则 | 11.8% | 46.0% | 14.2 | 42.5 | 79.4 | 152 (81.3%) | 15 | 20 |
| 候选里最佳（距离，天花板） | 29.4% | 69.5% | 5.8 | 13.2 | 29.4 | 104 | 83 | 0 |
| 候选里最佳（单侧，天花板） | 11.8% | 48.7% | 10.7 | 26.4 | 72.1 | 182 (97.3%) | 5 | 0 |
| HGB 页折（5折×3种子，标签=单侧过） | 11.8% | 42.8~44.4% | 14.6~14.9 | 42.5 | 79.4 | 150~153 | 14 | 20~23 |
| LR 页折（同上） | 11.8% | 45.5% | 14.3~14.6 | 42.5~42.9 | 79.4 | 150~151 | 14 | 22 |
| HGB 留出 vol03→vol02（vol02 160页，规则 130 过） | 13.1% | 48.1% | 14.1 | 39.3 | 64.7 | 126 | 13 | 21 |
| HGB 留出 vol02→vol03（vol03 27页，规则 22 过） | 0% | 3.7% | 23.4 | 52.7 | 79.4 | 22 | 1 | 4 |

（标签=距离 ≤6px 的 HGB：页折 ≤6px 45.5%、单侧过 151、改 6~8 页，同样不升。）

- 单侧天花板 182/187 说明**候选里几乎总有一条「过」的**；但模型分不出是哪条。
- 距离天花板只有 69.5%：**候选生成缺口**——约 30% 的页，人拖的线不在任何峰/墨条下沿位置上。排序模型补不了这个。

## 消融（HGB，页折 seed0/1 的单侧过；规则 152）

| 去掉 | 单侧过 | 改页数 |
|---|---|---|
| 先验类（rel_prior / has_prior / prior_rank） | 152 / 151 | 14 / 13 |
| 条外/条厚/上翼（paper_beyond, bar_len, up_ink） | 150 / 149 | 5~8 |
| 去拐角峰高（central_*） | 151 / 152 | 11~13 |
| 页内相对量 + 上框 | 151 / 154 | 13~15 |
| 全部去掉（只剩峰高/宽/分数等基础量） | 151 / 151 | 3~5 |
| 强护栏（margin 0.3, min_prob 0.5，全特征） | 152 / 152 | 2~3 |

没有哪一组信号单独撑起任何增益；去掉全部也只是更少改页。

## 负担保

- inner14（`border-detection/samples`，14 页）：模型改 0 页。
- 等距抽样正文页 48 页（vol01/02/03，不在 gold 里）：模型改 13 页，**全部移动 ≤1px**（落在同一条墨条的相邻候选上）。
- 注意：这 48 页没有下版框金标，只能数「改了没」，不能证明「原来就对」。inner14 的金标是内框线中心（口径与「切线」不同），也只做了「没改」的检查。

## 局限

- 金标是人挪过线的难页，且 **vol03 只有 27 页**，按册留出的 vol02→vol03 方向样本太小。
- 候选只沿「救援之后现役线」的倾角枚举；人拖的线若与现役倾角不同，天花板只会更低。
- 只测到 `find_horizontal_border` 口径；`push_bottom_to_bar`（detect_borders 之后一步）没纳入对比。
- 模型在「救援之后」换峰，所以不替代规则；真要「删补丁」需要先把候选生成改成覆盖人线位置（含按墨条上沿/下沿的几何候选），这是另一条线，未做。
- 合并本分支会让 Step1 的代码指纹变（`peak_line_search` / `border_geometry` 在 `code_deps` 里），已有产物会显示过期——**内容逐字节不变**，重跑即可。我没有把新模块加进 `code_deps`。

## 可删常量清单

**无。** 模型在 `_rescue_bottom` 之后、`finalize_bottom` 之前介入，不替代 `secondary_*`、`WILD_ANGLE_*`、`RESCUE_*`、`EDGE_*`、`BOTTOM_SAFETY_MARGIN`、`BPUSH_*` 中任何一个。

## 开关用法

```yaml
# books/<book>.yaml
params:
  border_detect:
    bottom_peak_model: true
    # bottom_peak_model_path: /path/to/bottompeak_v1.joblib   # 缺省 models/bottompeak/bottompeak_v1.joblib
```
关着时三个字段不进参数 dump。**开着需要模型文件，仓库里没有**（文件缺失会在 Step1 报 `BottomPeakModelError`）。
硬护栏（模型外，`chooser.select`）：候选终点不得比现役靠上超 2px；不得靠下超 70px；概率须比现役高 0.10 且 ≥0.30；任何异常原样返回现役线。

## 关着时逐字节不变（实测）

沙箱（`-w` 指到临时工作区、`GUJI_PRODUCTS_DIR` 指沙箱，原图软链）。基线 = `git worktree` 的 `96344ddd23`（main），新 = 本分支：
`python -m open_guji_cv step border_detect vol02 --pages 10,46,70,79,155,26 --force -w <沙箱>`，`diff -rq` 两棵产物树（除 `_manifest`）**无差异**（border_detect 与 border_detect_gate 共 12 个文件）。

## 测试

`python -m pytest tests/ -s -p no:cacheprovider`：2535 过 / 1 败 / 27 跳。败的是 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`（`ckpt_fingerprint()` 在本沙箱返回空串），与本分支无关，**未在 main 上单独复核**。

## 复现

```bash
S=<沙箱>   # 含 ws/books/vol0{1,2,3}.yaml、ws/data_full/zongmu -> guji-workspace 的 data_full/zongmu
export GUJI_WORKSPACE=$S/ws GUJI_PRODUCTS_DIR=$S/products PYTHONIOENCODING=utf-8
python scripts/eval_bottom_offset_oneside.py                                   # 基线（152/187）
python scripts/experiments/bottom_peak/build_table.py --out $S/table.pkl       # 候选表，~4 分钟（4 核）
python scripts/experiments/bottom_peak/train_eval.py --table $S/table.pkl --label oneside --kind hgb
python scripts/experiments/bottom_peak/train_eval.py --table $S/table.pkl --label oneside --kind lr --drop paper_beyond,bar_len,up_ink   # 消融
python scripts/experiments/bottom_peak/train_eval.py ... --save-model models/bottompeak/bottompeak_v1.joblib   # 存模型（本次不交）
```

## 过程记录（给后人）

- `open-guji-dataset` 起先挂载被拒，用户放行后只读克隆（`../open-guji-dataset`）。在放行前我曾从 guji-workspace 的人裁结论按 `freeze_bottom_offset_gold.py` 的办法重建过冻结金标，**与官方 `frozen_absolute.jsonl` 处处不同（最大差 148px）**，已弃用，全部结果用官方冻结金标。
- 负担保里的「现行本来就对」页没有独立真墨基准，只做了「改没改」；若要按用户给的口径（真墨为基准）严格做，需要另造一份下框真墨标注。
