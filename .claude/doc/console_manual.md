# 控制台使用手册

给**用这套东西干活的人**。架构为什么这么设计看
[console_architecture.md](console_architecture.md)，这里只讲怎么用。

---

## 0. 起步

```bash
cd D:\workspace\open-guji-cv

# 首次：建环境（仓里的 venv/ 已死，别用）
uv venv .venv --python 3.12
uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented

# 起控制台
.venv/Scripts/python -m open_guji_cv console
# → http://127.0.0.1:8640/ ，会自动开浏览器；加 --no-browser 不开
```

控制台只监听 `127.0.0.1`。要在 iPad 上用就走 Tailscale 连到这台机器。

**8 个 tab**：总览、运行、产物、审查、切线、夹注、评测、异体。顶栏的「册 / 管线 / 页」
是全局选择，换了它下面所有视图跟着变。（本手册目前只详细讲前四个 + 评测，切线／夹注／
异体三个 tab 的用法待补——先看 §9「重构后的新事实」了解代码在哪。）

---

## 1. 总览：现在跑到哪了

左侧选册即进总览（`/<book>/`），四张卡片：**总进度**、**待办**、**异常数据**、
**运行参数**。2026-09-11 重构掉了原来那张「每步 × 每页」的巨型状态矩阵
（vol01 有 9 步 × 206 页 ≈ 1800 格，挤在一屏看不出整体进度）——逐页细节去
对应 Step 页面查，总览只回答「跑到哪了 / 接下来干什么 / 有没有事要看」。

**总进度**每步一条进度条，数字是 `fresh 产物 / 全书页数`，括号内是同一步在
`dev_set` 12 页小集上的 fresh 数。两个口径并列：全书那份看真实进度，小集那份
调参时看一轮跑完没有。Step5「字符识别」展开成 5-a / 5-b / 5-d 三条子行
（5-c OCR 候选默认关闭，本书启用后才出现）。点步骤名跳到该 Step 页面。

> ⚠️ **2026-09-13 修**：此前总进度不传页范围，走的是接口默认 `dev_set`，
> 只统计 12 页，标题却写「全书页数」——看着像整本书跑完了，其实只跑了 12 页。
> 现在固定按 `all` 取（vol01 206 页，实测 ~1.3s，不必另做聚合接口）。

进度条大面积显示「过期」常常是正常的，但**别照着 code_rev 去理解**
（2026-09-18 实测订正）：指纹里参与比对的是 `code_hash`——**这一步自己的模块
加上它声明的 `code_deps` 的源码字节哈希**，不是 `code_rev`（git HEAD）。
`code_rev` 只写进 manifest 记账，不参与判新鲜。

所以：改了与某步无关的代码，那一步**不会**过期；只有改到它的 module 或
`code_deps` 里列的模块才会。查「为什么过期」按这个顺序：

```
现算 fingerprint ≠ manifest.fingerprint
  → 比 params_hash：不同 = 参数变了
  → 比 upstream：不同 = 上游产物变了（那就去看上游）
  → 都相同 = code_hash 变了，看这一步的 module 与 code_deps 最近谁动过
```

实例：bxgb 的 `border_detect` 显示过期，`params_hash` 与 `upstream` 都一致
——查下来是它的 `code_deps`（`border_geometry` / `peak_line_search`）在
9-16、9-17 被改过，而产物是 9-15 跑的。这是指纹机制在正常工作。

**待办**给的是**正文页**口径（`page_type == body`，vol01 为 108 页），
与总进度的全书 206 页不是一个分母——总进度含目录页 / 职名页等非正文页。

**页范围**三种写法：`dev_set`（每册固定的 12 页分层小集）、`all`（全书）、
`3-6,9`（页号表达式）。日常调参用 `dev_set`，几十秒一轮；全书跑放后台。

---

## 2. 运行：跑管线

「运行」视图填四样：

- **从 / 到步骤**：只跑一段。改了 Step2 就选 `column_warp` → `cell_shrink`，
  Step1 不用重跑。
- **页**：同上三种写法。
- **参数覆盖**：JSON，如 `{"column_gate": {"width_tol": 0.2}}`。留空用生产默认值。
- **强制重跑**：勾上则无视指纹，全部重算。平时不用勾——**跳过是特性不是偷懒**，
  没变的东西重算一遍只会浪费时间。

按「入队」。任务串行执行，日志实时流式显示。点任务行看它的日志。

**跑完看总览**：受影响的步骤应该变绿。如果某页红了，鼠标悬停看错误——引擎逐页
记录，一页失败不拖垮整轮。

⚠️ **状态是相对某套参数的**。用参数覆盖跑出来的产物，在默认参数视角下**永远显示过期**
——指纹里含参数，这是对的，不是 bug。总览会自动带上「运行」框里填的那套覆盖来看状态
（矩阵标题旁会显示「按参数覆盖看：…」）。所以：**别清空参数框再去看总览**，否则刚跑完的
东西照样满屏黄。想对比两套参数，就在参数框里换着填。

### 命令行等价

```bash
# dev_set 12 页跑完整链
.venv/Scripts/python -m open_guji_cv pipeline keben_body_v2 vol01

# 只跑一段、指定页、改参数
.venv/Scripts/python -m open_guji_cv pipeline keben_body_v2 vol01 \
    --from column_warp --to row_segment --pages 24,42 \
    --params '{"column_gate": {"width_tol": 0.2}}'

# 只跑一步
.venv/Scripts/python -m open_guji_cv step border_detect vol01 --pages 24

# 看状态
.venv/Scripts/python -m open_guji_cv status vol01
```

---

## 3. 产物：看结果对不对

选步骤与页，按「查看」。左边是**叠图**（原图上画出这一步的产物），右边是**数值产物** JSON。

各步叠图画的是什么：

| 步骤 | 叠图上能看到 |
|---|---|
| `border_detect` | 红线界行、蓝线上下版框、抬头框标记 |
| `column_warp` | 逐列窗口的左右边线与列号 |
| `column_gate` | 每列过没过闸、页级 period 与 ref_w |
| `row_segment` | 绿框字格（多边形，弯页是梯形） |
| `cell_shrink` | 紧框；带 flags 的显红 |

**顶部那行灰字**是这份产物的身份证：单位键、指纹、状态、耗时、代码版本。
两次结果不一样时先比指纹——指纹相同而结果不同，说明有不确定性，那是 bug。

### 存储：数值长期，图像即算

产物目录 `products/` 里**只有 JSON**（两册各 12 页约 2 MB）。列图、字块这些派生图像
在 `cache/`（同样规模约 34 MB），可以随时删，下次要用时自动重算。

```bash
.venv/Scripts/python -m open_guji_cv cache usage          # 看占用
.venv/Scripts/python -m open_guji_cv cache prune --limit-gb 5   # 压到 5 GB
```

---

## 4. 审查：人裁与反馈

### 4.1 批次是人裁的调度单位

一批卡片、一个 URL 或一个控制台页面、一份裁决。批次表取代了手写的
`artifacts/README.md` 台账。

```bash
# 建批次
.venv/Scripts/python -m open_guji_cv batch new border-cols-r2 \
    --title "界行切分裁决台 第二轮" --step border_detect \
    --transport artifact --url https://claude.ai/code/artifact/12a167f9 \
    --shard border-detection/column-split --n-cards 63

.venv/Scripts/python -m open_guji_cv batch list        # 看所有批次
.venv/Scripts/python -m open_guji_cv batch list --md   # 出台账 markdown
```

**两种传输**：

- `artifact`：卡片发布成 claude.ai 页面，你在手机上点。**复审必须重发到同一 URL**，
  用户书签和页面本地状态都锚在上面。
- `server`：页面直接跑在控制台，裁决实时回传，断网进本地队列、重连补发。

### 4.2 收割：把裁决收回来

artifact 模式裁完之后，用 `Artifact action:"read"` 读回 HTML，粘进控制台
「收割」框，选批次，按「收割」。

**四种旧格式都认**，自动识别：审查页 HTML、裁决 JSONL、种子事件日志、朱批 JSON。

```bash
.venv/Scripts/python -m open_guji_cv events harvest border-cols-r2 --file 读回的.html
.venv/Scripts/python -m open_guji_cv events list border-cols-r2
```

⚠️ **发布前必须先收割**。不先读回就重发，会盖掉线上还没收割的裁决。批次登记里有这道闸。

### 4.3 路由：裁决自动变成金标

按「试算（不落库）」先看会写什么，确认后按「按路由表消费」。

路由表在 `feedback/routes.yaml`（缺省用内置的），规则形如「`verdict` 类事件 +
`border_detect` 步骤 → 落进 `border-detection/column-split` 分片」。

**消费是幂等的**：同一批消费两次，第二次什么也不做。

```bash
.venv/Scripts/python -m open_guji_cv events route border-cols-r2 --dry-run
.venv/Scripts/python -m open_guji_cv events route border-cols-r2
```

### 4.4 金标分片

审查视图下半部分是 35 个金标分片表：载体、条数、状态分布、抽样分层。

- **载体 `items`** 是已迁到统一信封的（34 个已迁完）；其余显示旧载体名，可点「迁移」。
  迁移**不删旧文件**，两边并存。
- **「漂移检查」**按图像指纹比对：图没变的金标照旧成立，图变了的要回去重看。
  这是产物重生之后必做的一步——**先查漂移，再谈数字**。

```bash
.venv/Scripts/python -m open_guji_cv gold shards
.venv/Scripts/python -m open_guji_cv gold migrate <分片>          # 单个迁
.venv/Scripts/python -m open_guji_cv gold drift <分片> --apply    # 漂移检查并标 stale
PYTHONPATH=. .venv/Scripts/python scripts/verify_gold_migration.py --all   # 校验迁移无损
```

---

## 5. 评测：算法改动有没有变好

「评测」视图列出 27 个评测器。可跑的有「跑」按钮，跑不了的显示原因
（需要 OCR 引擎、重活、需要语料、需要中间产物）。

「跑全部轻量的」批量跑 17 个可跑的，几分钟。

**三种状态**：

| 状态 | 含义 |
|---|---|
| `ok` | 跑通了，指标见表 |
| `regressed` | 跑通了，但**回归门判定不合格**——这是有效结论，不是跑挂 |
| `failed` | 没跑起来（缺产物 / 报错） |

分清 `regressed` 和 `failed` 很重要：前者是门拦住了东西（该去看算法），
后者是门本身坏了（该去修评测）。

**报告里必看三样**：

- **分母**：比值要连着分母读。精确率从 0.71 掉到 0.52 可能不是退步，是缺陷基数变小了。
- **过期金标数**：非零就说明这些数字可能挂在已失效的键上，要先做漂移检查。
- **跳过的 uncertain 数**：人工也判不准的样本不进指标。

```bash
.venv/Scripts/python -m open_guji_cv eval list             # 看有哪些、能不能跑
.venv/Scripts/python -m open_guji_cv eval run              # 跑全部轻量的
.venv/Scripts/python -m open_guji_cv eval run normalize layout
```

---

## 6. 典型工作流

### 改了 Step2 的参数，想知道好没好

1. 运行视图：从 `column_warp` 到 `cell_shrink`，页选 `dev_set`，参数覆盖填 JSON，入队；
2. 总览：确认这四步变绿，Step1 应该纹丝不动；
3. 产物：挑一两页看叠图，肉眼确认没跑偏；
4. 评测：跑 `column_warp`、`instance_quality`，看指标与之前比；
5. 觉得对了，再对全书跑。

### 收一轮人裁

1. 建批次（记下 URL）；
2. 裁完，`Artifact read` 读回 HTML；
3. 审查视图粘贴、收割；
4. 试算 → 消费，裁决进金标；
5. 跑相关评测，看金标扩充后指标怎么变。

### 上游重跑之后

1. 总览确认下游全变黄（过期是对的）；
2. 审查视图对相关分片按「漂移检查」；
3. 有 recheck 的说明图变了，那些金标要回去重看，**别直接信旧数字**；
4. 重跑产物，再跑评测。

---

## 7. 排错

| 现象 | 多半是 |
|---|---|
| 某步整列斜纹（阻塞） | 上游没跑或失败了，先看上游 |
| 跑完还是黄的 | 参数覆盖没生效？指纹含参数，改了就该变绿 |
| 产物页图裂了 | 缓存被清了，刷新页面会自动重算 |
| 评测 `failed` 说「缺产物」 | 那个评测要 `output/<book>/` 下的东西，先跑管线 |
| 评测数字很怪 | 先看报告里的过期金标数；非零就先做漂移检查 |
| 收割回来 0 条 | 读的是不是审查页本身？截图和摘要里没有裁决数据 |

**日志**在 `runs/<任务号>.log`，任务记录在 `runs/<任务号>.json`，控制台重启不丢。

---

## 8. 目录速查

| 路径 | 是什么 | 进 git 吗 |
|---|---|---|
| `products/<册>/<步>/pNNNN.json` | 数值产物（几何、类别、参数） | 否，可重算 |
| `cache/<册>/<种类>/<键>.png` | 派生图像（列图、字块） | 否，缺了现算 |
| `runs/` | 任务日志与记录 | 否 |
| `open_guji_cv/books/*.yaml` | 每册的图源、dev_set、版式常量 | 是 |
| `open_guji_cv/pipelines/*.yaml` | 管线定义（步骤顺序） | 是 |
| `../open-guji-dataset/<分片>/items.jsonl` | 统一金标 | 是 |
| `../open-guji-dataset/feedback/events/` | 人裁事件 | 是 |
| `review/batches/*.json` | 批次登记 | 否（真源随数据集仓） |
| `output/<册>/phase2..phase9` | **v1 遗留产物**，v2 链不碰它们 | 现在还在，P3 时清 |

v2 链与 v1 产物完全解耦：Step1 直接吃原始扫描，Step4 由控制台把列图传给
`CharExtractor.extract_page`，不走它那个按 `s4_deskew` 等目录名找图源的整册入口。

---

## 9. 重构后的新事实（2026-09-10 补，控制台重构 `a200e37` 已合入 main）

- **46 条路由**现在在 `console/routers/` 下按**七类事**分成 11 个文件，`app.py`
  只做装配（建 app、挂中间件与静态、`include_router` ×11）。分类见
  `routers/__init__.py` 的表：`registry.py`(5)／`runs.py`(7)／`products.py`(6)／
  `feedback.py`(8)／`gold.py`(3)／`evals.py`(7)／`review.py`(3)／`cutline.py`(2)／
  `jiazhu.py`(1)／`rare.py`(2)／`variants.py`(2)。加一条路由先找它属于哪一类，
  写进那个文件即可，`app.py` 不用动。
- **领域逻辑搬到了 `console/` 之外**：`render/overlay.py`（叠图）、
  `review/cards.py`（待审卡片）、`eval/quality.py`（评测质量看板）、
  `clustering/rare_panel.py`（生僻字候选）等——路由文件只做参数解析与调用，
  真正的逻辑独立成模块，**CLI 与云端道可以直接 import，不必经过 HTTP**。
- **CLI 出口**：v2 子命令从 10 个涨到 16 个，现在是 `pipeline`／`step`／`preclean`／
  `status`／`console`／`cache`／`batch`／`events`／`eval`／`gold`／`product`（产物与
  图像：show/manifest/raw/overlay/patch）／`check`（判据与体检：quality/rulers/
  round/rate）／`cards`（待审卡片数据：dingzi/cutline/jiazhu/groups）／`rare`
  （生僻字候选）／`variants`（本书用字账，只读）／`runs`（控制台任务：
  list/show/cancel/log）。**这份列表照 `cli_v2.py` 的 `add_parser` 实况写，
  方案文档是计划，代码才是实况。**
- **前端切成了 `static/js/panels/*.js`**（`overview.js`／`run.js`／`products.js`／
  `review.js`／`cutline.js`／`jiazhu.js`／`evals.js`／`variants.js`，另有
  `groups.js`／`harvest.js`／`health.js` 等子面板），公共逻辑在 `js/api.js`／
  `js/state.js`／`js/shared/domain.js`，`js/main.js` 只做装配。**改一个面板**：
  先改对应 `panels/<名字>.js`，涉及新接口再改 `console/routers/<那一类>.py`，
  样式在 `css/panels.css`。

**改控制台之后跑这两条验收关**：`tests/test_console_routes.py`（路由）、
`tests/test_console_tabs.py`（8 个 tab 都渲染得出来）。

## 10. 页面结构：四板块（2026-09-18）

§9 写的前端是 `static/js/panels/*.js` 那一版；现在是 `frontend/src`（React+Vite），
**且每个 Step 页面固定四板块**。改页面前先认这个结构。

```
① 页范围   PageRangeSelector   ← 唯一源，控制下面所有板块
② 总览     ProgressGatePanel（闸摘要）/ StepStatusSummary（产物新鲜度）
③ 裁决台   各步自己的面板；多个时 StepLayout 自动排成 tab
④ 产物台   ProductViewer（按页）/ CellLookupPanel（按坐标）
```

骨架是 `components/common/StepLayout.tsx`，四个槽位都收 ReactNode，
它只管顺序与 tab，不替各页决定内容。

### 改页面怎么落手

| 想做什么 | 改哪 |
|---|---|
| 给某步加一个裁决台 | 页面的 `reviews` 数组加一项；面板接 `pages?: string` |
| 加一种页范围取值 | `PAGE_RANGE_PRESETS`（前端只是暴露，后端 `resolve_pages` 早就支持） |
| 加一个裁决问题 | **先在 `feedback/questions.py` 登记**，再改路由表，最后前端发 `payload.question` |
| 改总览指标 | `ProgressGatePanel` 的 `customMetrics` |

### 三条容易踩的

- **页范围只能有一个源**。面板内部那份 `usePersistedPages` 是兜底（非 Step
  页面还在用），页面传了 `pages` 就以页面为准。两个台各用各的页范围时，
  同一批用例会看起来「不重合」——Step3 拖切线台与 Step7 切分裁决台就这么
  误会过很久，而机制上 `blocking ⊆ all` 恒成立。
- **裁决台只做可裁，自由浏览归板块④**。让两处都能提交的话，批次归属、
  touched 集合、已裁去重要各维护一套。
- **不是每页都该有四块**。Step6（LLM 调用日志）、Step8（收割台账）与页无关；
  Step9 没有对应的后端 Step id（现场渲染，不是「选一页看产物」）。
  硬套只会造出空面板。

### 验收关

改控制台跑这几条：`tests/test_console_routes.py`（路由清单 + 行为快照，
加路由要同步改那份账本）、`tests/test_questions.py`（登记表与路由表一致）、
`npx tsc -b`（前端类型）。

## 切线 tab · 「坐标过期重标」模式（2026-09-14）

页码框填 **`drift`**（其余照常：条数、批次、只看未裁），载入的是**金标 `col_h` 与当前列图高不一致**的那批
切点——列图在标注后被 Step2 重矫正过，旧金标的 `y`/`polyline` 已不在当前坐标系（2026-09-14 实测 381 条，
其中 302 条能按 slot 对回当前 cells）。卡片 id 沿用金标 id，人重裁后 `cutline` 事件经 gold_add **按 id upsert**，
`y / col_h / polyline` 换成当前坐标系。这一档不按「已在金标里」跳过（它们本来就在），只按本批次事件去重；
`kind` 选项忽略；期望字沿用金标（不重新对齐整理本）。返回值里 `drift_skipped` 列出对不上的原因
（`column_not_ok` 当前产物不可用 / `slots_not_found` 格数结构变了 / `no_col_h(cand-verdict)` 新式「选切分方案」裁决本就不算过期）。
批次名建议 `<册>-cutline-drift`。裁完照常 `guji gold import --shard char-segmentation/touching-cuts` 进数据集。
代码：`eval/touching.py::drifted_boundaries`、`console/routers/cutline.py`；由来见 overview `Step3-逐字切分/09-切线金标坐标过期重标.md`。

**标错了怎么改（2026-09-14）**：取消「只看未裁」即时生效，已裁的卡按判定配色回到列表，← 回去按 U 重做。
刷新过页面：批次名照旧、取消「只看未裁」再载入——drift 档会把本批次里**对着当前坐标系裁过的**条目（事件 col_h ≈ 当前列高）
也出出来（`redo=True`），因为重标一落定 col_h 就是当前值、不再「过期」，不带批次名就找不回。
drift 档的「只看未裁」**不按批次事件跳过**（重裁过的自己出池）：批次框留空会落到 `vol03-cutline` 这种老批次，
按事件跳过会把整册算成已裁（2026-09-14 实测 94 条只剩 4 条）。数据按 id upsert，与批次名无关。
右栏按钮分「判定 / 干扰 / 工具」三组，快捷键印在按钮角标上；顶部说明折叠在「怎么裁 · 快捷键速查」里。
前端同理：drift 档载入时，批次里的裁决只有 col_h ≈ 当前列高的才算「已裁」（否则勾「只看未裁」全隐藏、不勾把旧坐标系的
30 点折线套在新图上，2026-09-14 实锤）；`/api/cutline/verdicts` 因此每条带 col_h。

**回车的含义（2026-09-14 改）**：回车 = 把卡片当前状态落定。点过一种非直线切法、线没动、没在画折线 → 记为「切法正确」（cand）；
其余同以前：线动过 = moved，没动 = 现切点正确。之前回车只记直线 ok，选中的切法被丢掉。

**复核清单模式**：页码框填 `list:<名字>`，读 workspace `feedback/lists/<名字>.txt`（一行一个金标 id，`#` 开头是注释），
按 id 出卡，不管坐标过没过期。用途：机器筛出可疑条目让人只看这几张。首个清单 `cand_recheck`（28 条：drift 重标里
多候选卡上按了 ok 的，可能本想选切法）。批次名建议 `<册>-cutline-recheck`。

**切线卡里的候选（2026-09-14 起）**：产物 `cut_candidates` 每条候选多了 `agree`（U-Net 裁判的置信加权一致率），切点多了 `chosen_by`
（rule / unet / human）。`chosen_by=unet` 表示裁判改选过；`agree` 全为 None 表示这个切点没过裁判（池里只剩一条，或裁判不可用）。

