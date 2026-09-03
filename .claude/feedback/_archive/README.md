# 反馈通道存档（v1 时代）

> ⚠️ **已被取代，仅存档。** 这里是 2026-02 那一代的外部反馈通道：
> guji-platform 的 merger 跑完出一份质量报告，人工搬回本仓。
> 操作步骤里的路径（`src/detectors/`、`src/run_ocr.py`）在本仓都不存在。
>
> **现在的反馈走统一事件**：人裁 → `feedback/events/` → 路由表 → 金标 / 字形库，
> 见 [../../doc/console_architecture.md](../../doc/console_architecture.md) §3.6
> 与 [../../doc/console_manual.md](../../doc/console_manual.md) §4。
> 三条人裁回流环见 [../../doc/review_feedback_loops.md](../../doc/review_feedback_loops.md)。

留档的价值：`ocr_quality_comprehensive_20260226.md` 里的三个指标口径
（Title 匹配率 / Detail 使用率 / 行数差距）说明了「下游进库到底用不用得上」这件事
怎么量，这个视角现在仍然成立，只是数据是 ce01 那批的、与当前只做正文页的策略无关。
