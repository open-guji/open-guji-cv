# 把 cv 拆成 pipeline 和 pipeline manager（设计，2026-10-27）

> 起因：sheldon 2026-10-26——cv 包太大。拆成两部分：**pipeline**（图像处理、切分、文字识别）和**pipeline manager**（调用 pipeline，并管工作区、原图取图、打包上传中心库、R2、任务库等一切对外交互）。
> 目的：改 manager 的功能时，**pipeline 不用发新版本**。分界线：**凡会影响最终识别产物的，一律在 pipeline；其余大部分在 manager。**
> 本文只是设计与迁移方案，**没有任何代码改动**。数字来自对 `dev`（v0.5.26 之后）的静态 import 分析，脚本思路见第九节。

## 一、一句话结论

1. **pipeline 继续叫 `open_guji_cv`（本仓 `open-guji-cv`，tag 线 `vX.Y.Z` 不变）；manager 另起一个包 `guji_manager`、另起一个仓。** 不给 pipeline 改名：`core/engine.py::code_hash` 把**模块全名**喂进指纹，改名等于全册产物过期。
2. 判据只有一条：**同样的输入，改这段代码会不会改变任何一册任何一页的识别产物字节？** 会 → pipeline；不会 → manager。
3. 现在两者缠在一起的反向边（pipeline 反过来 import manager 一侧）**只有 12 条**，其中只有 1 条动到进指纹的文件（`seed_admit` 的 `code_deps`），可以靠「代码等价登记」做到产物不过期。切开代价小得多。
4. manager 通过三个口子用 pipeline：**命令行（`guji-cv … --json`，子进程，在任务点名的那版 pipeline 环境里跑）**、**磁盘契约（册 yaml / 产物 manifest / 事件日志的 schema，带 `schema_version`）**、**输入物化（manager 先把语料、字形库、原图、模型资源摆到工作区，pipeline 只读本地文件，不联网）**。
5. 分五步走，**前两步不发 pipeline 版**；真正动 pipeline 代码的只有「清反向边」，并进一次本来就要发的 PATCH。换图源批量正在跑，**现在不碰任何发版**。

## 二、盘点：12.4 万行各归哪边

`open_guji_cv/` 共 124,528 行 / 约 40 个包。从 19 个 Step 出发的静态 import 闭包 72,506 行（含函数内惰性 import）；闭包之外的 5.2 万行是 manager 一侧。

### 2.1 pipeline（凡影响识别产物，含它的输入契约）

| 包 | 行数 | 说明 |
|---|---|---|
| `steps` `gates` `shadow` | 9,966 / 1,459 / 421 | 19 个 Step、出口闸、影子放行闸 |
| `core`（大部分） | ≈4,900 | Step 引擎 `step/engine/spec/pipeline/reuse/parallel/runlock`、`book`（BookSpec）、`book_config`、`workspace`（路径解析）、`corpus_pin/glyph_pin`、`cv_version`、`code_equiv`、`event_files`、`anchor`、`yaml_cache` |
| `clustering` | 24,715 | 字形匹配、聚类、播种、准入、生僻字候选（闭包内 22,127） |
| `utils` | 13,396 | 切分、版面、二值化、对勘对齐等算法（闭包内 11,508）。其中纯脚本用的零散模块实施时逐个核 |
| `groups` `hanzi` `variants` `variant_ledger` `gloss` `detectors` `ocr` `pagetype_model` | 5,407 / 1,430 / 282 / 144 / 54 / 167 / 96 / 256 | 形近／异体字组、汉字关系库、字表账、OCR 检测器、页型模型。都是 Step 的输入或判据 |
| `products` | 1,989 | 产物仓 `ProductStore`、manifest、产物 schema（`products.kinds.*`）。**这是两边的磁盘契约，归 pipeline 定义** |
| `feedback`（消费一侧） | ≈1,900 | Step 要读人裁结果：`lookup` `bindings` `keys` `mojibake` `events`（事件格式）`lock`。人裁结果是 pipeline 的输入，读法归 pipeline |
| `eval.rulers` `eval.colgeom` `report.witness` `report.slots` | 351 / 142 / 165 / 277 | 被闸与 Step 直接用的度量／对齐小库，下沉到 pipeline 内部 |
| `formats.guji_page_cv` 等 | 待核 | Step9 汇总与导出若决定「book-text 里的文字」，算 pipeline；只是换格式的算 manager。见 6.3 |
| 资源 `models/` `config/`（字表、变体、IDS、字组、seal_templates…） | — | 决定识别结果，随 pipeline 发版（现已随资源包）。`fonts/` `corpus/` 按 10-23 定，自有版本，不随 pipeline |

### 2.2 pipeline manager（不影响识别产物字节）

| 包 | 行数 | 说明 |
|---|---|---|
| `datastore` | 4,924 | Postgres 中心库、R2、原图/页表取图（`sources` `spreads`）、产物/语料/字形包的推拉（`packs` `pull` `workcopy`）、备份、导入 |
| `jobs` | 1,599 | 任务库、执行方 `runner`、任务看板 |
| `ops` | 5,772 | 冻结、发版检查、部署检查、`close_check`/`exit_check`、重跑、字形快照、基线测试… |
| `console` | 6,482 | FastAPI 控制台与路由（闭包里 345 行是两处反向依赖，见第四节） |
| `review` `snap` `opinions` `exp` | 4,427 / 1,864 / 3,246 / 2,654 | 审阅批次与卡片、快照导入、网站意见池、A/B 实验框架 |
| `feedback`（生产一侧） | ≈6,300 | `harvest` `routes` `consumers`（事件→裁决表）`returns` `vision` `questions` `step8` `web_votes`… |
| `eval` `gold` `report`（其余）`render` `formats`（其余） | 4,044 / 1,243 / 2,207 / 3,311 / 2,879（减去上面划走的） | 评测、金标、汇总报告、叠图与阅读排版、交换格式导出 |
| `cli_*` | ≈6,500 | `guji` 命令里除 pipeline/step/status/rerun/book 以外的几十条子命令 |
| `scripts/`（约 200 个） | — | 绝大多数是 manager 或一次性脚本；`rerun_prep.sh` 等归 manager；产生模型/字表的构建脚本留 pipeline 的 `tools/` |

### 2.3 三个灰区，先给倾向

| 灰区 | 倾向 | 理由 |
|---|---|---|
| `feedback.consumers`（事件→裁决表） | **manager**，裁决表格式归 pipeline | 人裁事件落成裁决表是「外界输入的整理」，Step 只读表。要核 `consumers` 是否在 Step 运行时被调（闭包里有边，经 `core.step`） |
| `groups` 的 `group_flow`（统一流程） | pipeline | 它决定哪些格放行 |
| `hanzi` 的离线 sqlite | pipeline 读、manager 管构建与更新 | 构建脚本 `build_hanzi_db.py` 属 manager，库文件按版本钉 |

## 三、分界规则（写进守卫测试）

1. **方向**：manager 可以 import pipeline 的**公开面**；pipeline 不许 import manager（含函数内惰性 import）。现有 `tests/test_architecture.py` 的层级机制直接扩展：给每个顶层包加 `side = pipeline | manager`，新增守卫「pipeline → manager 一条都不许」。
2. **公开面**：pipeline 只导出 `open_guji_cv.api`（新，薄层：跑 pipeline／step、读 status、读 manifest、读册配置、版本信息）和 `open_guji_cv.products.kinds`（schema）。manager 不 import `clustering` `utils` `steps` 的内部。
3. **不联网**：pipeline 内不得出现 psycopg、R2、HTTP 取图、令牌读取。取不到输入就报「缺 X，请 manager 先 pull」，不要自己去拉（现在 `seeding`、`font_pack` 缺了会自己去 R2 取，见第四节）。
4. **环境变量**：pipeline 只认路径类（`GUJI_WORKSPACE` 等）与行为开关；`GUJI_DATA_TOKEN` 之类凭据只给 manager。

## 四、要切断的反向边（pipeline → manager 一侧，共 12 条）

| # | 边 | 做什么 | 动指纹？ |
|---|---|---|---|
| 1 | `clustering.seeding → datastore.packs.fetch_derived`（播种时缺派生缓存就去 R2 取） | 改成只读本地；缺时报错提示 manager 先 `pull`。manager 的 `prep` 里加这一步 | **是**（`seeding` 在 `seed_admit` 的 `code_deps`）。行为只在「缓存缺」分支变，走 `code_equiv` 登记；做不到逐字节相同的话就并进下一次有意的重跑窗口 |
| 2 | `clustering.font_pack → datastore.packs`（2 处） | 同上，字体包由 manager 物化 | 否 |
| 3 | `products.store → datastore.sources.PULL_MARK` | 把标记常量挪到 `products` | 否 |
| 4 | `core.cv_version → datastore.client.is_exp_branch` | 改读环境变量 `GUJI_DATA_BRANCH` 本身，不 import | 否 |
| 5 | `core.book → review.cards.parse_cells_spec`（惰性） | 把 `parse_cells_spec` 挪进 `core`（纯字符串解析） | 否 |
| 6 | `clustering.glyph_selfcheck → console.routers.workspace.discover_workspaces` | 改用 `core.workspace` 里的发现函数；控制台反过来用它 | 否 |
| 7 | `gates.row_segment_gate → eval.rulers` | `rulers` 与 `eval.colgeom` 搬进 `gates`／`utils`（只搬不改） | 否 |
| 8 | `steps.seed_admit → feedback.bindings / lookup / mojibake`（3 条）、`steps.row_segment → feedback.lookup` | 不是反向边：这几个模块本来就归 pipeline（2.1），连同 `keys` `events` 一起划到 pipeline 一侧即可 | 否 |
| 9 | `steps.align_ref → report.witness` | `witness` 归 pipeline，同上；它在 `code_deps`，**只搬位置不改内容**，指纹里记的是模块名，所以搬动本身要登记等价 | **是**（模块名变）。尽量把 `witness` 留在原路径 `open_guji_cv.report.witness`，**不搬**，只在守卫里把它标成 pipeline 一侧 |

> 要点：**不为整齐而搬进指纹的文件。** 模块全名和内容都进 `code_hash`，搬家 ≈ 改算法。凡在某个 `code_deps` 或某个 Step 里的文件，原地不动，只给它标 `side=pipeline`。要搬的只有不进指纹的。

另有不是「边」的：
- 现存的 42 条向上依赖（`module_map.md` 第三节）与本拆分正交，但其中 `core → review/steps`、`report → feedback` 等跨 pipeline／manager 的会被新守卫一并盯住，顺手清。
- `ops ↔ snap` 同层环，两者都在 manager 一侧，不在本次范围。

## 五、两边怎么说话（契约）

### 5.1 进程接口：`guji-cv`（pipeline 的命令行）

pipeline 保留一个**小而稳**的命令行（入口 `guji-cv`，沿用 `python -m open_guji_cv`）：

```
guji-cv pipeline <册> <管线> --pages … [--from/--to/--force/--params/--override/--isolate-steps/--json]
guji-cv step <册> <步> …
guji-cv rerun --stale …
guji-cv status <册> [--json]
guji-cv book show <册> [--json]          # 合并后的生效配置与来源层
guji-cv check-env [--json]               # 依赖／资源／模型自检，输出 pipeline 版本与 schema_version
guji-cv version [--json]                 # cv_version、cv_commit、contract 版本
```

- 所有子命令 `--json`，退出码约定写进文档，作为契约的一部分（现有 `cli_v2.py` 里 `cmd_pipeline/step/rerun/status/book` 抽出）。
- **manager 一律用子进程调**，在任务点名那版 pipeline 的虚拟环境里（`jobs/runner.py` 已经是这样做的：`/opt/guji-venv/bin/guji`、去掉 `PYTHONPATH`）。这样同一台机器上不同册可以钉不同版 pipeline，manager 自己永远只有一个版本。
- 现在 `cmd_pipeline` 里夹带的 manager 行为要拿出来：`_auto_pack`（跑完自动存包推 R2）、`_print_unpacked`、`_ensure_rare_index`（拉生僻字索引）、`_ensure_glyph_pin`（建钉版字形库）。拆后 pipeline 只跑；manager 在**跑前**物化输入、**跑后**存包。过渡期这些行为留着，用开关缺省关掉（见第七节 M2）。

### 5.2 磁盘契约（pipeline 定义，manager 只读）

| 对象 | 位置 | 约定 |
|---|---|---|
| 册配置 `books/<册>.yaml` + `config/book_defaults.yaml` | 工作区 | BookSpec 的字段集合与分层规则归 pipeline；manager 改册 yaml 只改「身份、图源、钉版」这类 manager 字段，其余字段原样透传。加 `schema_version` |
| 产物 `products/<册>/<步>/…` 与 `manifest` | 工作区 | `products.kinds.*` 是 schema；manifest 增加 `contract_version` |
| 人裁事件 / 裁决表 | `feedback/` | 事件格式（`feedback.events`）与裁决表格式归 pipeline；生产归 manager |
| 工作区布局与路径解析 | `core.workspace` | 归 pipeline；manager 用同一份（`from open_guji_cv.api import workspace`） |

`contract_version` 单独编号（整数），**只在上面四样的格式变时加一**，与 pipeline 版本号无关。manager 声明 `supports_contract = [a, b]`，装的 pipeline 超出范围就拒跑（同现在 `cv_version` 钉版护栏的写法）。

### 5.3 输入物化（manager 的 `prep`）

pipeline 跑之前，工作区里必须已有：原图（`source pull`）、语料包、字形库（钉版快照）、生僻字索引、字体包、模型与配置资源。今天这些由 `scripts/rerun_prep.sh` 和 `cmd_pipeline` 里的 `_ensure_*` 分头做。拆后统一成 manager 的一个动作 `guji prep <册>`，输出一份 **`prep_manifest.json`**（每样输入的来源、版本、sha256）放在工作区，pipeline 启动时只做**存在性与 sha 核对**（`check-env`），不去取。

## 六、版本、发布与钉版

### 6.1 两条版本线

| | pipeline | manager |
|---|---|---|
| 包名 / 仓 | `open-guji-cv` / `open-guji/open-guji-cv` | `guji-manager` / `open-guji/guji-manager`（新仓，名字待用户定） |
| tag | `vX.Y.Z`（沿用，不动） | `m-vX.Y.Z`（避免与 cv 混淆） |
| 谁钉它 | 册 yaml 的 `cv_version`（现状不变）、任务库的 cv 版本 | 执行机跟 manager 的 `main`/最新 tag，**不钉到册** |
| 改了要不要重跑 | 看 `code_hash`，现有规矩 | **永不**；manager 版本不进任何指纹 |

### 6.2 产物里记什么

manifest 现记 `cv_version` `cv_commit`。拆后再加 `manager_version`（仅供审计，**不参与过期判定、不进 `self_hash`**）。排查「这批包是谁跑的」时两个都看得到。

### 6.3 一个要用户定的边界（唯一的）

**Step9 汇总与导出**（`report` 的 `slots/tiers/…`、`formats.guji_page_cv`、`render.guji_markdown`）：它们产出进 `book-text` 的文字。如果 Step9 的汇总逻辑变了会改变发布文本，它就是「影响最终产物」，该进 pipeline；若只是把已有产物排成另一种格式，归 manager。目前倾向：**Step9 汇总与 `char.json` 导出进 pipeline，`guji-page` / 阅读排版 / 叠图归 manager**。请 A31 与负责 Step9 的会话核对一遍后定稿。

### 6.4 发布

- pipeline：沿用 `doc/版本号规矩.md`（dev → rc → main + tag），**一个字不改**。区别只是以后 manager 的改动不会再触发它。
- manager：简化流程——`main` 直接发，打 `m-vX.Y.Z` tag 触发 workflow 构建 wheel；执行机 `pip install` 最新版。manager 的 CHANGELOG 单独一份。
- 兼容矩阵放在 manager 的 `COMPAT.md`：每个 manager 版本支持哪些 `contract_version`；pipeline 的 CHANGELOG 里凡改了契约的条目要标「契约 +1」。

## 七、迁移步骤

每步都能独立合并、独立回退，**M0–M2 不发 pipeline 版，M3 并进下一次本来就要发的 PATCH，M4 起 manager 独立**。

| 步 | 做什么 | 动 pipeline 版本/指纹？ | 前置 |
|---|---|---|---|
| **M0 标注 + 守卫** | `test_architecture.py` 给每个包标 `side`，加「pipeline 不许 import manager」守卫，现存违规（第四节）全部登记进白名单，只许减不许增。本文落 `doc/`，`module_map.md` 加指针 | 否（只改测试与文档） | 本设计过目 |
| **M1 公开面与契约文档** | 新增 `open_guji_cv/api.py`（薄层转发现有函数）；写 `doc/契约.md`（命令行、`--json`、退出码、四类磁盘 schema）；manifest 加 `contract_version`（**不进 `self_hash`**） | 否（不在任何 `code_deps`；manifest 加字段要先确认不改产物指纹——合前实算 19 步 `code_hash`） | M0 |
| **M2 夹带行为出站** | 把 `cmd_pipeline` 里的自动存包、`_ensure_rare_index`、`_ensure_glyph_pin` 挪进 `ops` 一个 `prep`/`post` 函数；`guji pipeline` 缺省仍调它们（行为不变），加 `--no-prep` `--no-pack`；`jobs/runner.py` 改成显式 `prep → guji-cv pipeline --no-prep --no-pack → pack`。第四节 #2–#7 不动指纹的反向边一并清掉 | 否（`cli_v2` 与 `ops` 不在 `code_deps`） | M1 |
| **M3 清进指纹的边** | 第四节 #1：`seeding` 去掉联网取缓存，改报错；跑 `scripts/code_equiv.py check` 证明逐字节相同后登记。**合进下一个 PATCH，与其它攒批小修复同车** | **是**（`seed_admit` 的 `code_hash`；若等价登记成立则产物不过期） | M2；等换图源批量跑完 |
| **M4 manager 成仓** | 建 `guji-manager` 仓，用 `git filter-repo` 把 manager 一侧的包连历史带过去；包名 `guji_manager`，`guji` 命令改由它提供；cv 仓只留 `guji-cv`。cv 仓同时删掉这些包 | pipeline 只删不在 `code_deps` 的文件，不动指纹；**发一个 PATCH**（因为删了文件、命令入口变了） | M3 |
| **M5 收尾** | 执行机 / `jobs/runner.py` / `rerun_prep.sh` / README / 任务库规范（`重跑需求与执行规范.md`）改指向；删 cv 仓里的 manager 残留与白名单；`doc/` 里 manager 的设计文档搬家 | 否 | M4 |

### 过渡期兼容

- `guji` 命令在 M4 之前由 cv 提供，M4 之后由 manager 提供并**在子命令里转发给 `guji-cv`**，所以 `/opt/guji-venv/bin/guji pipeline …`（任务库、`rerun_prep.sh`、各会话手里的命令）**继续能用**。
- 已钉在旧版（如 0.5.21、0.5.24）的册：旧版 cv 里仍带着 manager 代码，不受影响；manager 调旧版时用旧版 `guji`（没有 `guji-cv` 的话），M1 以前的版本通过一个 `legacy` 适配（`guji`→`guji-cv` 同名子命令）兼容，契约版本记为 0。

## 八、风险与未决

| 风险 | 对策 |
|---|---|
| 切分过程让某步 `code_hash` 变，整册重跑 | 第四节只有 #1 涉及；`code_equiv` 证明后登记；M0–M2 每个 PR 合前跑 19 步实算对比（现有规矩） |
| 灰区归属判错（把影响产物的代码划给 manager） | 守卫测试 + 抽样：对每个划走的包，在固定 10 页样本上跑「改 manager 包 → 产物逐字节不变」的探针；不放心的先留 pipeline，宁多勿少 |
| 子进程调 pipeline 的开销与错误传递 | 现在 `jobs/runner.py` 已是子进程；`--json` 输出与退出码进契约；日志原样透传 |
| 两仓同步改契约 | `contract_version` + manager 声明支持范围 + 拒跑护栏；契约变更必须在 pipeline CHANGELOG 里标出 |
| 过渡期 `guji` 命令双头 | 转发层 + 本文第七节兼容说明；M4 前不改入口 |
| 发版工具（`tag.py`、`release.yml`、`check_rc_target.py`、`check_release_tags.py`）都认本仓 | 留在 pipeline 仓；manager 仓用自己的更简单的一份 |

**需要用户定的：**
1. manager 仓名（建议 `open-guji/guji-manager`，包名 `guji_manager`）。
2. 6.3 Step9 汇总与导出的归属（倾向：汇总与 `char.json` 导出进 pipeline）。
3. M4 是否在换图源批量收尾、下一个 PATCH 发出之后再动（建议是）。

## 九、盘点怎么做的（可复现）

- 用 `ast` 解析 `open_guji_cv/**/*.py` 的全部 import（含函数内），建模块级有向图；以 `steps/*` 为根求可达闭包。
- 闭包行数按顶层包汇总得到第二节表；闭包里 pipeline 一侧指向 `datastore/console/review/eval/report/feedback` 的边共 12 条，即第四节。
- 对每条边核它的两端是否出现在某个 Step 的 `code_deps`（`grep '"open_guji_cv.<模块>"' steps/ gates/`）：只有 `clustering.seeding` 与 `report.witness` 在。
- `code_hash` 的计算见 `core/engine.py:143`（模块全名 + 源码哈希，经 `code_equiv` 换算）。
