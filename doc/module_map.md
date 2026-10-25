# 模块地图：包分层、各包职责、依赖方向（2026-10-17）

> 目的：让「谁可以依赖谁」有一张写下来的表，并由 `tests/test_architecture.py` 守住。
> 这是**现状的固化**，不是重构方案：2026-10-17 的分析里，包与包之间向上依赖共 42 条（存量），
> 全部登记在测试的 `ALLOWED_UPWARD` 里，**只许减不许增**。

## 一、分层

层号小的是底层。**低层不许 import 高层**（函数内的惰性 import 也算）；同层互相 import 不限制。

| 层 | 包 | 一句话职责 |
|---|---|---|
| L0 基础 | `errors` `variants` `variant_ledger` `gloss` `detectors` `ocr` `hanzi` | 领域错误信号；异体关系图与本书用字账；单字释义；OCR 检测器与 paddle 子进程 worker；**自建汉字关系库 `hanzi`**（字、关系边、IDS 与部件、形近对，离线 sqlite，只用标准库，见 [design/汉字字形与关系库-总设计.md](design/汉字字形与关系库-总设计.md)）。无内部依赖 |
| L1 设施 | `core` `products` `utils` `formats` `datastore` | **Step 引擎**（`Step`／`StepSpec`／`STEPS` 注册表／`Engine`）；**产物仓**（`ProductStore`、`ImageCache`、产物 schema）；通用工具；对外交换格式（guji-page 等）；**中心库**（`datastore`：Postgres 表结构、从 guji-workspace 幂等导入与核对、R2 图片上传，只依赖标准库＋psycopg，不进任何 Step 的 `code_deps`） |
| L2 算法与产出 | `clustering` `gold` `report` `render` `pagetype_model` `groups` | 字形匹配/聚类/播种（`clustering`，最大，约 2.4 万行）；金标信封与分片仓；Step9 汇总层；叠图与阅读排版；页型模型；**形近字／异体字组 `groups`**（注册表、方法数组、统一流程 `group_flow`；规范与各组卡见 [字组/](字组/README.md)） |
| L3 管线 | `steps` `gates` `shadow` `feedback` | 各 Step 的适配（`import open_guji_cv.steps` 即注册全部 Step）；挂在 Step 上的闸；影子放行闸；人裁事件与路由（`EventLog`） |
| L4 应用 | `eval` `review` `snap` `ops` `exp` `opinions` `jobs` | 评测；审阅批次与卡片；快照导入；发布/部署运维；A/B 实验框架；**任务库**（`jobs`：重跑／评测任务交到 Neon `jobs` schema、执行方领单跑单，只依赖 `datastore`，见 [design/重跑任务库.md](design/重跑任务库.md)）；**意见池**（`opinions`，M11：网站读者意见入池、证据包、规则分流、book-text 冻结册修订；只依赖 `core`／`datastore`、标准库与 Pillow，不进任何 Step 的 `code_deps`） |
| L5 控制台 | `console` | FastAPI 后端（`console/routers/*`）＋无构建前端，`guji console` 启动 |
| L6 命令行 | `cli_v2` `cli_exp` `cli_glyph_db` `cli_db` `cli_products` `cli_source` `cli_opinions` `cli_cellvotes` `cli_freeze` | `guji` 命令（pipeline / step / status / close-check / recheck / cache / collate / gold / eval …） |
| L7 入口 | `__main__` | `python -m open_guji_cv` |

## 二、各层之间的「接口」是什么

互相不必知道对方内部，只通过下面这些已有的口子说话：

| 口子 | 位置 | 谁提供 / 谁用 |
|---|---|---|
| Step 注册表 | `core.step.STEPS`、`@register_step`、`StepSpec` | `steps/*` 提供；`core.engine` 和 CLI 按名字调度，不直接 import 具体 Step |
| 产物仓 | `products.store.ProductStore`、`products.kinds.*`（schema） | 所有 Step 读写产物只走它；下游读上游产物也走它，**不 import 上游 Step 的代码** |
| 图像缓存 | `products.cache.ImageCache` | 列图、字块的读写 |
| 人裁事件 | `feedback.events.EventLog`（只追加、带批次与序号、消费幂等） | 审阅/控制台写事件；`feedback.consumers` 消费 |
| 金标 | `gold.store.GoldStore`、`gold.item` 统一信封 | 评测与建集读写 |
| 控制台 HTTP | `console/routers/*`（`/api/...`） | 前端与外部审查页调用；路由层不放业务逻辑，业务在下层 |
| 命令行 | `guji ...`、`python -m open_guji_cv` | 前台用控制台，后台用 `guji` 命令（见 `console_manual.md`） |

## 三、已知的向上依赖（存量，42 条）

按「谁依赖了谁」归类，全部登记在 `tests/test_architecture.py::ALLOWED_UPWARD`：

| 类别 | 条数 | 例 | 想修的话 |
|---|---|---|---|
| `utils`/`products` → `clustering` | 13 | `utils.binarized → clustering.normalize`、`font_calibrate*`、`seed_witness`、`products.fp_migrate` | `clustering.normalize`／`canonical` 本质是底层图像工具，应下沉；**动它会让各册产物判过期**，要等统一窗口 |
| `core` → `steps`/`clustering`/`review` | 6 | `core.step` 为指纹／可选消费者查 `steps.*` | 改成由 `steps` 向 `core` 注册 |
| `report` → `eval`/`feedback`/`review` | 6 | `report.progress`、`report.collate` | 汇总层依赖应用层，把共用函数下沉 |
| `gold` → `feedback`/`steps` | 5 | `gold.transfer`、`gold.v2_align` | 同上 |
| `clustering` → `steps`/`console` | 3 | `clustering.rare_panel`、`glyph_selfcheck` | 调用方把依赖当参数传进来 |
| 其他 | 9 | `utils.calibrate → steps`、`review.cards → console`、`render.overlay → gates.query`、`formats.guji_page_cv → report.slots`、`feedback.* → eval/review`、`gates → eval` | 逐条看 |

另有一对**同层环**，守卫测试看不到：`ops` ↔ `snap`。

## 四、改之前先看

- **产物指纹**：Step 模块和它声明的 `code_deps` 一改，各书产物判过期（`core.engine.code_hash`）。
  下沉 `clustering.normalize` 之类被 Step 依赖的文件，就是在让各册重算——别在 GUJI-525 上线、窗口甲核对这类节点前做。
  不在任何 `code_deps` 里的文件（评测、控制台、脚本用的模块）可以放心动。
- **新增顶层包**：先在 `tests/test_architecture.py` 的 `LAYER` 和本文第一节登记，否则测试会红。
- **修掉一条存量**：同时从 `ALLOWED_UPWARD` 里删掉它，否则测试会提示「存量已修掉」。
- **别用新的惰性 import 绕环**：守卫连函数内的 import 也看。

## 五、2026-10-17 清理记录

- 删 `steps/_v1_bridge.py` 与 `tests/test_v1_bridge.py`：v1 `CharInstance` 桥（阶段 B0），无任何 src 引用，只有它自己的测试在用。
- 根目录 `HANDOFF_S2/S3/Z_jys/Z_ry.md` 归档到 `doc/handoffs/`。
- 删 `steps/step6_signals.py`（X1 实验空壳 54 行，无注册、无调用方、不在任何 `code_deps`）。X1 完整代码在存档分支 `archive/pre-compress-2026-10` 的 `2401bb5a`，结论与取回办法见 `design/16-各步决策改学习模型-盘点.md` 末尾。
- **没删、留给后面**：vulture 扫出的约 30 个未引用函数（如 `GlyphKnnSource`、`scrub_nonchar`、`synth.make_dataset`、`reflow_page`、`measure_book_*`）。
  Step 类、路由处理函数是装饰器注册，不是死代码，别按 vulture 的结果删。

## 六、后续

- 剩余的包级向上依赖怎么分批清理：[design/模块化后续计划（待Mila定）.md](design/模块化后续计划（待Mila定）.md)（**待 Mila 定，未执行**）。
- 形近字／异体字组：规范、总表与各组卡在 [字组/](字组/README.md)。
