# yh 遺還（不同义）

## 字形差别
遺 還 都是辶，里头 貴／睘。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ hog`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核降审
- 配置：`config/groups/yh/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：遺83／還11（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意为主；整字 HOG 当第二路。遺＝遺文、補遺；還＝還朝、返還。

## 试过的和负结果
整字 HOG：人裁 21/24、放行同 61 异 0。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 33、文意 0、切线 0、部件 0，其中中心库 2。
- 人裁主要是中心库里 vol01–10 的刻形 confirm 事件，没有专门的标注批。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 321 格，放行率 98.4%，送审 5；进组流程 299 格，组判率 83.3%；有人裁的已放行格 25，与人裁不一致 0。
- 维持。
