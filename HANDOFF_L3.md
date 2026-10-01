# HANDOFF · L3 补标签两批（切线金标页面坐标 / 列端版框分档）

分支：cv `claude/L3-label-batches-1001`，dataset `claude/L3-label-batches-1001`（只新增 `char-segmentation/column-end-class` 分片 + touching-cuts README 追加说明）。
**没合 main，没写任何真实事件，没碰 products。** 手册：`.claude/doc/console_manual.md` §11。

## 给用户的本地操作（每批三步，在**本机**做）

> 前提：本机 cv 工作区有现行产物。A 批要 Step1→3（`row_segment/cells`），B 批要 Step1→2（`column_warp/column_windows`）；
> 没有就会清楚报错并告诉你先跑哪一步，**不会现算**。命令名是 `label-batch`（`review` 已被 v1 的 M6 审查占用）。
> 控制台地址 `http://127.0.0.1:8640/<工作区id>/<册>/step/…`。

### A 批 · 切线金标（页面坐标口径）
1. `git pull`（cv 切到 `claude/L3-label-batches-1001`；dataset 同名分支）
2. `guji label-batch make cutline-gold vol02 --n 200` → 打印批次 id（默认 `L3-cutline-vol02-<月日>`）
3. 控制台 `…/vol02/step/step3/` →「拖切线」→ **页码框填 `list:<批次id>`、批次框填同一个批次 id** → 载入，点卡（回车确认 / 拖线 / 拿不准）
4. 收割：`guji label-batch harvest <批次id> --dataset ../open-guji-dataset` → 写 `touching-cuts` 新条目（带页面坐标、`source=L3-batch`、权重）

### B 批 · 列端版框分档
1. `git pull`
2. `guji label-batch make column-end vol02 --n 240`（默认批次 id `L3-colend-vol02-<月日>`）
3. 控制台 `…/vol02/step/step1/` →「Step2 上下版框核校」tab → **页码框填 `batch:<批次id>`**（批次框留空即同名）→ 载入，每张点 无框 / 可整段削 / 粘字 / 双层框 / 拿不准
4. 收割：`guji label-batch harvest <批次id> --dataset ../open-guji-dataset` → 新分片 `column-end-class`

收割在**点卡那台机器**上做（事件在那台的 `feedback/events/<批次>.jsonl`）。

## 预计张数与耗时（⚠️ 估计，只在冻结样页上实测过，没在真书上跑过）

| 批 | 张数 | 出批次 | 点卡 |
|---|---|---|---|
| A 切线 | `--n 200`（总体够就是 200；每层至少 6 张，难度配额 hard40/mid35/easy25%）| 估 2~5 分钟（遍历全部正文页 Step3 产物 + 每页遮挡判据读原图；大头在遮挡判据）| 估 25~35 分钟（每张 8~10 秒，难例偏多）|
| B 列端 | `--n 240`（总体 = 正文列×2 端，远大于 240）| 估 1 分钟内（只读 240 张 `column_raw`）| 估 15~20 分钟（每张 4~5 秒，一图一键）|

用 `--n` 调；用 `--seed` 换一批；批次 id 撞了会报错不覆盖。

## 做了什么（对任务要求逐条）
- **A**：`review/label_batches.py::build_cutline_gold`。总体 = 现行 Step3 全部字–字切点（排除 blank / 小注 a·b / 已在金标）；
  层 = `上下文(jiazhu|tail|seal|body)|难度(hard|mid|easy)`，难度由 `escalate` / `dis_unet` / 候选数 / `agree` 判；每卡记
  `stratum`+`stratum_weight=N_h/n_h`，总体与各层抽样数存 `<批次>_sampling.json`。卡片走现成 cutline 卡（`list:<批次>` 通路，后端零改动）。
  锚：事件已带 D2 的 `anchor.product_key.fingerprint`、cutline 路径原有的 `geom_sig/page_x/page_y`（确认走到了）；收割时换成右上原点
  `page_x_tr = page_w-1-page_x`（`anchor.space=raw_page_px@top-right`）+ 出卡时冻结的上下格外接框 bbox + 出卡/点卡两个产物指纹（`input.fp_match`）。
- **B**：colborder 卡选项改为 `none/trim/glued/double/idk`；新增 `pages=batch:<id>` 回放冻结卡片（`/api/border-review/cards`）；
  卡图改看**削版框之前**的 `column_raw`（`src=raw`），**不显示算法分档**。按现行 `column_border_trim` 档位（a~e+层数后缀）× `triage end_class` 分层，
  hard 档（b/c/e、多层、glued/idk）配额 50%。分片 `column-end-class`，条目带 anchor bbox、`end_fingerprint`、产物指纹、权重。
- **旧事件映射**：`clean→trim`（旧 README 定义「有框墨且与首字有间隙」＝可整段削，同义）；`glued/none/idk` 同名；旧体系无 `double`，不猜。认不出计入 `unknown_class`。
- **旧 104 卡**：读到了（overview `项目进展/图片初步数字化/进度/inbox/S-列尾抽查页/20260927-verdicts.jsonl`），**74 个列端迁入**新分片（t 列尾 59 / h 列首 15，vol02，`source=legacy-overview`）。
  **但没有映射成类别**：旧卡问的是**削后状态**（clean/residual/cut），不是削前版框类别，无法无损映射 → `class` 一律 `idk`、`status=uncertain`、原值在
  `legacy_verdict`、附 `legacy_hint`。30 张 `l` 前缀末字块卡不是列端，未迁。→ 这 74 条**不能当标签用**，只是线索；B 批点出来的才是真标签。
- 前端 dist 已重建（`npm run build` 通过 tsc）。

## 需要你知道的偏差 / 决定
1. **命令名** `guji label-batch make|harvest|migrate-legacy`，不是 `guji review make-batch`（`review` 已被占）。
2. **L3 批的事件不自动消费**（`/api/events` 看到出批次冻结的卡片文件就跳过路由）：否则 cutline / glued / none 事件会进工作区裁决表并把 Step3/Step2 产物标 invalidated。收割只进 dataset。
3. **坐标口径提醒**：控制台现有切线事件的 `page_x/page_y` 是**左上原点**原图像素（`eval/colgeom.py`），和 `quad_page`（右上原点）不同系；新条目统一存右上原点并保留旧值，`touching-cuts` README 已写。
4. 两批都是**超采样**，条目带权重；**不要把它们和旧 touching-cuts 条目混着算均值**。
5. 冻结样页冒烟里发现并修了一个抽样 bug（档内缺口回填时地板重复计入、n_h 可超过 N_h），已补回归测试。

## 没做 / 待你
- **overview issue 评论**：未发（本会话没确认到那条新 issue 的编号），请你代贴本文件「本地操作」那一节。
- 未在真书上跑 `make`（云端无整册产物，也不该跑）；耗时是估计。
- 未处理的已知限制：A 批总体含 `seal` 层用的是定字入库闸的遮挡判据，遮挡判据读不到原图时该层为空，不报错。
- dataset 的 `.write.lock` 是本地杂物，未提交。

## 验收
- 新增 `tests/test_label_batches.py`（24 条：抽样/权重、类别映射、两批总体构造、两种收割、旧卡迁移、冻结样页 Step1→3 真产物出两批并收割）+ `tests/test_events_autoconsume.py` 一条；全量 `pytest tests/ -s`：2504 passed, 3 skipped, 5 deselected（0 失败）。
