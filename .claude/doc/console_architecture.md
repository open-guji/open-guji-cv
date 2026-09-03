# open-guji-cv 总体架构设计：控制台、产物、金标与反馈环

> 2026-09-03 由 overview 下发。目标读者：接手实现控制台与数据集抽象的人；
> 同时是各步骤优化会话之间的公共约定。
> 现状依据：open-guji-cv `main` 4f6a535（2026-09-03）、open-guji-dataset `main`（2026-09-03），
> 均已回源头核对，不依赖本地旧克隆。
> 本文与 overview 仓 `项目进展/图片初步数字化/open-guji-cv-架构设计.md` 同步维护；改这里也要改那边。

## 0. 一句话

把现在散落在 CLI 命令、`scripts/build_*` / `eval_*`、三个各自为政的本地服务器、
claude.ai Artifact 审查页和 `artifacts/README.md` 手写台账里的东西，收拢到四个抽象上
——**Step（步骤）/ Product（产物）/ Gold（金标）/ Event（反馈事件）**——再在它们上面
架一个本地控制台。步骤是插件，管线是按版面选的 DAG，产物带指纹，金标带锚点，
人裁一律变成事件并按路由表自动流向金标、字形库或上游回归集。

```
                          ┌──────────────── 控制台（FastAPI + 静态页）────────────────┐
                          │ 总览 DAG · 运行/队列 · 产物叠图 · 评测 · 审查批次 · 金标 · 事件 │
                          └───┬──────────────┬──────────────┬──────────────┬─────────┘
                              │ 跑           │ 读/比        │ 采样→批次     │ 收割/路由
   pipelines/*.yaml ──选──▶ Step 插件 ──写──▶ Product 产物 ◀──评测── Gold 金标 ◀──add── Event 事件
   （按版面的 DAG）      （薄适配层）   （带指纹·可过期）    （带锚点·可重键）   （只追加·可路由）
                                            │                    ▲                 │
                                            └── 过期传播 ─────────┘   glyphdb / 上游回归集 ◀──┘
   ─────────────────────────────────────────────────────────────────────────────────────
   存储： git（人产生·不可再生·小） │ 本地快照目录（大·可再生但慢） │ 工作副本（缓存·随时重算）
```

## 1. 现状与痛点

### 1.1 管线：两代并存

- **v1 链（退役中）**：s1..s6 预处理 → phase2_layout → phase3_char_grid → phase4_chars →
  phase5_clusters → phase6_labels → phase7_review / phase9_seed。坐标左上原点、格号从 0。
  **本设计不为它包壳**（用户 2026-09-03：v1 以后很可能不用，focus v2）；v2 仍复用的只有它的
  下游模块（`CharExtractor`、normalize、GlyphMatcher、seed、context_step），phase2..phase9
  产物目录在 P3 出 git 时一并清理。
- **v2 切分链（当前主攻，即用户说的「1、2、3 步」，本设计唯一建模的链）**：
  Step1 边框探测（`detect_borders`，直接吃原始 tif）→ Step2 单列射影 + 去噪 + 界行/版框清除
  （`step2_columns/`）→ Step2→3 交接闸（`export_step3_input.py`，三级准入）→ Step3 单列文字切分
  （`segment_column`，带类型字格 + 读序）→ Step4 字框收缩（沿用 `CharExtractor`，**尚未接上**）
  → 下游：归一化 / 字形匹配 GlyphMatcher / 逐页进库 seed / 上下文裁决 context_step。
  坐标右上原点、从 1 计数。
- 同一 `output/vol01/` 里两代产物混放（phase2..phase9 与 step2_columns / step3_input）。
- 书级共识量（格高、列距、`period` / `ref_w`）是隐式的：算在某一步里，靠人记得「透传到后续 pass」。
  手册记过一次真回归：Pass 2a 修好格高，2a2/2a3 没传 `cell_h_prior`，崩坏页 3 → 17。

### 1.2 控制与审查：三个服务器、四种事件格式

| 现有 | 干什么 | 问题 |
|---|---|---|
| `open_guji_cv/web/server.py` + `runner.py` | 跑 cut / recognize-profile / preprocess / extract / run，SSE 日志 | 命令表写死，v2 的 Step 一个都不认；任务不落盘，重启即失 |
| `clustering/review/server.py` + `state.py` | 簇审查，事件写 `phase7_review/labels.jsonl` | 绑死在 phase5/6 产物布局上 |
| open-guji-dataset `server.py`（已废）/ `index.html` | 浏览器 File System Access 直接改 expected.json | 只认 samples/NNN 布局 |
| Artifact 审查页（`review-artifact` skill、`_review_shell.py`、`persist_js.py`、`shells/*.html`） | 自存式 HTML；事后 `Artifact read` → `harvest_verdicts.py` | 事件格式四种：`verdicts {id,verdict,t}`、`GUJI-SEED-EVENT`、`GUJI-SEG-REVIEW`、`marks/patch_review_marks.json`；URL 台账手写；每轮「读回 → 收割 → build shard → 两仓提交」全手工，且发布前必须先读回否则覆盖掉未收割的裁决 |

### 1.3 数据集：二十来个分片，载体各异

`metadata.json` 已经相当规范（`eval_command`、`sampling`、`known_limitations`、`baseline_history`），
但样本载体有四种：samples/NNN 目录、扁平 expected.json、`verdicts_rN.jsonl`、以及
**写在 `scripts/build_*_dataset.py` 里的 LABELS 字典**。金标分「挂图像」（不漂）与
「挂产物键 `page:col:idx`」（上游一动就漂，`instances` 已重标 8 轮），重键靠
`rekey_triplets_by_patch.py`、`migrate_column_warp_gold.py`、`build_recrop_shard.py` 各写各的。

### 1.4 存储

- open-guji-cv 仓 **约 3.8 GB**：`output/`（约 6.8 万文件）与 `data_full/` 因「云容器重置会清空、
  重下不一定成」而入库；`glyph.db` 压库后 73 MB，曾撞 GitHub 100 MB 单文件上限；
  `features*.npz` 已单独排除。体积几乎全是**中间图像**：vol01 一册 phase4_chars 24,936 个字块、
  step2_columns 1,614 个列图，而它们都能由原图 + 几个坐标现算出来。
- open-guji-dataset 约 110 MB；`glyph-match` 一个分片 6380 个小文件。

### 1.5 痛点 → 设计目标

| 用户痛点 | 根因 | 对策 |
|---|---|---|
| 改一步，后面几步测试集全要重做 | 金标挂在会漂的产物键上；没有机制知道谁漂了 | 金标带**锚点**（原图坐标 + 内容指纹）；产物带**指纹**，上游一变下游自动标 stale；重键自动化 + 复核队列 |
| 反复跑整书，很慢 | 无增量、无缓存、任务不排队 | 指纹级增量跳过；每册固定 **dev_set**；任务队列后台跑；产物快照可拉取 |
| 几步之间难以沟通 | 接口契约只在文档里 | 产物 schema 进代码，写产物即校验；DAG 在控制台可见，「改这步影响谁」一眼看清 |
| 每步测试集要手标、格式不同 | 无统一载体、无统一 CRUD | GoldStore 统一信封 + 旧格式适配器；采样器直接开审查批次 |
| 总在云端 Artifact 手标 | 本地没有能收事件的服务 | 审查页双传输：控制台直连（Tailscale 远程可用）+ Artifact 自存兜底一键收割 |
| 中间图像把仓库撑到 3.8 GB | 每步都把图像当产物落盘 | **数值长期、图像即算**（§3.8）：长期只存坐标与类别，图像进有上限的本地缓存，缺了现算 |

## 2. 设计原则

1. **一切经过四个抽象**：Step / Product / Gold / Event。新功能先问落在哪个抽象上。
2. **不改算法只包壳**：现有函数原样保留，Step 是薄适配层。**只建模 v2 链**，v1 退役不包壳。
3. **git 只放人产生的和不可再生的**；数值产物本地、按需 pin 进 git；图像只是缓存。
4. **金标能挂图像就挂图像**（沿用 making-datasets.md）；必须挂产物键的，锚点 + 自动重键 + 人复核，
   绝不静默沿用。
5. **人裁一律是事件**：只追加、带批次与序号、消费幂等；审查页自包含、不回管线拿数据。
6. **旧 CLI 与旧脚本继续可用**：迁移按分片、按页面逐个做，不搞大爆炸。
7. **数值长期、图像即算**：能由原图 + 数值产物 + 代码确定性再生的图像一律不当产物；
   只有原始扫描和人看过并裁决过的图才长期保存（§3.8）。

## 3. 核心抽象

### 3.1 Step：步骤插件

```python
class StepSpec(BaseModel):
    id: str                        # "border_detect"
    title: str                     # "Step1 边框探测"
    version: str                   # 输出语义变了才升；参与指纹
    unit: Literal["book", "page", "column", "cell"]   # 可局部重跑的最小单位
    consumes: list[str]            # 产物种类 id，如 ["raw_page"]
    produces: list[str]            # 如 ["borders"]
    params: type[BaseModel]        # 参数 schema，默认值 = 生产配置
    when: str | None = None        # 单位级条件，如 "page_type == 'body'"

class Step(ABC):
    spec: StepSpec
    def run(self, ctx: RunContext, keys: list[UnitKey]) -> Iterable[ProductRecord]: ...
    def fingerprint(self, ctx: RunContext, key: UnitKey) -> str:
        """默认 = hash(spec.version, params, 本模块代码哈希, 上游产物 sha)。"""
```

- 书级共识量单独成步（`grid_prior`，unit=book），页级步骤 consumes 它。「改了共识没透传」
  那类回归在 DAG 上变成一条显式边，控制台能看见谁过期。
- 注册表 `STEPS = {id: Step}`，与现有 `context_step.STRATEGIES` 同一套路。
- 一个 Step 的 `run` 里可以就是一行 `return detect_borders(gray, expected_cols)`，
  外加把结果按 ProductKind 写盘。算法代码不动。

### 3.2 Product：产物与指纹

```
products/<book>/<step_id>/<key>.<ext>        # key：页号 / 页:列 / 页:列:格
products/<book>/<step_id>/_manifest.jsonl    # 每条：{key, sha256, fingerprint, params_hash,
                                             #        upstream:{step: sha}, code_rev, coord_space,
                                             #        ts, elapsed, status}
```

- 每种产物一个 `ProductKind`（pydantic 模型）：`raw_page`、`profile`、`borders`（= `BorderDetectionResult`）、
  `column_image` + `column_windows`、`gate_manifest`、`cells`（= `RowBoundaryResult.cells`）、
  `char_index`（= `phase4_chars/index.jsonl` 一行）、`char_patch`、`glyph_match`、`seed_queue` ……
  现在写在手册里的「接口契约不许私自改」变成代码里的 schema，写产物时校验，改契约先改模型。
  每种 kind 还声明 `storage`（`numeric` / `image_cache` / `image_keep`，§3.8）。
- `coord_space` 是产物字段。**规范空间是 `raw_page_px@top-right`**（用户 2026-09-03 裁定：古籍从右上角起）：
  原点在页面右上角、x 向左递增、y 向下递增、列号从右到左从 1 起，与 v2 切分链和阅读顺序一致。
  v1 产物声明为 `raw_page_px@top-left`（遗留，只读），列图为 `column_px`。转换函数集中在
  `core/anchor.py`，含与 OpenCV 左上原点互转的 `to_cv / from_cv`——算法内部照旧用 numpy / cv2 坐标，
  只在落盘和锚点处换算，`x_right = width - x_left`。
- **stale 判定**：`fingerprint(now) != manifest.fingerprint` → 过期。上游一改，下游整链自动过期，
  但**不自动重跑**（重跑是人下的命令，只是不再需要人去算哪些要重跑）。
- `windows.json` 那次「只存 `{x_at_top, slope}` 把三段页退化成直线」的静默丢失，
  在 schema 校验下会在写盘时被拦。

### 3.3 Pipeline：按版面选的 DAG

```yaml
# open_guji_cv/pipelines/keben_body_v2.yaml
id: keben_body_v2
title: 刻本正文（v2 切分链）
selector: {edition: keben, page_type: [body]}
steps:
  - page_type_gate        # 页型闸门（现 classify_page_type / refine_page_type）
  - grid_prior            # 书级共识：格高 / 列距 / period / ref_w（unit=book）
  - border_detect         # Step1
  - column_warp           # Step2
  - column_gate           # Step2→3 交接闸（export_step3_input）
  - row_segment           # Step3
  - cell_shrink           # Step4（CharExtractor）
  - normalize
  - glyph_match
  - seed
  - context_decide
```

- 边由 consumes / produces 推出，必要时 `needs:` 显式写。
- 只注册 v2 链。v1 的 s1..s6 / phase2 / phase3 不包壳；`cell_shrink` 起的下游 Step 包的是
  v1 时代写的模块（extractor、normalize、match、seeding、context_step），它们本来就以字块为输入，
  与切分链无关。
- 将来目录页 / 职名页 / 抄本各一份 yaml，复用同一批 Step；**新版面 = 新 yaml + 缺的那几个 Step**。
- 手册 §2「哪些步骤可以并行」的表由 DAG 自动推出：改到同一产物的不能并行。

### 3.4 Anchor：金标与事件的锚点（正面解决漂移）

```json
"anchor": {
  "book": "vol01", "page": 42,
  "space": "raw_page_px@top-right",
  "bbox": [x0, y0, x1, y1],
  "quad": [[x, y], [x, y], [x, y], [x, y]],
  "content_sha": "…",
  "product_key": {"step": "cell_shrink", "key": "vol01:42:3:17", "fingerprint": "…"}
}
```

- `bbox` 是该单位（列 / 格 / 图块）在**原图**上的框，x 从右边缘量起；列图坐标经 Step2 的逆映射回去
  （折线页按带取矩阵）。`quad` 可选，射影页用。`content_sha` 是 `normalize_patch` 后的内容指纹。
- `product_key` 允许失效；`bbox` + `content_sha` 不失效。
- **Rekeyer**（`gold/rekey.py`）：产物重生后，对每条金标 (a) 原图 bbox 就近取候选
  (b) 归一化内容匹配（`normalize_patch` → `verify_pair_elastic`，同列格差 ≤ 2 约束，
  沿用手册里已验证的「重键要用内容配、不能用几何重叠」）→ 出
  `rekey_receipt.jsonl {old, new, method, score, status: auto | needs_review | lost}`；
  `needs_review` 自动生成「重键复核台」批次。现有三个重键脚本收敛为它的三种策略。

### 3.5 GoldStore：统一金标

```
open-guji-dataset/<step_id>/<shard>/
  metadata.json      # 现有字段全保留 + step_id, unit, gold_kind (output | capability), item_schema
  items.jsonl        # 统一信封（下）
  assets/<sha>.png   # 内容寻址，跨分片去重
  report.json  README.md
```

```json
{"id": "…",
 "anchor": {…},
 "input": {"asset": "sha…", "params": {…}},
 "expected": {…本步专属…},
 "label_origin": "human | align | synth | model",
 "pipeline_version": "…",
 "stratum": "抽样·随机", "stratum_weight": 1.0,
 "status": "active | stale | uncertain | retired",
 "source_events": ["evt_…"],
 "history": [{"ts": "…", "change": "…", "why": "…"}]}
```

- API（Python 与 HTTP 同一套）：`list / get / add / update / retire / mark_stale / rekey / sample`。
  `sample(step, unit, strata, n, seed)` 直接生成审查批次（分层、固定种子、记权重）。
- **适配器**读旧格式：`SamplesDir`（samples/NNN）、`FlatExpected`（page-type 那种）、
  `Verdicts`（verdicts_rN.jsonl）、`LabelsDict`（build 脚本里的字典，只读）。
  控制台先能读全部分片，再逐个迁成 items.jsonl；迁完的分片删适配器。
- `uncertain`、分层权重、`known_limitations`、`baseline_history`、`relabel_history`
  这些既有纪律全部变成字段，不靠人记。

### 3.6 EventLog：统一反馈事件 + 路由

```json
{"id": "evt_…", "ts": "…", "batch": "border-cols-r2", "seq": 12,
 "actor": "user | model | align",
 "kind": "verdict | recrop | relabel | band | border_class | not_a_char | confirm | skip | mark | flag | split | merge",
 "target": {"step": "border_detect", "unit": "page", "key": "cols:vol02:171", "anchor": {…}},
 "payload": {"verdict": "ok"}}
```

- 存 `open-guji-dataset/feedback/events/<batch>.jsonl`（只追加；小；人产生 → git）。
- 四种旧格式在收割时映射成 `kind`；`seed_queue` 的疑问码、状态机原样放进 payload，
  `labels.jsonl` 的 confirm / relabel / split / merge / mark / flag 直接就是 kind。
- **路由表** `feedback/routes.yaml`：`kind × target.step → 消费者`：

  ```yaml
  - match: {kind: verdict, target.step: border_detect}   -> [gold.add: border_detect/column-split]
  - match: {kind: recrop}                                 -> [glyphdb.recrop, gold.add: cell_shrink/instances (seed=review_recrop)]
  - match: {kind: not_a_char}                             -> [gold.add: cell_shrink/instances]
  - match: {kind: confirm}                                -> [glyphdb.admit]
  - match: {kind: band}                                   -> [gold.add: column_warp/samples]
  ```

  这就是 review_feedback_loops.md 三条环（向上切分层 / 向下匹配栈 / 本步准入）的机器化。
- 消费幂等：`feedback/consumed/<consumer>.jsonl` 记已应用事件 id
  （手册「按 batch+seq 去重，不要整文件重灌」固化成机制）。

### 3.7 Evaluator

```python
class Evaluator(ABC):
    step_id: str
    shard: str
    def evaluate(self, gold: Iterable[GoldItem], products: ProductStore) -> Report
    # Report: metrics, strata, 分子分母, per_item, stale_n, uncertain_skipped, baseline_delta
```

- 先包 `scripts/eval_*.py`（`eval_command` 仍是兜底：控制台跑命令、解析 JSON），
  报告统一格式；基线与历史写回 metadata，per-item 报告留本地。
- 报告**必须**带：分母、分层、stale 金标数、被跳过的 uncertain 数——手册踩过的
  「比值要连着分母读」「分层报别合成一个数」「先查漂移再谈数字」三条，字段化。

### 3.8 图像产物策略：数值长期、图像即算

每种 `ProductKind` 声明 `storage`：

| storage | 含义 | 例 |
|---|---|---|
| `numeric` | **长期产物**。几何、类别、参数、来源，JSON / JSONL，KB～MB 级 | 边框线、warp 参数、字格、紧框 bbox、flags、队列 |
| `image_cache` | **派生视图**。由原图 × 数值产物 × 代码确定性再生；只进本地缓存（LRU、有上限），缺了就现算 | 列图、清理后列图、字块、归一图块、HOG 特征 |
| `image_keep` | **长期图像**。只有两类：原始扫描；人看过并裁决过的图 | `rebuild_src/`、金标 assets、GlyphDB 范例、审查页快照 |

Step 通过 `ctx.materialize(kind, key)` 拿派生图像的路径，引擎查缓存、没有就现算并写入缓存；
Step 自己**不写图像产物**。缓存目录不入 git、不进快照，容量上限可配（默认 20 GB，LRU 淘汰）。

逐步清单（v2 链）：

| 步 | 长期存的数值 | 即算的图像 | 再生成本 | 例外（长期存图） |
|---|---|---|---|---|
| Step1 `border_detect` | 上下 HLine、N+1 条 VLine 含折点、外框偏移、抬头框；每页 ≈ 2 KB | 无（叠图看时现画） | — | — |
| Step2 `column_warp` | 每列 warp 四角 / 分带矩阵、out_w、文字带 [x_lo, x_hi]、border_class、去噪与剥线参数及版本；每列 ≈ 1 KB | 矫正列图、清理后列图 `c<N>_clean.png` | 单页 < 0.1 s（`clean_column` 0.03 s） | 人裁过的列图存在 column-warp 金标 assets |
| `column_gate` | 准入裁决、period、ref_w、逐页拒绝理由 | `step3_input/` 列图（已 gitignore） | 秒级 | — |
| Step3 `row_segment` | cells（slot、y0/y1、x0/x1、kind、order、gap_center、ink_ratio、raised）+ 换算到页坐标；每页 ≈ 30 KB | 无 | — | — |
| Step4 `cell_shrink` | 紧框 bbox（页坐标）、flags、连通体归属摘要；每页 ≈ 40 KB | 字块 PNG（vol01 现存 24,936 个） | 整册 1～2 min | 人裁过的字块进 instances 金标 assets；进库范例进 GlyphDB（canonical 256×256 真源） |
| `normalize` | 参数版本 | canonical 图块 | 纯函数，毫秒 | golden 回归集自带图 |
| `glyph_match` / cluster | 候选、cov、簇成员 | HOG 特征 npz（现已排除） | 分钟级 | — |
| `seed` | queue.jsonl、progress、admissions | 审查卡片图（发布时从缓存现切成 data URI） | 秒级 | 人裁过的页面快照按批次留档 |

一册的数值产物合计约 10～40 MB；长期存储从 GB 级降到 MB 级。

**Step2 的图像也不必长期存。** 射影变换和去残留都是 (原图, Step1 线, 参数, 代码版本) 的确定性函数，
指纹里含代码版本，再生结果逐位相同——Step1 性能改造时已经用「全字段快照对拍」验证过这条链路的
可复现性。若将来 Step2 换成学习式去噪、单页超过秒级，把该 kind 的 `storage` 改成 `image_keep` 即可，
别的都不用动。

三条含义：

- **「冻结上游」不再靠打包图像**：`guji pin <book> <step>` 把该步的数值产物按指纹存进 git 的
  `pins/`（每册每步几 MB），数据集 `pipeline_version` 指向它；任何机器拿 pins + 原扫描就能把
  图像现算回来。云端会话缺产物的问题由此解决，不必再把 output/ 塞进 git。
- 锚点的 `content_sha` 在建锚时从缓存图块算一次，之后只存哈希。
- **切到 v2 Step4 的那一刻要重键一次**：`instance_id` 口径从 v1（左上、从 0）变成 v2（右上、从 1），
  GlyphDB、seed 队列、事件日志里的旧 id 用 §3.4 的 Rekeyer 按内容配一次性迁过来。这是 P4 的验收项。

## 4. 控制台（Console）

### 4.1 后端

- **FastAPI + uvicorn**。pydantic 的 schema 就是产物 / 金标 / 事件契约，顺带出 OpenAPI。
  单进程，监听 127.0.0.1。**先跑 Windows 开发机**（GPU 在这；用户裁定）；远程（iPad）走 Tailscale
  到开发机，不暴露公网。
- **任务**：子进程 `python -m open_guji_cv step run …`（隔离崩溃与 GPU 显存，沿用 runner.py 的模型），
  队列串行，同一 (book, step) 互斥；日志落 `runs/<id>.log`，记录落 `runs/<id>.json`，
  控制台重启不丢。子进程继承 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` / `PYTHONIOENCODING`。
- **路由**：

  | 路由 | 作用 |
  |---|---|
  | `GET /api/books` `GET /api/pipelines` `GET /api/steps` | 注册表 |
  | `GET /api/status?book=&pipeline=` | 每步每单位 fresh / stale / missing / running |
  | `POST /api/runs {book, pipeline, from_step, to_step, units: dev_set \| pages \| all, params, force}` | 入队 |
  | `GET /api/runs/{id}/log`（SSE） `POST /api/runs/{id}/cancel` | 日志、取消 |
  | `GET /api/products/{book}/{step}/{key}` `…/overlay` `…/diff?a=&b=` | 产物 JSON / 图；原图叠产物（现算现缓存）；两个指纹版本并排 |
  | `GET/POST /api/gold/…` `POST /api/gold/sample` | 金标 CRUD、采样开批次 |
  | `POST /api/events` `GET /api/events?batch=` | 审查页直连写入；查询 |
  | `GET/POST /api/batches` `POST /api/batches/{id}/harvest` `POST …/route` | 批次登记；喂 Artifact 读回的 HTML；按路由表消费 |
  | `POST /api/evals {step, shard}` `GET /api/evals/{id}` | 评测 |
  | `GET /review/{batch}` `GET /review/{batch}/export.html` | 控制台模式审查页；Artifact 模式导出 |

### 4.2 前端：七个视图

1. **总览**：每册一张 DAG，节点着色 = 新鲜 / 过期 / 缺失 / 运行中；旁边是该步最近评测对基线的差值。
2. **运行**：选册、选页（默认 dev_set）、选起止步、改参数、入队；实时日志；历史。
3. **产物**：按页浏览各步产物的叠图；两版本并排 diff——改了参数先肉眼看，再跑评测。
4. **评测**：每步的分片列表、一键评测、报告（分层、分母、历史曲线）、过期金标数。
5. **审查**：批次列表（替代 artifacts/README.md 的表格）、进度、打开 / 继续、收割、路由状态；
   「新建批次」就是采样器。
6. **金标**：逐条浏览 / 改判 / 退休 / 标 uncertain；重键复核队列。
7. **反馈**：事件流；每条事件被谁消费了、还没消费的堆在哪。

无构建步骤：ES modules + 本地 vendor 的 Preact + htm（约 15 KB）。视觉令牌延续现有审查页
（`--ok` 绿 / `--zhu` 朱 / `--ochre` 土黄 / `--faint` 灰），审查页壳与控制台共用一套。

### 4.3 审查页双传输

- `review/shell.py::render(..., transport="server" | "artifact")`：卡片构建器只写一次。
- **server 模式**：裁决 `POST /api/events`；localStorage 离线队列，重连补发；进度条实时。
- **artifact 模式**：现在的自存机制原样（`capabilities={"artifact": {}}`、定点检查、`#data`）。
  收割：`POST /api/batches/{id}/harvest` 上传读回的 HTML → 解析 → 事件入库 → 路由。
  发布前「必须先读回」的纪律由控制台执行：批次有未收割事件时导出按钮变灰。
- 批次登记 `review/batches/<id>.json {title, step, shard, cards_ref, transport, url, status, counts, created, harvested_at}`；
  `artifacts/README.md` 改为由它生成。卡片 id 照旧冻在 `cards.jsonl`。

### 4.4 dev_set

每册一份固定的分层小页集（如 12 页：按 page_type 与已知难页分层，固定种子），
写在 `books/<book>.yaml`。控制台默认对 dev_set 跑；全书是显式选项、后台队列。
Step1 现在 1.8 s/页，dev_set 一轮不到半分钟；聚类 / 识别那些分钟到小时级的只在全书跑。

## 5. 存储分层

| 层 | 放什么 | 在哪 | 为什么 |
|---|---|---|---|
| **A 长期（git）** | 代码、pipeline / book yaml、金标 items + 小 assets、事件日志、批次登记、评测基线与历史、`glyph_store/` 真源、重键回执、`profile.json`、各步 `_manifest.jsonl`、**`pins/` 钉住的数值产物** | open-guji-cv / open-guji-dataset | 人产生或不可再生；小（pins 每册每步几 MB） |
| **B 中期（本地快照目录）** | 原始扫描（`data_full/`、`rebuild_src/`）、`glyph.db`；可选：图像缓存的冷备 | 仓库外的本地目录（如 `D:\guji-snapshots\` 或 NAS，`GUJI_SNAPSHOT_DIR` 指定）；可选免费镜像 GitHub Release assets | 只给自己和少数开发者看，存免费的地方、优先本地（用户裁定）；大；可再生但慢 |
| **C 短期（工作副本）** | `products/` 数值产物工作副本、**图像缓存**（列图 / 字块 / 归一图块，LRU 有上限）、`features*.npz`、LM 缓存、审查页 HTML 快照、per-item 评测报告、`runs/` 日志 | .gitignore | 随时可重算 |

- 图像不再是产物（§3.8），B 层只剩原扫描和 glyph.db：`guji snapshot push / pull` 管这两样，
  后端可插：`local`（默认）、`github_release`（可选镜像，单文件上限 2 GB，供没有本地盘的云端
  会话拉原扫描）。不引入付费桶。「其他分支在用库」由 pull 满足，不再 push 73 MB 的 db。
- 迁移 `output/` 出 git：先 `pin` 当前数值产物、push 原扫描快照 → `git rm -r --cached output/ data_full/`
  → 进 .gitignore；v1 的 phase2..phase9 目录不迁、直接清。
  **历史重写（`git filter-repo`）留到稳定后做**（用户裁定）：P3 落地、分支收敛后执行，
  能把仓库从 3.8 GB 压到百 MB 级；重写前通知所有在跑的分支。
- **冻结上游**：数据集 `pipeline_version` 指向 `pins/` 里的指纹；控制台可把下游某步的评测
  「钉」在某个上游 pin 上——手册「开工前记 commit 号」的约定变成一个开关。

## 6. 代码组织

```
open_guji_cv/
  core/        spec.py        StepSpec / ProductKind / UnitKey
               step.py        Step 基类、注册表
               pipeline.py    yaml 加载、DAG、when 求值
               engine.py      指纹、stale 计算、执行
               anchor.py      坐标空间、Anchor、转换
  products/    store.py manifest.py cache.py（图像缓存：materialize / LRU / 上限）
               kinds/*.py（每种产物一个 pydantic 模型，含 storage 声明）
  steps/       page_type_gate.py grid_prior.py border_detect.py column_warp.py column_gate.py
               row_segment.py cell_shrink.py normalize.py glyph_match.py seed.py context_decide.py
  pipelines/   keben_body_v2.yaml
  pins/        <book>/<step>/<fingerprint>.jsonl.gz（钉住的数值产物，随仓库提交）
  books/       vol01.yaml vol02.yaml book9.yaml（图源、dev_set、edition）
  gold/        store.py item.py sampler.py rekey.py adapters/{samples_dir,flat_expected,verdicts,labels_dict}.py
  feedback/    events.py routes.py harvest.py consumers/{gold_add,glyphdb_admit,glyphdb_recrop,upstream_regression}.py
  eval/        base.py report.py evaluators/*.py（先包 scripts/eval_*.py）
  review/      shell.py batches.py cards/*.py transports/{server,artifact}.py
  console/     app.py api/*.py jobs.py static/{index.html, vendor/, views/*.js}
  snapshot/    store.py backends/{local,github_release}.py
```

CLI：`guji step run <step> <book> [--pages]`、`guji run <pipeline> <book> --from --to`、
`guji status <book>`、`guji gold …`、`guji events harvest …`、`guji pin <book> <step>`、
`guji snapshot push|pull`、`guji cache warm|prune`、`guji console`。
旧 `python -m open_guji_cv <cmd>` 全部保留为别名，脚本不需要改。

## 7. 现有模块 → 新家

| 现有 | 去向 |
|---|---|
| `web/server.py` + `runner.py` | `console/jobs.py`：保留子进程模型，加持久化与队列 |
| `clustering/review/server.py` + `state.py` | 一种批次类型（cluster）跑在 EventLog 上；`labels.jsonl` 变成消费者视图 |
| `persist_js.py`、`_review_shell.py`、`shells/*.html` | `review/shell.py` + 两个 transport |
| `harvest_verdicts.py` | `feedback/harvest.py`，四种旧格式各一个解析器 |
| `artifacts/README.md` | `review/batches/*.json` 生成 |
| `scripts/build_*_dataset.py` 的 LABELS | 迁入 items.jsonl，脚本改为「从 GoldStore 导出」 |
| `scripts/eval_*.py` | `eval/evaluators/`，先包后改 |
| `rekey_*.py`、`migrate_column_warp_gold.py`、`build_recrop_shard.py` | `gold/rekey.py` 的三种策略 |
| `seed_queue.py` 的事件 | EventLog 的 confirm / skip / recrop / not_a_char，疑问码进 payload |
| `output/<book>/manifest.json` | 每步一份 `_manifest.jsonl` |
| `output/<book>/step2_columns/*.png`、`phase4_chars/*.png`、`step3_input/` | 图像缓存，不再是产物；`windows.json`、`index.jsonl` 里的数值部分升格为 numeric 产物 |
| `output/<book>/phase2..phase9`（v1 产物） | 退役；P3 出 git 时清理，不迁移 |
| pipeline_handbook §2 并行分工表 | 由 DAG 自动推出，控制台显示 |
| `context_step.STRATEGIES` | 不动；是 Step 注册表的样板 |

## 8. 分阶段落地

每阶段单独可交付、旧流程始终可用。

| 阶段 | 做什么 | 验收 |
|---|---|---|
| **P0 骨架** | `core/` + `products/`（含图像缓存）；v2 四步 + `column_gate` 包成 Step，写 `_manifest.jsonl`；`keben_body_v2.yaml`；控制台「运行 / 日志 / 取消 / 状态」；dev_set | 控制台对 vol01 dev_set 跑 Step1 → Step3，总览页显示每步新鲜 / 过期；**Step1–3 落盘只有数值，列图经 `ctx.materialize` 走缓存**；旧 CLI 行为不变 |
| **P1 反馈** | EventLog + 批次登记 + server 传输壳；把「界行切分裁决台」改成控制台模式；Artifact HTML 收割器；路由 verdict → gold | 一批裁决从控制台发起 → 裁 → 自动进 items.jsonl，中间不跑手工脚本；旧 Artifact 页收割后结果一致 |
| **P2 金标** | GoldStore + 四个适配器（全部分片可读）；迁 border-detection、column-warp、char-segmentation/instances 三个最活跃的分片；包 Step1/2/3 评测器；评测视图 | 控制台一键跑 Step1/2/3 评测，显示对基线差值、分层、过期金标数 |
| **P3 增量与存储** | 指纹级 stale 与跳过；`pin` + `snapshot` 工具（本地目录后端 + 可选 Release 镜像）；`output/`、`data_full/` 出 git，v1 产物目录清理；稳定后重写历史 | 改 Step2 参数后只重跑受影响页；重新克隆后拿 pins + 原扫描把 vol01 dev_set 的图像十分钟内现算回来；仓库工作集降到百 MB 级 |
| **P4 扩展** | 锚点 + 自动重键 + 复核队列；GlyphDB / seed 队列 instance_id 一次性迁到 v2 口径；第二条 pipeline（目录页或职名页）；新 Step 模板 + 契约测试 | 上游重切后受影响金标自动标 stale 并给出重键回执；旧 id 迁移后库匹配与队列对得上；新版面只加 yaml 与缺的 Step |

P0 与 P1 可以并行（一个碰产物，一个碰事件，不改同一文件）；P2 依赖 P1 的事件格式；P3 依赖 P0 的 manifest。

### 8.1 P0 落地记录（2026-09-03）

分支 `feat/console-p0`，提交 `d63d1b4`。新增约 3,800 行，不动任何算法函数。

| 模块 | 文件 | 说明 |
|---|---|---|
| core | `core/spec.py` `step.py` `book.py` `pipeline.py` `engine.py` `anchor.py` | StepSpec / ProductKindSpec / 单位键；Step 基类 + 注册表 + RunContext（`product` / `image` / `materialize`）；BookSpec（`books/*.yaml`，dev_set）；yaml → DAG；指纹 = sha(version, params, 代码哈希, 上游 sha)，**stale 沿 DAG 向下传**；右上原点换算 |
| products | `products/store.py` `manifest.py` `cache.py` `kinds/*.py` | `products/<book>/<step>/<key>.json` + `_manifest.jsonl`；图像缓存 `cache/<book>/<kind>/<key>.png`（LRU，20 GB 上限）；产物 schema：borders / column_windows / gate_manifest / cells / char_index + 三种缓存图 |
| steps | `steps/border_detect.py` `column_warp.py` `column_gate.py` `row_segment.py` `cell_shrink.py` `_warpmap.py` | 五个薄适配；`_warpmap` 把列图坐标经 Step2 射影（含三段折线分带）逆映射回原图规范空间 |
| pipelines / books | `pipelines/keben_body_v2.yaml` `books/vol01.yaml` `vol02.yaml` | 五步链；两册各 12 页 dev_set |
| CLI | `cli_v2.py`，`__main__.py` 注册 | `guji-cv pipeline / step / status / console / cache`；`guji` 独立入口；旧命令原样 |
| console | `console/app.py` `jobs.py` `static/index.html` | FastAPI：注册表 / 状态 / 任务队列（子进程，落 `runs/`）/ SSE 日志 / 产物 JSON / 叠图 / 缓存图；前端三视图：总览矩阵、运行、产物 |
| tests | `tests/test_core_v2.py` | 9 条：键、DAG、产物仓、跑 / 跳过 / 过期 / 失败 / 强制、缓存再生、真实 vol01 第 24 页全链 |

**实测**（本机 Windows，Python 3.12，numpy 2.5 / cv2 5.0）：

- vol01 第 24 页全链 2.4 s（Step1 0.87 / Step2 0.19 / 闸 0.07 / Step3 1.03 / Step4 1.03）；9 列全过闸，
  每列 21 格、180 字块；叠图核对 Step1 线与 Step4 紧框都贴在字上，逆映射正确。
- vol01 dev_set 12 页 35.6 s，无异常退出。**两个算法层发现**（引擎按设计逐页记录、不拖垮整轮）：
  第 42 页被 L1 按列宽拦下（c9 边线落在外框，宽 224 vs 中位 187，已知问题）；
  第 119 页页级周期估成 70（应约 116），9 列 DP 全部无解——`estimate_shared_period` 在弯页上的问题，
  不在包壳范围；第 60 页 c8 DP 无解。
- 第二遍全部「新鲜，跳过」；改 Step2 参数后 Step2 及其下游过期、Step1 不动。
- 控制台端到端：起服务 → 状态 → 入队（column_gate → row_segment，2 页，强制）→ SSE 日志到完成（2.4 s）
  → 叠图 PNG → 缓存图现算。

**P0 的已知简化**（都写在代码注释里）：

1. 存储与指纹粒度是**页**：column / cell 单位的产物放在页文件里，过期按页算。
2. Step4 把 Step3 已拆好的夹注 a/b 合成满宽格喂 `CharExtractor`，由它再拆一次（网格字典表达不了半宽格）。
3. `page_type_gate` / `grid_prior` / normalize 起的下游尚未包壳；yaml 只列已包的五步。
4. `when` 条件只记录不求值；`tier=gold` 的 L3 准入等 P2 接数据集。

**环境**：仓里的 `venv/` 指向已卸载的 Store Python 3.13，是死的；新环境
`uv venv .venv --python 3.12` + `uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented`。
`tests/recognize-profile/test_recognize_profile.py::test_snapshots` 是被 pytest 误收集的脚本函数（fixture `books` 不存在），改动前就失败，与本次无关。

### 8.2 P1 落地记录（2026-09-03）

同分支，提交 `6130449`。新增约 1,700 行。

| 模块 | 文件 | 说明 |
|---|---|---|
| feedback | `events.py` `harvest.py` `routes.py` `consumers.py` | 事件信封 + 只追加日志（append 幂等、resolve 后到覆盖、consumed 记账）；四种旧格式解析；路由表；`gold_add` 消费者（`glyphdb_*` 显式未实现，不静默吞事件） |
| gold | `item.py` `store.py` | 统一金标信封（label_origin / stratum / status / history / source_events）+ 分片仓 upsert / retire / mark_stale / summary |
| review | `batches.py` `shell.py` | 批次登记（取代手写 `artifacts/README.md`，含发布前必须先收割的闸）；双传输壳（artifact 原样走现有壳，server 加一段同步 JS） |
| console | 审查视图 + 7 个 API | 批次表 / 收割 / 路由消费 / 金标摘要；`/api/batches.md` 生成台账 |
| CLI | `batch` `events` `gold` | list / new / show，harvest / route / list，shards / show |

**修掉三处格式对齐 bug**（真格式与解析器对不上，各有回归测试）：

1. `GUJI-SEG-REVIEW` 的前缀在 `t` 字段里而非行前缀，且 `t` 是字面量不是时间戳——原实现拿它排序会 TypeError；
2. marks 的值是 `{"s": N}`，语义 1=切错 / 2=存疑 / 3=没问题，原映射把 2 和 3 弄反了；
3. 续裁要 `{id: {"v","t"}}`，扁平串会让页面上一轮裁决全部消失（补 `to_shell_verdicts`）。

另修两处本轮自测暴露的：`dry_run` 试算曾照样落库；收割进已有事件的批次时因撞号丢掉整份文件，改为按 `target.key` 去重并续号。

**实测**：真实的 `border-detection/column-split` 第一轮 60 条裁决走完收割 → 路由 → 金标，
分布 ok 56 / extra 2 / miss 2，与该分片 README 记载一致；重复收割与重复消费都不产生副本。
`tests/test_feedback_v2.py` 19 条全过，全量 627 条零失败。

**P1 的已知简化**：`glyphdb_admit` / `glyphdb_recrop` 两个消费者还没接（照旧走 `seed-ingest`）；
server 传输壳只做了同步 JS，还没把「界行切分裁决台」真正改成控制台模式跑一轮；
`column-split` 分片没有机器可读的 metadata.json。

**下一步**：P2（GoldStore 适配器读全部旧分片 + 迁三个最活跃分片 + 评测器进控制台），
或先补 P0/P1 的尾巴（`page_type_gate` / `grid_prior` 包壳；把裁决台迁成 server 模式跑一轮真人裁）。

## 9. 已裁定（用户 2026-09-03）

| 事项 | 裁定 | 落到设计的哪里 |
|---|---|---|
| 快照仓放哪 | **本地**。产物不给用户看，只给自己和少数开发者；存免费的地方 | §5 B 层：仓库外本地目录（`GUJI_SNAPSHOT_DIR`），`local` 后端为默认；`github_release` 只作可选免费镜像，不引入付费桶 |
| 是否重写 git 历史 | **稳定后重写** | §5、§8 P3：P3 落地、分支收敛后跑 `filter-repo`，重写前通知所有在跑的分支 |
| 控制台跑哪台机 | **先跑本机**（Windows 开发机） | §4.1；iPad 走 Tailscale 到开发机 |
| 数据集仓是否合并进 cv 仓 | **不合并，独立存在** | §3.5：GoldStore 用相对路径 `../open-guji-dataset`，与现状一致；对外 benchmark 身份保留 |
| 锚点的规范坐标空间 | **右上角原点**（古籍从 top-right 起） | §3.2、§3.4：规范空间 `raw_page_px@top-right`，v1 的左上原点只作遗留声明；`core/anchor.py` 提供与 cv2 互转 |
