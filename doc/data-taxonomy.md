# 三类数据的定义与现状盘点

> 本文档只做**定义与现状盘点**，不搬移任何现有文件、不改任何代码路径引用。
> 新数据要放哪，看本文档判断；老数据暂时留在原处。
> 2026-09-11 首次写，随分布变化需要更新。

## 三个概念的关系

**benchmark（测试集）** 与 **gold standard（金标）** 不是并列的两类，是包含关系：
一个 benchmark 分片（如 `touching-cuts`）是一批样本的集合，每条样本里的标注答案
（如 `verdict`/`y` 字段）就是这条样本的 gold standard。"金标"是 benchmark 内部
每条记录携带的东西，不单独成类。

跟 benchmark 并列、性质完全不同的另外两类：

| 类别 | 回答什么问题 | 谁在读它 |
|---|---|---|
| **benchmark** | 这一步做得对不对、多准？（含每条样本的 gold standard） | 评测脚本，离线跑 |
| **guardrail** | 这一条不能自动过，必须拦住/排除/永不匹配 | 管线运行时，在线拦 |
| **statistics** | 跑下来实际产生了什么数字？（人审率、耗时、通道占比…） | 人看趋势，或回填判据 |

区分方法：**benchmark 是静态的"考卷+答案"，不参与线上判定**；**guardrail 是运行时
真的会被代码读取来拦截决策的规则/名单**；**statistics 是运行产生的既成事实记录**，
不是判据也不是拦截规则，只是"发生了什么"的账本。

## 现状盘点（2026-09-11）

### benchmark（含 gold standard）——`open-guji-dataset` 仓

集中、命名统一（统一金标信封 `items.jsonl`），见该仓 [STEP_MAP.md](https://github.com/open-guji/open-guji-dataset/blob/main/STEP_MAP.md)
按 Step 索引。这一类目前状态最好，不需要额外整理。

**2026-09-11 补充（Step2 数据盘点核实）**：`char-segmentation/column-warp`
115 条与 STEP_MAP.md 记的一致，但**同一分片下还有一个子目录
`legacy-page-anchor/`（25 条）没有单独出现在这份文档里**（STEP_MAP.md 本身
已经把它列成单独一行，只是本文档之前没提）——两者不是同一坐标系（前者是
"算法边线+逐列窗口"，后者是"人工金标边线+页级锚点"，见
`.claude/CLAUDE.md`"金标按输入口径拆成两套"那段），评测脚本
（`eval_column_warp.py`）不能把两套数字混着报，读这个分片时要注意区分。

**2026-09-11 补充（Step5-d 数据盘点核实）**：`open-guji-dataset` 仓
[STEP_MAP.md](https://github.com/open-guji/open-guji-dataset/blob/main/STEP_MAP.md)
第39行已经写明"Step5-d 整理本匹配：对齐金标是自动生成，无独立分片；人裁两本
对比未落 dataset 仓分片"，"已知空白"一节也把 Step5-d 与 Step0、Step7 并列为
"不受统一金标信封机制约束"——`align_label.py` 产出的 `AlignedLabel`（`equal`/
`replace` 采信闸过滤后的逐字位标签）**已有明确归类结论，不是盘点遗漏**：
它服务的是聚类/进库流程的对齐载体，不作为独立 benchmark 分片维护，现状与
STEP_MAP.md 记载一致，不需要改动。

### guardrail——`open-guji-cv` 仓，分散在 `config/` 与代码常量里

`config/` 目录里**混杂着护栏与非护栏配置**，需要先分辨：

| 文件 | 是不是 guardrail | 说明 |
|---|---|---|
| `config/crop_exclusions.jsonl` | 是 | 判非字/切坏的图块排除名单 |
| `config/crop_exclusions_released.jsonl` | 是 | 排除名单的已释放记录 |
| `config/confusable_human.json` | 是 | 人裁形近字护栏表 |
| `config/variants/never_group.json` | 是 | 异体字永不合并名单 |
| `config/rekey_502fa04d0c_to_current.json` | 是 | 库重键映射（防止旧 id 误配） |
| `config/confusable_font_clean.json` / `_degraded.json` | 不是 | 形近字候选来源（字体渲染派生），不是拦截规则 |
| `config/dicts/*`、`config/gloss/*`、`config/ids/*`、`config/kangxi/*`、`config/charset/*`、`config/fonts/*` | 不是 | 字典/术语/字形资源，是输入数据不是护栏 |
| `config/variants/local_edges.json`、`report.json` | 不是 | 异体关系图与报告，是派生数据 |

代码常量形式的护栏（不落文件，写在 `.py` 里）：`NEVER_MATCH_FAMILIES`、
`SEMANTIC_MERGED_PAIRS` 等。这类天然没有"存放位置"问题，本文档不管它们，
只管落成文件的那部分。`align_label.py::clean_labels()` 的 `ink_ratio < 0.05`
近空格位判据、`frame_bars` 版框横线判据同属此类——运行时会拦 `replace` 段
标签是否采信，但判据写死在代码里、不落配置文件，本文档不单独立目。

**现状问题**：真正的护栏文件（5 个）淹没在 `config/` 三十多个文件里，
不看内容分不出哪些是"运行时会拦人"的规则、哪些只是普通配置数据。

**2026-09-11 补充（Step3 数据盘点核实）**：`config/crop_exclusions.jsonl`
逐条实测**只被 Step5+（`clustering/`、`feedback/`、`steps/seed_admit.py`
等）读取**，Step3（`row_segment.py`/`row_boundaries.py`/`jiazhu_split.py`/
`seam.py`）完全不引用任何 `config/` 文件——与本文档"Step3 切分层大概率
不用"的猜测一致，实地 grep 已证实，结论不改。但发现**guardrail 的产出方
与消费方可能不是同一个 Step**：`crop_exclusions.jsonl` 里 `origin: human`
的条目部分源自 Step3/Step4 切分审阅反馈（见
`.claude/doc/jiazhu_defects_for_segmentation.md`），只是写入后只在 Step5+
被读取用于拦截——判断"这份 guardrail 归哪个 Step"时，要分清"谁写入"和
"谁读取来拦截"，不能只看写入来源。

**2026-09-11 补充（Step2 数据盘点核实）**：Step2 三个核心文件
（`steps/column_warp.py`、`utils/column_projection.py`、`gates/column_gate.py`）
逐个 `grep "config"` 实测**零匹配**——一个 `config/` 文件都不读，不止不读
护栏文件，连非护栏的字典/字体资源都不读。与 Step3 的结论（"完全不引用任何
`config/` 文件"）一致，Step1-2 这段几何层看起来都不碰 `config/`。

顺手核实了一个容易看错的地方：`feedback/routes.py` 里有两条命中
`target.step: column_warp` 的路由（`kind: band` 与 `kind: border_class`），
乍看像是"Step2 的路由规则"，但**这条路由表本身不是 guardrail**——它不拦截
任何决策，只是把人裁事件转发给 `gold_add` 消费者写入
`char-segmentation/column-warp` 分片，本质是"喂 benchmark 的管线代码"，
不满足 guardrail"运行时真的会拦"这条定义，判断时不要被"路由表"这个名字
和"写着 Step2 名字"这两点误导进 guardrail 类。

### statistics——分散在两个仓

| 文件/目录 | 仓 | 内容 |
|---|---|---|
| `output/review_rate_history.jsonl` | open-guji-cv | 人审率台账，按批次追加 |
| `output/ocr_result.json` / `ocr_summary.md` | open-guji-cv | OCR 引擎评测的一次性结果 |
| `output/frame_geometry.json` / `gutter_straightness.json` | open-guji-cv | 几何判据的一次性量测结果 |
| `output/llm_context_evalset/report_*.{json,md}` | open-guji-cv | 大模型接入实验的多引擎对照报告 |
| `output/crop_exclusion_receipt.jsonl` | open-guji-cv | 排除名单变更的操作留痕（介于 guardrail 变更记录与 statistics 之间，归 statistics：它记录的是"发生了什么"不是"规则本身"） |
| `open-guji-dataset/feedback/events/*.jsonl` | open-guji-dataset | 人裁事件流（只追加） |
| `open-guji-dataset/feedback/consumed/*.jsonl` | open-guji-dataset | 事件消费记账（幂等） |

**现状问题**：`output/` 目录名太泛（"输出"可以是任何产物），完全没有标出
"这是统计量"；且台账类（`review_rate_history.jsonl`，持续追加、要看趋势）与
一次性报告类（`ocr_summary.md` 之类，跑一次留一份快照）混在同一层，
性质不同却没有子目录区分。

**2026-09-11 补充**：新加了 `eval/throughput.py`（`guji check throughput <book>`），
一键产出逐页输入输出量、自动放行通道占比、各 Step performance 三块 statistics，
不落文件、每次现算——这类"跑一次现查"的统计不需要落盘也算 statistics 的一种，
不要求所有 statistics 都必须是台账文件。

**2026-09-11 补充（Step3 数据盘点核实后）**：`eval/rulers.py` 的四把尺子
（R1/R2/R2s/R2x/R2c/R3/R4）之前没有明确分类——它们只读产物、不落盘、不参与
线上判定（闸只是把 R2/R2s 的分类结果写进 `flags` 供人看，不拦），与
`throughput.py` 是同一种"跑一次现查"的 statistics，本文档此前完全没提到
这个模块，属于盘点空白，现予补全归类：**R1-R4 归 statistics**，不是
benchmark（不含 gold standard、不是静态考卷）也不是 guardrail（不拦截）。

**2026-09-11 补充（Step2 数据盘点核实，新发现一类本文档三分类都装不下的东西）**：
`gate_manifest`（`column_gate` 落盘在 `products/<book>/column_gate/`，
Step3 `row_segment.py` 与引擎 `core/pipeline.py` 都会读它）**不属于
benchmark / guardrail / statistics 里的任何一类**：

- 不是 benchmark——它不含人工标注答案，也不是拿来"离线评这一步准不准"的。
- 不是 guardrail——虽然它确实在运行时被下游读取来决定"这一列能不能往下走"，
  但 guardrail 的定义是**人工维护的静态名单/规则**（写死的阈值表、排除名单），
  `gate_manifest` 是**每次运行现算出来的裁决结果**，跟着输入图像和算法版本变，
  不是人在维护的一张表。
- 不是 statistics——它不是"发生了什么"的既成事实账本，是**流水线里游到下一步
  的正式产物**，`row_segment.py` 靠它决定要不要处理某一列，删掉它下游会跑不动，
  这跟"人看趋势用的台账"性质完全不同。

这是**交接产物**（pipeline product / 闸的裁决结果），本文档目前的三分类框架
是从"这份数据服务什么目的"切的，没打算覆盖"Step 之间流转的正式产物"这条线——
`products/` 目录下的东西本来就有自己的一套体系（`ProductStore`/`Manifest`，
见 `doc/console_architecture.md`），不需要也不应该被塞进 benchmark/guardrail/
statistics 三选一。**这条留给协调者定夺**：如果确实需要给"交接产物"单独立
一类，应该在本文档加一节说明"哪些属于 `products/`、不在本文档管辖范围"，
而不是勉强把 `gate_manifest` 分到三类之一；`eval/rulers.py` 的 R1 是"读
`gate_manifest` 现算出来的统计量"，这条本身仍然成立、不受此结论影响
（R1 是 statistics，`gate_manifest` 是它的输入，两者是不同的东西）。

**2026-09-11 补充（Step5-d 数据盘点核实）**：`products/<book>/align_ref/p*.json`
（`PageAlignRef`，Step5-d 输出）与 `gate_manifest` 同属这一类交接产物——
`seed_admit` 等下游 Step 直接消费它，不是人工维护的静态规则、也不是离线
评测用的考卷+答案、更不是"发生了什么"的既成事实账本。与 `gate_manifest`
唯一的区别是它不参与拦截判定（`align_ref` 本身不是闸，四路证据里任一路
缺席只降级不阻塞，见 `Step5-字符识别/README.md`），但这不影响它归入
"交接产物"这条待定类别——判断标准是"下游是否靠它继续跑"，不是"是否拦截"。

## 以后新数据往哪放（判断规则，不要求现在搬旧数据）

新增一份数据前，先问三句话：

1. **它是用来"离线评这一步做得好不好"的一批样本 + 答案吗？**
   → 是，放 `open-guji-dataset` 对应 Step 的分片下，走 `doc/making-datasets.md` 流程。
2. **它是"运行时真的会被代码读取来拦截/排除某个决策"的名单或表吗？**
   → 是，放 `open-guji-cv/config/`，文件名带 `_exclusions` / `_never_` /
   `never_` 之类能一眼看出"这是拦截规则"的词根（现有 5 个护栏文件已经这么做，
   照此惯例延续，不需要新开子目录）。
3. **它是"跑完之后产生的既成事实记录"（台账/报告/事件流）吗？**
   → 是，且**持续追加、要看趋势**的放 `open-guji-cv/output/`（台账类）或
   `open-guji-dataset/feedback/`（事件类）；**跑一次留一份快照**的报告
   （如引擎对照报告）放 `output/<实验名>/`，不要和台账文件平铺在 `output/` 根目录。

不属于以上三类之一的（字典、字体、术语表、派生的关系图），按现状继续放
`config/` 或 `corpus/`，不是本文档管的范围。

**2026-09-11 补充（Step5-d 数据盘点核实）**：`corpus/zongmu_wenyuange_wikisource.txt`
（现役，`align_ref`/`context_decide` 的默认整理本语料）与已退役的
`zongmu_wuyingdian_reference.txt`、`zongmu_wikisource_reference.txt` 同属
这条兜底——是跨步骤共享的输入资源（Step5-d 对齐、Step6 上下文裁决都读），
不是样本+答案、不拦截决策、不是既成事实记录，性质与 `books/*.yaml` 的
版式常量一档，继续放 `corpus/` 即可，之前盘点 Step2/Step3 时没提到这一项，
现补记。

**2026-09-11 补充**：`open_guji_cv/books/*.yaml`（如 `vol01.yaml`，记
`chars_per_line`/`expected_cols` 等版式常量）也不属于以上三类——它是
Step1-8 各步都会读的版式先验配置，性质与"字典/字体/术语表"一档相同。
之前盘点 Step3 数据时漏了这一项（不在 `config/` 目录下，容易被忽略），
现补记：这类"跨步骤共享的版式常量"，判断规则同上——不是样本+答案、
不拦截决策、不是既成事实记录，继续放它现在的位置即可，不需要新分类。

**"退役"不等于"废弃"**：`char-segmentation/row-boundaries`、
`char-segmentation/cell-truncation` 两个 benchmark 分片标注为"已退役"
（旧坐标系，不再扩充新样本），但其 README 记录的历史实验结论（弹性 DP
参数网格搜索、空白区间波谷丢弃 bug 的根因定位）仍是现行判据设计的依据，
不是内容作废。引用"退役分片"时按字面理解成"数据没用了"会漏掉这层历史
依据，看这类分片时留意 README 里是否有这种设计沿革记录。

## 不做的事（本次明确排除）

- 不重命名 `config/`、`output/`、`feedback/` 目录本身。
- 不给已有文件改名或搬家——它们已被主代码与多个脚本硬编码引用，
  搬动需要同步改代码，且当前仓里有其他并行任务在跑，此时动路径风险高。
- 不建 `guardrails/`、`statistics/` 新目录——即便只做软链接，也要处理
  Windows 符号链接的额外权限问题，收益（换个地方能找到）小于成本，
  上面的表格已经起到"从文档能查到实际在哪"的作用。

如果以后确实需要物理重组（比如 `config/` 文件数量继续涨到分不清），
再另开一个任务书评估搬移成本，本文档到那时候可以升级为迁移计划的基础。
