# touching_cuts（粘连切点）金标迁移（M1 B 道，2026-09-30）

## 原金标
`char-segmentation/touching-cuts/items.jsonl` 共 1603 条：active 1599（vol01 789 / vol02 476 / bxgb 240 / vol03 94；verdict ok 672 · seam_ok 412 · cand 193 · overlap 178 · moved 147），
另 stale 2 / uncertain 1 / retired 1。y、polyline 记在 Step2 列图（射影矫正后）坐标里。

## 评测为什么「parse_metrics 0 条」
评测本身已是 v2 口径（读 `row_segment` cells + 列图缓存 + `eval/colgeom.py` 当前列窗几何），空跑只因沙箱没有这几册的产物：
vol01/vol02 正文页、vol03、bxgb（北行日錄，需 overlay 工作区）都缺 → 全部「缺产物」。补齐后能跑，无需改口径。
（顺带修了一个崩溃：59 条折线条目没有 `y`，`eval_touching_cuts.py` 取 `ex["y"]` KeyError，bxgb 一有产物评测就整个崩；缺 y 时取折线平均高。）

## 判据
**「人当时看的图」没有保存**：条目里只有 `col_h`、字符标签，控制台卡片裁片不落盘，也没有图像指纹。所以能认的只有：
- `page`：记了页面坐标 `page_x/page_y`（金标锚在原图上）→ 按**当前**列窗几何换算到现役列图（`colgeom.gold_rows_now`）——人看的是原图那一处，图还在；
- `sig_ok`：记了列窗签名且与当前一致（本集合里 0 条单独存在）；
- `legacy`：只有列图坐标 + col_h → **无法证明坐标系没漂**（`colgeom.py` 文档实测：vol02 一批漂了 20–50px 而 col_h 逐像素相等）。**不迁**。
**不以「y_old 与现役 Step3 格线吻合」当判据**（那是算法一致性，循环论证；评测里保留它只为向后兼容，且分档单独报）。

## 结果（`migrate_touching_cuts_v2.py`）
| 去向 | 条数 |
|---|---|
| 迁（page 口径，vol02 49 页） | **101** |
| legacy，无法验证（active 1599 − 101；按册 vol01 789 / bxgb 240 / vol03 94 / vol02 375） | **1498** |
| 非 active（stale 2 / uncertain 1 / retired 1） | 4，本就不进指标 |

合计 101 + 1498 + 4 = 1603；classification.json 里 tier=legacy 即这 1498 条。
legacy 的 1498 条**未标 stale**（没有证据证明它们错了，只是无法证明它们对）——由主会话决定：
(a) 保持现状，评测分档报（page / legacy 两行，本轮已做）；(b) 整批标 `stale/unverifiable`，只让 101 条进头条指标；(c) 重新人裁一批 page 口径金标。

## 文件
- `migrate_touching_cuts_v2.py`：分类 + 迁移（读沙箱 column_warp 产物算当前几何）。
- `classification.json`：每条的 tier / status / why。
- `items_v2.jsonl`：101 条迁移后的条目——expected.y / polyline 已换成现役列图坐标（原值留 `y_legacy_colimg`），`col_h` 改为当前列图高，加 `geom_sig`/页面坐标重新盖章，history 追加 `m1_migrate`。
- 评测改动：`scripts/eval_touching_cuts.py` 增加按 `page / sig_ok / legacy` 分档输出（整体行与原指标名保持不变）+ 缺 y 崩溃修复。
