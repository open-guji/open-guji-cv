# weiw 衛衞（同义）

## 字形差别
衛 衞：字中下部。

## 怎么判
方法数组：`composite(crop(0.25, 0.75, 0.5, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/weiw/` 下 ids_bank.json
- 模板库：衛41／衞14（dataset char-groups labels/unified.jsonl（kind=shape、status=ok，sheldon 人裁刻形））

取框 HOG（x 0.25–0.75、y 0.5–1）。次形太少，只当「放主形」用，次形留人审。

## 试过的和负结果
门槛 0.7 → 衛 37／55 给对，0 错。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 55、文意 0、切线 0、部件 0，其中中心库 0。
- `variant/wei/labels.jsonl`（衛 41／衞 14）。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 149 格，放行率 99.3%，送审 1；进组流程 0 格，组判率 —；有人裁的已放行格 2，与人裁不一致 1。
- v0 里 1 格人裁 衛 对放行 衞，要看图。
