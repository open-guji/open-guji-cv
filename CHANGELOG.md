# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号规矩见 `doc/版本号规矩.md`。
本文件记录**全部**版本（含 PATCH）；动代码的 PR 在待发分支的 `## [X.Y.Z] - 待发` 下加一行；发版时把「待发」改成日期（见版本号规矩第三节）。

## [0.3.3] - 待发

待发分支 `rc/v0.3.3`。

### Added
- 字组统一流程 `seed_admit.group_flow`（新 variant-tie，2026-10-18 sheldon 定，缺省关）：点名注册表里声明了 `flow` 的字组（首批七个异体组 蒙𫎇／點㸃／參㕘叅／讖識䜟／隸𨽾／慎愼／旨㫖，三个形近组 己已巳／日曰／入人八）；没放行的格若库候选（与 top1 分差 <0.03）＋整理本字全在一组，按组声明的解法给字放行（通道 `group_flow`）或留人审，己已巳、入人八另对已放行格复核；每格写 `evidence.group`。新解法「字频」：按人裁刻形冻结每套书一张表（`python -m open_guji_cv.groups.freq <工作区>`），主形 ≥20 且次形为 0 才给字。`groups/registry.py` 新增 `FlowSpec` 与七组（`groups/flow.py`、`groups/freq.py` 进 `seed_admit` 的 `code_deps`）。PATCH；**`seed_admit` 的 `code_hash` 变**（与下面删 5-c 合计 a995ac96→03ad95f1），关时产物不变。
- `group_flow` 的 `ids` 解法接上在线判别（方案 S7，sheldon 10-18 定）：新模块 `groups/ids_online.py`，字块图自动缝一刀 → 决定字的那一段在冻结模板库里最近邻 → margin ≥ 门槛且该类刻例 ≥8 才给字，否则弃权，`evidence.group` 里留 IDS、部件、margin、各部件分数。首批只开 參㕘叅（`can`，门槛 0.04；人标池 74 格留一 59 对／15 弃权／0 错，留一册 57／17／0；叅只 2 例永不给），模板库 `config/groups/can/ids_bank.json` 由 `python -m open_guji_cv.groups.ids_online build can --dataset <dataset>` 从 dataset 人标池建（工作区 `config/groups/ids/<组>.json` 优先）；模板库、判法参数、`ids_override.tsv`、`ids_lv1.txt` 的哈希进 `group_flow_fingerprint`（没有在线 IDS 的组不加，旧指纹不变）。其余组（彝、慎愼、旨㫖…）没有模板库，照旧弃权且不取图。`groups/ids_online`、`ids`、`ids_two`、`ids_parts`、`ids_segment`、`ids_solver` 进 `seed_admit` 的 `code_deps`。PATCH；**`seed_admit` 的 `code_hash` 变**（ce3a31cce2908038→332a5956257e5a6b），关时产物不变。
- `group_flow` 的表路径：相对路径按工作区解释；没给时用工作区 `config/groups/freq.json`、`config/groups/l2/<组>.json`（有才用）。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。
- 字频表计数也认字形库体检的改字／撤库事件（`glyph_audit` relabel／evict），同格按时间取最晚。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。

### Removed
- 删两个不再用的步骤（2026-10-18，sheldon 定）：Step6b `group_decide`（连同产物 `group_decision`、书级 `group_decide:`）与 Step5-c `ocr_candidates`（连同产物种类、书级 `ocr_candidates:`、控制台开关 `PUT /api/books/{book}/ocr_candidates` 与汇总 `GET /api/ocr-candidates/{book}/summary`、前端 5-c 子页）；两条 pipeline yaml 去掉这两步，老 yaml 里的两个键读进来无作用。`align_ref`／`context_decide`／`seed_admit` 不再把 `ocr_candidates` 列为可选上游，OCR 一路恒缺席（等价于原先开关关着，四庫 vol01–10 输出语义不变）。**这三步 `code_hash` 变**（215217611967ce6c→e66b1c3f632c469a、043c75a9ba56ddae→4a12db2db381a543、a995ac964c981e29→03ad95f1c34eb510（连同本版 group_flow）），各册这三步判过期；其余 14 步不变。

## [0.3.2] - 2026-10-17

PATCH。版本护栏、冻结基线、`archive fetch`、`rerun --stale`、规矩文档（没赶上 0.3.1 的 4 个 PR），中心库导入（`datastore`），以及 GUJI-555／622 积下的几个缺省关开关（夹注忽略 rule_bar、遮挡救回、绑定严格档、column_gate 周期先验）。

### Added
- 产物 manifest 每条记 `cv_version`（最近正式 tag，不在 tag 上写 `0.3.0+N`，有未提交改动加 `+dirty`）与 `cv_commit`（完整 sha）；册配置可写 `cv_version`，`guji step`／`pipeline` 发现装的版本不同就拒跑（`--allow-cv-mismatch` 放行），`status`／`progress` 只提醒（GUJI-577，版本号规矩第五节）。PATCH；`core/engine.py`、`core/book.py`、`core/cv_version.py`、`products/manifest.py` 都不在任何 Step 的 `code_deps`，新字段不进 `book_deps`，19 步 `code_hash` 不变。
- 冻结基线（GUJI-601，规矩见 ai-team `domain/CV/规范/冻结基线与重跑分级.md`）：册 yaml 写 `freeze: {at, cv_version, snapshot|manifest}` 后，`guji close-check` 1a 改比快照 manifest 的产物 sha256，不再因 cv 升版、人裁进库报过期；只有产物被改／缺、册配置或参数被改才不过（各步 `_manifest.jsonl` 不比；旧条目分不清代码还是册配置的单列请人核）；另报「基线后新人裁 N 条待落地」（`ops/freeze.py`）。PATCH；`ops/`、`core/book.py` 不在任何 Step 的 `code_deps`，`freeze` 不进 `book_deps`，19 步 `code_hash` 不变。
- 新命令 `guji archive fetch <tag> --out <空目录>`：取回 open-guji-dataset Release 上的归档 tar，按 `--sha256` 或资产自带 digest 核对后安全解包（拒越界路径、设备文件；跟随重定向跨域时去掉 token）（`ops/archive_fetch.py`，GUJI-601）。PATCH（10-18 起新 CLI 命令只算 PATCH）；不碰任何 Step。
- 新命令 `guji rerun --stale <册>`：只重跑 manifest 里显式标了失效（人裁落定等）的页，逐步往下传，只把上游真重算了的页交给下游；上游跳过的页不往下传，因 cv 升版、字形库变化而过期的页不跑（`ops/rerun_stale.py`，GUJI-578，设计 §5.2 第 4 条）；与 pipeline 一样过 cv 版本护栏（`--allow-cv-mismatch` 放行）。PATCH；不碰任何 Step，19 步 `code_hash` 不变。
- 中心库 `open_guji_cv/datastore/`（GUJI-603／605）：Postgres 表结构 `schema.sql`；从 guji-workspace 某个提交幂等导入（`python -m open_guji_cv.datastore import`，按主键比内容哈希、全局 rev、只追加台账的删除护栏）；库与提交逐行核对（`verify`）；刻例图与锚图按 sha256 上 R2 的计划与上传（`r2-plan`，默认只出清单）。新 extra `datastore`（psycopg、boto3、websockets）；只通 443 时用 `datastore.wsbridge` 经 Neon 的 WebSocket 连库。说明见 `doc/datastore.md`。PATCH；新包，19 步 `code_hash` 不变。
- 闸2 `column_gate` 两个周期开关（GUJI-622／GUJI-364，vol01 p196）：`period_prior_pages`（点名页不估页级周期，直接用书级 `period_prior`，记 flag `period_fallback`）与 `period_edge_fallback`（估值贴窗口下界 ≤ int(先验×0.7)+1 时回落先验）。都缺省关，关时不进参数 dump、产物逐字节不变。PATCH；**`column_gate` 的 `code_hash` 变**（8935ff6f → 25658f2b），各册该步判过期，重跑后产物不变、下游不重算。
- 人裁绑定 R1/R3 严格档（环境变量 `GUJI_BINDINGS_STRICT`，缺省关，关时行为逐字节不变；GUJI-555）：补锚 ink 路径 rebound 且上下文核对 `differ`→待审；同页同列整列同量偏移无 ctx 旁证→待审；`human_chars` 同格更晚事件不可用时更早事件不顶上、rebound 落点有更晚原生事件时让位。动 `feedback/`，19 步 `code_hash` 不变（worktree 复算）；开关不进参数指纹，开了要手动重算 seed_admit。
- `seed_admit.nonchar_jiazhu_ignore_rule_bar`（缺省关，方案 A）：开了 `nonchar_gate` 对夹注格不再因 `rule_bar` 撤回放行；关着不进参数哈希（GUJI-555，vol04 p216／p218）。动 `seed_admit` 的 `code_hash`，**seed_admit 及下游步产物判过期**，窗口合并，同 cv#102 只让该步过期一次。
- `seed_admit` 参数 `occluded_rescue_ink`（缺省 0＝关）：遮挡块里格内大块墨占比 ≥ 该值的清楚的字格不算遮挡（GUJI-555，vol04 p130 前 8 格误判 occluded）。`cell_shrink`、`seed_admit` 的 `code_hash` 变（`steps/occlusion.py` 在二者 `code_deps` 里），关着时输出不变。

### Changed
- 版本号规矩（`doc/版本号规矩.md` 第二、三、六节，用户 2026-10-18 定）：任何时候都有一条待发分支 `rc/vX.Y.Z`（缺省 PATCH 加一，CHANGELOG 记在 `## [X.Y.Z] - 待发` 节），功能分支合进它、不直接合 main；合进来的改动缺省关、随时可发，谁都可以发 PATCH；MINOR 收紧为「对大部分册值得重跑一遍」，新增 CLI 命令或参数只算 PATCH。文档改动，PATCH。

### Fixed
- `close-check` 2b「人裁字≠放行字」：字形与放行字互为规范字／异体（埀↔垂 类）的单列 `kind=canon`，不再混进正文一类（GUJI-555）。PATCH；仅 `review/verdict_view`、`cli_v2`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.3.1`：`column_gate`（GUJI-622）、`seed_admit`（夹注忽略 rule_bar、遮挡救回）、`cell_shrink`（`steps/occlusion.py`）3 步变，其余 16 步不变；新开关全部缺省关，关时产物不变。

## [0.3.1] - 2026-10-17

集成分支 `rc/v0.3.1`，M7 扩展（第二阶段）；各功能 PR 合入时在此补条目。

### Added
- M7 上下文路扩展：戊戌戍／未末／土士的 L1 规则与 L2 提示词（`config/groups/{wxs,wm,ts}`）及研究脚本 `research/m7/ctx/ext_*.py`（#118）。**尚未接线**（registry 无对应 GroupSpec），不生效；19 步 `code_hash` 不变。
- M7 量横画法：土士／未末按两横长短取字的研究脚本 `research/m7/bars/` 与结论文档（#119）。仅研究脚本与文档，19 步 `code_hash` 不变。

- 量横长短 ts／wm 接进 `seed_admit`（书级开关 `m7_bars`，缺省关）与 registry 的 wxs／wm／ts 登记（#120、#121）；IDS 两段版 `groups/ids_two.py` 与參㕘叅配置（#117，未接 Step）。

Step 的 `code_hash` 相对 `v0.3.0`：仅 `seed_admit` 变（684cd42c → a60d8f25），其余 18 步不变。vol04 组合 A/B 见 `doc/exp/m7_rc031-vol04-报告.md`：组外差异 0。

### Fixed
- 引擎页级并行（`--jobs>1`）：worker 改由主进程直接传入册、管线、合并后的参数与产物／缓存根目录，不再按 id 重新加载。以前 CLI `--params` 与管线 yaml 的 `params:` 在并行步（`border_detect`、`line_detect`）上全丢，产物按缺省参数算、指纹却记覆盖后的参数；沙箱 `ProductStore` 也被忽略（GUJI-580）。PATCH；`core/engine.py` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

## [0.3.0] - 2026-10-17

### Added
- Step1 `border_detect`：窄对合并 `merge_narrow_pair`（缺省关，不进参数 dump）：相邻两条内部窄列、宽度和≈一列时用 `expected_cols−1` 重探，去掉把大字列劈成窄条的伪竖线（GUJI-572，vol04 p80／p217）。`border_detect`、`border_detect_gate`、`column_gate` 的 `code_hash` 变，关着时输出逐字节不变。
- M7 形近字优化算法（GUJI-563）的库代码 `open_guji_cv/groups/`：IDS 路（`ids*.py`，彝六字形，通用 IDS 语法、折线切分、字体模板二选一）与上下文路（`context.py`/`ctx_l1.py`/`ctx_l2.py`，日曰／己已巳／入人八，上下各 20 字）；注册表加 `kind`／`solvers`／`config_dir`；`config/groups/<组>/` 规则与提示词。**尚未接进任何 Step**，缺省不生效。
- `seed_admit` 的 M7 接线开关 `m7_groups`／`m7_l2_tables`（缺省关）与 `groups/m7_pass.py`（GUJI-563）；`doc/exp/m7_groups-vol04.yaml`、`doc/exp/跑实验经验.md`。
- 设计与评测：`doc/design/M7-*.md`、`research/m7/`。
- `scripts/zhengli/collect_exit.py`＋`exit_report.py`：对一册自动取粗校出口 R1–R5 的数并拼固定格式报告（GUJI-556）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。
- `guji close-check --tier rough|final`（缺省 `final`，行为不变）：粗校档第 2 项「待审清零」只报数、不计（GUJI-555）。PATCH；仅 `ops`/`cli_v2`，19 步 `code_hash` 不变。
- `guji pipeline --isolate-steps`：每个 Step 一个独立子进程跑（默认关），整册跑时内存不再逐步叠加（GUJI-555）。PATCH；仅改 `cli_v2`，19 步 `code_hash` 不变。
- `scripts/relanding/`：重落后核对脚本（manifest_cmp／relanding_diff／products_snapshot），从 guji-workspace 的 exports 迁入（GUJI-555）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。

### Fixed
- `guji snap import` 认 `GUJI_PRODUCTS_DIR`（沙箱），不再无视它写进工作区本体的 `products/`（GUJI-555）。PATCH；`snap/` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。
- 导出（`export format`／`export_guji_page.py`）：看图判错、人还没裁的放行格记 `review: pending`（并带 `vision_flag` 标记），不再当已校对写进 char.json；与 close-check／控制台待审同口径（GUJI-555）。PATCH；`formats`/`feedback` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.2.1`：`border_detect`、`border_detect_gate`、`column_gate`、`seed_admit` 4 步变化，其余 15 步不变（实算 `core.engine.code_hash`）；新参数缺省关、关时不进参数 dump。

## [0.2.0] - 2026-10-17

### Added
- guji-proof 0.2 审阅字段模块 `open_guji_cv/review/proof_fields.py`。
- 统一字组接口 `open_guji_cv/groups/` 与统一评测 `open_guji_cv/eval/groups.py`（尚未被任何 Step 引用）。
- 字组参数守卫 `tests/test_group_params_guard.py`：不许再往 `SeedAdmitParams` 加新的字组参数。
- 包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。

### Changed
- 版本号规矩改为 `vX.Y.Z` tag、按 PR 滚动升版。

### Removed
- 旧 exe 发布流水线 `release.yml`（移至 `doc/archive/release.yml.legacy`）。
- 死代码：`steps/step6_signals.py`、v1 桥。

Step 的 `code_hash` 相对 `cv-v0.1.0` 无变化（19 步逐位相同）。
