# fc 傅傳（不同义）

## 字形差别
傅 傳 右部 尃／專。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ composite(crop(0.0, 1.0, 0.25, 0.75) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核降审
- 配置：`config/groups/fc/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：傅16／傳154（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意为主；整字 HOG（中段框）当第二路。

## 试过的和负结果
整字 HOG：人裁 9/30、放行同 1034 异 0（门槛 0.8，覆盖低）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 45、文意 0、切线 0、部件 0，其中中心库 45；多来源 32 条，其中来源之间结论不同（被更正过）2 条。
- 人裁主要是中心库里 vol01–10 的刻形 confirm 事件，没有专门的标注批。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 3417 格，放行率 99.8%，送审 7；进组流程 3377 格，组判率 82.8%；有人裁的已放行格 20，与人裁不一致 0。
- 维持。
