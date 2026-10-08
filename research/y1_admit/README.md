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

## 字组裁决（10-07，用户在字组页点完）与 variant_tie 按组收窄
`group_verdicts.tsv`：12 组里 7 组「刻形＝系统码位」（𫎇蒙、㸃點、㕘參、䜟讖識、𨽾隸、慎愼、㫖旨）、3 组「刻形＝正字」（顛顚、厯歷、水氷：库码位误挂，交 H 道）、
2 组拿不准（𢑴彝異、官宮：样例含不同字形）。`apply_group_verdicts.py` 把整理看图在那 7 组上的「图是正字」改记对，出 `gold2_vol0X.jsonl`。
`variant_tie_extra` 给了组表就只认组表。A/B（`doc/exp/variant_tie_groups-vol04-vol05.yaml`，cov 0.95／0.97 结果相同）：
新增放行 31（vol04 22、vol05 9）：27 个看图 ok、3 个 wrong（全是 㫖→首／肯，整理看图高置信）、1 个 unsure。**去掉 㫖 组后 27 放行、0 放错**：
vol04 待审 487→469，vol05 348→339（−27），金标新增放行错 0。㫖 组在 `variant_tie_extra` 里不要列。

## 去章（overview#471，2026-10-08）：seal_lib_agree

印章遮挡待审 59 格（vol04 44、vol05 15），`lane_seal` 已放掉其余 334 格。剩下的成因：
卷端题列整列拦 26（vol04 p3 13、vol05 p3 13）；整理本坐标对位缺失 `via=none` 24（vol04 p130 第 1、5 列）；`via=align` 8（p130）；异体护栏拦 4（類/𩔖、亭、鬱、㫖）；其余 coord_blank 在题列。
新开关 `seal_lib_agree`（缺省关，需同开 `lane_seal`）：默认字与库首位同字且 cov≥0.9 → 放行（题列、`via=align` 也认）。vol04 487→476（+11：p3 题列 3、p130 align 8），vol05 348→345（+3，p3 题列）；14 格人工看图全对，金标不含这些格，金标误放行 0（无检验力，已如实标注）。
