# HANDOFF_C258 — 控制台版本条 + 部署重启期间写请求重试（overview#258）

分支 `claude/C-version-banner-0928`（基于 main，未推 main）。

## 改了什么
1. **版本接口** `GET /api/version`（免鉴权，同 `/healthz`）→ `{commit, subject, deployed_at}`。
   `commit`/`subject` 来自 `git rev-parse --short HEAD` / `git log -1 --format=%s`，**每进程只算一次**（进程报的始终是它自己加载的那一版）；
   `deployed_at` = 进程启动时间（部署必重启，所以不必改部署器写文件）。取不到 git → `commit=null`，前端显示「开发版」。
   （`routers/auth.py`）
2. **前端版本条**（`layout/VersionBanner.tsx`，挂在侧栏底角）：显示 `cv <短提交> · 部署时间`；每 60 秒轮询，
   与页面加载时的 commit 不同 → 顶部悬浮提示「已更新到 xxx（改动：标题），刷新即可」+ 刷新按钮，不自动刷新、不挡操作（pointer-events 仅按钮可点）。
3. **写请求重试**（`api/events.ts::postEvents`，所有 12 个审查/切线面板都走它，调用方零改动）：
   网络错误或 502/503/504 → 批次留内存，提示「服务器正在更新，稍后自动重试」，每 5 秒重发、最多 2 分钟，之后才把错误抛给调用方；4xx/500 照旧立刻抛。
   `api/client.ts` 新增 `ApiError`（带 status，仍是 Error 子类）。
4. **幂等**：查了现有 `/api/events` 没有批次/`client_ts` 去重，故新增 `EventsIn.request_id`；前端每批一个 UUID。
   后端在批次日志里查 `payload.request_id`，已有 → 整个请求视为重复（`appended:0, duplicate:true`，不写不消费）。
   id 落在事件 payload 里，因此**进程重启后仍能判重**（覆盖「第一次其实写成功、只是响应丢了」）。不带 id 的老调用行为不变。
5. `static/dist` 已用 `npm run build` 重出。未动部署定时器、`deploy_check`。

## 测试
- `tests/test_console_auth.py::test_version_is_public_and_shaped`、`tests/test_events_autoconsume.py::test_request_id_dedups_retry`（新增）；
  `test_console_routes.py` 路由表 111→112 并补了沿革注释。
- 全量 `pytest tests/ -s -q -p no:cacheprovider`：**2342 passed / 1 failed / 27 skipped**。
  唯一失败 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file` **在干净 main 上同样失败**（stash 掉本分支改动复测，同一断言），与本次无关，未处理。
- 前端：`npx tsc -b` 无错；`npm run build` 成功。

## 实测（headless Chromium，真后端）
脚本在 scratchpad（不入库）：起真实控制台（`--no-auth`，独立 `GUJI_FEEDBACK_DIR`）→ Chromium 页面里用打包的**真实 `postEvents`** →
先杀后端再提交 → 等过至少一次 5 秒重试（仍 pending，没报错）→ 重启后端 → 提交自动完成，返回 `appended:1`；
事件日志里该批恰好 1 行，另一个先成功的批次也是 1 行。
**没有**在真 UI 面板里点过（没有真书数据），横幅组件只过了类型检查/构建，没有截图验证外观。

## 拿不准的地方
- 部署时间用「进程启动时间」而非部署器记录；若控制台因别的原因重启（崩溃拉起）也会刷新这个时间。
- `deployed_at` 是服务器本地时区 ISO 串，前端只截到分钟显示。
- 重试期间调用方的 `await postEvents` 会一直挂着（最长 2 分钟）；切线台是「回车先跳下一张、不等返回」所以无感，
  其他面板的「提交中」状态会持续到恢复——我认为符合预期，未逐个面板核对。
- 横幅的更新提示按 commit 变化触发；`/api/version` 在重启间隙请求失败时静默忽略，不误报。
- 本地没有 `.venv`，我用 uv 新建了一个（`.venv` 未入库）；`node_modules` 同理。
