# cutline_eval:A 批 200 张切线金标 × 现行 Step3(row_segment)评测(#554,Esme,10-11)

**只评测+提案,没改 `open_guji_cv/steps/*`。** 数据:dataset 分支 `claude/A-cutline-vol02-1011-harvest` `5de7ff2`(`char-segmentation/touching-cuts`,`source=L3-batch` 200 条:196 active+4 uncertain);产物 snap `snap/96mid1ogzk/vol02/20261009T2340`(cv `2356bec`,与金标出卡指纹一致,`fp_match` 全真)。

## 复现
```
GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=… python3 -I research/cutline_eval/eval_cutlines.py <items.jsonl> --source L3-batch --book vol02 --out a_batch_report.json
python3 -I research/cutline_eval/valley_probe.py old_vol02_report.json old_vol02_valley.json    # 旧金标不一致条的"零墨走廊"探针
```

## 口径
- 现役切点 = `row_segment` 该列 `boundaries[slot_above]`(槽下标;含 raised/夹注的列槽下标会错一格,脚本按"离金标出卡时引擎切点 y_old 最近的现役边界"自动校正,4 条被校正:186:9:9、157:2:3、3:2:11、3:2:2)。金标 `y`、现役切点都在**现役列图行坐标**(核了 `col_h`)。
- A 批是**分层超采样**(层=上下文×难度,`stratum_weight`=层总体/抽样数,Σw=27,691≈vol02 全部切线数);**比例不是全书率**,以下"加权"仅作量级。

## 结果(A 批)
| | 条数 | 加权 |
|---|---|---|
| ok(|dy|≤3px;其中 193 条 `verdict=ok` 即用户认定现役切点就是理想位置) | 194 | 27,682 |
| 不一致 | 2 | 4.4 |
| uncertain(印章污点无字,不进指标) | 4 | 4.6 |
可比 196 条:|dy| 中位 0.0px、p90 0.0px。**按层**:body|easy 80/80、tail|easy 24/24、body|mid 45/45、seal|easy 10/10、jiazhu|easy 7/7 全 ok;tail|mid 14/15、body|hard 7/8、seal|mid 7/10(3 条 uncertain)。
两条不一致(图 `overlays/a_batch_nonok.png`,红=引擎,绿=金标):
1. `vol02:113:1:4`(老|莊,verdict=cand,金标 360 vs 引擎 400,差 40px):引擎在「莊」字上部切过去,把「莊」的顶部切进上格;**同时该列第 4 格只有 41px 高(period 113 的 0.36 倍),flags 为空——"矮格未报"**。
2. `vol02:129:8:20`(大|畜,moved,+4px):两条线都落在字缝里,几乎无影响。

## 成因分类与"批量改"结论
**A 批里没有可批量改的成因类**:196 条里只有 1 条真错(0.5%,上述矮格切进字)。为了不只看这一小批,我另用旧金标(vol02 老 touching-cuts 479 条,可比 305 条;按 `col_h` 剔除 112 条旧坐标)做了三个探针:
- **旧金标不一致条的"零墨走廊"探针**(`valley_probe.py`,101 条 |dy|>3):其中 **89 条金标与引擎都不在零墨走廊里**(真粘连,无谷可依,"理想位置"本身是判断,3–25px 的差多属人眼难分);同一走廊内仅 6 条。→ 不是"切在走廊边上"的系统问题。
- **朴素改法 1 失败**:把切点改到 ±8/15/25px 窗内行墨最小处——不一致条数 101→122/126/133(变好 11、变差 29–47)。
- **朴素改法 2 失败**:整体下移 δ 像素(旧金标 cand 类金标偏下 47 对偏上 16,看起来有系统偏)——δ=2 合计 200/305(基线 204),δ≥4 骤降;**没有常数偏移**。
- **全书矮格扫描**:vol02 29,916 个字格里,高<0.6×period 且 flags 为空、非 raised/sub 的只有 **3 个**(15:9 slot20 37px、113:1 slot4 41px、188:4 slot20 39px)——113:1:4 正是 A 批那条真错。

## 提案(不实现)
| # | 修什么 | 预计改善 | 风险/爆炸半径 |
|---|---|---|---|
| 1 | **不改 Step3 切线算法**:A 批 194/196 与金标一致,朴素改法都变差。 | — | — |
| 2 | **矮格预警(只在评测/gate 外挂)**:字格高<0.6×period 且无 flag 的 → 送审/记数。vol02 仅 3 格,含 A 批唯一真错。 | vol02 圈出 3 格(1 个已确认伤字);成本≈0 | 若进 `row_segment`/gate 的 triage 会让 row_segment 起产物过期;先放评测脚本,等下个有改动的窗口并入 |
| 3 | **Step3 回归 fixture**:把 A 批 196 条+旧金标可比条冻结(列图+现役切点+金标),仿 `tests/fixtures/colend`,之后改 `row_segment`/U-Net judge 阈值有尺子。 | 之后才敢改 Step3 | 零引擎风险(只加 fixture/测试) |
| 4 | 现役 U-Net judge(`cut_select.py`)在"cand 多候选、无谷"线上与人眼差 3–25px:**需要更多"该切哪"的金标**(含"人眼难分"标记)才能谈学习排序;A 批的 `ok` 太多(分层是按引擎难度抽的,仍 97% ok),说明难例在 A 批没抽够。建议下一批只抽 `cand`+无零墨走廊的线。 | 才有可批量改的类 | 只花人审(约 15 分钟/批) |
