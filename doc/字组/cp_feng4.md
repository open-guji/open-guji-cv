# cp_feng4 鳳鳯（同义）

## 字形差别
鳳鳯：同一个字的不同写法，sheldon 已在工作区 `config/codepoints.yaml` 定「鳯 → 鳳」（暂归一，见 README 第二节「已有码位归一登记」里「组外异体对 45 对」一行；2026-10-26 全册任务 01 的定码位页）。

## 怎么判
方法数组：`codepoint`（`CODEPOINT_GROUPS`）。入口 `ref_top_enter`：库首位与整理本（缺位时坐标对位）字同在 鳳鳯 里就进；码位法给字要库首位 cov ≥ 0.91。
给字 = 册配置 `codepoints` 定的 鳳。只补放，不复核。

## 试过的和负结果
—

## 人工数据
—（不训练）

## 现状与待办
- 2026-10-28（A24 压低组外异体对送审第 1 轮）：codepoints 早定了，但没建组，流水线见「库首位与整理本是异体对」一律送审。
  vol01–99 main 包离线回放（`replay_groups.py --codepoints`）补放 3 格（其中改字 0 格），逐格看图见 PR。
- 上线：各册 `group_flow` 加 cp_feng4（见 dataset `char-groups/待上线.md`）。
