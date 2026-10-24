# di 扺抵（同义）

## 字形差别
扺 抵：右部 氏／氐（下面一点）。

## 怎么判
方法数组：`composite(crop(0.0, 0.75, 0.5, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/di/` 下 ids_bank.json
- 模板库：扺10／抵90（dataset char-groups labels/unified.jsonl（kind=shape、status=ok，sheldon 人裁刻形））

取框 HOG（左下到右下）。次形 扺 留人审。

## 试过的和负结果
门槛 0.55 → 78／100（扺 0）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 102、文意 0、切线 0、部件 0，其中中心库 85；多来源 83 条，其中来源之间结论不同（被更正过）1 条。
- `variant/di/labels.jsonl`（抵 90／扺 10）。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 196 格，放行率 98.5%，送审 3；进组流程 0 格，组判率 —；有人裁的已放行格 18，与人裁不一致 0。
- 维持。
