# seam（切缝墨率）迁移（M1 B 道，2026-09-30）

## 性质
无监督指标，无金标点；「金标」= `expected.json` 冻结的基线 + 回归门。迁移 = **评测改读 v2 产物重算并重冻基线**。

## 为什么空跑
`scripts/eval_seam.py` 读 v1 链 `output/<册>/phase3_char_grid/<页>_char_grid.json` + `output/<册>/<页>.png`，云端没有 → 静默扫到 0 页 →「✓ 0%」假通过。
E 道已在注册表加 `v1_output` 前提挡住（skipped）。

## 改了什么
- `open_guji_cv/eval/v2cols.py`（新）：`body_pages()`（page-type 金标 body 页）、`iter_columns()`（row_segment cells + Step2 列图缓存）。
- `scripts/eval_seam.py`：默认改读 v2——格线 = `row_segment` 的直线格线（`CellRec.y1`，相邻 char 格才算），列窗 = `content_x`±2，周期 = `ColumnCells.period`，
  列图 = cache `column_image`；**切缝墨率公式 / 0.7 门槛 / BASE_FLOOR / 页级分布 / 回归门一字未改**。`--v1` 保留旧读法。
  加了空跑闸：一条切缝都没读到就 exit 2，不写基线、不判回归。
- 注册表 seam 行 needs 去掉 `v1_output`。

## 新基线 = 「新口径首个基线」，不与旧值同口径可比
v1 是 deshear 整页 + `grid_strict` 格线；v2 是射影列图 + `row_segment`。旧值（`expected_v1_legacy.json`，2026-08 冻结）只作趋势对照。
重冻：`PYTHONPATH=. python scripts/eval_seam.py ../open-guji-dataset/char-segmentation --update`（需沙箱 env + vol01/vol02 正文页 row_segment 产物）。

## 读数与警告
- 范围：vol01 108 + vol02 186 = 294 正文页（与旧值同页集），沙箱跑全。
- **阳性对照（证明它在 v2 上不是哑的）**：把 vol01/60 的全部格线人为平移 +20px，重切缝 0/171 → 100/171；+40 → 94/171；+55 → 92/171。
- **仍不能证明 Step3 吸附/DP 本身是对的**（README 原警告）：v2 格线本来就是 DP 落进墨谷，这个指标量的正是它优化的目标，只能当「守住」的闸。
- 只看直线格线，不看 `seam_bottom` 折线缝（实际切法）——真粘连处的缝另由 touching_cuts 的折线金标 / R2c 管。
