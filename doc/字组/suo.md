# suo 瑣𤨏（同义）

## 字形差别
瑣 ⿰王⿱⺌貝、𤨏 ⿰王⿱巛貝：差别只在右上。殿本两种刻法都有，一眼可分：
- 瑣：右上两点内收（⺌）；
- 𤨏：右上三笔竖排（巛）。

vol04–20 已放行 瑣 14、𤨏 8（𤨏 全是坐标兜底通道放的），字形库人裁 𤨏 5；整理本 23 格全与刻形一致。

## 怎么判
方法数组：`composite(crop(0.4, 1.0, 0.0, 0.5) → hog)`（`groups/registry.py` 的 `SHAPE_GROUPS`，与 尙尚、凖準 同一套）。
- 判别区只取右上（x 0.4–1、y 0–0.5），48×48，岭回归 λ=1（`ids_online.SPECS["suo"]`）。
- 𤨏 模板只有 9 格，每类至少 5 例（`min_class=5`）才给字，按册留出时 𤨏 集中的册（vol14 三格）留出后也还够。
- **复核只降审不改码位**（`_SHAPE_PAIR_NO_FIX`）：模板少，判出另一形先送人审。
- 门槛 0.5：按册留出不设门槛也 0 错（23 格，最低 margin 0.34），0.5 时给字 21/23。

## 试过的和负结果
- 每类至少 8 例（其他组的缺省）：留出 𤨏 所在册后 𤨏 不足 8 例，只给 2/9；改成 5 例后 9/9 都给、0 错。

## 人工数据
- 模板＝殿本 vol04–20 已放行格（每册每字 ≤12，放行字当标签）＋看图补的送审格 vol16:142:2:10（𤨏）。字块用线上同款 char_patch。
- 训练集：dataset `char-groups/variant/suo/`（labels.jsonl 23 行；crops/；split.json 按册）。建库 `research/m7/glyph_expand/build_shape_pair.py suo … --char-patch --write --dataset=…`。
- 字形库里 vol01:5:3:18 原标 瑣，sheldon 10-24 裁 𤨏（GUJI-719 第 1 项，已改库）。

## 现状与待办
- 2026-10-25 离线回放（vol04–20 现有产物，`replay_pair.py --groups suo`）：复核 22 格全照旧，补放 1（vol16:142:2:10，𤨏，看图对），改字 0。
- 字形库重判（`research/char_groups/variants_719/libcheck.py`）：库里 7 例，判 5 例与库标一致，2 例弃权。
- 未上线：等 A24 成批上线时加进册 yaml 的 group_flow（dataset `char-groups/待上线.md`）。𤨏 攒到 ≥20 例后再考虑复核改码位。
