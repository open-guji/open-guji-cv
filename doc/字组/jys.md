# jys 己已巳（不同义）

## 字形差别
殿本 己 已 巳 基本同形（封口与否刻工不守），字形分不开。

## 怎么判
方法数组：`[ctx_rule → llm]`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核改字；弃权也降审；相邻成对 己巳；陪衬 巴
- 配置：`config/groups/jys/` 下 prompt.md rules.yaml

只按文意（sheldon 10-17：形近字组不看刻字像谁，一律按文意）。L1 规则含旧 `ji_yi_si_clf` 规则；弃权查 L2 haiku 表（只收 conf=high）。相邻两格都在组里给「己巳」（干支）。已放行的格没有文意证据也降审（`review_abstain`），复核时文意给别的字直接改字（`review_fix`）。巴 是库形陪衬。

## 试过的和负结果
首轮强真值 217 格：现行规则路 64% 给字全对；L1→L2（opus∧sonnet）95.9% 给字 1 错。改正金标后 L1→haiku 172/183 全对，Wilson 下界 0.978。Gemini 几乎不弃权、错的也标 high，不用。《總目》校对本里己已巳互讹严重（「巳著」744 次），不能拿它挖规则。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 153、文意 104、切线 0、部件 0，其中中心库 153；多来源 32 条，其中来源之间结论不同（被更正过）8 条。
- 数据集 `jys/items.jsonl`（A_human 186／B_vision 40／C_weak 31）；复审页 `review/jys_*`、`ctx_r1/r2`；中心库人裁刻形。按文意口径的更正在 cv `research/m7/ctx/l2_results/review_semantic_overrides.jsonl`。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 1379 格，放行率 83.5%，送审 227；进组流程 1359 格，组判率 83.9%；有人裁的已放行格 73，与人裁不一致 0。
- vol11–20 送审 191 格全是文意表缺（cache_miss）；v19 文意表能给 101 格，剩约 90 格表也弃权，已到天花板，不再投入。
