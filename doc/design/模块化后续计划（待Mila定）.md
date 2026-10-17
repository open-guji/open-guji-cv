# 包级模块化：后续计划（待 Mila 定，不执行）

> 2026-10-17，Emerson 起草。用户定：**先不做，留给 Mila，等合适的时机一起做。**
> 背景与现状见 [../module_map.md](../module_map.md)；守卫 `tests/test_architecture.py` 已合（cv#78），42 条存量违规在它的 `ALLOWED_UPWARD` 里。
> 本文只列「剩下什么、怎么分批、什么时候、怎么证明没改坏」，**不含任何已执行的改动**。

## 一、一句话

存量 42 条向上依赖里，**18 条牵涉产物指纹**（源或目标是某步的 Step 模块或 `code_deps`），**24 条不牵涉**。
前者必须并进「会让各册 `seed_admit`（或相关步）判过期」的那次统一窗口一起做；后者可以随时分小批做，但**窗口甲（10-20）前碰 `steps/`、`core/`、`code_deps` 的一律先问 Mila**。

## 二、18 条牵涉指纹（留到窗口之后，和别的改动合批）

量法：对 `STEPS` 里每步取 `[type(step).__module__, *spec.code_deps]`（共 19 步），42 条的源或目标落在这个集合里的算牵涉。

| 类 | 条数（约） | 例 | 改法方向 |
|---|---|---|---|
| `core.step` 反查 `steps.*`／`clustering.cnn_candidates` | 4 | `core.step → steps.align_ref/context_decide/rare_candidates` | 改成由 `steps` 向 `core` 注册（可选消费者表由 Step 自己声明） |
| `utils` → `clustering`（图像归一化类） | 7 | `utils.binarized → clustering.normalize`、`font_calibrate*`、`seed_witness → clustering.seeding` | `clustering.normalize`／`canonical`／`features`／`verify` 本质是底层图像工具，下沉到 `utils`（或新建 `imaging`）；`seed_witness` 依赖 `seeding` 的部分要拆 |
| `gold.v2_align` → `steps.align_ref/context_decide` | 2 | | 依赖用参数传入 |
| `products.fp_migrate` → `clustering.cnn_candidates/font_candidates` | 2 | | 迁移只需指纹常量，抽出 |
| `clustering.rare_panel` → `steps.*` | 2 | | 同上 |
| `gates.row_segment_gate` → `eval.rulers` | 1 | | `rulers` 下沉 |

**为什么不能现在做**：这些文件在 `code_deps` 里，改一个字节（去注释、docstring、空行后的代码行）就让对应步的 `code_hash` 变，各册产物判过期；其中 `seed_admit` 单册重跑约 5–12 分钟（沙箱 4 核，引自 B1 窗口清单），十册合计约 1.5 小时。
**所以要和别的本来就让 `seed_admit` 过期的改动合批**（Evan 的 W2 删死开关、W4 `group_clf`、PR2 `ctx_window`，以及 [形近字组统一接口设计](形近字组统一接口设计.md) 的 S2），只重跑一次。

## 三、24 条不牵涉指纹（可分小批，随时做）

| 批 | 条数 | 内容 | 前置 |
|---|---|---|---|
| M1 | 5 | 放错层、最机械的：`review.cards → console`（2）、`core.book → review.cards`、`clustering.glyph_selfcheck → console.routers.workspace`、`core.pipeline → steps`（惰性） | **先读代码**，我还没逐条读 |
| M2 | 7 | 汇总层依赖应用层：`report.progress → feedback/review`（4）、`report.collate/tiers → eval.round_check`（2）、`formats.guji_page_cv → report.slots` | 要拆函数，改动可能不小 |
| M3 | 8 | `gold.store/transfer → feedback.*`（3）、`feedback.lookup → eval.colgeom`、`feedback.vision → review.verdict_view`、`render.approx → feedback.events`、`render.overlay → gates.query`、`products.fp_migrate → clustering`（惰性） | 同上 |
| M4 | 4 | `utils.calibrate → steps`、`utils.font_calibrate/font_calibrate_direct → clustering.canonical/font_glyphs` | 与第二节的归一化下沉有关，建议同批或之后 |

**每批的做法**（照 cv#78 的规矩）：
1. 先读相关代码，确认改法与改动量，再动手，不先承诺数量；
2. 修一条就从 `tests/test_architecture.py::ALLOWED_UPWARD` 删一条（不删会红）；
3. 每批跑全量 `pytest tests/ -s`（已验证可在装好 `.[console,torch,dev]` 的环境跑，约 9 分钟）；
4. 合 cv main 前先 `send.py Mila`：PR 号＋改了哪些 `open_guji_cv/` 文件，她登记并核 19 步 `code_hash`；
5. **窗口甲前凡碰 `steps/`、`core/`、`code_deps` 先问 Mila。**

## 四、建议的时序

| 时间 | 做什么 |
|---|---|
| 窗口甲（10-20）前 | 不碰 `steps/`、`core/`、`code_deps`。可做：M1–M4 里**确认不碰这些目录**的小批（先问 Mila）；写文档 |
| 窗口当日 | 不做模块化。配合核指纹 |
| 窗口后第一轮 | 第二节 18 条＋统一接口 S2，和 W2／W4／PR2 同批合，`seed_admit` 版本号只升一次，十册只重跑一次 |
| 之后 | 把 `clustering`（约 2.4 万行，最大）按职责拆包（见下），这是另一件独立的事 |

## 五、`clustering` 拆包（更远的事，仅记录）

`clustering` 约 58 个文件、2.4 万行，扮演了「图像底层工具」「字形库与匹配」「候选与稀有字」「聚类」「播种与准入」多个角色，被 19 个包依赖，是依赖环的主要一环。
拆包没有现成方案，**我只在这里记一笔，没有设计**；要做的话应先出分块设计、评审通过再动手（项目驱动、计划优先）。

## 六、需要 Mila 定的

1. 窗口后第一轮是否把第二节 18 条并进来，还是单独再开一次窗口？（单独开＝十册 `seed_admit` 再过期一次）
2. 第三节 M1–M4 先做哪批？是否允许在窗口甲前做不碰 `steps/`／`core/`／`code_deps` 的那几批？
3. `clustering` 拆包是否立项。
4. 另（上一轮遗留）：`steps/step6_signals.py` 的删除已报备，等她登记后单开 PR；`scripts/_from_overview/` 等 10-20 后她逐目录点头再删，我出「目录→是否在 main→删/留」表。
