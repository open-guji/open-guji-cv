# truncation（字身截断率）迁移（M1 B 道，2026-09-30）

## 性质
无监督指标，无金标点；基线 = `expected.json`。迁移 = 评测改读 v2 重算并重冻。

## 为什么 n=0
`scripts/eval_truncation.py` 读 v1 链 `output/<册>/phase3_char_grid` + 整页 png；云端没有 → `scan` 得 0 页；旧代码 `np.zeros(1)` 兜底，回归门对 0 比较「通过」。

## 改了什么
- 复用 `open_guji_cv/eval/v2cols.py`。
- `scripts/eval_truncation.py`：默认读 v2——单字墨段在 **Step2 列图** `content_x`±4 内取（`col_runs` 判据原样：RUN_INK 0.06 / RUN_MIN_H 14 / RUN_GAP 6 / 高度窗 0.45~1.35 格），
  格线 = `ColumnCells.boundaries`（含首尾），格高 = `period`；截断深度公式、DEPTH_T=0.10 主口径、EDGE_TOL、页级分布、回归门一字未改。`--v1` 保留旧读法。
  加了空跑闸（0 段 exit 2）。注册表 truncation 行去掉 `v1_output`。

## 新基线 = 新口径首个基线
旧值（`expected_v1_legacy.json`：单字段 32862、≥10% 393…，README「第三版」）仅作趋势对照。重冻命令同 seam，把脚本名换成 eval_truncation.py。

## 读数与警告
- 范围：294 正文页（vol01 108 + vol02 186）。
- **阳性对照**：vol01/60 格线平移 +20px，≥10% 截断 2/168 → 104/168；+40 → 155/168；+55 → 164/168。
- 沿用 README 的偏乐观警告：上下粘连成一坨（>1.35 格）的墨段被排除在「单字段」外，最脏的页上偏乐观。
- 单字段总数变大（32862 → 37698）：v2 链有更多 ok 列/更多可取段，分母不同，绝对条数不可与旧值直接比，看占比。
