# shan 刪删（同义）

## 字形差别
刪 删：左下 冊／册 的下半。

## 怎么判
方法数组：`composite(crop(0.0, 0.5, 0.5, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/shan/` 下 ids_bank.json
- 模板库：删5／刪111（dataset char-groups labels/unified.jsonl（kind=shape、status=ok，sheldon 人裁刻形））

取框 HOG（左下）。次形 删 留人审。

## 试过的和负结果
门槛 0.85 → 97／116，0 错。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 116、文意 0、切线 0、部件 0，其中中心库 0。
- `variant/shan/labels.jsonl`（刪 111／删 5）。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 268 格，放行率 95.9%，送审 11；进组流程 1 格，组判率 0.0%；有人裁的已放行格 31，与人裁不一致 0。
- 维持。
