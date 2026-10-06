# HANDOFF · B 道（Step3 row_segment 层评测）：row_boundaries / touching_cuts / seam / truncation

2026-09-30，分支 claude/M1-gold-seg-0930。沙箱：GUJI_WORKSPACE=overlay（四庫 vol01/vol02 + bxgb），产物=`/home/user/sandbox/products`（全组共享），
范围：vol01/vol02 全部 294 正文页 Step1→row_segment 齐全（vol01 149 页 / vol02 186 页有 row_segment，另含别道补的页）；bxgb 与 vol03 的金标页 row_segment 齐全（touching_cuts 金标页 53 + 11 页）。
通用命令前缀：`source /home/user/sandbox/env.sh`；注册表一把跑：`python -m open_guji_cv eval --from-raw --timeout 3000 run row_boundaries seam truncation touching_cuts`
（实测 4 个全部 ✓，通过 4 / 回归门失败 0 / 跑不起来 0）。
代码改动清单见文末。**没有 git commit；测试集仓的改动见文末「要提交到测试集仓的文件」。**

---
## 1. row_boundaries

### 空跑原因
`对齐相关只有 -2.00`：-2.00 是 `best_map` 初值，不是相关系数——现役 cells 里没有一列读得到列图（cache `column_image` 不存在），`best_col is None`，
而报错文案照旧打 `corr`。补齐 row_segment + 列图后暴露真问题：
(1) vol01/33 九列对齐相关全 <0.9（0.39~0.86）→ 全跳过；(2) vol02/135 样本**没存 row_proj**，旧评测走「金标格线当梳齿」——拿金标点找谷，对周期信号有一格歧义，不是图像指纹。

### 迁移结果
18 列（2 页 × 9）→ 迁 **5**（vol01/33 金标列 0/3/4/6/7 → 现役列 9/6/5/3/2，指纹相关 0.907/0.982/0.955/0.981/0.955），失效 **13**：
vol01/33 列 1/5/8（相关 0.80/0.83/0.83 <0.9）、列 2（最优贴搜索边、尺度漂出来的假高相关）；vol02/135 九列全失效（无 row_proj、原图 noenh_out 已不在，无图像指纹）。
判据=图像指纹（金标附带的当时列图行墨曲线 vs 现役列图，平滑+文字带、贴边闸、周期歧义闸、认列唯一闸）；详见 `row_boundaries/MIGRATION.md`。

### 新基线（沙箱：vol01/33 的 5 列，n=110 格线点，其中内部 101）
命令：`python scripts/eval_row_boundaries.py`（读 `migrated_v2.json`）
- 全部格线 n=110：mean 8.6 / median 3.0 / p90 25.8 / max 52.8；≤3px 50.0% ≤5px 60.9% ≤10px 82.7%
- 内部格线 n=101：mean 7.8 / median 3.0 / p90 21.2；≤3px 52.5% ≤5px 64.4% ≤10px 85.1%；R2s 粘连 n=0（全是非粘连）

### 与 doc 上次值对照
- 上次（你给的）：n=198，≤3px 30.3% / ≤5px 48% / ≤10px 67.7%。**我用 `--realign`（旧的现场互相关路径）在当前产物上精确复现了这组数**：
  `python scripts/eval_row_boundaries.py --realign` → 全部格线 n=198，mean 11.1 / median 5.5 / p90 32.2，≤3px 30.3% ≤5px 48.0% ≤10px 67.7%。那 198 点**全部来自 vol02/135**（vol01/33 九列全被 <0.9 跳过）。
- doc 出处 `doc/design/step3_touching_and_jiazhu.md` §3.5：内部格线（两页）n=221、中位 5.6px、p90 27px、≤3px 28.5%、≤10px 67%（2026-09 初，当时 vol01/33 还有 2 列通过）。
- 变化性质：**口径变化，不是真变化**。新基线只含 vol01/33 的 5 个指纹核实列，vol02/135 整页因无指纹退出；两者不在同一页集上，不可比。
  新数字偏好（≤3px 50%）部分原因是 README 已警告的：vol01/33 里有列的金标是旧算法产物当种子、人工没动过（误差恰为 0）；另一方面列 3 尾段误差到 ~45px，可能含线性映射的误差。
  趋势用途请看 `--realign` 那组（n=198，与上次同口径），它现在是 30.3/48.0/67.7 = 与上次完全一致（Step3 这段没变）。

### 仍跑不了的原因
vol02/135 没有图像指纹，无法证明「人看的图还在」。要恢复这页：需要在现役 v2 坐标系**重标一页**（约 9 列 × 22 点），或在控制台切线页补 page 口径金标。

---
## 2. touching_cuts

### 空跑原因
评测本身已是 v2 口径（读 row_segment + 列图缓存 + colgeom 当前列窗几何），`parse_metrics 0 条` 只因沙箱缺 vol01/vol02/vol03/bxgb 产物。补齐后能跑。
另修一个崩溃：59 条折线条目没有 `y`，bxgb 有产物后 `eval_touching_cuts.py` 在 `ex["y"]` KeyError 整个崩。

### 迁移结果
active 1599 条：**迁 101**（有页面坐标 `page_x/page_y` 的 vol02 条目，按当前列窗几何换算，49 页）；**legacy 无法验证 1498**（vol01 789 / bxgb 240 / vol03 94 / vol02 375）——
只记列图坐标 + col_h，当时列窗几何没留档，控制台人裁裁片不落盘，无图像指纹；`colgeom.py` 文档自己实测过 col_h 相同但坐标漂 20–50px。**不迁、不硬造；但也没标 stale**（无证据证明它们错）。
不以「y_old 与现役格线吻合」当判据（循环论证）。详见 `touching_cuts/MIGRATION.md`、`classification.json`、`items_v2.jsonl`。

### 新基线（沙箱：vol01/vol02/vol03/bxgb 全部金标页）
命令：`python scripts/eval_touching_cuts.py`（或注册表 `eval … run touching_cuts`）
- 直线（moved+ok）**n=553**（moved 98 / ok 455；overlap 另计 177，缝正确 412，干扰另计 15，漂移跳过 192，列尾另计 1）：mean 3.9 / median 0.3 / p90 12.2 / max 116；≤3px 78.5% ≤5px 83.9% ≤10px 89.3%
- 分档：`page`（可信）n=90：mean 7.1 / median 0.0 / p90 36.8；≤3px 72.2% ≤10px 78.9%　|　`legacy`（无法验证）n=463：mean 3.3 / median 0.5 / p90 8.9；≤3px 79.7% ≤10px 91.4%
- 分册：vol01 n=201 mean 2.8；vol02 n=203 mean 3.9；bxgb n=144 mean 5.5 / ≤3px 65.3%；vol03 n=5
- 折线 n=776（现役有缝 637）：最大偏差 mean 14.0 / median 7.0 / p90 32.0；≤3px 38.4% ≤6px 47.6%；其中 page 档 n=11：median 14.0、≤6px 36.4%；legacy n=765：median 7.0、≤6px 47.7%

### 与 doc 上次值对照
- 上次（你给的 E 道基线）：n=727，mean 7.4 / median 1 / p90 23px。我这次 n=553、mean 3.9 / median 0.3 / p90 12.2——**n 与均值都不可比**：我没法复现 727（不知 E 道当时产物/页集；我的「漂移跳过 192」由 legacy 条目对**当前**格线的 anchor 复核决定，随产物版本变），不要据此说「变好了」。
- doc `step3_touching_and_jiazhu.md` §1.4：直线金标（124 条最近格线口径）mean 1.0 / p90 2.0 / ≤3px 94.4% / ≤10px 98.4%（2026-09-05/06）；§1.4.3：直线 ≤3px 90.5%/p90 3px（262 条）；折线最大偏差 median 2 / p90 4 / ≤3px 88.7% / ≤6px 96.1%（231 条）。
- 解释：折线金标 ≤6px 96.1% → 现在 47.6%，**主要是口径问题**：折线分支在评测里**不做 anchor 复核**，legacy 折线（765 条）按老坐标直接比，Step2 几何漂移后大偏差是坐标对不上，不是切缝变差；
  可信的 page 档折线 n=11 只有 11 条、median 14，太小不能下结论。直线 ≤3px 78.5% vs 94.4% 也是样本集不同（现在含 vol02 page 档 90 条 + bxgb 144 条，这两类都更难，page 档 ≤3px 72.2%）。
  page 档里 >10px 的 19 条大多是 `ok` 且发生在列首/列尾格线（bi=1/2/20/21），金标是人认可过的旧切点，现役切点已移 30–50px ——可能是 row_segment 1.12 / 抬头格 / 列端处理改动的**真变化**，值得排查（ids：vol02:55:8:1、59:5:1、28:8:12/11、23:9:20、17:5:20、188:4:20、119:8:20、15:9:19 …）。

### 仍跑不了的原因
legacy 1498 条无法验证坐标系，只能分档报。要把头条指标变可信：重新人裁一批 page 口径金标（控制台切线页，新条目自动带 geom_sig/页面坐标）。

---
## 3. seam（切缝墨率）

### 空跑原因
脚本读 v1 链 `output/<册>/phase3_char_grid` + `output/<册>/<页>.png`（已退役），云端没有 → 0 页 →「✓ 0%」假通过。

### 迁移结果
无金标点（无监督）。迁移 = 评测改读 v2：格线=row_segment 直线格线（相邻 char 格），列图=Step2 `column_image`，指标公式/0.7 门槛/页级分布/回归门一字未改；`--v1` 保留旧路径；加空跑闸（读不到任何缝 exit 2）。
基线 `expected.json` 按 v2 重冻（旧值存 `expected_v1_legacy.json`），**是「新口径首个基线」**。详见 `seam/MIGRATION.md`。

### 新基线（沙箱：294 正文页全）
命令：`PYTHONPATH=. python scripts/eval_seam.py ../open-guji-dataset/char-segmentation`（冻结用 `--update`；注册表 `eval … run seam`）
- 切缝 44287，重切缝（≥0.7）**7**，中位 0.0118，p90 0.148；页级：中位 0 / p90 0 / p99 0.0062；≥5% 的页 0 / ≥10% 0；最差 vol02/108 2/149、vol02/179 2/162、vol02/180 1/140。
- 阳性对照：vol01/60 格线平移 +20px → 重切缝 0/171 → 100/171（指标不哑）。

### 与 doc 上次值对照
出处 `open-guji-dataset/char-segmentation/seam/expected.json`（v1，2026-08-26）：切缝 44627，重切缝 **179**，中位 0.0388，p90 0.1769；页级 p99 0.1211；≥5% 页 10、≥10% 页 5；最差 vol02/135 26/163、vol02/108 22/143、vol01/87 18/117。
**口径变化为主**：v1 是 deshear 整页 + grid_strict 格线，v2 是射影列图 + row_segment DP 格线；重切缝 179 → 7 不能全算「修好了」，但 vol02/135 这类页 26/163 → 0/162 与 Step3 重写方向一致。
警告（README 原话仍成立）：该指标量的正是格线 DP 优化的目标，只能当「守住」的闸，不能证明 Step3 本身对；且只看直线格线、不看折线缝。

### 仍跑不了的原因
无（可跑）。

---
## 4. truncation（字身截断率）

### 空跑原因
同 seam：读 v1 `output/…`，云端没有 → n=0；旧代码 `np.zeros(1)` 兜底，回归门对 0 判「通过」。

### 迁移结果
无金标点。评测改读 v2（Step2 列图 + row_segment `boundaries`），判据/深度公式/≥10% 主口径/页级分布/回归门一字未改；`--v1` 保留；加空跑闸。基线按 v2 重冻（旧值 `expected_v1_legacy.json`），**新口径首个基线**。详见 `truncation/MIGRATION.md`。

### 新基线（沙箱：294 正文页全）
命令：`PYTHONPATH=. python scripts/eval_truncation.py ../open-guji-dataset/char-segmentation`
- 单字段 37698；切进 ≥5% 139（0.37%）、**≥10%（主口径）133（0.35%）**、≥20% 84（0.22%）、≥30% 27（0.07%）；页级：中位 0 / p90 0.0113 / p99 0.04；≥10% 的页 0、≥25% 0、≥50% 0；最差 vol02/188 4/82、vol02/179 3/70、vol02/182 3/74。
- 阳性对照：vol01/60 格线平移 +20px → ≥10% 截断 2/168 → 104/168。

### 与 doc 上次值对照
出处 `char-segmentation/truncation/README.md`「第三版」与 `expected_v1_legacy.json`：单字段 32862；≥5% 544、**≥10% 393（1.20%）**、≥20% 234、≥30% 100；页级 中位 0 / p90 2.9% / p99 30.3%；≥10% 页 13、≥25% 8；最差 vol02/135 37%、vol02/108 32%。
**口径变化为主**（v1→v2 输入换了，分母 32862 → 37698 也变）；占比 1.20% → 0.35%、重灾页（30% 级）消失，方向与 Step3 重写一致，但不能拆出「真修好多少」。
警告沿用：上下粘连成一坨（>1.35 格）的墨段不进「单字段」，最脏页上偏乐观。

### 仍跑不了的原因
无（可跑）。

---
## 代码/文件改动清单（引擎仓）
- 新：`open_guji_cv/eval/v2cols.py`
- 改：`scripts/eval_seam.py`、`scripts/eval_truncation.py`（读 v2 + `--v1` + 空跑闸）；`scripts/eval_row_boundaries.py`（读 migrated_v2.json、`--realign`、-2.00 文案修正）；`scripts/eval_touching_cuts.py`（分档输出、缺 y 崩溃修复）
- 改（仅自己那几行）：`open_guji_cv/eval/registry.py`——seam / truncation 的 needs 去掉 `v1_output`；row_boundaries 的 note。
- 新：`artifacts/m1_gold/{row_boundaries,touching_cuts,seam,truncation}/`（MIGRATION.md、迁移脚本、迁移后分片、baseline_run.txt）

## 要提交到测试集仓 open-guji-dataset 的文件（云端无 push 权限）
- `char-segmentation/row-boundaries/migrated_v2.json`（= artifacts/m1_gold/row_boundaries/migrated_v2.json）
- `char-segmentation/seam/expected.json`（v2 新基线）+ `expected_v1_legacy.json`
- `char-segmentation/truncation/expected.json`（v2 新基线）+ `expected_v1_legacy.json`
- touching-cuts：**未改 items.jsonl**（你决定 legacy 1498 条怎么处置，见 MIGRATION；`items_v2.jsonl` 是 101 条迁移后条目，仅供参考/替换用）。
