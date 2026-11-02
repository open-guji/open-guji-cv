# chi 勅敕（同义，按刻形拆判）

## 字形差别
右边 力（勅）／攵（敕）。殿本两形都有，整理本与字形库的码位常与刻形不符，原先是组外异体对送审（全册任务 01）。

## 怎么判
方法数组：整字 HOG＋岭回归（`ids_online.SPECS["chi"]`，48×48，去碎墨），SHAPE 组，补放与复核改码位（`registry.py` SHAPE_GROUPS）。
- 门槛 0.5。
- 模板库 `config/groups/chi/ids_bank.json`：86 格（勅64 敕22）。

## 人工数据
标签不来自放行字（放行字跟整理本走，两形混放）：两形放行格与送审格各抽样，HOG 两类聚类，看图对上刻形，去掉低把握 15%（A24 10-26）。
训练集 dataset `char-groups/variant/chi/`。

## 评测
建库：`research/m7/glyph_expand/build_shape_pair.py chi <原图> <数据目录> <产物> --labels=<表> --write --dataset=…`。
按册留出：0.5 给 86/86，0 错。

离线回放 vol02–99（不含 vol05 vol06；`replay_groups.py --raw`，2026-10-26）：补放 1、改码位 10（敕→勅 9、勅→敕 1）。改动逐格看过图。

## 现状与待办
- sheldon 10-26 在定码位页把这一对选为「留人审」＝建组按刻形分。
- 上线：殿本各册 `group_flow` 加 chi；模板库随发版。
- 2026-11-01（第 2 轮，`solo_margin=0.5`）：整理本缺字（坐标对位 〓）的 8 格，HOG margin 0.86–1.07、看图全是 勅，原先被当组外字拦（coord_dissent）；`solo_margin` 取 ids 自身门槛，只让 〓 不再拦。
