# ts 土士（不同义）

## 字形差别
土 上短下长、士 上长下短。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ custom:bars ＋ composite(crop(0.0, 0.5, 0.0, 1.0) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 配置：`config/groups/ts/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：土12／士151（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意为主；文意弃权时量横与左半整字 HOG，给字须一致。

## 试过的和负结果
量横：强真值 18/18、AUC 1.0，与文意几乎一致。量错的都是横画缺损或断裂（vol07:115:9:21 上横缺损）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 36、文意 17、切线 0、部件 0，其中中心库 36；多来源 25 条，其中来源之间结论不同（被更正过）0 条。
- 复审 49 格（三组共页）；整字 HOG 人裁 17/29、放行同 409 异 0。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 998 格，放行率 99.0%，送审 10；进组流程 16 格，组判率 62.5%；有人裁的已放行格 37，与人裁不一致 2。
- 维持。
