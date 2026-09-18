# -*- coding: utf-8 -*-
"""49 条业务路由，按**八类事**分成 12 个文件，另加 1 个前端兜底。

分法照 `console_architecture.md` 与控制台重构方案 §7.2：一个文件一类事，
每个文件都能整屏读完。`app.py` 只负责建 app、挂中间件、`include_router` ×12。

| 文件 | 条 | 管什么 |
|---|---|---|
| `registry.py` | 5 | 册 / 管线 / Step / 产物种类 / 前端入口（`/` 与 `/v1/`） |
| `workspace.py` | 2 | 当前工作区与各个根；**热切工作区**（改 GUJI_WORKSPACE + 重建单例，2026-09-15）|
| `runs.py` | 7 | 状态、入队、查任务、取消、日志 |
| `products.py` | 6 | 数值产物、清单、原图、缓存图、叠图、列图裁段 |
| `feedback.py` | 8 | 批次台账、裁决回传、收割、按路由表消费 |
| `gold.py` | 3 | 金标分片 / 迁移 / 漂移 |
| `evals.py` | 7 | 评测器、质量看板、四把尺子、一轮体检、人审率台账 |
| `review.py` | 3 | 定字待审卡、裁决回读、一列的上下文 |
| `cutline.py` | 2 | 拖切线用例与裁决回读 |
| `border_review.py` | 3 | Step1 列探测/抬头/外框外延、Step2 上下版框核校的卡片与图（原 artifact 迁入，2026-09-11） |
| `column_review.py` | 4 | Step2 列清理人裁：左右文字带 + 上下端部类别（2026-09-17） |
| `slot_count_review.py` | 3 | Step3 逐列字数人裁：`chars_per_line` 常量在个别列不成立时的兜底（2026-09-18） |
| `jiazhu.py` | 1 | 夹注段卡 |
| `rare.py` | 2 | 生僻字单查与批量 |
| `glyph_match.py` | 3 | Step5-a 字形库匹配单查、候选缩略图、档位分布聚合（2026-09-11） |
| `variants.py` | 2 | 本书用字账、组视图 |
| `step9.py` | 1 | Step9 结果整理 · 坐标转字符位现场渲染（2026-09-11，不进管线） |
| `spa_fallback.py` | 0（非业务） | v2 React 前端路由兜底，**必须最后 include** |

**加一条路由**：找它属于哪一类，写进那个文件即可；`app.py` 不用动。
**加一类**：新建一个文件，在 `app.py` 的 `ROUTERS` 里加一行（`spa_fallback` 前面）。
"""
