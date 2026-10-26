# xiang 鄉鄕（同义；与 卿 形近）

## 字形差别
鄉 鄕：殿本只一种刻法，工作区 codepoints `鄉: 鄕`（sheldon 10-25 定暂归一）。
难点是 **卿**：殿本 卿 右边也刻作 阝 样（整理本常录 〓），与 鄉 只差左边：鄉 左作 乡（三折），卿 左作 卯 的左半（一竖带钩）。
字形库分不开（cov 差 0.01 内），整理本作 鄉／鄕 的格库首位一大半是 卿 → 送审。看图：项目文件 `a24/全册/任务04/鄉卿-看图.png`。

## 怎么判
方法数组：整字 HOG＋岭回归一对多（`ids_online.SPECS["xiang"]`，48×48，λ=1，去碎墨），SHAPE 组（`registry._NEAR_FAMILY`）。
- 模板库 `config/groups/xiang/ids_bank.json`：两码位并成一类 鄕（`build_shape_pair.ALIAS`），陪衬 卿 鄭 鄒 郡 也进库（判成它们＝弃权）。
  殿本 vol02–99 main 包已放行格（每册每字 ≤12、每字 ≤80，线上同款 char_patch）：鄕 82、卿 96、鄭 82、鄒 80、郡 80。
- 门槛 0.5；补放须与整理本（缺位时坐标对位）同字（`lift_ref_agree`）；库首位是陪衬（卿…）也按整理本进入（`ref_enter`）。
- 只补放：成员只一类，复核给不出组里另一个字。

## 评测
按册留出（`build_shape_pair.loo`）：判成 鄕 的格 0.3 起 0 错（判错的只有 鄕→郡 0.35，弃权侧），门槛 0.5 给 鄕 79／82。

离线回放 82 册（`replay_groups.py --patches --codepoints`，2026-10-26）：进组 51，补放 43（本任务送审格 41、别处 2），逐格看图都是 鄉；
弃权 8（判别值不够或判成 卿）。

## 试过的和负结果
—

## 人工数据
训练集 dataset `char-groups/variant/xiang/`（labels.jsonl、crops/、split.json）。

## 现状与待办
- 上线：各册 `group_flow` 加 xiang；模板库随发版（新 ids_bank 是 repo 语料）。
