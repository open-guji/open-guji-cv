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
