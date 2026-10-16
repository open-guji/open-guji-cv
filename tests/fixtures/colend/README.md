# tests/fixtures/colend —— 列端(Step2 上/下端版框)回归 fixture

冻结 vol02 的 **231 个列端**(dataset `char-segmentation/column-end-class`,`source=L3-batch` 的 B 批)与人判标签,
用来在整理 `column_border_trim` / `second_layer` 的阈值时有一把尺子。**默认不动**;要新形态就新加一份。

## 内容
- `cols/p<页>_c<列>.png`:**整列** `column_raw`(col 产物的原始矫正去噪列图)二值化后的 1-bit PNG,224 个唯一列,≈2.5 MB。
  为什么存整列:`clean_column` 里 `strip_column_rules` 等依赖整列统计。实测只存端部 300 行时重算与产物一致仅 216/231,
  整列 1-bit 重算 **231/231** 一致。
- `manifest.json`:`layers` / `layer_gap`(vol02 的 frame_layers / outer_gap)、每列的 `inner_bottom`(Step1 内框线在列内的位置)、
  每端 `{id, col_key, end, label, frozen_case, frozen_px}`。`frozen_*` 是**冻结时现行规则的输出**(cv main `2ee6068` +
  snap `snap/96mid1ogzk/vol02/20261009T2340`,cv `2356bec`),不是真值。

## 标签口径
`label` = dataset 人判:none / trim / double / glued。**本 fixture 的标签含 10-11 c 档 10 条 trim→none 的复核**
(dataset main `d7f732f`;Mila 抽查后 `32:1:bot` 保留 trim,端口有断续下框碎片;分布 trim 143/double 57/glued 18/none 13,共 231 端,不含另 9 条无引擎字段的覆盖条)。
评测口径(Mila 10-11):trim 与 double **互通**(任一都算对),"人眼难分"不当缺陷;glued ≈「框与首字零间隙」,规则按内框线补削(Xi)是对的。

## 怎么用
- `tests/test_colend_fixture.py`:只钉**完整性**和**行为**(冻结整列 → 现行 `clean_column` → 每端 `(档位, 削行数)` 与 `frozen_*` 一致)。
  它变红 = 列端行为变了:预期的就更新 `frozen_*`(重跑 `research/colend_eval/build_fixture.py`)并在 PR 写清哪些端变了、为什么;否则是回归。
- `research/colend_eval/eval_fixture.py`:质量口径的评测(矩阵、deep_cut 预警);**不进测试**(对真书数据的质量断言归评测)。
- 重建:`python3 -I research/colend_eval/build_fixture.py <dataset>/char-segmentation/column-end-class/items.jsonl tests/fixtures/colend`
  (需 `GUJI_WORKSPACE`/`GUJI_PRODUCTS_DIR` 指向含 vol02 原图+snap 产物的工作区)。

## 局限
只有 vol02(四庫全書總目,雙邊框、frame_layers=2/2)一本书;样本分层超采样,**比例不是全书率**;没有单边框册(如北行)、没有别的字体/版式。
别的册的列端要有标签后再加新的 fixture 目录。
