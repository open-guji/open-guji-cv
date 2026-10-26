# lei 類𩔖（同义）

## 字形差别
類 𩔖：左上 米／⺌ 一类的写法差别。殿本只一种刻法（vol21–50 整理本作 𩔖 送审 26 格，与已放行 類 1,684 格看图同一刻法，对照图项目文件 `a24/vol21-50/对照-類𩔖.png`）。

## 怎么判
方法数组：`codepoint`（注册在 `groups/registry.py` 的 `CODEPOINT_GROUPS`）。工作区 codepoints `𩔖: 類`（sheldon 10-25 定**暂归一**，见 README 第二节）。
- 入口 `ref_top_enter`：库首位是 類／𩔖、整理本（缺位时坐标对位）字也是 類／𩔖 就进，分差内的组外字（頗 頻 顚 頴 顯 煩 …）不拦。
- 码位法给字要库首位 cov ≥ 0.91（`FlowConfig.codepoint_min_cov`）。

## 试过的和负结果
—

## 人工数据
—（不训练）

## 现状与待办
- 2026-10-26（A24 全册任务 04「码位已定仍送审」）：整理本作 𩔖、库首位 類 的格，库 cov 0.93–0.99 都是 unsure、坐标对位又过不了 `match_ref_weak` 的 0.98，
  全册 main 包送审 68 格。离线回放 82 册（`replay_groups.py --codepoints`）：补放 67，逐格看图都是 類；
  剩 vol68:161:3:19（库 0.909，码位法 cov 下限弃权）。
- 上线：各册 `group_flow` 加 lei（见 dataset `char-groups/待上线.md`）。
