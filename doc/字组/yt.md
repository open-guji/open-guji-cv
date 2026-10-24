# yt 圓圖（不同义）

## 字形差别
圓 圖 口里 員／啚。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ composite(crop(0.25, 1.0, 0.0, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核降审
- 配置：`config/groups/yt/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：圓36／圖147（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意为主；整字 HOG（右部框）当第二路。圖＝河圖、圖書；圓＝圓通、方圓。

## 试过的和负结果
整字 HOG：人裁 19/32、放行同 608 异 1。vol04 上 top1≠整理本 11 格，是第四批建组的理由。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 43、文意 1、切线 0、部件 0，其中中心库 12。
- 人裁主要是中心库里 vol01–10 的刻形 confirm 事件，没有专门的标注批。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 1161 格，放行率 98.3%，送审 20；进组流程 1092 格，组判率 73.3%；有人裁的已放行格 24，与人裁不一致 0。
- 维持。
