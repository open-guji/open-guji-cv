# B：CV 回流、重跑与字形库自检（GUJI-638 调研之 CV 侧）

> 调研日期 2026-10-20（洛杉矶）。只管文字，不管标点、专名。
> 读的版本：open-guji-cv 本地检出（rc/v0.4.8 一带）、ai-team main、guji-format、book-text `ffbf1d496`、kaiyuanguji-web 本地检出；Jira GUJI-610、GUJI-638。
> 写法：事实带「文件:行号」或文档出处；推测标「推测」。路径缩写：`cv/` = `/home/user/open-guji-cv/`，`ai/` = `/home/user/ai-team/`，`gf/` = `/home/user/open-guji/guji-format/`，`bt/` = book-text（git HEAD），`web/` = `/home/user/open-guji/kaiyuanguji-web/`。

---

## 〇、一页结论

1. **人裁事件只有一种信封**（`Event`：id/ts/batch/seq/actor/kind/target/payload/reviewer，`cv/open_guji_cv/feedback/events.py:136-151`），按格号 `册:页:列:格[a|b]` 记，写入时由控制台按**当时工作区的产物**算「定位锚」（原图框＋字块指纹＋前后文＋产物指纹）。网站意见要变成人裁，只能经「快照工作区 + 控制台 `/api/events`」写，才带得上锚（ai `team/CV/格级审阅页-数据流程.md` §五）。题面里说的 `slot_edit`／`override` **不是 kind**：仓里没有这两个值（全仓 grep 无），「override」是设计文档对「带锚人裁事件」的统称（ai `team/整理/设计/文本整理三阶段流程.md` §5.1）。
2. **网站到 CV 的通道现在只通了一半**：精校页的 `cellreview` 票 → Action 每天写进中心库 `feedback/lists/web/<书>/<rev>.jsonl` → `web_opinions.py`（ai-team 脚本，H 道手工四步）→ 正式人裁事件。阅读页「改字」`charfix`（1.0 之后的主入口）→ Action 写进中心库 `feedback/lists/web/<书>/fixes.jsonl` 后**没有任何程序消费它**；规格里写的去向是「直接落成 GUJI-541 对照表 A 行、PR 改 book-text」，**绕过 CV 人裁事件**，与「已放行格只增不改、改放行格走人裁事件」的规矩冲突。
3. **book-text 的格号与 CV 的格号已经分叉**：vol01 0.1.4/0.1.5、vol02/03 1.0.1 都在 book-text 里手拆格、手删格、手补格（cord「按原框近似」），这些格在 CV 产物里不存在；交接里明说「格 id 与 cv 切分对不上，所以不能落成格事件」。网站上对这些格的反馈落不回 CV。
4. **文本版本 ↔ CV 快照没有机器可读的对照**：char.json 只有 `version`，cord 的 `producers.cv` 还停在旧提交（vol01 205 页写着 `9587e67c`／`claude/vol01-prod-4324e4b`，而冻结基线是 `snap/96mid1ogzk/vol01/20261019T2303`、cv 0.4.5）；`text_version ↔ r 号 ↔ cv 版本` 只写在 CHANGES 的散文里，中心库里本来为此设计的 `freeze_baselines`／`snapshots`／`cv_versions` 三张表**没有任何代码写**。
5. **重跑侧**：冻结、钉子（`glyph_pin`／`corpus`／`cv_version`）、产物包、`products diff`、`rerun --stale`、`recheck` 都已有；但「已放行格只增不改」**没有代码强制**，L2「只合并待审→可放行的改进」**没有实现**；也没有「机器报错」这种事件或队列——唯一现成的机器意见通道是 `vision_check`（模型看图），只送人审、不改字。
6. **字形库自检**：现有 `glyph-db selfcheck`（同字离群／形似本书他字／形似他书他字／更像另一字的字体）＋控制台「体检」tab ＋ `glyph_audit` 事件，能查「库里刻例标错字」；**查不出「选了异体 A、其实更像异体 B」**——两套体检都把异体当同字（`VariantMap.semantic`＋Unihan 异体，`cv/open_guji_cv/clustering/glyph_selfcheck.py:341-375`），而且**只查库里的刻例，不查文本里数万个机器放行格**。体检裁决账 `decisions.jsonl` 不在中心库范围内，换机器就丢。

---

## 一、人裁回流（Step8，「H 道」）

### 1.1 事件信封（schema）

真源：`cv/open_guji_cv/feedback/events.py`。

| 字段 | 类型 | 说明 | 出处 |
|---|---|---|---|
| `id` | str | `evt_<batch>_<seq:06d>` | events.py:162-167（`make_event`） |
| `ts` | str | 服务端 UTC 时间（收割时间） | 同上 |
| `batch` | str | 批次名，一批一个文件 `feedback/events/<batch>.jsonl`；Windows 不合法字符换 `-` | events.py:203-221 |
| `seq` | int | 批内序号；撞号且内容不同时顺延，不丢 | events.py:224-286 |
| `actor` | `user`/`model`/`align` | 谁的动作触发 | events.py:101 |
| `kind` | Literal（见下） | 粗分类；真正的问题分类真源是 `feedback/questions.py` | events.py:23-99 |
| `target.step` | str | 产出该单位的 Step id，如 `seed_admit` | events.py:124-133 |
| `target.unit` | `book/page/column/cell` | | 同上 |
| `target.key` | str | **格号 `vol01:72:4:4`**（或卡片 id `cols:vol02:171`） | 同上 |
| `target.book/page/col/slot` | | 由 key 解析 | 同上 |
| `target.anchor` | dict | 定位锚（见 1.3） | events.py:133 |
| `payload` | dict | 各 kind 自定 | |
| `source_format` | str | 从旧格式收割来时记原格式名 | events.py:148 |
| `reviewer` | str | 网站账号（控制台接入后填，email） | events.py:149-151 |

写入口 `EventLog.append`：只追加；`payload.shape/reading/char` 不是单字或合法多码位就整批拒（`BadRequest`），兼容汉字折叠（events.py:224-286）。同一 `(kind, unit, key)` 后到覆盖；`compact` 只压重复、不改 id（events.py:288-327）。

**kind 一览**（events.py:37-99；注释自己承认 9 个值没有前端出口）：

| kind | 与文字相关？ | 去处（路由表 `feedback/routes.py:21-179`） |
|---|---|---|
| `confirm` | **是，主力** | `glyphdb_admit`（进字形库）、`gold_add`（金标）、`crop_exclude`（排除名单）、`product_invalidate(seed_admit)`（routes.py:135-154）。`payload.v` 二次分流：`confirm`（定字，带 `shape`）／`not_a_char`／`seg_defect`（带 `quality=truncated` 或 `reason=jiazhu_as_main|main_as_jiazhu`）／`damaged`（出 □）／`skip` |
| `cell_review` | 是，但只是「意见」 | **不配消费者**，不改字、不进库、不让产物过期（events.py:91-94；ai `格级审阅页-数据流程.md` §四） |
| `collate_verdict`／`collate_ok`／`char_convention`／`mark_jiajie`／`variant_deny`／`unmark_jiajie` | 对勘复核 | 各自消费者，不进字形库（routes.py:167-176）；真要改字另写一条带 via 的 confirm |
| `glyph_audit` | 字形库体检 | `glyph_audit` 消费者（routes.py:178） |
| `admit_candidate` | 候选格收不收 | 不配消费者，进库由 H 道重放（replay.py:25-37） |
| `vision_check` | 模型看图 | 不算人裁（`counts_as_human`，events.py:107-121），存 `feedback/vision/`，判 wrong 送回待审（doubt `vision_flag`） |
| `cutline`／`n_body_slots`／`border_class`／`head_raise`／`border_offset`／`band`／`verdict` | 切分 | 金标＋`product_invalidate(row_segment/column_warp)` |
| `recrop`／`relabel`／`mark`／`flag`／`split`／`merge`／`note` | — | **无出口**（`recrop` 消费器自报「尚未接入」，routes.py:90-98） |

题面里的 `cellreview`：网站精校页的票叫 `cellreview`（KV 前缀 `cr:`），控制台格级审阅页的事件叫 `cell_review`，二者不是同一东西；`slot_edit`、`override`：**不存在**。

### 1.2 写入中心库

- 2026-10-19 起（GUJI-608）guji-workspace 的 git 不再存数据；工作区根只留 `workspace.yaml` 与标记 `.central.json`，`feedback/` 在数据目录 `$GUJI_DATA_HOME/<分支>/<ws>/`（`cv/doc/datastore.md:147-155`）。
- 进库口径：`feedback/events/*.jsonl`、`feedback/vision/*.jsonl` → 表 `events`（主键 ws+src_path+id，**只追加**）；`feedback/consumed/*.jsonl` → `consumed`；`feedback/anchors/*.jsonl` → `anchors`；锚图 → `anchor_patches_meta`（图进 R2）；`feedback/verdicts/**` → `verdicts`；`feedback/lists/**`、`feedback/candidates/*`、`config/**`、`review/batches/**` → `files`（整文件）（datastore.md:38-51；`cv/open_guji_cv/datastore/scope.py:124-160`）。
- 命令：`guji db pull / push / sync / status / migrate / branch / diff / import`（datastore.md:100-227）。`push` 先比 rev（`StaleBase`），只追加台账少行拒绝；`sync` 自动合并：只追加台账按「共同前缀＋库里新行＋本地新行」合，其余文件两边都改就 `SyncConflict`（datastore.md:176-186）。
- Worker 另有 `POST /v1/events`（按 ws、src_path 追加行；`cv/open_guji_cv/datastore/client.py:255-257`），目前只用于实验分支事件导回 main（`pull.py:46-60`）。**它只写表，不跑任何消费者**。

### 1.3 定位锚与绑定表（重切后人裁不丢的机制）

- 锚的内容（`cv/open_guji_cv/feedback/anchor.py:1-35`）：`space=raw_page_px@top-right`、`bbox`（原图外接框）、`quad`、`content_sha`（当时字块图，图存 `feedback/anchor_patches/<book>/`）、`ctx`（前后各 2 字）、`product_key`（当时 Step3 产物 sha）、`evidence.fp`（图像指纹）。
- **锚在写入那一刻按工作区现行产物算**（控制台 `_api_events` 调 `_anchor_events`，`cv/open_guji_cv/console/routers/feedback.py:178-208`；`_product_anchor` 同文件 105-140）。所以「用户看 A 版、事件写进 B 版」锚就错（ai `文本整理三阶段流程.md` §5.2 第 1 条）。
- 绑定表 `feedback/bindings.py`：每条人裁按锚在现行切分里找格，状态 `valid`（原格）／`rebound`（整列顺移，改绑新编号）／`review`（切开、合并、图块不像）／`void`／`unanchored`（bindings.py:1-60）。`review`／`void` 的不采信，回待审。缓存 `feedback/bindings/<book>/pNNNN.json`，谁读谁触发重算（不进中心库，是现算缓存）。严格模式 R1/R3 缺省关（`GUJI_BINDINGS_STRICT=1`，bindings.py:80-96）。
- 没锚的老事件：查补锚档 `feedback/anchors/<book>.jsonl`（`anchor_backfill.py`），再不行拿字形库里当时的图块比；都不行且裁于现行切分之前 → 不采信（bindings.py:21-35）。vol01 曾有 682 条 09 月老裁一重切就全部不采信（ai `文本整理三阶段流程.md` §5.2 第 3 条）。

### 1.4 怎么回放进产物与字形库

两条腿，**不对称**：

| 腿 | 读什么 | 何时生效 | 出处 |
|---|---|---|---|
| **文本腿**（seed_admit 人裁通道） | `lookup.human_chars(book)`：遍历全部事件，只认 `kind=confirm ∧ v∈{confirm,seg_defect} ∧ 带 shape`，按 ts 后到覆盖，先过绑定表、再扣掉撤下标记（`human_stale_<日期>` 与 `feedback/lists/stale_verdicts.tsv`） | seed_admit 重跑时 | `cv/open_guji_cv/feedback/lookup.py:308-474`；seed_admit.py:736-738 |
| **字形库腿** | `glyphdb_admit` 消费者把 confirm 写进 glyph.db（provenance=human），再经 `db sync` 导出到 `output/glyph_store/` 真源 | 写事件时 `consume=True` 当场消费；或 `guji events route <批次>` | consumers.py:295-490、696-750 |
| 产物失效 | `product_invalidate` 把该页 seed_admit（或 row_segment）标 `invalidated`，**只标不跑**；`guji rerun <册> --stale` 只跑这些页 | 手动 | routes.py:149-154；cli_v2.py:2492-2503 |
| rebuild 后补放 | `glyph-db rebuild` 后按水位线（真源 admissions 最晚 `admitted_at`）补放 confirm 与 `admit_candidate`；`glyph_audit` 只报数不补放 | rebuild 时 | `cv/open_guji_cv/feedback/replay.py:1-38、157-194` |

seed_admit 里人裁一票定案，字优先取**库里**那份，库里没有才取事件里的（seed_admit.py:882-899）。排除名单在人裁之前判（seed_admit.py 注释 886；交接 ai `domain/文本/交接/vol02-03补精校-交接-10-20.md:20`：vol02 124 格名单盖住人裁）。

### 1.5 网站反馈要变成人裁事件，需要哪些字段

最小集合（按现行写法 `web_opinions.py write` → 控制台 `/api/events`，ai `team/CV/公众意见导入/web_opinions.py:25-40`）：

| 需要 | 从哪来 | 备注 |
|---|---|---|
| **cv 册 id**（`vol01`） | 网站给的是 book-text 条目 id＋`volume`；`web_opinions.py:184` 缺省拼 `vol<两位>` | 只对四庫成立（推测：换书就要映射表） |
| **格号** `页:列:格[a/b]` | 网站 `a`（精校页）／`cell_id`（charfix），与 char.json 的 `a` 同口径（`gf/spec/02-guji-char.md:18-33`） | 拼成 `vol01:72:4:4`。格号 = cv 几何格号（同上 :31） |
| **看到的是哪一版** | 精校页 `rev`（`001-r2` ↔ cv 侧 `vol01-r2`）；charfix `text_version` | **charfix 只有 text_version，没有 rev／cv 快照**，见断点 6.2 |
| **机器当时显示的字** | 精校页 `shown`；charfix `old_char`（前端取 char.json） | 用来核版本 |
| **建议**（字／无字／切坏／小注当正文…） | 精校页 `choice∈char/none/unsure/cut/jiazhu/main`＋`char`；charfix `new_char`（单字或 `{{组字式}}`）；charfix span 类别 `wrong/missing/extra/order/note/...` | 映射见 web_opinions.py:28-35：char→`confirm v=confirm shape`；none→`not_a_char`；cut→`seg_defect quality=truncated`；jiazhu/main→`seg_defect reason=…`；unsure→不写 |
| **来源** | `voter`（aid+IP 哈希前 16 位） | 写进 payload.note/source；`reviewer` 记写入人（H 道） |
| **锚** | **不能从网站来**：必须在「该 rev 对应的快照工作区」里由控制台现算 | ai `文本整理三阶段流程.md` §6.2「裁决必须在 rev 对应的那一版快照工作区里写」 |

`{{组字式}}`（charfix 允许，`web/edge-functions/api/charfix.js:41-47`）在 CV 侧会被 `EventLog.append` 的单字校验拒掉（events.py:247-252，`is_legal_shape` 只收单字/IDS/PUA）。推测：需要转成 IDS 或走 `fidelity`/`approx`。

---

## 二、文本导出与版本

### 2.1 Step9 → book-text 的流程

runbook（`cv/doc/runbook/整理一册书.md` 第四节）：

1. S14 `guji db sync -w $WS`（人裁、字形库进中心库）；
2. S16 `guji export md <册>`（Step9 md）＋ `guji collate`（对勘）；
3. S17 有新人裁先 `guji pipeline keben_body_v2 <册> --from seed_admit`，再 `python scripts/export_guji_format.py --products … --book <册> --chapter NNN --meta … --format char-cord --keys cv`（或 `guji export format`）出 char／cord／norm，自带 schema 与往返自检（runbook:330-342）；
4. `guji close-check <册> [--export-dir][--pending][--tier rough|final]`（第五节 14 项）；
5. S19 推 book-text：只替换本章 char/cord/norm、改 index.json（runbook:354-356）；版本号由 overview `scripts/book-text/bump_original.py` 改并写 CHANGES（bt `docs/VERSIONING.md:104-112`）。
6. 冻结：`guji snap pack` 打快照分支（guji-workspace `snap/<书>/<册>/<时刻>`），册 yaml 写 `freeze: {at, cv_version, snapshot}`（`cv/open_guji_cv/ops/freeze.py:1-20`）。

### 2.2 版本号

| 东西 | 号 | 出处 |
|---|---|---|
| 文本线 | char.json 顶层 `version` = index.json `text_version`；0.x＝粗校完（`proofing: true`）、1.0.0＝精校完、2＝出版级；≤50 处 patch，成批 minor | bt `docs/VERSIONING.md:53-98`；`gf/spec/02-guji-char.md:71` |
| 快照 r 号 | `<册>-r<n>`（cv 侧 `vol01-r2` ↔ pending 里 `001-r2`），每次并 main 推一个快照 | ai `team/整理/设计/定稿后增量修订.md:73-74`；`文本整理三阶段流程.md:228` |
| CHANGES | `<版本目录>/CHANGES.md` 一行 `日期｜册｜线｜旧→新｜说明｜PR`；规定写「cv 版本（commit）＋ws 快照＋事件库 commit」 | bt VERSIONING.md:55；三阶段流程 §2a 第 8 条 |
| 冻结基线 | 到 0.1.0/1.0.0 登记 `snap/<册>-r<n>`＋cv 版本＋产物 sha；冻结册不随 cv 升版重跑；**已放行格只增不改**，改放行格走人裁事件＋修订对照表 | ai `domain/CV/规范/冻结基线与重跑分级.md:7-19` |
| 修订对照表 | `revision_cells.py diff`（ai `team/整理/GUJI-541/revision_cells.py`）：`change∈char/state/geom/moved/shift/split/merge/added/removed`、`cell_id`、`old_id`、`mapping`、`text_changed`、`iou`；文件 `team/整理/修订/<册>-r<n-1>_to_r<n>.tsv` 长期保存 | `定稿后增量修订.md:53-68`、`:26-31` |

现状（bt `Book/g/z/k/96mid1ogzk/default/index.json`）：001 文本 1.0.0（proofing 仍 true）、002 1.0.1、003 1.0.2、004 0.2.2、005–006 0.1.1、007–010 0.1.0。

### 2.3 文本版本变了，网站反馈怎么映射回格号

- **字 → 格的对齐表就是 char.json 本身**：每格 `{"a": "页:列:格[ab]", "c": 字}`，数组顺序即读序（`gf/spec/02-guji-char.md:97-115`）；cord.json 按同一 `a` 给像素框，另有 `marks` 记空格与排除格（`gf/spec/01-guji-cord.md`）；decision.json 按 `cell` 记候选。网站前端取 `[data-char-id]` 作 `cell_id`（ai `team/网站/GUJI-561-charfix-接口规格.md:7`），所以**网站侧天然按格号报**，不按字序。
- guji-page／pages.json（cv 内部导出格式，`cv/doc/formats/guji_page_v0.2.md`）是 cv 工作格式，不进 book-text（`gf/spec/01-guji-cord.md` §一）。
- **跨版本**：格号不变（A 改字、B 放行态变）可直接用；格号变（C 重切、D 补页）要靠对照表 `moved/shift` 把旧 `a` 映射到新 `a`。设计要求「公众意见按 rev 重挂」由每日导入脚本实现（`定稿后增量修订.md:26-31`），**实际 `web_opinions.py` 没用对照表**，用的是「按 rev 找快照工作区，在那一版产物上写带锚事件，再交绑定表跟到新格」（web_opinions.py:21-26、255-277）。charfix 只带 `text_version`，没有 rev，靠 CHANGES 散文才能找到快照，见断点。

---

## 三、重跑

### 3.1 规矩

- **冻结册**（到 0.1.0/1.0.0）：代码变不报警只计影响；字形库/人裁变不报警、计「基线后新人裁 N 条待落地」；册配置变、产物 sha 与快照不符报警（`冻结基线与重跑分级.md:12-19`；实现 `cv/open_guji_cv/ops/freeze.py:85-150`，close-check 1a 冻结模式）。
- **重跑四级**：L0 只登记影响；L1 `guji exp run` 以发布快照作上游跑到 seed_admit 出差异报告，不动正式产物；L2 只对有待审格的页重跑、**只合并「待审→机器可放行」**；L3 整册重跑出差异单（`冻结基线与重跑分级.md:21-28`）。
- **草稿册受控重跑**（`ai/domain/CV/规范/受控重跑方法论.md`）：先算影响面、钉住无关变化（`glyph_pin: N`、`corpus: N`、`cv_version`）、重跑前存「前」（`guji products pack push`／`snapshot make`）、沙箱跑、`guji products diff` 看「放行字变」「人裁没带过来」「人审率」，验收后落正式并 `pack push`。新鲜只看本册当时的 cv 版本（close-check 1a 缺省「只因代码变过期、产物记着正式 cv_version 的页算新鲜」，`cv/open_guji_cv/ops/close_check.py:34-52`）。
- 指纹＝本步版本＋参数＋代码哈希＋直接上游产物 sha（不含上游代码），Step5-a/5-b 有格级复用（`core/reuse.py`）（`冻结基线与重跑分级.md:30-34`）。

### 3.2 重跑后旧人裁、旧裁决怎么保留

| 保留的东西 | 机制 | 能保多少 |
|---|---|---|
| 人裁定字（confirm） | 事件不进指纹、只追加；seed_admit 每次重读，过绑定表跟到新格 | 框没动或图块指纹相近才认；切开/合并/图块变了回待审。vol02 v0.4.6 重跑后掉 172 格，原因未查清（`受控重跑方法论.md:54`） |
| 切线、列字数 | `resolved_cuts`／`resolved_slots`（lookup.py），Step3 重跑时读 | 按 (page,col,slot) 编号，**未接入锚机制**（设计 15 的 P4 未做，`cv/doc/design/15-人裁锚定与重切后重绑定.md:7、150-151`） |
| 排除名单 `config/crop_exclusions.jsonl` | 按格号，先于人裁 | 同上，P4 未做；名单盖住人裁（vol02 124 格） |
| 机器放行字（非人裁） | **没有任何保留机制**：重跑就按新算法重算；冻结册靠「不重跑」保 | 「已放行格只增不改」只是规矩，代码里没有（全仓 grep 无 freeze/只增 相关的 Step 逻辑）；L2「只合并待审→放行」也没实现 |
| 撤下的人裁 | 字形库 `admissions.provenance='human_stale_<日期>'` 或 `feedback/lists/stale_verdicts.tsv` | lookup.py:308-342 |

### 3.3 现成的重跑工具

见第七节命令表。要点：`guji rerun <册> --stale`（只跑 product_invalidate 标过的页及下游）、`guji recheck`（Step5-a 点名格：`--chars`、`--verdicts`、`--dead`）、`guji products diff`（按位置对齐、切分变了也能比，`cv/open_guji_cv/ops/products_diff.py:1-25`）、`guji products pack push/fetch`（R2 产物包）、`guji exp run/report`。

### 3.4 机器发现新问题时怎么上报——「机器报错」通道

**没有专门的通道**。现有零散的几条：

| 来源 | 落到哪 | 后续 |
|---|---|---|
| 模型看图 `guji events import-vision` | `feedback/vision/*.jsonl`，`kind=vision_check, actor=model`；同时进金标分片 `char-recognition/vision-checks` | 判 `wrong` 送回待审（doubt `vision_flag`），不改字；`unsure` 只记账（runbook:236-258；`cv/open_guji_cv/feedback/vision.py`） |
| 放行错穷举 `guji audit admitted` | `reports/<册>/` 清单（读对勘 JSON，按系统性/异体/非系统分层） | 人逐格看，只读（`cv/open_guji_cv/ops/audit.py:1-60`） |
| 己已巳 `guji audit jys` | 清单＋muse 输入 | 人按文意判 |
| 重跑对比 `guji products diff` | report.md／columns.tsv／index.html，「放行字变」单列 | 人看图；vol01 0.1.6 就是用户在「重跑对比定字」页定 14 格、再把 128 格写成人裁事件 `H-rerun-diff-vol01-1019`（bt CHANGES 0.1.5→0.1.6） |
| 字形库体检 `guji glyph-db selfcheck` | 数据目录旁 `output/glyph_selfcheck/findings.jsonl` | 控制台体检 tab 裁 → `glyph_audit` 事件 |
| 升格候选 `guji promote mine` | 清单（形近对、异体对） | 人审后走引擎仓 PR |
| 冻结册「基线后新人裁 N 条待落地」 | close-check 1a 的 detail | 只计数 |

这些产出都是**各自的报表文件**，没有统一的「机器意见」事件种类、没有与网站讨论串打通、没有按冻结册「文本当前版本」去核对的入口。对冻结册，L1 差异报告（新算法 vs 冻结文本不同的格）是最自然的机器报错来源，但目前只是报告，不进任何队列（推测：可以把 L1 的「放行字变」「待审→放行」落成与 `vision_check` 同形的 `actor=model` 事件，进同一个待审／讨论面板）。

---

## 四、字形库自检

### 4.1 现有能力

| 能力 | 入口 | 查什么 | 产出 | 谁裁 | 裁决回到哪 |
|---|---|---|---|---|---|
| **库自检**（主力） | `guji glyph-db selfcheck -w <ws> [--no-others]`；控制台字形库页「体检」tab | 每个刻例 vs 本书其余刻例、兄弟工作区刻例、六套字体渲染：`outlier` 同字离群（留一最优 cov<0.90）、`rival` 形似本书他字（≥0.90 且反超同字）、`rival_xbook` 形似他书他字、`font_rival` 与所定字的字体不像却明显像另一字（cov≥0.90 且高出 0.15）；另按「人裁×人裁冲突」「context 放行」加权排序 | `output/glyph_selfcheck/findings.jsonl`、`summary.json` | 人在控制台体检 tab | `glyph_audit` 事件：`ok`／`near_form`（记 `near_forms.jsonl`）／`evict`（撤库）／`relabel`（改字重进库，provenance=human）／`fidelity`（exact/nearest/unencoded＋IDS，先查 Unicode 有无同结构字）（`cv/open_guji_cv/feedback/glyph_audit.py:1-155`；`clustering/glyph_selfcheck.py:1-75`） |
| **老体检 skill `glyphdb-audit`** | `scripts/audit_glyph_db.py run/apply` → review.html 发 Artifact | outlier、rival、`ocr`（RapidOCR top1≠库内字且 prob≥0.80） | report.json、review.html | 用户在 Artifact 点 X/O | `apply` 撤库或写 `audit_ok.json` 白名单（`cv/.claude/skills/glyphdb-audit/SKILL.md`） |
| 抽查 | 控制台 `glyph_spotcheck`（key `spot:<实例>`） | 随机抽 | 同一份 decisions.jsonl | 人 | 同上 |
| 撤下陈旧人裁 | `scripts/check_stale_human.py`、`research/verdict_drift_check.py` | 重字签名、人裁时图块 vs 现图块漂移 | `human_stale_<日期>` | 会话 | lookup.stale_human_marks |
| 金标漂移 | `guji gold drift [--apply]` | 产物重生后金标是否成立 | 标 stale | — | `cv/open_guji_cv/gold/drift.py` |
| 生僻字候选 Step5-b `rare_candidates` | 管线 | 字块 → 字体模板＋CNN 分类＋embedding 的 RRF top-k（字体域 `font:jigmo`、`font:iming` 由 `guji glyph-db import-font --edition …` 生成，不进中心库） | 产物 | Step6/7 用 | — |
| 相似字（以字找字） | `guji audit alt`／`alt-eval` | 给待审卡算相似字（字统网缓存；`hanzi` 离线关系库在建 B0/B1） | `<册>.cards.alt.json`，并进网站待审单雪碧图 | 公众/人 | 待审单 |
| 形近字组、异体字组 | seed_admit `group_flow`（M7，GUJI-563）：IDS 路、上下文 L1/L2、字频 `groups/freq.py` | 组内定字 | 产物 | 机器 | — |
| 字频表 `config/groups/freq.json` | `python -m open_guji_cv.groups.freq <ws>` | 异体组里本书人裁刻形哪个多（主形≥20、其余 0 才给主形） | 冻结成表，内容哈希进指纹 | 机器 | `cv/open_guji_cv/groups/freq.py:1-15` |
| 本书用字账 | `guji variants`；`scripts/build_book_variants.py` | 每个异体组本书刻了哪些形、各多少（products/db/human/align） | `config/variants/books/<edition>.json` | 只读 | `cv/open_guji_cv/variant_ledger.py:1-40` |
| 己已巳 | `guji audit jys` | 全族按文意 | 清单 | 人／muse | 人裁事件 |
| 升格 | `guji promote mine` | 对勘裁决里挖形近对、异体对 | 清单 | 人 | 引擎仓 PR → `guji corpus build-base` |

### 4.2 能查出／查不出

**能**：库里刻例标错成形近**他字**（紛→給 这类）；与字体都不像的刻例（可能该标 `nearest/unencoded`）；跨书第二意见；人裁手误。

**查不出**：

1. **「更贴近的异体」**：两条体检都按 `VariantMap.semantic`＋Unihan 异体把异体当同字，异体之间**不互判 rival**，`font_rival` 也排除异体字（`glyph_selfcheck.py:25-27、341-351、375`）。所以「刻的是卽、标成即」在体检里看不见。现在只能靠 M7 字组（逐组手写规则）、字频表、用字账间接覆盖。
2. **文本里的机器放行格**：体检只读 glyph.db 的刻例（`load_entries` 取 `exemplars`，`glyph_selfcheck.py:194-215`），一册 3 万多个放行格里不在库里的不查。放行字错只能靠 `audit admitted`（需要证人／整理本不同才出现）和看图抽查。
3. **整理本与刻本一致地错**、或没有证人的位置：对勘发现不了。
4. **OCR 路**：Step5-c 已删（seed_admit.py:752 注释），老 skill 的 `ocr` 信号要装 rapidocr 才有，新体检没有 OCR 路。

### 4.3 体检的回流问题

- 裁决账 `decisions.jsonl`、`near_forms.jsonl`、`findings.jsonl` 写在 `glyph.db` 旁的 `output/glyph_selfcheck/`（glyph_audit.py:40-42、105-112；glyph_selfcheck.py:437-471），**不在中心库范围**（scope.py 只收 `output/glyph_store/`，`scope.py:146-158`），换机器后「已裁不再出卡」失效；`glyph_audit` 事件本身在中心库，但 `decisions()` 不从事件重建。
- `evict` 撤掉一个**有 confirm 事件的人裁刻例**时：库里没了（`hs` 空），seed_admit 退回事件侧 `ht`，**照旧按旧字一票放行**（seed_admit.py:887-899；lookup.human_chars 只认 `human_stale_` 标记，`evict_instance` 是直接删行，`clustering/audit.py:155-185`）。glyph_audit.py:9 说的「下次跑到那一格重新出卡」对这类格不成立（代码推断，未实测）。
- `relabel` 走库侧（字优先取库），文本会跟着变；但它不是 confirm 事件，`human_chars` 仍返回旧字，任何只读事件的下游（如 `freq.py` 已处理、`revision_cells.py events` 模式未必处理）口径不一（推测）。
- 老 skill 文档已过时：用 `venv/bin/python`（CLAUDE.md 说旧 venv 是死的）、说「glyph.db、audit_ok.json 随 open-guji-cv 提交」（SKILL.md:17、50-52），与中心库现状不符；glyph_audit.py:18 也还写「裁完 glyph-db export 把真源带进 git」。

---

## 五、中心库（Neon＋Worker＋R2）里与反馈相关的表与接口

### 5.1 表（权威 `cv/open_guji_cv/datastore/schema.sql`）

| 表 | 内容 | 与反馈的关系 |
|---|---|---|
| `events`（:130-154） | 人裁事件与看图结论，带 `book/batch/kind/actor/reviewer/payload/target/rev` | 所有回流的真源 |
| `consumed`（:156-169） | 消费台账（按行号） | 判「这条事件消费过没有」 |
| `anchors`、`anchor_patches_meta`（:171-197） | 补锚档、锚图 sha | 重绑定 |
| `verdicts`（:212-227） | 金标信封 | gold_add 去向 |
| `files`（:229-246，视图 `lists`、`batches`） | 整文件：`feedback/lists/proofing/<书>/<章>.pending.json`（待审单）、`feedback/lists/web/<书>/<rev>.jsonl`（精校票快照）、`feedback/lists/web/<书>/fixes.jsonl`（读者改字快照）、重切清单、列交代单、`stale_verdicts.tsv`、`config/crop_exclusions.jsonl`、`config/groups/freq.json` | 网站意见的落点 |
| `glyph_*`（:248-） | 字形库各表；`glyph_evictions` 有撤例审计 | 体检裁决的结果 |
| `freeze_baselines`、`snapshots`、`cv_versions`（:91-125） | 冻结基线、快照、cv 版本登记 | **设计用来存 文本版本↔快照↔cv 的对应；没有任何代码写**（全仓 grep 只有 schema） |
| `changes`、`imports`、`source_files` | 逐行变更留痕、全局 rev | 审计 |

### 5.2 接口

- Worker `guji-data`（`https://data.open-guji.com`）：`/v1/tables/*`（读）、`/v1/tables/changes`、`/v1/events`（POST 追加事件行）、`/v1/assets/sign[-batch]`、`/v1/blob`、`/v1/snapshots/*`、`/v1/branches`、`/v1/packs`、`/v1/backups/*`（`cv/open_guji_cv/datastore/client.py:37-271`）；web 角色的 `GET/PUT /v1/files`（只读 `feedback/lists/proofing/**`、`feedback/lists/web/**`，只写 `feedback/lists/web/**`，只写 main），在 guji-workspace-data #8/#9 实现，10-19 已部署（ai `team/整理/设计/待审单与公众意见走中心库.md:39-43、73-80`）。
- 令牌分读／实验／正式／web；web 令牌复用网站 `FEEDBACK_ADMIN_TOKEN`（同上 :76）。

### 5.3 GUJI-610 是什么

Jira GUJI-610「[M8·8.9] 国内通道：网站内容导出到 COS，国内意见入口转发中心库」，**状态 待办**（2026-10-20 查）。原设计：国内意见先进 EdgeOne 边缘函数／腾讯云函数，再**转发** guji-data；国内页面不直连 Cloudflare/Neon（ai `通用/中心库设计.md:36-37、111`）。

实际落地的方案已改成**拉模式**（`待审单与公众意见走中心库.md` v0.1，10-19）：网站只写自己的 KV、只读 COS；kaiyuanguji-web 的 GitHub Action 每天 ① 从 KV 管理读意见 → `PUT /v1/files` 写进中心库 ② 从中心库读待审单 → 发 COS `proof/`。`proofing-sync`（web #500，定时 web #502，21:23 UTC）已上线；读者改字有 `fixes-sync`（`web/nextjs/scripts/lib/fixes-sync.mjs:1-20`，写 `feedback/lists/web/<书>/fixes.jsonl`、发 COS `proof/fixes/<书>.json`）。推测：GUJI-610 的实质已被这两个 Action 覆盖，但卡没更新、「国内网络实测能读能提交」的验收未记。

---

## 六、断点与问题（每条带出处）

### 6.1 通道没接上

1. **读者改字 `fixes.jsonl` 没有消费者。** Action 已把 `cf:` 记录写进中心库 `feedback/lists/web/<书>/fixes.jsonl`（`web/nextjs/scripts/lib/fixes-sync.mjs:1-20`），但 cv 与 ai-team 都没有读它的代码（grep `fixes.jsonl`/`charfix` 只命中规格与设计文档）。
2. **charfix 规格的去向绕过了 CV**：「记录由下游落成 GUJI-541 对照表的 A 类行，合入走 PR」（`web/edge-functions/api/charfix.js:9-10`；ai `team/网站/GUJI-561-charfix-接口规格.md:25`）。这样改的是 book-text，不写人裁事件、不进字形库；下次 CV 重导出会把它冲掉，或者像 vol01 0.1.6 那样事后要人再把手改格反写成事件（bt CHANGES 0.1.5→0.1.6）。与「改放行格走人裁事件＋修订流程」冲突（`冻结基线与重跑分级.md:11`）。
3. **精校票的 `web_opinions.py` 是一次性 H 道脚本**，没有定时、没有幂等台账（只在 Jira 记一行）；它读写 `<ws>/feedback/events`（web_opinions.py:215、450-457），迁中心库后 feedback 在数据目录，若照旧传工作区根会写错地方（推测，看调用方传哪个目录）；存档写 `<正式工作区>/feedback/web/<日期>.jsonl`（:20、191-192），`feedback/web/` **不在中心库收录范围**（scope.py:124-141 只认 events/vision/consumed/anchors/anchor_patches/verdicts/lists/candidates 与 feedback 根下文件）。
4. **册映射写死**：`web_opinions.py:184` 缺省 `vol<两位>`，book-text 条目 id 与中心库工作区 id（`96mid1ogzk` vs `siku-zongmu`）、cv 册 id 之间没有登记表（推测：换第二本书就断）。
5. **Worker `/v1/events` 直写的事件不会被消费、也不让产物过期**：消费只在本地 `route_and_consume` 跑（consumers.py:696-750），`product_invalidate` 也是消费者；seed_admit 的人裁指纹只看 glyph.db（seed_admit.py:617-628），不看事件，所以只进了事件表、没在工作区消费的人裁**不会让任何页过期**，`rerun --stale` 也找不到它们。若以后让网站／Action 直接写 events，必须补一个「拉下来后补跑消费者」的步骤。
6. **`{{组字式}}`**：charfix 收（charfix.js:41-47），CV 事件写入拒（events.py:247-252）。
7. **设计里的 `GUJI_EVENTS_BACKEND=central` 未实现**（ai `通用/中心库设计.md:93`；cv 全仓无此变量），设计里「consumed 与写库同一事务」（同文 3.1 表）也不成立：消费在本地、推库在 `db sync`，中间可分叉。

### 6.2 定位与版本

8. **book-text 格号与 CV 格号分叉**：vol01 0.1.4 手拆 90:6:2→2a/2b、184:9 拆格；0.1.5 删框线碎片格 10:7、48:8 等、补字 4 处，cord「按原框近似」；vol02/03 1.0.1「补删格的 cord 按原框近似」（bt CHANGES 0.1.3→0.1.4、0.1.4→0.1.5、1.0.0→1.0.1）。交接：「格 id 与 cv 切分对不上，所以不能落成格事件」（ai `domain/文本/交接/vol01-1.0.0收尾与18列重切-交接-10-20.md:11`）；18 列重切已叫停（ai `domain/CV/交接/vol01重切18列-交接-10-20.md:44`）。网站上对这些格的反馈落不回 CV。
9. **文本版本 → CV 快照没有机器可读映射**：char.json 只有 `version`（`gf/spec/02-guji-char.md:68-75`）；cord `producers.cv` 过期——vol01 1.0.0 的 cord 205 页仍写 `rev 9587e67c / snapshot claude/vol01-prod-4324e4b`（bt `001.cord.json` 实查），而冻结基线是 `snap/96mid1ogzk/vol01/20261019T2303`（cv 0.4.5）；`text_version↔r 号↔cv 版本` 只在 CHANGES 散文里，且 0.1.6、1.0.0 两行已不写 r 号（bt CHANGES 第 129 行）。中心库 `freeze_baselines/snapshots/cv_versions` 三表无人写（schema.sql:91-125）。
10. **charfix 只带 `text_version` 不带 rev**（charfix.js:12-13），而 CV 写事件要的是「那一版产物」（锚）。从 text_version 找产物要人读 CHANGES。
11. **对照表重挂没实现**：设计要求「旧 rev 的意见用对照表映射到新 rev 格号，映射不到的列给人」（`定稿后增量修订.md:26-31`），`web_opinions.py` 改用快照工作区＋绑定表；对照表长期保存目录 `team/整理/修订/` 在 ai-team 里**不存在**（实查）。
12. **写事件必须有该 rev 的产物在本机**：锚由控制台按现行产物算（feedback.py:105-140、178-208）。冻结册产物在 guji-workspace 快照分支或 R2 包；vol01 曾「本机没有产物、pack list 为空」（`vol01重切18列-交接-10-20.md:33`）。
13. **close-check/release_gates 的 `--pending` 仍指 book-text `NNN.pending.json`**（cli_v2.py:2726；ops/release_gates.py:4-6、110-111；runbook:368），而待审单 10-20 起已改存中心库 `feedback/lists/proofing/`、book-text 的 pending_file 已删（`文本整理三阶段流程.md:195`；index.json 实查 `pending_file: None`）。

### 6.3 重跑与保留

14. **「已放行格只增不改」无代码保障**；L2「只合并待审→放行」未实现（全仓无相关逻辑）。冻结册要吸收新算法的改进，只能 L3 整册重跑或手工挑格。
15. **只有人裁定字走了锚**；切线、列字数、排除名单仍按格号（设计 15 P4 未做，`cv/doc/design/15-人裁锚定与重切后重绑定.md:7、150-151`）。排除名单先于人裁、盖住人裁（`vol02-03补精校-交接-10-20.md:20`）。
16. **重跑后人裁掉格原因未明**：vol02 v0.4.6 重跑掉 172 格（`受控重跑方法论.md:54`）；vol02 交接另报绑定表判 review 约 10 格（`vol02-03补精校-交接-10-20.md:21`）。
17. **人裁进库让所有共用该库的册 seed_admit 过期**（`冻结基线与重跑分级.md:34`）；`glyph_pin` 缓解但第一次写会过期一次（`cv/doc/受控重跑.md:16`）。网站反馈若高频落裁决，未钉的草稿册会被反复判过期。
18. **没有「机器报错」队列**（见 3.4）；vision 结论、audit 清单、products diff、体检各自成文件，不能在网站讨论串或统一待审面板里出现。

### 6.4 字形库自检

19. **异体选错查不出**（glyph_selfcheck.py:25-27、341-375）。
20. **只查库、不查文本放行格**（glyph_selfcheck.py:194-215）。
21. **体检裁决账不进中心库**（glyph_audit.py:40-42、105-112；scope.py:146-158）。
22. **撤库不撤文本**：evict 有 confirm 事件的人裁刻例后，文本仍按事件出旧字（seed_admit.py:887-899；lookup.py:308-342；audit.py:155-185）（代码推断，未实测）。
23. **glyphdb-audit skill 过时**（SKILL.md:17、50-52；glyph_audit.py:18）。
24. 网站读者看到的「这个字更像 X」（charfix 改成异体）没有路径回到字形库的 `relabel`／`fidelity`。

### 6.5 其他

25. **事件 kind 枚举有 9 个死值**（events.py:23-35 自述），`recrop`（整列重切）无出口——而重切正是 1.0 后改字的主要难点（`文本整理三阶段流程.md` §5.3 缺口表：补格、删格、版框坐标、逐页页型、整列重切都「没有」）。
26. **中心库事件 id 重复**：四庫 `vol01-cutline.jsonl` 与 `vol01-cutline-split_char.jsonl` 有 14 个 id 相同内容不同；`consumed/glyphdb_admit.jsonl` 178 处重复记账（`cv/doc/datastore.md:86-88`），「等人定」。
27. **GUJI-610 卡状态与实际不符**（Jira 待办；实际 proofing-sync 已上线，fixes-sync 已写）。

---

## 七、相关现成命令（输入 → 输出）

全部带 book 的命令要 `-w <工作区>`。

| 命令 | 输入 | 输出／作用 | 出处 |
|---|---|---|---|
| `guji db pull -w <ws> [--rev N] [--force]` | 中心库 | 数据目录还原；拉到新字形库就重建 glyph.db | datastore.md:158-175 |
| `guji db push -w <ws> [--dry-run] [--allow-delete]` | 数据目录 | 推中心库；先比 rev，只追加台账少行拒 | 同上 :176-181 |
| `guji db sync -w <ws> [--dry-run] [--watch 600]` | 两边 | 拉＋合并＋推 | :182-186 |
| `guji db status -w <ws>` | | 落后几条、哪些没推 | :164 |
| `guji db migrate -w <ws> [--keep-local]` | 旧布局工作区 | 数据挪进数据目录、写标记 | :171-172 |
| `guji db branch create/list/delete`、`guji db diff`、`guji db import --from exp/… [--events ids.txt]` | | 实验分支；事件按 id 幂等导回 main（经 `/v1/events`） | :196-227 |
| `guji store check/commit -w <ws>` | glyph.db | 导出真源＝`db push` | cli_v2.py:2759-2764 |
| `guji glyph-db rebuild [--no-replay] [--no-borrow]` | glyph_store 真源＋事件 | glyph.db；缺省按水位线补放人裁 | cli_glyph_db.py:137-170；replay.py |
| `guji glyph-db selfcheck [--no-others]` | glyph.db（＋兄弟库、字体域） | `output/glyph_selfcheck/findings.jsonl` | cli_glyph_db.py:100-107 |
| `guji glyph-db import-font --edition font:jigmo|font:iming` | `fonts/` | 字体域进 glyph.db | 经验.md |
| `python -m open_guji_cv.feedback.replay [--dry-run]` | 事件 | 只补放 admit_candidate | replay.py:197-210 |
| `guji events harvest|route|list|verdicts|import-vision` | 批次／文件 | 收割旧格式、按路由表消费、列事件、导入看图结论 | cli_v2.py:2864-2877 |
| 控制台 `POST /api/events`（`EventsIn{batch, step, unit, kind, events[{id,…}], request_id, consume}`） | 格号＋payload | 追加事件、现算锚、可当场消费 | console/routers/feedback.py:48-70、143-250 |
| `guji rerun <册> --stale [--dry-run] [--to]` | manifest 里 invalidated 的页 | 只跑这些页及下游 | cli_v2.py:2492-2503 |
| `guji recheck <册> [--chars][--verdicts][--dead][--all]` | Step5-a 记录 | 点名格失效；再 `pipeline --from glyph_match` | cli_v2.py:2766-2776 |
| `guji pipeline <pl> <册> --from X --to Y --pages …`；`guji step` | | 跑管线 | cli_v2.py:2479-2490 |
| `guji status <册> --pages all` | | 各步新鲜/过期及原因 | cli_v2.py:2706 |
| `guji close-check <册> [--export-dir][--pending][--tier][--strict-cv][--json]` | 产物、导出、清单 | 14 项体检（1a 冻结模式比快照；8 查数据目录有没有没推的） | ops/close_check.py:1-20 |
| `guji products diff <册> --a <前> [--b <后>] [--images N]` | 两份产物根 | report.md、columns.tsv、summary.json、index.html；「放行字变」单列 | ops/products_diff.py；doc/受控重跑.md:22-34 |
| `guji products pack push|list|fetch|push-index|fetch-index` | 产物 | R2 产物包（标签 `cv<版本>-c<语料>-g<字形>-<改动>`） | doc/受控重跑.md:36-52 |
| `guji snap pack|import|list` | 产物 | guji-workspace 快照分支（冻结基线用） | cli_v2.py:2664-2704 |
| `guji snapshot make <册>` | | 本机拷贝一份「前」 | cli_v2.py:2625 |
| `guji exp run|report|flips` | 快照＋开关 | A/B 沙箱，不动正式产物 | doc/exp_framework.md |
| `guji export md|format <册> [--chapter][--meta]`；`scripts/export_guji_format.py` | 产物 | Step9 md；lines.md/pages.json/norm；char/cord | cli_v2.py:2729-2737；runbook S16-S17 |
| `guji collate <册>` | 产物＋证人 | 对勘 JSON/HTML | cli_v2.py:2995 |
| `guji audit admitted|jys|count|sheet|alt|alt-eval <册>` | 对勘、导出、卡片 | 放行错穷举、己已巳清单、核数、请审单、相似字 | cli_v2.py:2739-2757；ops/audit.py |
| `guji gold shards|show|migrate|drift|import|export|rebuild` | 裁决表／测试集 | 金标管理；`drift --apply` 标漂移 | cli_v2.py:2889-2905 |
| `guji eval list|run [--from-raw]` | 测试集 | 评测 | cli_v2.py:2879-2887 |
| `guji promote mine -w <ws>` | 对勘裁决 | 形近对、异体对候选清单 | datastore.md:292-298 |
| `guji glyphlib build … [--push]` | 人裁刻例 | 共享刻例库（借用时降一档） | datastore.md:272-290 |
| `guji variants` | | 本书用字账（只读） | cli_v2.py:2991 |
| `python -m open_guji_cv.groups.freq <ws>` | 字形库＋事件 | `config/groups/freq.json` | groups/freq.py |
| ai-team `web_opinions.py fetch [--from-db <ws> --book <条目> --rev <rev>] / import / triage --ws-for-rev / sheet / write --official-ws` | 中心库票快照 | 拟写裁决、给用户单、正式事件 | ai `team/CV/公众意见导入/web_opinions.py:1-40` |
| ai-team `revision_cells.py diff --before --after --book` / `events` | 两份产物或产物＋事件 | 对照表 TSV | ai `team/整理/GUJI-541/revision_cells.py:1-30` |
| ai-team `pending_list.py --ws <ws> --text-id <条目>` | 产物 | 数据目录 `feedback/lists/proofing/<条目>/<章>.pending.json` | `待审单与公众意见走中心库.md:75` |

---

## 八、给后续设计的几点建议（推测，供讨论）

1. **定一个统一入口**：所有网站文字意见（cellreview 票、charfix 改字、span 报错）都先落中心库 `feedback/lists/web/…`，再由**同一个**定时 H 道程序（把 `web_opinions.py` 并进 cv，作为 `guji web-opinions`）转成 `cell_review` 形状的「意见事件」，AI 判后写正式 `confirm`；book-text 只经 CV 重导出更新，不手改。
2. **补版本映射**：每次导出把 `{text_version, rev, cv_version, cv_commit, snapshot, products_pack}` 写进 char.json 或 index.json 的一个可选字段，并写中心库 `freeze_baselines/snapshots`；charfix 记录加 `rev`。
3. **book-text 手改格先补回 CV**：要么 CV 支持「补格／删格／拆格」人裁事件（三阶段流程 §5.3 缺口），要么规定 book-text 不再手改格号。
4. **机器报错 = `actor=model` 的意见事件**：L1 差异、vision、体检、`audit admitted` 统一落成一个 kind（例如扩 `vision_check` 的 `source`），进同一待审／讨论面板；对冻结册只送人，不改字。
5. **体检加「异体贴合度」一路**：在异体组内比刻例与各异体字体渲染／本书各异体刻例的距离，出「标 A 更像 B」卡；同时把文本放行格（不止库）按批抽进体检；`decisions.jsonl` 改从事件重建或纳入中心库。
6. **撤库要连带撤事件侧人裁**：evict 有 confirm 的人裁刻例时写 `stale_verdicts.tsv` 或 `human_stale` 标记，让该格回待审。
