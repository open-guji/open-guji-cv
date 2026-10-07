# R 补字道（#471 第 5 条）静态统计

`miss_stats.py`：读 `research/y1_admit/{gold,pending}_vol0{4,5}.jsonl`（金标 wrong 且有 char），
看「图上正字是否在库候选 top4」「与放行码位是否有 variants.json 异体边」「Jigmo/I.Ming 是否有该字」。
产出 `miss_cells.json`。**只是静态统计**：沙箱无工作区快照／glyph.db／torch，没跑 `guji exp` A/B，没有任何放行规则改动。

| 册 | gold wrong(有 char) | 正字不在库 top4 | 其中异体边 | 其中字体可补 |
|---|---|---|---|---|
| vol04 | 100 | 47 | 5 | 47 |
| vol05 | 55 | 21 | 4 | 21 |

其余 wrong（vol04 53／vol05 34）正字在库候选里但不是 top1：不是缺字，是排序／码位口径。
