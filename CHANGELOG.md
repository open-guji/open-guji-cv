# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号规矩见 `doc/版本号规矩.md`。
本文件记录**全部**版本（含 PATCH）；动代码的 PR 在待发分支的 `## [X.Y.Z] - 待发` 下加一行；发版时把「待发」改成日期（见版本号规矩第三节）。

## [0.3.5] - 2026-10-18

PATCH。中心库客户端与写入切换（数据迁出工作区、`guji db sync` 自动合并、每日备份；GUJI-606/608/611），group_flow 第三批形近字组。相对 v0.3.4 只有 `seed_admit` 的 `code_hash` 变（6a4e2bd27c35fa8a → f0f2713200ae880e），其余 16 步不变；没迁进中心库的工作区行为不变。

### Added
- `guji db status|pull|branch|import`：中心库客户端（GUJI-606，工作包 8.5）。`pull -w <工作区>` 经 guji-data Worker 把字形库账本按当前版本还原到 `<工作区>/output/central/<分支>/output/glyph_store/`（每个文件核 sha256，刻例图按 sha 从 R2 拉进本地缓存 `GUJI_DATA_CACHE`、去重），再重建 `glyph.db`，等价于 `glyph-db rebuild --no-replay --no-borrow`；git 管着的 `output/glyph_store/` 不动，库旁写 `glyph.db.central.json` 记分支与 rev。`--rev N` 只在该工作区 N 之后没变时放行（中心库不存旧内容），`--with-feedback` 连 feedback/ 一起还原。`branch create|delete` 开删实验分支，`import --from exp/<名>` 把实验分支的事件显式导入正式库（经 Worker `/v1/events`，按事件 id 幂等；写入切换 GUJI-608 前 Worker 不接受写 main）。连接只认 `GUJI_DATA_URL`／`GUJI_DATA_TOKEN`／`GUJI_DATA_BRANCH`。新模块 `datastore/client.py`、`materialize.py`、`pull.py`、`cli_db.py`，不进任何 Step 的 `code_deps`，**17 步 `code_hash` 全部不变**（逐步对照验过）；不用就没有任何影响。`python -m open_guji_cv.datastore r2-plan --via worker` 改为每 200 张调一次 `/v1/assets/sign-batch`（旧版 Worker 退回逐张签）。

- **数据迁出工作区**（GUJI-608，2026-10-19，用户定）：中心库是册 yaml、人裁事件、台账、批次、人工配置、字形库唯一的家，工作区里只留 `workspace.yaml` 和标记 `.central.json`，数据在工作区外的数据目录 `$GUJI_DATA_HOME/<分支>/<工作区 id>/`（缺省 `~/.guji-data`）。`core/workspace` 加 `data_root`／`books_dir`／`ws_config_dir`，见到标记就把数据路径指向数据目录，没有标记照旧；各处从工作区根直拼的路径改走这些函数（`core/book`、`corpus_pin`、`seed_admit`、`groups/freq`、`groups/ids_online`、`collate_consumers`、`snap/*`、`deploy_check`、控制台工作区列表），守卫 `tests/test_central_paths.py`。新命令 `guji db migrate`（核对后挪数据、写标记，glyph.db 不动）、`guji db pull`（中心库 → 数据目录，拉到新字形库才重建 glyph.db）、`guji db push`（拿库锁后先比版本号，别人先写过整次拒绝；只追加台账少行、整个文件丢了也拒绝；glyph.db 改过先导出；新图先经 Worker 传正式桶；连库用 `GUJI_DATA_PG_DSN`，没有就从 `NEON_DATABASE_URL` 自动起 443 桥）。迁过的工作区上 `guji store commit|check` 改为推中心库，close-check 第 8 项改查没推的改动。新模块 `datastore/workcopy.py`、`ops/central_glyph.py`；`importer.import_scans` 从 `import_commit` 拆出（加 `guard` 钩子）；旧的 `db pull` 只读快照（`output/central/`）删掉。**`seed_admit` 的 `code_hash` 变**（50b4c7c96150b33d → f0f2713200ae880e，字组表改从数据目录找；本版字组第三批已经让它变过一次），其余 16 步不变。没迁的工作区行为一字不变。

- `guji db sync -w <工作区> [--dry-run] [--watch 秒]`（GUJI-608 B 块）：拉＋合并＋推一步做完。别人先写过时不再整次拒绝：库里改了本地没改的取库里的，只追加台账（events、consumed、anchors）两边都追加了就把两边的新行都留下，其它文件两边都改了才停（`SyncConflict`，本地不动）。`--watch` 定时反复做，冲突与断网只记日志，用来替代服务器上 30 分钟一次的 `guji-glyph-store-sync.timer`（往 guji-workspace git 提交）。只动 `datastore/workcopy.py`、`cli_db.py`，17 步 `code_hash` 不变。

- 中心库备份与恢复演练（GUJI-611）：`python -m open_guji_cv.datastore backup` 在一个只读快照里把全部表 `COPY` 出来、gzip，附清单（每表列、行数、排序后哈希、序列值、rev），经 Worker `/v1/backups` 存进正式桶 `backup/<日期>/`，清掉超过 30 天的；`restore-check --endpoint <ci 端点>` 取最新一份完整备份恢复到 main 以外的分支（给 main 的端点直接拒绝）并逐表核对。首次实测（10-19，rev 1356）：26 张表 189,964 行，备份 12 MB、31 秒；恢复到 ci 分支 39 秒，逐表行数与哈希全部一致。连库抽成 `datastore/connect.py`。

### Removed
- 往 guji-workspace git 提交数据的旧路径（GUJI-608/611，2026-10-19，用户定「后面这些数据在中心库的就不应该再出现在 workspace 里面」）：删 `scripts/glyph_store_sync.py`（服务器 30 分钟一次的 `guji-glyph-store-sync.timer`，由 `guji db sync --watch` 替代）、`scripts/snapshot_glyph_store.py`、`clustering/store_merge.py`（git 三方合并）、`ops/store_commit.py`（`guji store commit` 的 git 路径）及其测试。`guji store check|commit` 现在只推中心库，没迁的工作区直接提示先 `guji db migrate`；close-check 第 8 项同理。近似字 store 导出与重建的两条用例挪进 `tests/test_approx_store_export.py`。runbook S14、`workspace_layout`、`.claude/CLAUDE.md` 等文档改成中心库口径。17 步 `code_hash` 不变。

### Fixed
- 中心库 push／sync 判「glyph.db 改过要先导出」改用导出签名（`ops/central_glyph.export_signature`，即原 `glyph_store_sync.db_signature`），不再用匹配器库指纹：只标了／撤了近似字、改了实例 label／ids 时匹配器指纹不变，此前这类改动会漏推。
- 中心库客户端与 `r2-plan --via worker` 遇到断流（`http.client.IncompleteRead`）也退避重试，不再整次中断（2026-10-18 正式桶上传时碰到）。
- group_flow 第三批形近不同义字组（2026-10-19，sheldon 定）：論諭 `ly`、大太 `dt`、問間 `wj`、曾會 `zh`、遺還 `yh`，按文意（L1 规则＋haiku 答案表，只收 conf=high，只补放不复核）。注册表加 5 个 `GroupSpec`，配置 `config/groups/{ly,dt,wj,zh,yh}/{rules.yaml,prompt.md}`，扩展脚本 `ext_enum_cells.py`／`ext_make_batches.py` 加 `--groups`。缺省关（书 yaml 的 `group_flow` 点名才生效）。vol04 A/B：组外格逐格不变，放行 +10（曾會，均无强真值可对），报告 `doc/exp/group_flow-3-vol04-报告.md`。PATCH；**`seed_admit` 的 `code_hash` 变**（6a4e2bd27c35fa8a → 50b4c7c96150b33d），其余 16 步不变。
- group_flow 第四批形近字组（2026-10-19，sheldon 定）：象彖 `xz`、王玉 `wyu`、圓圖 `yt`，做法同第三批（L1 规则＋逐册 L2 haiku 表，只补放不复核；彖傳／象傳、玉篇／帝王篇、方圓等两可词弃权）。vol04 A/B 组外格 0 变化，放行 +1（该册这三组几乎都已被放行，收益在没放行的册），L1 对整理本零冲突。`seed_admit` 的 `code_hash` f0f2713200ae880e → c3dbd4dac0582b47，其余 16 步不变。报告 [group_flow-4-vol04-报告](doc/exp/group_flow-4-vol04-报告.md)。
- group_flow 第五批八组（2026-10-19）：目自 `mz`（与日目 `rm` 共用「目」，互相声明 `overlaps`）、一二 `yr`、千干 `qg`、十卜 `sb`、甲申 `js`、而面 `em`、傅傳 `fc`、木本 `mb`，均形近不同义、按文意（L1 规则先行，弃权查 L2 haiku 表，只收 conf=high），补放也复核（只降审不改字）。L1 规则由整理本奇偶册交叉验证生成（两半都不矛盾才收），再手工剔掉「蔡傳」「王宗傳」「草本」类两可词，对 vol02–10 整理本零冲突；一二的 haiku 表对整理本有 5% 分歧，不稳，**一二只用 L1、不挂 L2 表**。vol04 A/B：组内格 0 降审、0 改字，补放 +4（千 1、十 1、傅 1、一 1；其中三格整理本为空，未逐格看图），其余 4000 多个组内格都是「文意与现放行字一致」；原因是这八组在 vol04 几乎都已被基线放对。`seed_admit` `code_hash` f0c37eac6214999c → e05fed6d5f32f4b7，其余 16 步不变。报告 [group_flow-6-vol04-报告](doc/exp/group_flow-6-vol04-报告.md)。
- group_flow：允许组成员重叠＋形近组复核＋日目组 `rm`（2026-10-19，sheldon 定）：①`GroupSpec.overlaps`（须互相声明），`flow.entry` 一个字可属多个组——补放选第一个装得下「分差内全部候选＋整理本字」的组，复核选第一个声明了 `review` 且装得下整理本字的组；日曰 `ry` 与新组日目 `rm`（L1＋L2 haiku 表）共用「日」，日曰候选归 ry、日目候选归 rm、三者混杂留人审。②已放行格复核（只降审、不改字）：`ry wxs ly dt wj zh yh xz wyu yt rm` 打开 `review`（原来只有 jys／rr）。③`seed_admit` 的待审补放通道（witness3／coord_fallback）不再把复核判了 `group_flow_disagree`／`_conflict` 的格放回去（原来降审被 coord_fallback 按整理本字又放行，白降；含 jys／rr 原有的降审）。vol04 A/B：复核降审 8 格（象彖 4、大太 2、問間 1、入人八 1，原来被放回去的那 1 格），无改字；日目 L2 表 57 格答 37；组外格仅 iron 通道 +3（本机重拉字形库后库内容变化所致，与本改动无关）。`seed_admit` `code_hash` c3dbd4dac0582b47 → f0c37eac6214999c，其余 16 步不变。报告 [group_flow-5-vol04-报告](doc/exp/group_flow-5-vol04-报告.md)。

## [0.3.4] - 2026-10-18

PATCH。语料库 corpus-vN（清单、册钉子、补指纹缺口）、group_flow 第二批异体组、清理旧字组代码。相对 v0.3.3 只有 `seed_admit` 的 `code_hash` 变（9d3e5deb232d84f2 → 6a4e2bd27c35fa8a），其余 16 步不变；各册 Step7 本来就要用新字组重算，下面各条自述的中间 `code_hash` 以此为准。没写 `corpus:` 的册其余指纹逐位不变。

### Added
- 册钉了语料库版本（`corpus: N`）后，读语料的 5 步（`glyph_match`、`rare_candidates`、`context_decide`、`align_ref`、`seed_admit`）的指纹整步多带一个 `corpus-vN`（P2，2026-10-18）：补上此前没有内容指纹的输入——形近表（`confusable_*`、`NEVER_MATCH_FAMILIES`）、`context_decide`／`align_ref` 的异体表、`rare_candidates` 的字表与部件库。几何步不受语料库升级影响。名单登记在 `core/corpus_pin.CORPUS_STEPS`（不放进 `StepSpec`，免得改 Step 源码让 `code_hash` 变）。没钉的册指纹逐位不变，17 步 `code_hash` 不变。
- 册 yaml 可钉语料库版本 `corpus: 1`（P1，2026-10-18，sheldon 定）：钉了之后，`params_for` 把参数里的语料类内容指纹（`core/corpus_pin.PIN_FIELDS`：整理本参考文本、证人、用字账、异体表、异体图、夹注词表、铁证形近、group_flow 字频／规则／答案表共 9 个字段）整体换成 `corpus-v1`，**指纹只认版本号，不看内容**；钉的版本没有清单就报错，清单之后文件被改只警告一次。**不写 `corpus:` 的册一字不变**；17 步 `code_hash` 全部不变（逐步对照 rc/v0.3.4 验过）。字形库、人裁排除名单、模型不属语料，指纹照旧。`ops/corpus_pack.py` 的清单读取与扫描挪进 `core/corpus_pin.py`。
- `guji corpus build|verify|list`（P0，2026-10-18，sheldon 定）：语料库 corpus-vN 的清单，登记流程里读的 51 份语料类文件（整理本参考文本、字频表、L2 答案表、规则、IDS、异体表、形近表、字表）的 sha256 和 `NEVER_MATCH_FAMILIES` 哈希，落 `<工作区>/corpus-pack/vN/manifest.json`；版本号递增、不覆盖；`verify` 发现清单之后又被改的文件。**只登记，Step 仍读原位置，指纹不变，17 步 `code_hash` 全部不变。** 方案见 `doc/design/语料库版本化方案.md`。
- group_flow 第二批异体组（2026-10-18，sheldon 定）：即卽（`ji`）、卿𨜊（`qing`）、變𠮓（`bian`）、彙彚（`hui`），只看字频：主形人裁 ≥20 且次形 0 才放行，数据不够送人审，重算字频表后自动放行。缺省关，按册在 `group_flow` 里点名。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → 51a72b61d8354196（注册表在其 `code_deps` 里），其余 16 步不变。字形库清了 3 格误标（變 2、旨 1，工作区 events）。A/B 配置 `doc/exp/group_flow-2-vol04.yaml`、`group_flow-2-vol02-vol03.yaml`：vol04、vol02、vol03 三册新增放行共 3 格（都是卿），變 1 格弃权送审，旨㫖字频解封后放行不变，其余格一格没变。

### Removed
- 清理被 `group_flow` 取代、已无调用的旧字组代码（2026-10-18，sheldon 定）：删 `utils/ry_group.py`（日曰 ry-v2 答案表）、`utils/ji_yi_si_clf.suggest`（己已巳旧答案表）、`groups/backends.py` 的 `RyV2TableBackend`／`JysSuggestBackend`、`eval/groups` 的 `suggest:` 后端与 ry-v2 表识别（`table:` 只认 `group_clf/1`），及对应测试、`research/char_groups/{ry/build_cache,jys/build_clf_table}.py`、`scripts/_from_overview` 里量 group_decide 口径的 `ctx_caliber_compare.py`。`seed_admit` 的 `code_hash` 9d3e5deb232d84f2 → 6f24d51db9b8ebcb（改了 `utils/ji_yi_si_clf` 源码，在其 `code_deps` 里），其余 18 步不变。vol04 A/B：旧码 vs 新码，`seed_admit` 产物逐格一致。
- 删 `seed_admit.rare_cp_ctx_review`（罕用码位×context 落审，缺省关，无书在用；2026-10-18 sheldon 定）：参数、`_rare_cp_ctx_pass`、测试 `test_seed_admit_rare_cp_ctx.py` 及 `test_w5_demoted_from` 里的一条。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → eba68e984cd2a5ae，其余 18 步不变。

## [0.3.3] - 2026-10-18

PATCH。字组统一流程 group_flow（新 variant-tie）：收编全部旧字组开关、字频与在线 IDS 两个新解法；删 Step5-c／Step6b。

### Added
- 字组统一流程 `seed_admit.group_flow`（新 variant-tie，2026-10-18 sheldon 定，缺省关）：点名注册表里声明了 `flow` 的字组（首批七个异体组 蒙𫎇／點㸃／參㕘叅／讖識䜟／隸𨽾／慎愼／旨㫖，三个形近组 己已巳／日曰／入人八）；没放行的格若库候选（与 top1 分差 <0.03）＋整理本字全在一组，按组声明的解法给字放行（通道 `group_flow`）或留人审，己已巳、入人八另对已放行格复核；每格写 `evidence.group`。新解法「字频」：按人裁刻形冻结每套书一张表（`python -m open_guji_cv.groups.freq <工作区>`），主形 ≥20 且次形为 0 才给字。`groups/registry.py` 新增 `FlowSpec` 与七组（`groups/flow.py`、`groups/freq.py` 进 `seed_admit` 的 `code_deps`）。PATCH；**`seed_admit` 的 `code_hash` 变**（与下面删 5-c 合计 a995ac96→03ad95f1），关时产物不变。
- `group_flow` 的 `ids` 解法接上在线判别（方案 S7，sheldon 10-18 定）：新模块 `groups/ids_online.py`，字块图自动缝一刀 → 决定字的那一段在冻结模板库里最近邻 → margin ≥ 门槛且该类刻例 ≥8 才给字，否则弃权，`evidence.group` 里留 IDS、部件、margin、各部件分数。首批只开 參㕘叅（`can`，门槛 0.04；人标池 74 格留一 59 对／15 弃权／0 错，留一册 57／17／0；叅只 2 例永不给），模板库 `config/groups/can/ids_bank.json` 由 `python -m open_guji_cv.groups.ids_online build can --dataset <dataset>` 从 dataset 人标池建（工作区 `config/groups/ids/<组>.json` 优先）；模板库、判法参数、`ids_override.tsv`、`ids_lv1.txt` 的哈希进 `group_flow_fingerprint`（没有在线 IDS 的组不加，旧指纹不变）。其余组（彝、慎愼、旨㫖…）没有模板库，照旧弃权且不取图。`groups/ids_online`、`ids`、`ids_two`、`ids_parts`、`ids_segment`、`ids_solver` 进 `seed_admit` 的 `code_deps`。PATCH；**`seed_admit` 的 `code_hash` 变**（ce3a31cce2908038→332a5956257e5a6b），关时产物不变。
- `group_flow` 的表路径：相对路径按工作区解释；没给时用工作区 `config/groups/freq.json`、`config/groups/l2/<组>.json`（有才用）。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。
- 字频表计数也认字形库体检的改字／撤库事件（`glyph_audit` relabel／evict），同格按时间取最晚。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。

### Changed
- 字组统一流程 `group_flow` 收编旧 m7 的全部字组（方案 S6，2026-10-18 sheldon 定「旧的都并进来、旧的删掉、每册都开」）：注册表给 土士 `ts`、未末 `wm`（文意＋量横）、戊戌戍 `wxs`（文意）补 `FlowSpec`；`FlowSpec` 加三个旋钮——`review_fix`（复核时文意给了别的字就改字，己已巳用）、`review_abstain`（复核时文意弃权就降审，己已巳用，接替旧 `ji_yi_si_clf` 对规则不命中的 `split_ref` 退役）、`lift_needs`（补放必须有这几路之一给字；入人八要文意，字形分类器不许单独补放）；复核时解法互相冲突也降审；形近护栏（`never_match`／`conflict`／`near_form`）不再挡字组；取上下文窗口时剔除排除名单格（与建 L2 表同一取法）。`always_review` 缺省仍是「己已巳」：vol04 A/B 上留着它比改成空多放 3 格对的、少 2 格错降（报告 `doc/exp/group_flow-S6-vol04-报告.md`）。**没在 `group_flow` 里点名 `jys` 的书，`split_ref` 放行的就是整理本字、不再复核**（旧 `_resolve_ji_yi_si` 删了）。vol04 A/B（旧开关全删＋13 组 vs 现行配置）：组外格逐格不变，放行 +47，强真值上放行 72 对 0 错 → 81 对 0 错，错降 1。PATCH；**`seed_admit` 的 `code_hash` 变**（与下条删旧开关合计，以 S7 之后为底 332a5956257e5a6b → 9d3e5deb232d84f2），各册该步判过期，其余 16 步不变。

### Removed
- 旧字组开关并进 `group_flow` 后删除（方案 S6）：`SeedAdmitParams` 删 `ji_yi_si_review`、`ji_yi_si_ctx_rule`（`_purity`／`_min_n`／`_fingerprint`）、`ji_yi_si_clf`（`_llm`／`_margin`／`_table`／`_fingerprint`）、`ry_group`（`_cache`／`_fingerprint`）、`rr_clf`（`_p`／`_model`／`_fingerprint`）、`m7_groups`／`m7_l2_tables`／`m7_fingerprint`／`m7_bars`、`variant_tie`（`_cov`／`_extra`）共 24 个字段；删 `_resolve_ji_yi_si`、`_ji_yi_si_clf_cell`、`_ctx_known`、`_ry_group_pass`、`_rr_clf_pass`、`_m7_group_pass`、`_variant_tie_ok` 与主循环的 `variant_tie` 通道；删 `groups/m7_pass.py`（`judge`／`fingerprint` 挪进 `groups/flow.py` 为 `ctx_judge`／`ctx_fingerprint`）、`groups/apply.py` 与注册表的 `GroupPolicy`／`GroupSpec.policy`、`utils/ji_yi_si_clf.STRONG_CHANNELS`。`seed_admit` 的 `code_deps` 去掉 `utils.near_form_ctx`、`utils.ry_group`、`groups.m7_pass`、`groups.apply`（`utils/ry_group.py`、`utils/near_form_ctx.py` 只剩离线评测用）。书 yaml 里的旧键读进来被忽略（pydantic 缺省忽略多余字段，不报错），应从十册 yaml 里删掉；`tests/test_group_params_guard.py` 的白名单清空。PATCH；`code_hash` 见上条。
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
