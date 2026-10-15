# tests/fixtures/cutline —— Step3 切线回归 fixture

冻结 vol02 的 **A 批 196 条切线金标**(dataset 分支 `claude/A-cutline-vol02-1011-harvest` `5de7ff2`,`touching-cuts` 分片 `source=L3-batch`,
196 active;4 条 uncertain〔印章污点无字〕不收)涉及的 **178 个列**的 `column_image`(Step3 `segment_column` 的输入,1-bit PNG,≈2.2 MB),
外加 3 个"矮格"所在列(vol02 15:9 slot20、113:1 slot4、188:4 slot20)。**默认不动**;要新形态就新加一份。

## 内容
- `cols/p<页>_c<列>.png`:清理后列图(`column_image`)二值化。
- `manifest.json`:
  - `columns[p<页>_c<列>]`:`segment_kwargs`(period/n_body_slots/n_raised/border_*/ref_w/top_slack/content_x,取自 snap `row_segment` 产物)、`run_kwargs`(RowSegmentParams 的缺省)、
    `frozen_boundaries`(**现役** Step3〔U-Net 裁判〕产物里的 boundaries)、`frozen_rule_boundaries`(`cut_judge=None` 现算的 rule-only,**无 torch 也能复现**);
  - `gold[]`:`{id,page,col,slot_above,y_gold,verdict,stratum,w,y_frozen}`;`y_frozen` = 现役切点(抬头列按 `pos=slot+n_raised` 取);`w` = `stratum_weight`;
  - `runt_cells`:3 个矮格。
- 冻结基线:cv main `28a500f`,snap `snap/96mid1ogzk/vol02/20261009T2340`(cv `2356bec`)。

## 怎么用
- `tests/test_cutline_fixture.py`:钉**完整性**与 **rule-only 行为**(冻结列图 → 现行 `segment_column(cut_judge=None)` → boundaries 逐点 ≤0.5px 一致)。
  变红 = Step3 规则路径行为变了:预期的就重跑 `research/cutline_eval/build_fixture_cuts.py` 更新冻结值并在 PR 写清;否则是回归。
  已做变异验证:`INK_LAM` 0.8→0.4 变红(已还原)。
- **U-Net 裁判路径(现役)不在测试里钉**:要 torch 与权重。有环境时用 `research/cutline_eval/eval_cutlines.py` 对账(金标 vs 现役切点)。
- 质量评测(不进测试):`eval_cutlines.py`(金标对账)、`runt_cells.py`(矮格预警,外挂)。

## 局限
只有 vol02;A 批是按引擎难度分层的超采样(97% ok,难例没抽够),**不报全书率**;金标的 `ok` 是"用户认定现役切点就是理想位置",所以本 fixture 更像"别退化"的守卫,不是"哪里还能改"的探针。
