# 全唐文借四庫库失效——查根因（overview#86，R 道，2026-09-27）

沙箱实验，**不改任何缺省行为**。结论与数字见 overview 仓
`项目进展/图片初步数字化/进度/inbox/R-全唐文借库失效/` 的 done 单。

## 数据

| 东西 | 来源 |
|---|---|
| 全唐文 v006–v010 产物 | guji-workspace `products-snap/qtw-v006-v010-full-20260927`，原图 `raw-snap/qtw-v006-v010-png`，搭成 `QTW_WS`（books/ corpus/ data_full/ products/） |
| 四庫 vol03 产物 | guji-workspace `products-snap/vol03-20260927` 的 `cloud-20260927-4e2e0b7-iron.tar.zst`，搭成 `SIKU_WS` |
| 四庫库 | 四庫工作区 `output/glyph_store` → `rebuild_from_store` 到沙箱 `GUJI_GLYPH_DB`（17166 例，全来自 vol01/vol02，**vol03 不在库里**） |
| 全唐文真值 | overview `新书整理/书/全唐文/人裁待导入/batch2-v2-partial.jsonl` + `batch3-v3-partial.jsonl`（用户簇级确认 + 手打字，2851 格，37 字）；AI 看图 `ai-vision-v1.jsonl` **不当真值** |

## 脚本（按顺序）

| 脚本 | 做什么 |
|---|---|
| `a1_score_dist.py` | 只读现成产物：两书判档、top-1/5、cov/wmax 分布 |
| `a2_extract.py` | 从原图 + 产物现场重建字块（`RunContext.image("char_patch")`），存 pickle |
| `metrics.py` | 笔粗（面积/骨架长、距离变换，可先中值去毛刺）与相对笔粗 |
| `a4_rematch.py` | 查询侧预处理变体 × 四庫库重比对（库侧不动）；含反向仿真 `sim_*` |
| `a5_cnn.py` | CNN r5 embedding 对四庫库**按字均值原型**检索（≠ 线上 5-b） |
| `a6_bootstrap.py` / `a6b_bootstrap_curve.py` | 自举：人裁格进库（每字 K 例），按页留出 / 换异源测试集 |
| `a7_summ.py` / `a5_summ.py` / `a9_cross.py` | 汇总与两路交叉 |
| `a8_review_data.py` + `build_review.py` + `review_page.tmpl.html` | 并排审查页 |

跑法（云端，`$SC` 为 scratchpad）：

```bash
export GUJI_GLYPH_DB=$SC/siku_glyph.db QTW_WS=/home/user/qtw-ws SIKU_WS=/home/user/siku-sb
GUJI_WORKSPACE=$QTW_WS  python a2_extract.py qtw_human  $SC/qtw_human.pkl    # ~10 min
GUJI_WORKSPACE=$QTW_WS  python a2_extract.py qtw_corpus $SC/qtw_corpus.pkl
GUJI_WORKSPACE=$SIKU_WS python a2_extract.py vol03      $SC/vol03.pkl
python a4_rematch.py $SC/qtw_human.pkl $SC/rm.jsonl base med5 down dil1 med_dil thick1 thick2 thick3
python a4_rematch.py $SC/vol03.pkl $SC/rm_v3.jsonl base sim_up sim_thin sim_speck sim_all
python a7_summ.py $SC/rm.jsonl
python a5_cnn.py $SC/qtw_human.pkl $SC/cnn.jsonl base && python a5_summ.py $SC/cnn.jsonl
python a6b_bootstrap_curve.py $SC/qtw_human.pkl $SC/qtw_corpus.pkl $SC/curve.json base [--holdout-human]
```

每次 match 约 0.06 s，重建字块约 0.4 s/块（首次要渲染列图）。
