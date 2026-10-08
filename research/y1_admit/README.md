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

## Step6 形近／字组分类器接线：可行性与回放（overview#471，2026-10-08，只读 research/，未改 steps/）

脚本 `step6_sim.py`（输出 `step6_sim_vol0{4,5}.json`），回放口径＝cv main 80370fd366＋沙箱重放 `juan_rule`＋`variant_tie`（6 组表、cov 0.97），待审 vol04 469、vol05 314。金标＝gold2。

**1. 待审格按「形近／异体组」成因分**

| 类 | vol04 | vol05 | 说明 |
|---|---:|---:|---|
| 组表字，却没放（`covered`） | 15 | 7 | top1 在 6 组里，被 `库 unsure`＋`上下文 margin 不足`／`ctx_guard_ref` 的 doubts 挡在 `variant_tie` 的「doubts 只许 replace_align／context_vs_ref」之外。有金标的 14／6 格，**金标字＝库 top1 全对** |
| 组外 variant／near 对（`variant`/`near`，不含己已巳、卷巻） | 42 | 49 | 土士、決决、繫繋、涉渉、顛顚、官宮…；有金标 21／23 格，库 top1 对 8／14（38%／61%），整理本字对 12／8，上下文首位对 11／12 |
| 卷巻（juan_rule 残余） | 0 | 19 | 5 格 cov≥0.98 仍待审，余下 cov<0.98 或前字不是数字 |
| 己已巳（#437 另做） | 32 | 38 | 不在本题 |
| 非字组关系（库里没有／乱码 137／66、margin 不足 96／64、印章 44／15 …） | 380 | 225 | 分类器管不着，只能人审或另有专项 |

**2. 结论：现在不值得做 Step6 分类器，也不需要新字段**
- Step7 手里已有三路独立证据——库候选＋cov（Step5）、上下文首位与 margin（Step6 `context_decide.ranked`）、整理本字（对位／坐标）。「打包成一条字段」没有新信息。
- 组外 variant／near 里，库首位对错约五五开，上下文与库同走语义空间，**分不出同义异体两个码位**（top==ctx 放的 12／16 格里只对 6／10）；三票多数放行会错 6／17（vol04）。唯一干净的是「整理本字＝上下文首位」：vol04 5／5 对，vol05 1／2（貎／貌 错），总共才 9 格，不值得开通道。
- 真要分码位要靠字形本身：pair 级训练样本（confusable-context 154 题字形层只有 0.643，glyph_match_stack.md）不够。这块要先补 Step5 的组内样例，不属接线。

**3. 能做的最小方案：只动 Step7，一个默认关的开关（需点头才写）**
`variant_tie_margin`：组表字（`variant_tie_extra`）、cov ≥ 0.96、top-3 近邻 gap<0.03 的都在组内、无护栏、无 `ctx_garble*`，**放宽 doubts 白名单到 `库 unsure`／`上下文 margin 不足`／`ctx_guard_ref`／replace_align／context_vs_ref**，放 top1。
- 预计放行：vol04 约 +13（469→~456），vol05 约 +5（314→~309）；cov<0.96 的（vol04:199:4:4 0.939、vol05:37:8:20 0.946）与 `ctx_garble_rare` 不放。
- 金标误放行预测：0（有金标的 20 格全是 top1 对）；无金标的 2 格被 cov 门槛挡掉。上下文首位与 top1 不同的 5 格（如 13:7:17 議、63:2:17 載、85:5:14 𤋰、123:2:20 𧞬、187:2:19 蒙）金标仍是 top1，说明上下文在这几组上是噪声，不应让它否决。
- 改动文件：`open_guji_cv/steps/seed_admit.py`（开关＋判断）、一条 `doc/exp/*.yaml` A/B、测试。**指纹**：只有 seed_admit 步判过期（及其下游），不碰 Step5/Step6，context_decide 产物不变。㫖 组仍不进表。
- 若要把「分类器」做成 Step6 字段：会改 `context_decide`，则 context_decide、seed_admit 及下游全部过期，收益 ≈0（见 2），不建议。
