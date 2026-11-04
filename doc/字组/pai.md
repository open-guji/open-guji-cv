# pai 派𣲖（同义，按刻形拆判）

## 字形差别
派 ⿰氵𠂢：右边上有一横；𣲖：右边无横、三竖并列（形近 泒）。殿本 vol51–99 两形都有（𣲖 集中 vol68、vol78、vol85–93）。
字形库没有 𣲖，库把它排成 泒（再往后 孤弧）→ 首跑 V 类送审 51 格。

## 怎么判
方法数组：整字 HOG＋岭回归（`ids_online.SPECS["pai"]`，48×48，去碎墨），SHAPE 组，补放与复核改码位（`registry.py` SHAPE_GROUPS）。
- 门槛 0.5。
- 陪衬 `tolerate`：泒孤弧滅渢（入口容许紧咬；不进模板库）。`ref_enter`：库首位是 泒、整理本作 𣲖 → 进组。补放须与整理本同字（`lift_ref_agree`）。
- 模板库 `config/groups/pai/ids_bank.json`：vol51–99 已放行格每册每字 ≤12，共 291 格（派 212、𣲖 79）。

## 评测
建库：`research/m7/glyph_expand/build_shape_pair.py pai <原图> <工作区> <产物> --write --dataset=…`。
按册留出：首轮唯一错例 vol62:140:5:16 放行成 泒、刻 𣲖，改标后 **0.1 起 0 错**，0.5 给 277/291。

离线回放 vol51–99（`replay_groups.py --groups pai,qi,sui --raw <原图>`，2026-10-26）：补放 45（44 格 𣲖 送审格＋1 格放行成 泒 的错放），
复核照旧 327、弃权 4，没有改字；仍送审 8。改动逐格看过图，都是 𣲖。

## 现状与待办
- 上线：vol51–99 各册 `group_flow` 加 pai；模板库随发版。
- 2026-11-01（第 2 轮，`ref_margin=0.15`，只对 𣲖）：整理本作 𣲖、HOG 第一名 𣲖、margin 0.20–0.50 的 9 格看图全是 𣲖，转放行。
