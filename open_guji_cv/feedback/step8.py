# -*- coding: utf-8 -*-
"""Step8 落库反馈：给三条散落的支线一个名字与位置。

三条支线本来就是同一件事的三个出口——落库与反馈上游的裁决走完 Step7（放行判定）
之后，往哪儿去：

    ① 落字形库   glyphdb_admit  → output/glyph_store/ → 重建 glyph.db
    ② 反馈上游   gold_add       → open-guji-dataset/<step>/<shard>/items.jsonl
    ③ 排除名单   crop_exclude   → config/crop_exclusions.jsonl

现役代码（`routes.py` 的路由表、`consumers.py` 的四个消费者 + `CONSUMERS` 表 +
`route_and_consume`）已经把这三条都实现了，本模块不重写它们——只是让「Step8」
成为一个可以被指到、被列出来的东西：路由表是它的配置，三个消费者是它的出口。

## 为什么这不是 `core.step.Step`

任务书 §三点名要查这件事，结论记在这里（详见
`overview` 的 `进度/inbox/Step8-统一成步/*-ask.md`）：

`core.step.Step.run_page(ctx, page)` 与 `core.engine.Engine` 假定的形状是
「单本书 × 单页 × 经 `ProductStore`/`ImageCache` 落盘的产物，按 (book, step, page)
算指纹、判 stale」。Step8 三处都对不上：

- **输入不是页级产物，是事件流**：`EventLog` 按 `(batch, seq)` 排序回放，
  一批事件可以跨书跨页跨卡片（`cols:vol02:171` 是页级卡、`vol01:22:5:4` 是格级卡）；
  `Engine` 没有「这一步吃的是任意一批事件」这个概念，它的 `RunContext` 是绑定
  单一 `BookSpec` 的。
- **输出不经过 `ProductStore`**：三个出口分别落 SQLite（`glyph.db`，且真源是
  `glyph_store/` 的 PNG + JSONL）、另一个仓的金标 JSONL（`open-guji-dataset`）、
  以及配置目录下的排除名单——没有一个是 `ProductKindSpec` 描述的「这本书这一步
  这一页的一份产物」，套 `numeric`/`image_cache` 存储类型都不成立。
- **幂等机制不同**：Step8 靠 `EventLog.consumed/<consumer>.jsonl` 按事件 id 记账
  （见 `EventLog.pending`/`mark_consumed`），不是 `code_hash + params_hash + 上游产物
  sha` 那套页级指纹——两套幂等模型解决的是不同的重放问题，硬凑成一套要么是指纹
  对事件 id 没有意义，要么是事件消费要伪造一个「page」参数,两边都会误导以后的人。

按模板 §四铁律「改不动就报，别硬改」，这里选择**不**把 Step8 注册进
`core.step.STEPS`、也不出现在 `pipelines/*.yaml` 里，避免为了塞进模子而扭曲
`run_page(ctx, page)` 的契约。名分与位置改用下面这个只读的 `Step8Spec` 声明：
控制台/文档要展示"管线走到这一步了"，认这个模块就够，不需要 Step8 是一个能被
`Engine.run` 调度的 `Step`。执行体仍然是 `consumers.route_and_consume`——
这个模块只是把它、路由表、三个出口用一个名字接起来。
"""

from __future__ import annotations

from dataclasses import dataclass

from .consumers import CONSUMERS, route_and_consume  # noqa: F401  给外部一个统一入口
from .routes import RouteTable  # noqa: F401


@dataclass(frozen=True)
class Outlet:
    """Step8 的一个出口：对应 `consumers.CONSUMERS` 里的一个消费者。"""

    consumer: str    # CONSUMERS 的键
    title: str       # 一句话名字
    sink: str         # 落到哪儿（人看的路径描述，不是强类型）


# 顺序与任务书 §二表格一致
OUTLETS: tuple[Outlet, ...] = (
    Outlet(consumer="glyphdb_admit", title="落字形库",
           sink="output/glyph_store/ → 重建 glyph.db"),
    Outlet(consumer="gold_add", title="反馈上游",
           sink="open-guji-dataset/<step>/<shard>/items.jsonl"),
    Outlet(consumer="crop_exclude", title="排除名单",
           sink="config/crop_exclusions.jsonl"),
)


@dataclass(frozen=True)
class Step8Spec:
    """Step8 的自描述。字段名有意仿 `core.spec.StepSpec`，但不是同一个体系——
    见模块 docstring「为什么这不是 core.step.Step」，这里没有 `unit`/`consumes`/
    `produces`/`params`，因为那些字段描述的是页级产物契约，Step8 不满足。"""

    id: str = "step8_feedback"
    title: str = "落库反馈"
    upstream: str = "admit_decide"   # Step7：放行判定
    outlets: tuple[Outlet, ...] = OUTLETS
    config: str = "feedback/routes.py（RouteTable，可被 feedback/routes.yaml 覆盖）"


STEP8 = Step8Spec()


def describe() -> dict:
    """给控制台 / CLI 用的自描述，形状仿 `core.step.Step.describe()`。"""
    return {
        "id": STEP8.id,
        "title": STEP8.title,
        "upstream": STEP8.upstream,
        "config": STEP8.config,
        "outlets": [{"consumer": o.consumer, "title": o.title, "sink": o.sink}
                    for o in STEP8.outlets],
    }
