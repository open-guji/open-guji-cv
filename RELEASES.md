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
