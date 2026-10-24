# ce 冊册（同义）

## 字形差别
冊 册：独体字，竖笔与横的交接不同。

## 怎么判
方法数组：`freq → ids`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/ce/` 下 ids_bank.json
- 模板库：冊13／册3（中心库 siku-zongmu 人裁（groups.freq.human_shapes，sheldon 2026-10-20 合审））

字频→IDS，但独体字已踢出 IDS 路（`SPECS` 里删了），实际只剩字频。

## 试过的和负结果
IDS 切不开（sheldon 10-21 定另想办法）；旧 `config/groups/ce/ids_bank.json` 已无用。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 16、文意 0、切线 0、部件 0，其中中心库 16；多来源 16 条，其中来源之间结论不同（被更正过）0 条。
- 人裁主要是中心库里 vol01–10 的刻形 confirm 事件，没有专门的标注批。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 61 格，放行率 88.5%，送审 7；进组流程 6 格，组判率 0.0%；有人裁的已放行格 1，与人裁不一致 0。
- 考虑整字 HOG；旧模板库可删。
