# HANDOFF Z-jys — 己已巳分类器离线评测（overview#443，父卡 #437）

分支：cv 与 dataset 均 `claude/Z-jys-1006`（基于 G1 分支）。**没改任何 Step 与 code_deps，没跑整册、没打包导入、没写事件/排除名单/字形库，没合 main、没开 PR。**

## 做了什么（cv `research/char_groups/jys/`，数据在 dataset `char-groups/jys/`）
1. `rules.py` 词组/搭配规则（不看字形、不看整理本）：前天干→巳、后地支→己（未/申/子等需日期语境）、自己/克己类、己意/以己見类、而已/業已/不得已/已經类→已。
2. `corpus_clf.py` 外部语料（daizhige，与《總目》无重叠）训练的前后 3 字搭配逻辑回归（语料内留出 81.9%，标签带噪）。
3. 大模型判文意：`llm_batches.py` 出盲判批次（只给前后各 30 字，不给整理本/字形/机器判断），PROMPT 与 schema 可原样交 muse。**muse 此容器没登录，用 sonnet 子代理代跑**（强真值 188 格两遍 + pool 规则弃权的 160 格一遍）；p1 第 1 批判官是写脚本手填的，p2 起逐条读判。
4. `cascade.py`（在 dev 上选策略，冻结后 val/vol05 一次性报）、`export_preds.py` → `classifier_preds.jsonl`、`classifier_eval.json`。

## 结果（强真值 A+B，按册；策略 S1＝规则 → 大模型∧语料分类器同字，否则弃权）
| 册 | 划分 | 格 | 给字率 | 给字准确率 | 弃权 |
|---|---|---|---|---|---|
| vol01 | extra | 12 | 92% | 11/11 | 8% |
| vol02 | dev | 54 | 91% | 48/49 | 9% |
| vol03 | dev | 48 | 96% | 46/46 | 4% |
| **vol04** | **val 留出（只看一次，没调参）** | 55 | 93% | **51/51** | 7% |
| vol05 | 人裁 19 | 19 | 100% | 18/19 | 0% |

对照：整理本错 26/46，库首位错 37/46，现行 `ji_yi_si` 规则 6/19，现行送审率 69–92%。单路：规则 dev 55/114 给、错 0（val 38/55、错 0）；大模型两遍一致 dev 99.1%、val 98.1%；语料分类器单用 0.9 阈 dev 82%/97.8%。
两个错例：`vol02:186:7:3`（人裁作「己」，读「多已見」更通，疑真值有误，请复核）；`vol05:36:6:15`「而【己】易」书名《己易》被「而已」规则误伤（该规则要加「后字」限制或交大模型）。
pool（vol05–10，420 格无真值）：给字 94%（规则 260、大模型+分类器同意 138）、弃权 22；**准确率未量**。

## 局限（别过度解读）
- 强真值多是机器拿不准才送审的难例，且样本小（188），val 51/51 的 95% 下界约 93%。真值里「巳」只有 18 格，「巳」的非干支用法没样本。
- 大模型是 sonnet 子代理、不是 muse；conf 字段不可靠（high 里仍有错），所以策略不看 conf，只看两遍一致 + 与分类器同意。pool 上大模型只有一遍。
- 规则在 dev 上看过错例后微调过一次（加「異」）；val 没有参与任何调整。

## 迁移建议（本卡不改 Step）
- Step6 加 jys 分类器，产物记 组名/字/把握（`rule`｜`llm+lr`｜弃权）；Step7 只当一路证据：规则路与「两路同意」路可放行，弃权送审，可把 jys 送审率从 69–92% 压到约 7%。
- 干支/时辰路沿用现 `_resolve_ji_yi_si`；「默认→已」「整理本路」「split_ref 放巳」应退役（整理本错 26/46）。N1 的 `ji_yi_si_ctx_rule` 表被「语料分类器+规则」取代（它的 vol04:40:4:6 错例在这里由「己未召試」交大模型判对）。
- 上线前需：① 大模型换 muse 或本地小模型，确认离线一致率；② 抽 pool 随机 ~60 格请用户/看图裁，量放行错率；③「而→已」规则加后字限制。

## 复现
```bash
python research/char_groups/jys/run_rules.py dev
python research/char_groups/jys/llm_batches.py <out> p1 20261006 47 ; ... p2 20261007 47 ; ... pool 20261008 50 --ids pool_ids.txt
python research/char_groups/jys/cascade.py <llm_dir> dev|val|vol05
python research/char_groups/jys/export_preds.py <llm_dir>
```
判官原始输出在 dataset `char-groups/jys/llm_judge/`。需要 `pip install scikit-learn`。
