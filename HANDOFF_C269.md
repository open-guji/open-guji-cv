# HANDOFF · C 道 · overview#269 影子预排序＋预勾（分支 claude/C-shadow-preselect-0930）

## 做了什么
「对齐改字层 · 网格」（#265）接入影子放行模型的输出，**只做排序＋预勾标记，提交仍要人点，不自动放行**。

| 位置 | 内容 |
|---|---|
| `open_guji_cv/review/shadow.py`（新） | 预测文件读取（缺失／损坏 → None，不报错）、文件指纹、`shadow_view`（`pre` 判据：conf≥0.9 且影子字==整理本字） |
| `review/cards.py::cards(shadow=True)` | 卡加 `shadow:{char,conf,pre}`；`cls_sub=grid` 时**先收全再排序、后截断**（pre 排最前，按把握降序，其余原序）；带 `cls` 的响应加 `shadow_info:{available,thr}` |
| `console/routers/review.py` | 新查询参数 `shadow`（缺省 true）；文件指纹／关闭状态进缓存键（文件不存在时缓存键与改前相同） |
| 前端 | `ReplaceAlignGrid` 角标「影子 0.9x」＋预勾卡描边；网格工具栏复选框「使用影子预勾（本屏 N 张）」，缺省开，无预测文件时置灰；切换即重载；`gridRows(…, shadowOn)` 每行加 `shadow_preselect` |
| `scripts/experiments/shadow_admit/export_for_cards.py`（新） | `shadow_picks.jsonl` → 预测文件 |
| `tests/test_shadow_preselect.py`（新） | 8 条：无文件／坏文件不变、排序在截断前、阈值与字不等不预勾、开关、路由缓存键、node 协议事件字段、导出脚本 |

## 预测文件格式（我定的）
路径 `<ws>/cache/shadow/<book>.json`（即 `cache_root()/shadow/<book>.json`）：
```json
{"version": 1, "book": "vol03", "cells": {"vol03:12:3:5": {"char": "之", "conf": 0.9734}}}
```
`cells` 的键 = 卡片 `id`；`char` = 影子字（`shadow_picks.jsonl` 的 `pick`）；`conf` = 把握度（`conf`，即该格候选得分/该字位得分总和）。
生成：
```bash
python scripts/experiments/shadow_admit/predict.py <signals_all.jsonl> --out <dir>      # 已有，出 shadow_picks.jsonl
python scripts/experiments/shadow_admit/export_for_cards.py <dir>/shadow_picks.jsonl --book vol03
```
导出脚本只用标准库；换文件后不用重启控制台（指纹进缓存键）。

## 事件字段
网格提交的每一行多 `shadow_preselect: true/false`：**该格提交时是否为影子预勾**（复选框开着、文件在、`card.shadow.pre`）。
预勾被人改掉 = 行里 `shadow_preselect=true` 且 `v != confirm`（点成 skip／seg_defect）。统计口径：
`count(shadow_preselect=true & v≠confirm) / count(shadow_preselect=true)`。复选框关着或无文件时全为 false。
不带 `shadowOn` 的旧调用（含既有测试）事件行逐字节不变。只加可选字段，下游（glyphdb_admit 等）只认 `v`，不受影响。

## 拿不准（保守处理，请总管/用户定）
1. **「预先勾选」的含义**：现网格本来就是「每张缺省采信」（人只点掉异常的），没有逐张复选框。任务书说「其余不动」，所以我**没有**把非预勾卡改成缺省不采信，而是把「预勾」做成**视觉标记＋排序＋事件字段**（描边＋角标＋排最前）。若用户想要「只有影子预勾的才缺省采信、其余缺省跳过/不提交」，那是行为改动，需另定。
2. 排序时为了「先排后截断」，网格且有影子文件时会把整个网格集合（vol03 约 283 张）都收进内存再截，比原先多做一点活，可接受；无文件时走老路径。
3. 预测文件里的 id 格式假定与卡片 `id` 一致（`extract.py` 的 `s.id`，未在云端用真数据核对）——请用真数据导一份后看角标是否出现。
4. `shadow_picks.jsonl` 里对**人已看过**的格给的是交叉验证预测；网格本就不出已裁格，无影响。

## 用户要点哪几步验（云端点不了浏览器）
1. 用真书导出预测文件（上面两条命令），刷新控制台 → 审阅 → 「对齐改字层」→ 细项「网格」。
2. 看：复选框「使用影子预勾（本屏 N 张）」是勾上的；最前面 N 张有绿描边、下方角标「影子 0.9x」，其后的卡角标是较低把握或无角标。
3. 取消勾选 → 网格重载，角标／描边消失、顺序回到原序；再勾上恢复。
4. 把一张预勾卡点两下（→跳过），提交这一屏；到事件日志查该行有 `shadow_preselect:true, v:skip`，其余预勾采信行 `shadow_preselect:true, v:confirm`。
5. 删掉（或改名）`cache/shadow/<book>.json` 刷新：复选框置灰、网格与改前一致、无报错。

## 验证
- 新增 `tests/test_shadow_preselect.py`；`npm run build` 已重出 dist（本地 build，无冲突）。
- 全量 `pytest tests/ -s`（云端 venv 装 .[torch]，deselect 了 test_cli_build_rare_index…）：**2471 passed, 3 skipped, 6 deselected**；新增 8 条 + 既有 test_replace_align_grid 全绿。
