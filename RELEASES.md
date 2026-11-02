# RELEASES

服务器（对外校对平台）只跟 `production` 分支，`main` 是开发线。发布节奏现阶段
不设限（用户 2026-09-26 定：平台未上线、会更新得很频繁）；`production` 随时可以
被总管快进到 main 上验过的提交。

每次发布：

```
guji release check <候选提交> [--against <上一个 cv-* tag>]
```

它会：静态比对两个提交之间参与各 Step 指纹的文件（不跑管线）列出「哪些步会
过期」；跑一遍全量测试，把「失败＋跳过的测试 ID 集合」与 `open_guji_cv/ops/
baseline_tests.json` 比——**这是发布前唯一的硬门槛**：只要不比上一版多失败/多
跳过就能发，其余（指纹影响清单）只作报告，出问题靠回滚（服务器侧 `guji deploy
check` 健康检查失败会自动回滚，见下）。通过后把草稿贴进本文件最新一节之上，
`--write-baseline` 把这次的结果定成下一版基线，然后打 tag、把 `production`
分支快进到这个提交。

流程与三机分工见 overview
`进度/图片初步数字化/进度/总览/16-三机分工与发布流程.md` §三；
`guji deploy check` 是服务器定时器（`guji-deploy.timer`）跑的那一半，拉模式、
健康检查失败自动回滚，见 `open_guji_cv/ops/deploy_check.py` 模块头。

---

## cv-2026.09.26-base

- 提交：`dc77c84`
- `production` 分支从这里建出来，只建分支＋打 tag，**未部署**（overview
  任务书-K-发布与部署.md §一·5）。服务器上线时的运维卡从这个提交开始装。
- 这是第一版，`open_guji_cv/ops/baseline_tests.json` 还不存在——下面
  `cv-2026.09.26-2` 是第一次写基线。

## cv-2026.09.26-2

- 提交：`ffae613`（对比 `cv-2026.09.26-base`）

### 改动摘要

- K 道·发布与部署 ①：guji release check / guji deploy check（overview 任务书-K-发布与部署.md §一·1-2）

### 影响清单（指纹变了的步，读代码比对，未跑管线，只作报告不作硬门槛）

- 无（本轮改动不影响任何 Step 的指纹）

### 全量测试（唯一硬门槛：不许比上一版多失败/多跳过）

- 首次发布，没有基线——以下是当前失败/跳过，不作硬门槛，已用 `--write-baseline`
  定为下一版基线（`open_guji_cv/ops/baseline_tests.json`）：11 个失败、19 个
  跳过，均为环境缺项（`torch`/GPU OCR 未装）与已知的 s2t/字体候选问题，与本轮
  改动无关——本轮改动前后这两个集合逐字节相同（K 道 done 单有对比记录）。

### 回滚目标

- `cv-2026.09.26-base`

## v0.6.0

对比 `v0.5.32`。用户 2026-10-31 定升 MINOR：切分代码模块化（共用原语库 `seg/`、各套书自管 `books/`）和一批功能拆分出去。tag 经 ai-team 中转站打在 main 的发版合并提交上。

### Added
- 切分模块化 M2–M4：共用原语库 `seg/`（lines、grid、polyline、frame_types、seam、cut_select、warp、profile …）、每套书自管的 `books/<套书>/`（殿本 siku_zongmu、史記 shiji_wyg、增廣幼學 zengguang_youxue、北行日錄 beixing）、套书登记 `core/seg_set.py`、每套书的样页单 `samples.yaml` 与 `scripts/seg_samples.py` 改前改后对比。
- 任务库按书 ID 区分：`jobs.job.book_id`、`guji_jobs submit/ls --book-id`；网站「重跑任务」表多「书 ID」列；`spec.WS_REPOS` 登记「书 ID → 工作区仓」。
- 精校前移：存包查纯净性、出单图源门、任务库按字形库差分增量重算（A2–A4）。
- `align_ref` 近簇合并 `anchor_merge_gap`、replace 段长上限 `replace_max_len`（按册开，缺省关）；页钉位 `page_pins`；keben_free 第八轮块格式 `fmt`。

### Changed
- 控制台拆成独立包 `guji-console`、manager 部分拆出（用 `guji.commands` 插件命令并入）。
- 殿本四庫總目工作区迁到独立仓 `guji-workspace/96mid1ogzk-si-ku-zong-mu`（仓根即工作区）；执行方按册所属的书取工作区。
- 同册互斥锁改成（书 ID，册号）：不同书的 vol01 可以并跑。

### Fixed
- 执行方：加列后老连接计划失效自动重连；连续 3 单环境类失败暂停领单；`seg_samples --base` 取提交而不是 tag 对象；`rerun_prep.sh` 按工作区 `.central.json` 找册 yaml。
- 史記前三册职名页、卷端标题按整理本字数切，列端字不再被当框线抹掉。
- 纯净性 `describe` 下沉到 `datastore`，修架构守卫。

### Removed
- 控制台代码（`open_guji_cv/console/`，随 guji-console 搬走）。

影响：`guji release check HEAD --against v0.5.32` 静态比对，**没有任何 Step 的 `code_hash` 变**（模块化各步登记「指纹逐位不变」）。组合验收：切分样页 v0.5.32 对 rc/v0.6.0 逐页比，殿本 vol04／08／16／40／46／48 与北行古本 bxgb 共 7 册、比对产物页 1,174 页，cells／text／state／geom 全部 0 列变化。**未比**：史記与增廣幼學（工作区不在旧总仓，没来得及按新仓提单）、北行日錄（本机跑）、vol01（已冻结，当前代码拒跑）、vol06（册 yaml 的 seed_admit 参数比旧版新，旧版 cv 校验不过）。全量测试 4268 过；`test_frame_pin::test_real_page_tight_boxes_do_not_clip_char_tops` 在已发的 v0.5.32 上就红，非本版引入。

## v0.5.0

对比 `v0.4.9`。用户 2026-10-20 定升 MINOR：切分 `layout_prior` 改了命中格位表各册的缺省输出，值得重跑。tag 经 ai-team 中转站打在 main 的发版合并提交上（annotated）。

### Added
- 字组呂吕、徵徴走在线 IDS 整字岭回归（`groups/ids_whole.py`）；要在册配置 `group_flow` 点名才生效。
- 人裁事件规范 v1 与 `guji events lint`；人裁历史遗留一次规整工具 `feedback.migrate_v1`（中心库殿本、北行已迁）。
- `scripts/check_release_tags.py`：核对每个发进 main 的版本都有 tag。

### Changed
- 切分 `row_segment` 1.23、`cell_shrink` 1.9：`layout_prior` 候选格网统一打分、列端表空格段记空、表认字格不判渣。殿本 vol04–10（第 4 页起 10,521 列）逐格 98.79% → 99.03%，修好 27 列、改坏 1 列。没有格位表的书逐字节不变。
- 人裁「后到覆盖」一律按 `(ts, batch, seq)`：`gold rebuild` 等此前按批次名序的地方改为时间序。锚里切分产物 sha 改记 `anchor.cells_sha`。
- 请审单自动填看图判错格；`zl.py` 新增 `db`、`pending`；`republish.py` 重发待审单。

### Fixed
- 语料库清单不再收字组提示词，改提示词不再让钉 corpus 的册 CorpusDrift 拒跑。
- 并行限流按容器内存算，glyph_match 单进程登记 3.6 GB（修 4 进程 OOM）。

### Removed
- 无。

影响：`row_segment`（d5f4ceedcfbd2d06 → 89ea9a967e3dd407）、`cell_shrink`（17162d9e3ed6047f → f9206af1e771f0e5）、`seed_admit`（3337e7b0b2dc43ec → c1cc30263b355ed5）三步 `code_hash` 变，其余 14 步不变；没冻结的册 Step3 起重算。组合验收：本版改缺省输出的只有 `layout_prior` 一项（单项 A/B 见 #322，即上面的 vol04–10 数字）；呂吕／徵徴要点名才开，人裁事件的改动不在任何 Step 的 `code_deps` 里，所以没有另做全关对全开的组合 A/B。全量测试 3632 过（2 条失败在 v0.4.9 上同样失败）。

## v0.4.0

对比 `v0.3.5`（`34035c10`）。用户 2026-10-19 同意升 MINOR：609 改指纹，没冻结的册重算一次。只此一项，不涉及判决逻辑，组合 A/B 不适用（见下「影响」）。tag 由 Deploy 在 main 上打（annotated）。

### Added
- `clustering/glyph_fp.py`：字形库内容指纹（人裁通道、字体域）。`glyph-db import-font` 在库里新表 `font_manifests` 记字体文件与字表的 sha256（不导出进账本）。

### Changed
- `seed_admit.human_fingerprint` 改取人裁通道真正读到的 `(实例 id, 字头)` 的哈希：glyph.db 从中心库重建、rowid 重排时不再白白过期（GUJI-609）。
- `rare_candidates` 新参数 `db_font_fingerprint`：库里带不带字体域、导的哪版字体进指纹。

### Fixed
- 无（中心库导出漏推近似字标记已在 v0.3.5 修）。

### Removed
- 无。

影响：`seed_admit`（f0f2713200ae880e → 50bdd1fb5f0bcbd1）、`rare_candidates`（ac757fe8b73ba312 → 4168770d80cbde67）两步 `code_hash` 与参数指纹变，其余 15 步不变。没冻结的册这两步及下游重算一次，**判决不变**（改的只是参数里的指纹字符串，`run_page` 一行没动；`_human_shapes` 换成同一条查询的常量）；冻结册按快照比，不受影响。全量测试 3204 过（除 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，缺检查点的环境问题，base 上同样失败）。

## v0.3.0

对比 `v0.2.1`（`d5c84d8b`）。`v0.3.0-rc.1` 只作集成起点；用户 2026-10-18 定免做组合 A/B，`rc/v0.3.0` 合 main 后直接在 main 上打正式 `v0.3.0`（annotated，Owen 打）；规矩见 `doc/版本号规矩.md`。

### Added
- M7 形近字优化算法库 `open_guji_cv/groups/`：IDS 路（彝六字形）与上下文路（日曰／己已巳／入人八），含注册表 `solvers`、`config/groups/<组>/`。
- 粗校出口一键取数 `scripts/zhengli/collect_exit.py`；`guji close-check --tier rough|final`；`guji pipeline --isolate-steps`；`scripts/relanding/`。

### Changed
- `seed_admit` 新增 M7 接线开关 `m7_groups`／`m7_l2_tables`（缺省关，关时不进产物指纹）：己已巳／日曰／入人八的上下文判别（规则先行、答案表补位）按注册表策略升降放行。vol04 单项 A/B：组外 33899 格逐格不变，己已巳 3 格送审→放行无错放，入人八 1 格放行→送审（GUJI-563）。
- `border_detect` 新增 `merge_narrow_pair`（缺省关）：窄对合并，去掉把大字列劈成窄条的伪竖线；vol04 全书只在 p80、p217 触发（GUJI-572）。

### Fixed
- `guji snap import` 认 `GUJI_PRODUCTS_DIR`；导出把看图判错未裁的放行格记 `review: pending`。

### Removed
- 无。

影响清单：`border_detect`、`border_detect_gate`、`column_gate`、`seed_admit` 4 步 `code_hash` 相对 `v0.2.1` 变化，其余 15 步不变（两个 Step 的新参数缺省关、关时不进参数 dump；各册产物是否过期以 `guji status` 为准）。全量测试：除 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`（缺检查点的环境问题，base 上同样失败）外全过。

## v0.2.0

对比 `cv-v0.1.0`（`26657f84`）。tag 为 `v0.2.0`（annotated），由 Owen 在 main 上打；规矩见 `doc/版本号规矩.md`。

### Added
- guji-proof 0.2 审阅字段模块 `open_guji_cv/review/proof_fields.py`。
- 统一字组接口 `open_guji_cv/groups/` 与统一评测 `open_guji_cv/eval/groups.py`（尚未被任何 Step 引用）。
- 字组参数守卫 `tests/test_group_params_guard.py`：不许再往 `SeedAdmitParams` 加新的字组参数。
- 包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。

### Changed
- 版本号规矩改为 `vX.Y.Z` tag、按 PR 滚动升版（`doc/版本号规矩.md`）。

### Fixed
- 无。

### Removed
- 旧 exe 发布流水线 `release.yml`（移至 `doc/archive/release.yml.legacy`）。
- 死代码：`steps/step6_signals.py`、v1 桥。

Step 的 `code_hash` 相对 `cv-v0.1.0` 无变化（19 步逐位相同）。
