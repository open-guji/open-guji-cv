# rr 入人八（不同义）

## 字形差别
入 人 八 都是两笔，差在交接位置与出头。

## 怎么判
方法数组：`[ctx_rule → llm] ＋ custom:rr_img ＋ composite(crop(0.0, 1.0, 0.0, 0.5) → hog)`（注册在 `groups/registry.py` 的 `GROUPS`）。
- 复核与门：复核降审；补放须 ctx/ids
- 配置：`config/groups/rr/` 下 ids_bank.json prompt.md rules.yaml
- 模板库：人158／入152／八151（dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤20））

文意＋随机森林字形分类器（`rr_img`）＋上半整字 HOG。补放须文意或整字 HOG 给字且各路不冲突；随机森林只许降审（vol04 A/B 曾把过切的半个「爻」单独放成「人」）。

## 试过的和负结果
L1 只给 10.8%；L1→haiku 50/57 全对（下界 0.929）。整字 HOG 上半：人裁 42/48 对、放行格同 1817 异 2（`ids_online.SPECS` 注释）。

## 人工数据
- 汇总（dataset `char-groups/labels/unified.jsonl`，2026-10-24 重建）：刻形 65、文意 78、切线 0、部件 0，其中中心库 65；多来源 58 条，其中来源之间结论不同（被更正过）4 条。
- 数据集 `rr/items.jsonl`（A_human 81／B_vision 2／C_weak 2264）；`review/rr_*`。

## 现状与待办
- 2026-10-24 本机 vol04–20 产物（各册版本不一，vol11–20 尚未按 10-24 修复重落）：出现 4430 格，放行率 99.2%，送审 34；进组流程 4390 格，组判率 99.0%；有人裁的已放行格 59，与人裁不一致 2。
- 送审很少（vol11–20 17 格）；样本不够把下界推到 0.97，随人裁增长复测。
- 2026-10-25 A24 残留送审清理（铺开 #9）：`rr-ext-l1-人` 去 族窮梓英友某旁遠，聖家刑賢 加反向例外；`rr-ext-l1-八` 去 隆。随机森林 `rr_img` 改成弱票（`FlowSpec.review_weak`）：vol06–20 复核里它单独反对的格看图多是它错（入 判 人）。回放送审 33→21，放回的 12 格看图全是 入，0 错。
