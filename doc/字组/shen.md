# shen 慎愼（同义）

## 字形差别
慎 愼：右部 真／眞。殿本只刻 愼。

## 怎么判
方法数组：`freq → ids → custom:top1`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/shen/` 下 ids_override.tsv

字频→IDS→库形最近（刻形＝系统码位，直接取字）。

## 试过的和负结果
IDS 路评估后认为不需要二选一（只有一种刻形）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 26、文意 0、切线 11、部件 0，其中中心库 1。
- `variant/shen/labels.jsonl` 17 格切线；人裁刻形 26 条。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 160 格，放行率 96.2%，送审 6；进组流程 15 格，组判率 93.3%；有人裁的已放行格 4，与人裁不一致 0。
- 维持。
