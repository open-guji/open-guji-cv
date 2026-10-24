# jue 絕絶（同义）

## 字形差别
絕 ⿰糸⿱刀巴、絶 ⿰糸⿱⺈巴（sheldon 10-22 定细 IDS），差在右部「色」上半。

## 怎么判
方法数组：`freq → ids`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/jue/` 下 ids_bank.json ids_fine.tsv unet.npz
- 模板库：絕15／絶24（char-groups/variant/jue/labels.jsonl）

字频→通用 IDS＋细 IDS（`ids_fine.tsv`）：本组 U-Net 切左右，再自动缝切到叶子，最近邻。

## 试过的和负结果
旧窗口 23%、U-Net 部件 31%、整字 HOG 44%；通用判法＋细 IDS 0 错覆盖 59%（门槛 0.05）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 42、文意 0、切线 39、部件 0，其中中心库 1。
- `variant/jue/labels.jsonl` 39 格切线（絕 15／絶 24）；`fine_ids_1022.jsonl`。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 103 格，放行率 99.0%，送审 1；进组流程 0 格，组判率 —；有人裁的已放行格 1，与人裁不一致 0。
- 维持。
