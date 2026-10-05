# HANDOFF · Q1 道（overview#403 缺口 A + C）

分支 `claude/Q1-decided-gap-1005`，基于 cv main `73fa8b3af5`（缺口 B 已在其中）。未合 main，未开 PR。

## 改了什么

### 缺口 A：`decided_cells` 只收仍有效的裁决
- `open_guji_cv/review/verdict_view.py`
  - 新增 `decided_view(book, log=None, bindings=None)`，返回 `(decided, stale)`。
    - 逐条裁决事件判断：有绑定行（`feedback/bindings.py::book_bindings`）的，落到 `usable(row)`；`rebound` 的落到新编号；`usable` 为 None 算失效。
    - 没有绑定行的，照原编号算已裁，跟改前一样。包括非 confirm 事件、事件自带锚点但还没进绑定表、绑定表算不出来这几种情况。
    - 一格只要有一条有效裁决就算已裁。所以用户补确认之后，新写的那条带锚事件会让这格回到「已裁」。
    - `stale` 的内容：有裁决、但一条有效的都没有的格 → 最后一条失效裁决，按定字台前端的裁决形状给出，外加 `ts`、`batch`、`status`。
  - `decided_cells` 改成 `decided_view(...)[0]`。缺省口径和 `lookup.human_chars` 相同：读工作区事件日志时绑定，传入测试日志时不绑。
  - 缺口 B 的口径保持不变：排除名单格带字算已裁，`seg_defect` 不带字不算。
  - `review_verdicts` 里的映射抽成 `_verdict_of(e)`，和 `stale` 共用。输出跟改前逐字相同。
- `open_guji_cv/review/cards.py`
  - 改用 `decided_view`。每张卡多一个 `stale_verdict` 字段，没有失效裁决时为 None。
  - **排除名单上、人给过字但裁决已失效的格，也放回队列**。这类格 Step7 不会挂 `human_char`，文本出阙文；如果还被挡在队列外，就又成了两边都不管的格。非字和只标切坏的格照旧挡掉。已在卡上请整理总管确认。
- `open_guji_cv/report/progress.py`（Step9-9.0 看板）：上一条那类格计入 `review_new`，保证看板数和出卡数逐 id 相等。
- 前端（`console/frontend/src/...`，`static/dist` 已重建）
  - `doubt.ts::staleDefault`：载入时预勾当时的裁决，算本轮动过（`touched`/`autoTouched`），优先级高于 AI/CNN 默认。「跳过」不预勾。
  - 卡头加徽标「旧裁「X」已失效 · 已预勾」，悬停显示当时日期、批次和绑定状态。
  - 提交走原有的 `POST /api/events`，所以写出的新事件带现行锚点。

### 缺口 C：收尾闸
- `verdict_view.closure_gaps(book, pages, store=None, log=None)`：「事件里定过字的格」∩「seed_admit `admit=False` 且没出字」。
  - 定过字 = confirm 事件，`v ∈ {confirm, seg_defect}` 且带 `shape`。后来改判 not_a_char/damaged 的不算（`shape_decided_cells`）。
  - 以下情况算出了字：`admit=True`；带 `evidence.human_char`（缺口 B）；遮挡格带默认字（`occluded` 且 `char`）。
- `guji status <book>`：末尾打印「收尾闸 ✓/✗ 已定字却没出字 N 格」，并列出字位（最多 30 个），排除名单格会加标注。`--json` 多一个 `closure_gaps` 字段。闸算不出来时只在 stderr 提示，不影响 status 本身。
- 手册 `.claude/doc/console_manual.md` 的 status 一节补了一段说明。

## 测试
- 新增 `tests/test_decided_gap_403.py`，共 9 条，数据全部自己造，绑定表用 monkeypatch 注入，不读工作区：
  - 老事件 `unanchored` + `bound=None` 的格不算已裁，并带预勾「困」；
  - `rebound` 只算到新编号上；
  - 补确认之后，失效裁决被新裁决覆盖；
  - 没有绑定行时，行为和改前一致；
  - `seg_defect` 不带字的格不算已裁，也不进 `stale`；
  - `cards(skip_decided=True)` 会出失效格，包括排除名单上的失效带字格，并带 `stale_verdict`；有效格和名单上有效带字的格不出卡；
  - `closure_gaps` 的列出和不列出（`human_char`、遮挡格、改判非字、已放行）。
- 全量：见下方「全量结果」。

## 本地要做的
1. 拉这个分支（或合 main 之后拉 main），重启控制台（`runs/restart_console.sh`）让新 dist 生效。
2. `guji status vol03`、`guji status vol02`：看末尾的收尾闸。
   - 如果 Step7 过期，先重跑 seed_admit。
   - 剩下的格去审查页处理：默认视图（跳过已裁开着）里就能看到，卡头有「旧裁「X」已失效 · 已预勾」，看图后点提交即可。
   - 补完再跑 seed_admit，收尾闸应为 0（验收第 3 条）。
3. 验收第 1 条：vol03 `9:8:4` 在默认视图里出卡，并预勾「困」。

## 没做 / 留意
- 字形库里的撤下标记（`human_stale_*`、`stale_verdicts.tsv`）这次没并进 `decided_view`。`human_chars` 会按这类标记丢弃旧事件，所以被标记撤下的格 `decided_cells` 仍会算已裁。这类格会被收尾闸 C 报出来，所以不会再被悄悄漏掉。要不要也让它们回到队列，请总管定。
- 收尾闸目前只看 `admit=False`。如果 Step7 产物过期，闸会把「已有效裁决、但还没重跑」的格也报出来（单测里 `keben:1:1:4` 就是这种），处理办法是先重跑 Step7。
