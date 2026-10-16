# Step 页面统一设计：五点结构 + 复用组件规格

- **状态**：设计已定，作为唯一权威规范供各 Step 任务书引用
- **来源**：用户 2026-09-11，见 [02-页面结构设计.md](02-页面结构设计.md)（原话，一字不改）
- **前置**：控制台重构 v2（[../finished/控制台重构v2/](../finished/控制台重构v2/)）已完成，
  路由骨架、状态摘要、产物查看器、各 Step 现有面板都已就位——**本文档是在这个基础上
  补齐结构，不是重新设计控制台**

> **给各 Step 任务书的用法**：任务书只写"你的 Step 现状 + 对照本文档 §三 的落位表
> + 引用 §四 的组件"，**不要把本文档内容抄进任务书**。本文档改了，所有任务书自动跟着新——
> 这是写本文档的唯一目的，别让它退化成"写一次就没人看"的档。

## 一、用户原则（五个板块，原话）

> 每个 step 整体重构一下这个进入的界面（如 `/vol03/step/step1/`），包括 5a-d 这些小步。

1. **页面选择器**：控制下面内容包括哪些页面，默认所有。
2. **第一板块：整体进度**——包括这一步的闸探测到的情况。
   - Step1 例：识别了哪些页，按页面类型分类（封面、职名页、正文）
   - Step7 例：多少自动放行、多少待审
3. **待人工裁决的内容**：根据不同 step 用不同展示方式，可能有多个 tab。
4. **产物**：让用户能看到所有产物，即使是没问题的。
5. **标注**：其它标注任务，如 Step1 可以标注多种，包括列探测、抬头有无。

**这五点是检查表，不是五个必选组件**——没有的板块可以不放，但任务书要写清楚
"为什么这一步没有 X"，不能是漏做。

```
┌─────────────────────────────────────────────┐
│ ① PageRangeSelector：页码/类型筛选，默认全选   │  ← 影响下面全部板块
├─────────────────────────────────────────────┤
│ ② ProgressGatePanel：进度摘要 + 闸判据         │
├─────────────────────────────────────────────┤
│ ③ 待裁决（Step 各自的面板，可能多 tab）        │
├─────────────────────────────────────────────┤
│ ④ ProductViewer：产物（已有组件，直接复用）    │
├─────────────────────────────────────────────┤
│ ⑤ 标注任务（Step 特有，不是每步都有）          │
└─────────────────────────────────────────────┘
```

## 二、四个跨 Step 复用组件

**先找组件里已经在用的东西，不要重新发明**——`ProductViewer`、`GateSummaryPanel`、
`usePages` 都已存在，本节只是把它们的复用边界说清楚，加两个新组件补板块①②的空白。

### 2.1 `PageRangeSelector`（新建）—— 板块①

**从哪来**：Step7Page.tsx 已经手写了一份"页范围输入框 + localStorage 记忆"
（`PAGES_KEY_PREFIX`、`loadSavedPages`），逻辑对但没抽出来，Step7 之外的页面
现在各写各的（多数干脆没有，直接吃 `usePages` 全量）。**抽出来给所有 Step 用**。

```tsx
// components/common/PageRangeSelector.tsx
interface PageRangeSelectorProps {
  book: string
  stepId: string              // localStorage key 用 `guji-${stepId}-pages:${book}`，Step 间不互相污染
  value: string
  onChange: (v: string) => void
  typeFilter?: {               // 可选：按页面类型筛选（Step1 的"封面/职名页/正文"用得上）
    options: { value: string; label: string }[]
    value: string
    onChange: (v: string) => void
  }
}
```

- 默认值 `'all'` 不是 `'dev_set'`——用户原话"默认所有"，Step7Page.tsx 现在默认
  `dev_set` 是历史遗留，迁移到新组件时**顺带改成 `all`**（除非某个 Step 有明确理由
  保留窄默认，写进任务书说明）。
- 页范围表达式复用 `usePages`/`fetchStatus` 已支持的语法（`dev_set` / `body` /
  `all` / `3-6,9`），不新造一套解析。
- `typeFilter` 是可选 prop，只有 Step1（封面/职名页/正文分类）这类有"页面类型"
  概念的 Step 才传；多数 Step 不传，只有页码范围一个筛选维度。

### 2.2 `ProgressGatePanel`（新建，从 `GateSummaryPanel` 拆出通用部分）—— 板块②

**从哪来**：`components/evals/GateSummaryPanel.tsx` 现在只服务评测页，硬编码了
三道已收闸的 `GATE_LABEL`，且统计口径是"页级 ok/blocked/missing + 拒因分层"——
这套形状**是对的**，但耦合在 evals 页面里，各 Step 页面拿不到。

**改法**：不是每个 Step 都已经"收成闸"（多数还是"判据已有，未收闸"，见
[流程与模块.md §1.3](../../流程与模块.md) 的八道闸现状表）。所以
`ProgressGatePanel` 要能兼容两种数据源：

```tsx
// components/common/ProgressGatePanel.tsx
interface ProgressGatePanelProps {
  book: string
  stepId: string
  // 状态摘要：五态计数，直接来自现有 /api/status（StepPage.tsx 已经在用，抽出来）
  statusCounts: { fresh: number; stale: number; missing: number; failed: number; blocked: number }
  // 闸/判据数据：已收闸的传 gateId 走 GateSummaryPanel 原逻辑；
  // 未收闸的传 customMetrics 渲染现成的判据数字（比如 Step1 的列数/w80/版框墨/抬头框）
  gateId?: string                                    // 闸2/闸3 等已实现的，见 evals/api.ts::GATE_IDS
  customMetrics?: { label: string; value: string; tone?: 'ok' | 'bad' }[]
  // 页面类型分类（Step1 例）：可选的分类计数条，不是所有 Step 都有
  typeBreakdown?: { label: string; count: number }[]
}
```

- 样式复用 `evals.css` 已有的 `.qgrid`/`.qk`/`.qv`/`.qs`/`.qchip`——这套统计卡片
  语言已经在评测页验证过，不用另起一套 class。
- **未收闸的 Step**（Step0/1/3/4/6/7/8 目前都是"判据已有，未收闸"）不要为了填这个
  组件就临时造假闸——`customMetrics` 就是为这种情况设计的：把现成的判据数字
  （已经在 README/eval 里跑出来的）摆进统一的卡片形状，不等真闸落地。
- Step9 是整册汇总不是逐页，`statusCounts` 五态计数这套不适用，Step9 用自己的
  体检表形状，不必削足适履塞进这个组件（见 §三 Step9 那行）。

### 2.3 `ProductViewer`（已有，直接复用）—— 板块④

`components/ProductViewer.tsx` 已经做到"手动输入页码 + 有数据就下拉快选 +
叠图/数值产物双栏 + 404 时给文字提示不给破损图标"。**各 Step 只需要确认自己的
产物类型已经能被它展示**：

- 传参数只需要 `book` / `step`（后端 `core/step.py` 的 step id）/ `pages`
  （用 `usePages(book)`）三个，不用改这个组件本身。
- 若某 Step 的产物有 `ProductViewer` 现在展示不了的形态（比如 Step9 的整册体检表
  不是"叠图+JSON"这个形状），**不要硬塞**，另建专属展示，在任务书里写明为什么
  `ProductViewer` 不适用。

### 2.4 待裁决区（板块③）：不抽象成组件，各 Step 保留自己的面板

**这条是刻意的，不是漏做**：`CutlinePanel`／`JiazhuPanel`／`ReviewPanel`／
`RarePanel`／`HarvestPanel` 等已有的裁决面板，形态差异很大（拖拽切线 vs
候选按钮 vs 表格批次），**硬抽象成统一组件只会两头不讨好**。板块③的"统一"
只体现在：
1. **位置固定**在页面结构里的第③个板块（页面选择器→进度+闸→待裁决→产物→标注）
2. **多个待裁决来源用 tab 切换**，不是垂直堆叠一大长条（Step7 现在是垂直堆叠
   `BlockingCutlinePanel` + `ReviewPanel`，够简单的 Step 可以保留堆叠，
   3 个以上来源的建议改 tab，具体看该 Step 任务书怎么定）
3. 各面板内部逻辑、交互、快捷键**原样保留**，不因为这次重构就顺手"优化"——
   跟 v1/v2 重构时的规矩一样：功能原样搬，不是借机重新设计交互。

## 三、九步 + 四小步落位表

协调者按 [流程与模块.md](../../流程与模块.md) 与各 Step README 现状初判，
**各道开工后核实/修正，以实测为准**。

| Step | ②进度+闸（`customMetrics`/`gateId`） | ③待裁决（现有面板） | ⑤标注 | 备注 |
|---|---|---|---|---|
| Step0 预清理 | 已处理页清单 + 闸0 数字（带内墨占比修前→修后，已落地，直接读） | 反色带候选确认（`scan_inverted_bands.py` 产出） | 缺陷类型标注（目前只反色带一类） | 多数书这步全空，页面要能优雅显示"无事可做" |
| Step1 边框界行 | ✅ 已完成（2026-09-11）。`gateId="border_detect_gate"`——**核实后闸1其实已实现**（本表原写"闸1未收"是滞后信息，实测 `gates/query.py::GATES` 早就登记了它），直接复用 `ProgressGatePanel` 走闸数据路径；`typeBreakdown` 用闸1 L1 判据（探出列数 != 版式列数）分"疑似正文/疑似非正文"两档，不细分封面/职名页（无现成判据，细分需另立方案） | 边框类裁决（cols/head/outer/colborder，已常驻） | 列探测标注、抬头有无标注（已有，`BorderReviewPanel` 的 cols/head 两个 tab 直接满足） | 见 [Step1-边框界行/任务书-页面结构统一.md](../finished/Step1-边框界行/任务书-页面结构统一.md) 完工记录 |
| Step2 单列射影 | `gateId="column_gate"`（直接接现成 `GateSummaryPanel` 逻辑；闸1也已实现，见 Step1 行） | 列级 mixed/clean 人裁 | 列级准入候选标注（若有产出） | 闸2 可视化已完成，本次是核对整合进新结构 |
| Step3 逐字切分 | ✅ 已完成（2026-09-11）。`gateId="row_segment_gate"`——**核实后闸3其实已实现**（本表原写"未收"是滞后信息，跟 Step1 闸1 同样情况），+ `customMetrics` 接 R1/R2/R2s/R2x/R3 尺子（`eval/rulers.py::measure`，随页范围联动） | CutlinePanel + JiazhuPanel（已有，两个 tab，不动） | 核实后 7 类缺陷里 4 类已有入口可标（夹注两类走 JiazhuPanel，界行残段/邻字残墨走 CutlinePanel 干扰标签），3 类（顶部被切/書被劈/范围外）真缺口，涉及新锚点设计，方案见 [finished/Step3-逐字切分/06-缺陷标注入口盘点.md](../finished/Step3-逐字切分/06-缺陷标注入口盘点.md)（已归档，暂不实现） | 见 [finished/Step3-逐字切分/任务书-页面结构统一.md](../finished/Step3-逐字切分/任务书-页面结构统一.md) 完工记录 |
| Step4 字框收缩 | R4 尺子 + flags 分布（truncated/contaminated/boundary_ink/frame_bars） | flags 人工核实（现缺入口，见已有04号卡） | 缝形态标注 | 04号任务卡目标一致，合并处理 |
| Step5-a 库匹配 | ✅ 已完成（2026-09-11）。匹配档位分布（same/unsure/diff 计数）+ 护栏触发计数（`glyph_match_summary`） | `GlyphMatchPanel` 单点查询调试工具（查询图与库里刻例并排比对，不是人裁交互——候选人裁涉及新准入通道政策，留给下一轮） | — | 先出方案（08号卡）再实现，无头 Chrome 实测通过 |
| Step5-b 生僻字候选 | ✅ 已完成（2026-09-11）。核实"待判位列表"后结论是不需要——该集合属于 Step7 review 队列口径，重复实现会口径分裂，本次不改代码 | `RarePanel`（已有，查询工具形态） | — | 核实结论见 5b-生僻字候选/03号卡 |
| Step5-c OCR候选 | ✅ 已完成（2026-09-11）。核实"大概率不需要独立页"判断仍成立，补板块②聚合数字（引擎在线状态+候选覆盖率，`ocr_candidates_summary`） | 无独立裁决（挂 Step7 卡片），维持现状 | — | 07号任务卡判断维持有效 |
| Step5-d 整理本匹配 | ✅ 已完成（2026-09-11）。补齐板块①页面选择器（`PageRangeSelector`），串到已支持 `pages` 参数的 `api_align_ref_summary` | 未锚定页排查（已有 8-gram 投票明细） | — | 已完成度高，核对后只缺①，已补 |
| Step6 上下文裁决 | 大模型调用统计（已完成）+ 闸6 数字（断言+弃权计数，未收） | 大模型调用明细（已完成，列表+详情） | 形近字/夹注短语表标注 | 已完成度最高，重点检查①⑤ |
| Step7 放行判定 | 判据A/B 实时数字（自动放行/人审比例，用户原话例子） | ReviewPanel + BlockingCutlinePanel（已有） | 异体三档裁决 | 用户例子点名这一步；本次顺带把手写的页范围选择器换成 `PageRangeSelector` |
| Step8 落库反馈 | 三条支线消费进度 | HarvestPanel（已有） | — | D5 已完成，重点检查① |
| Step9 结果整理 | **不适用五态计数**，用整册体检表自己的形状 | — | — | 整册汇总不是逐页，"页面选择器"这条也不适用，见 Step9 README §三 |

## 四、下发与写域

每个 Step 目录下的 `任务书-页面结构统一.md` 只写三件事：
1. 指向本文档（不复述内容）
2. 该 Step 的现状交底 + 对照 §三 的具体缺口
3. 写域：`console/frontend/src/pages/Step<N>Page.tsx` 及其子组件；
   新建/改动 `components/common/PageRangeSelector.tsx`、
   `components/common/ProgressGatePanel.tsx` 时要写 `cross` 单
   （这两个文件被多个 Step 共用，**谁先动手谁先建，后面的 Step 复用不要重复造**）。

**开工顺序建议**：先开一道把 `PageRangeSelector` / `ProgressGatePanel` 两个
共用组件建好（可以挑手上任务顺带做，比如 Step1 或 Step7），其余 Step 直接引用，
不要每道各自发明一份相似组件——**这正是写本文档要避免的重复**。

**不要求所有 Step 一次做完**：先出"对照 §三 的现状盘点"（哪些已满足、哪些缺），
缺口小的顺手做掉，缺口大的（如 Step5-a 要新建整套视图）先出方案再动手，
跟 v1/v2 一样的规矩——改的是所有人每天在用的工具。
