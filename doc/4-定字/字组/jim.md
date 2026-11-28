# jim 覊羈（同义，按刻形拆判）

## 字形差别
上部 覀（覊）／罒（羈）。殿本两形都有，整理本与字形库的码位常与刻形不符，原先是组外异体对送审（全册任务 01）。

## 怎么判
方法数组：整字 HOG＋岭回归（`ids_online.SPECS["jim"]`，48×48，去碎墨），SHAPE 组，补放与复核改码位（`registry.py` SHAPE_GROUPS）。
- 门槛 0.5。
- 模板库 `config/groups/jim/ids_bank.json`：40 格（羈24 覊16）。

## 人工数据
标签不来自放行字（放行字跟整理本走，两形混放）：两形放行格与送审格各抽样，HOG 两类聚类，看图对上刻形，去掉低把握 15%（A24 10-26）。
训练集 dataset `char-groups/variant/jim/`。

## 评测
建库：`research/m7/glyph_expand/build_shape_pair.py jim <原图> <数据目录> <产物> --labels=<表> --write --dataset=…`。
按册留出：0.5 给 34/40，0 错。

离线回放 vol02–99（不含 vol05 vol06；`replay_groups.py --raw`，2026-10-26）：改码位 2。改动逐格看过图。

## 现状与待办
- sheldon 10-26 在定码位页把这一对选为「留人审」＝建组按刻形分。
- 上线：殿本各册 `group_flow` 加 jim；模板库随发版。
