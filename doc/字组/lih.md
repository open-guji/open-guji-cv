# lih 厯歴（同义）

## 字形差别
厯 歴：下部 止 的写法不同（另有 歷 曆；歷／曆 是不同的词）。

## 怎么判
方法数组：`freq → composite(crop(0.0, 1.0, 0.5, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/lih/` 下 ids_bank.json
- 模板库：厯91／歴31（dataset char-groups labels/unified.jsonl（kind=shape、status=ok，sheldon 人裁刻形））

字频→整字 HOG（取下半，48×48）。

## 试过的和负结果
旧左右窗口按册留一有错；整字 HOG 按册留出 122 格错 3，0 错覆盖 81%，门槛 0.25。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 130、文意 0、切线 0、部件 0，其中中心库 124；多来源 120 条，其中来源之间结论不同（被更正过）0 条。
- 中心库人裁刻形 131 条（旧人裁，无切线）。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 339 格，放行率 98.2%，送审 6；进组流程 2 格，组判率 0.0%；有人裁的已放行格 1，与人裁不一致 0。
- 码位归一已把 歷→厯（工作区 codepoints）。
