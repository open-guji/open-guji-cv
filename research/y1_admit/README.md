# Y1（overview#454）Step7 放行规则批量优化：重放与结论

沙箱重放（不碰正式 products）：快照 `snap/96mid1ogzk/vol05/20261006T2008`、`vol04/20261006T1208`
解到 `<S>/prod/products`；`glyph-db rebuild` 出库；`GUJI_PRODUCTS_DIR=<S>/pv_x python -m open_guji_cv step seed_admit <book>
-w <ws> --pages all --force --params '{"seed_admit":{"patch_missing":"skip","use_human_verdicts":false, ...开关}}'`。
基线是 main（含 R2 三通道）上的重放，vol05 放行 28628（快照 28617）；人裁关着。

| 规则 | 开关 | vol05 | vol04 |
|---|---|---|---|
| 数字＋卷 | `juan_rule` | +25 放行，全是「卷」；看图结论零命中 | 无（vol04 的 15 格冲突不是卷） |
| 非字过滤 | `nonchar_gate` | 0 格变化 | 33 格放行→待审；有看图结论的 3 格全是放行错，0 格看图 ok；已知放行错 20→17，看图 ok 236→236 |

第 2（margin／库 unsure）、第 3（对齐改字）条**不能标定**：看图结论只覆盖已放行格，待审的 margin 不足／仅库 unsure／
对齐改字没有任何标注样本；已放行里 lib-only 的最低 cov 是 0.99（match_solo 闸），0.93–0.986 区间无样本。
`pending_vol0{4,5}.jsonl` 是待标清单（带证据特征，`label` 留空），看图回填后再标定。

## 待标清单看图回填（labels_vol0{4,5}.jsonl）
`labels_vol04.jsonl`（186 格）、`labels_vol05.jsonl`（134 格）：逐格看原图（原图＋`cell_shrink.bbox_page`，x 轴换算 `W−x`，带上下各一格上下文）的结论，
judge=claude-sonnet-5-5，ts=2026-10-07。**这是看图标注，不是人裁**，不进字形库／裁决表。
（注：清单里 pending_vol04 实为 186 格、pending_vol05 为 134 格，与卡面口径相反。）

键：`cell` 格号；`cls` 待审成因类；`shown` 系统建议字＝库首选（`lib_top[0]`）；`ref` 整理本字（无则 null）；
`char` 看图认的字（认不出为 null）；`v`：`ok`＝char 等于 shown，`wrong`＝char 不等于 shown（含异体字形之别，见 note），`unsure`＝认不出；
`conf`：high／mid／low（low 只配 unsure）；`agree_ref`：char 是否等于整理本字（无整理本为 null）；`note` 依据。
口径：mid 里大量是异体之别（蒙/𫎇、彝/𢑴、槪/慨、點/㸃、别/別、叙/敘、參/叅 等），库首选与 char 是同字异形，标定阈值时宜按「同字」处理而不是真错。
`unsure` 含：版框／界行／鱼尾墨迹无字、框切偏只剩半字、夹注窄列认不出、污损；这类格不是 ok／wrong 样本，不要拿去标定。
