# em 而面（不同义）

## 字形差别
而 面 下半不同。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ composite(crop(0.0, 1.0, 0.5, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核降审
- 配置：`config/groups/em/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：而157／面23（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意为主（而＝虚词；面＝東面、四面）；下半整字 HOG 当第二路。

## 试过的和负结果
整字 HOG：人裁 21/21、放行同 1718 异 1。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 42、文意 0、切线 0、部件 0，其中中心库 42；多来源 35 条，其中来源之间结论不同（被更正过）0 条。
- 人裁主要是中心库里 vol01–10 的刻形 confirm 事件，没有专门的标注批。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 5201 格，放行率 99.7%，送审 17；进组流程 5158 格，组判率 89.8%；有人裁的已放行格 29，与人裁不一致 0。
- 维持（收益主要在复核，防 而→面）。
