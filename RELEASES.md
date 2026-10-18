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
