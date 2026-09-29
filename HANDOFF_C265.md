# 交单 C265：对齐改字层网格批审 + 「小注当正文」裁决

任务卡：open-guji-core/overview#265 · 分支 `claude/C-grid-accept-0928`（基于 main `7d7b469`，没推 main）

## 做了什么

### 1. 「对齐改字层」分三组细项，非列尾的格改成网格审

**后端**（`open_guji_cv/review/cards.py`）

- 新增 `REPLACE_ALIGN_SUBS` 和纯函数 `replace_align_sub(slot, doubts, ref)`，把这一类的卡分成三组：
  - `tail`：**列尾（易混框线）**，`slot ≥ 20`（`TAIL_SLOT`），逐张审。这条规则排在最前，哪怕这张卡也符合下面 manual 的条件，也归 tail；
  - `manual`：**逐张**，四种情况归这里：带形近疑因（`near_form` / `solo_confusable`）、整理本这一位是空的、本书惯刻形和整理本字不同（`ref.form`）、人上次只标了切分缺陷没给字（见下文「要注意的」第 2 条）；
  - `grid`：**网格（采信整理本）**，其余的都归这里。
- `cards(cls=…)` 给「对齐改字层」的每张卡加一个 `cls_sub` 字段；响应里多两项：`class_sub_counts`（`{replace_align: {grid, tail, manual}}`，计数口径和 `class_counts` 相同，不受 `limit` 截断）和 `class_subs`（细项表）。新参数 `cls_sub` 只接受 `cls=replace_align`，其他组合报 ValueError，路由层返回 400。
- 路由 `/api/review/cards` 加了 `cls_sub` 参数，只在请求里给了这个参数时才写进缓存键。不传 `cls` 的请求，返回值和改前相同（有用例覆盖）。

**前端**（`console/frontend/src/components/review/`）

- 进入「对齐改字层」默认显示网格细项。类别按钮下面多一行「本类细项」，有三个按钮：网格 N、列尾（易混框线）N、逐张 N。
- 网格（`ReplaceAlignGrid.tsx`）默认一屏 60 张，「一屏」输入框可以改。每张缩略图下面标整理本字，默认采信。点一下切到「字形不完整」（朱色虚线框，标「缺」），再点一下切到「跳过」（淡色，整理本字划掉），再点一下回到采信。
- 「提交这一屏 N 张（采信 k）」一次写完整屏，写完自动载入下一屏；工具栏上原来的「提交裁决」在网格模式下也走这条路。
- 事件行由 `reviewClass.ts::gridRows` → `gridVerdict` → **`pickVerdict` / `verdictRow`** 生成，和逐张卡上做同一件事的结果逐字段相同：
  - 采信：等于普通卡按 1（候选第一位就是整理本字），写 `v=confirm, shape=整理本字, no_glyph_lib=false, client_ts, dwell_ms`；卡上有 AI 预选时带 `ai_accepted`，口径同 `aiAccepted`；
  - 字形不完整：等于按 T，写 `v=seg_defect, quality=truncated, shape=""`；
  - 跳过：等于按 S，写 `{id, v:"skip"}`。
- 两道安全设置：网格**永远不出已裁过的格**，即使勾了「含已裁决」也一样，因为网格默认采信，一提交就会把以前的裁决静默改成整理本字；点过的档位按 id 保存，**静默刷新（切线联动 `reloadSignal`）也不清**，只有提交成功的格才从状态里去掉。否则人点掉但还没提交的格会退回「采信」。
- 帮助行随细项切换：`CLASS_HELP['replace_align:grid']`、`['replace_align:tail']`，键由 `classHelpKey()` 生成。

### 2. 新裁决「小注当正文」

- 放在卡片上「字形不完整」按钮旁边，快捷键 **Z**。默认帮助行、`lib_miss` 帮助行、列尾细项帮助行都写上了。注意 `j/k` 已经是翻卡键，所以没用 J。
- 事件写 `v=seg_defect, quality=truncated, reason="jiazhu_as_main"`，shape 的处理和 T 相同：键盘清空，按钮保留已填的字。先标这一档再点候选字时，缺陷档保住（`DEFECT_DONES` 并进 `pickVerdict`）。印章遮挡整组确认（`doubt.ts`）遇到这一档也写同样的行。
- `review_verdicts` 读回时认出 `reason=jiazhu_as_main`，还原成前端的 `done='jiazhu'`。不这么做的话，刷新后会显示成「字形不完整」。
- **下游行为不变**，由 `tests/test_replace_align_grid.py::test_downstream_ignores_reason` 和 `::test_seed_admit_same_with_or_without_reason` 守住。同一组事件带不带 reason，下面几处的结果都相同：`human_chars`（带字的出字，不带字的不出）、`decided_cells`、打回路由 `classify_return`（→ `row_segment/seg_truncated`）、金标 `_expected_of`、`seed_admit` 产物逐条。seed_admit 那条用例把绑定表 stub 成空，因为用例里没有切分产物。

## 验收

| 项 | 结果 |
|---|---|
| 全量测试 `pytest tests/ -s -q -p no:cacheprovider` | **2367 passed, 27 skipped, 1 failed**（409 s）。唯一失败的是 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`：`DEFAULT_CKPT` 存在，但算出的指纹为空。**在未改动的 main（7d7b469）上单跑也一样失败**，是云端环境的 checkpoint 问题（没装 torch，或 ckpt 是占位文件），和本单无关，没有处理 |
| 前端 `tsc -b` + `npm run build` | 通过；dist 已重出（`index-JucMqF6u.js` / `index-BKBKwQNu.css`） |
| 新用例 `tests/test_replace_align_grid.py` | 10 条全过：划分纯函数、`defect_only_cells`、`cls_sub` 筛选/计数/报错、网格点掉的格归逐张、路由、node 跑 TS 比对网格行和逐张行、jiazhu 行、下游不变 ×2 |

### vol03 实测（快照 `snap/96mid1ogzk/vol03/20260928T1708-full`，全书 110 页，事件日志为空）

- 「对齐改字层」344 张 = **网格 281 / 列尾 45**（第 20 格 16、第 21 格 29）/ **逐张 18**。逐张的 18 张全是「本书惯刻形 ≠ 整理本字」，例如整理本「睹」、本书惯刻「覩」。这一类里没有带形近疑因的卡：`card_class` 会先把这种卡归到「形近字」。
- **网格一屏 60 张的载入**（控制台进程，`/api/review/cards?cls=replace_align&cls_sub=grid&limit=60`，页范围 = 全书）：

  | | 耗时 | 控制台 RSS |
  |---|---|---|
  | 进程刚起、空闲 | — | 320 MB |
  | 冷请求（先删掉 `cache/review_cards`） | **3.32 s** | 326 MB |
  | 热请求（进程内缓存） | 10–18 ms | 326 MB |
  | 峰值 VmHWM | — | **334 MB** |

  在浏览器里点「对齐改字层」，到 60 张缩略图全部加载完：卡片接口命中缓存时 **2.0 s**；控制台刚重启、接口冷算时 5.2 s（其中接口约 3.3 s）。下面细说命中缓存的那次：其中卡片接口命中磁盘缓存只要 189 ms，其余时间花在 60 张图逐张走 `/api/cache`（6 路并发）。页面 JS heap 9.3 MB。
- **headless Chromium 点了一遍**（Playwright + `/opt/pw-browsers` 的 chromium）：
  - 网格 60 张，第 2 张点一次（→ 字形不完整），第 3 张点两次（→ 跳过），第 4 张点三次（→ 回到采信），然后提交；
  - POST 了 60 行，顺序和屏上一致：采信 58（shape 全部等于整理本字）、seg_defect 1、skip 1。提示「已写入 60 条事件…（采信 58 · 字形不完整 1 · 跳过 1）；已载入下一屏 60 张，网格还剩 222」；
  - 这一遍在最终构建上又跑了一次，结果相同：221 张网格提交 60 张，采信 58 / seg_defect 1 / skip 1，采信的 shape 全部等于整理本字，网格剩 161；
  - 换到「列尾（易混框线）」逐张卡，依次按 1 / T / S / Z 后提交。按 1 / T / S 得到的行，**键集合和取值形状与网格行逐字段相同**（confirm：`id,v,shape,no_glyph_lib,client_ts,dwell_ms`；seg_defect：`id,v,quality,shape,client_ts,dwell_ms`；skip：`id,v`）。信封（batch / step / unit / kind）相同。按 Z 写出 `{v:seg_defect, quality:truncated, reason:jiazhu_as_main, shape:"", …}`，卡上亮的是「小注当正文」。

## 要注意的（按保守做法处理的地方）

1. **缩略图用的是占位图**：快照里只有 `products/`，没有原图，也没有 `cache/`，`char_patch` 现算不出来。实测时我给 344 张卡各生成了一张 96×96 占位 PNG，放在临时工作区的 `cache/vol03/char_patch/`。所以上面「2.0 s 看到 60 张图」不代表真图首次现算的耗时；生产上图多半已在缓存里。临时工作区的册配置 `books/vol03.yaml` 也是我写的最小版，`dev_set` 设成全书 1–110。
2. **「字形不完整」在网格里不带字**：按 T 键的口径是 shape 为空。卡片上的按钮会保留已选的字，但网格里点掉一张，说明人不认这个整理本字，所以按 T 键口径不带字。不带字的 seg_defect 不算「裁过」（`decided_cells`），这些格还会回到待审队列。如果回到网格，又会默认采信，等于把人点掉的格又收了。所以新加了 `verdict_view.defect_only_cells`：最新一条定字裁决是不带字 seg_defect 的格，从 `grid` 改归 **`manual`（逐张）**；列尾那组不受影响，照旧归 tail。实测：网格里点掉的 `vol03:5:3:14` 提交后出现在「逐张」里，细项计数从 281/45/18 变成 221/43/19，和提交的行数对得上。
3. **「小注当正文」写 `quality=truncated`**：卡上只写了「v=seg_defect 外加 reason」，没说 quality。我归到「字形不完整」那一组，所以取 truncated，下游照旧当字形不完整处理（退回 `row_segment/seg_truncated`）。没有用 `defect="jiazhu_*"` 这条通道，因为它会把打回改成 `jiazhu_split`，这就不算「照旧」了。
4. **惯刻形 ≠ 整理本字的卡不进网格**：网格只标一个字，两种写法没法在网格里选，所以这些卡归「逐张」。vol03 有 18 张。
5. **发现的旧问题（这次没改）**：先按「全部」载入时，印章遮挡卡的默认裁决会登记为 touched。之后切到别的类别、按「提交裁决」，这些默认裁决会跟着一起提交，界面上看不到。实测列尾那次提交就多出了 30 行印章遮挡默认行（`no_glyph_lib: true`，没有 dwell_ms）。这是 #247 的 `load()` 里原有的行为，和网格无关（网格提交只发屏上的格），建议另开一单处理：换类别时只提交当前屏的 touched。
6. `console_manual.md` 目前没有定字裁决面板各类别的说明（#247 也没写），这次没有补文档，说明写在了代码注释和帮助行里。

## 改动文件

- `open_guji_cv/review/cards.py`：细项划分、`cls_sub`、响应字段
- `open_guji_cv/console/routers/review.py`：`cls_sub` 参数、校验、缓存键
- `open_guji_cv/review/verdict_view.py`：读回 `reason=jiazhu_as_main`；新增 `defect_only_cells`
- `console/frontend/src/components/review/`：`reviewClass.ts`（网格纯函数、jiazhu 行、帮助行）、`ReplaceAlignGrid.tsx`（新）、`ReviewPanel.tsx`（细项行、网格载入/提交、Z 键）、`ReviewCardView.tsx`（「小注当正文」按钮）、`doubt.ts`、`groupReview.css`、`review.css`
- `console/frontend/src/{api,types}/review.ts`：`clsSub` 参数、响应类型
- `console/static/dist/`：重新构建
- `tests/test_replace_align_grid.py`（新）

## 补丁（2026-09-29，CV 总管验收意见两条）

### 1. 「提交裁决」只提交当前屏（修掉上面第 5 条旧问题）

- `reviewClass.ts` 新增两个纯函数：
  - `screenRows(cards, verdicts, touched, aiAcc)`：只收**当前屏上显示着的**、本轮动过的卡，按屏上顺序出行。`ReviewPanel.submit` 改用它，不再遍历全部 `verdicts`。
  - `dropOffScreen(keep, touched, auto)`：切换类别或细项时，找出不在新一屏上的 touched 卡。
- **切换类别或细项时**，这些卡连同本地裁决一起丢掉。如果只丢 touched、不丢本地裁决，卡以后再出现时会显示着旧裁决，却不算动过，提交时又会漏掉。
  - 载入时预填的默认裁决（印章遮挡默认、AI 或 CNN 预选）登记在新的 `autoTouched` 里，切换时悄悄丢掉；
  - 人亲手点过、还没提交的也丢掉，但在状态栏提示「⚠ 切换时丢弃了上一屏 N 张手动裁决（没提交）」。**不会静默提交。**
  - 人一改某张卡的裁决，这张卡就从 `autoTouched` 里摘掉。提交成功的两边都摘。
- 静默刷新（同一类别下的切线联动、切页）不丢 touched，免得丢掉人正在做的裁决；但这些卡不在屏上时，提交也不会带上它们。
- 用例：`test_replace_align_grid.py::test_ts_submit_only_screen_and_drop_on_switch`（node 跑 TS）。
- **headless Chromium 复测**：新开一个工作区，事件日志为空，四庫 vol03 全书。
  1. 按「全部」载入，首屏 30 张全是印章遮挡卡，都有预填默认裁决；在第 1 张上人工按 S。
  2. 切到「其余」类别，状态栏提示「30 张 · 已裁 0；⚠ 切换时丢弃了上一屏 1 张手动裁决（没提交）」。
  3. 在第一张上按 1 后提交，POST **只有 1 行**（`vol03:3:8:17 confirm 位`），没有一行印章遮挡行，全部在当前屏上。改之前同样的操作会多出 30 行。
  4. 再切到「对齐改字层 · 列尾」逐张按 C 后提交，同样只有当前屏那 1 行。

### 2. 「列尾（疑似小注）」改名为「列尾（易混框线）」

- S #266 查明，vol03 列尾的毛病是下版框线混进字块、或末字被切掉，不是小注。细项名、说明、`cards.py` 头注释、路由文档都改了。
- 帮助行改为：「列尾（第 20 格起，易混框线）：常见下版框线混进字块（C 有噪声）或末字被切掉（T 字形不完整）」，Z「小注当正文」保留。
- 用例：`test_tail_sub_label_renamed`、`test_ts_tail_label_and_help`。浏览器里细项按钮显示「列尾（易混框线）45」。

### 复测

- 全量测试：**2370 passed, 27 skipped, 1 failed**。唯一的失败仍是上面那条在 main 上也失败的 `test_ckpt_fingerprint_empty_for_missing_file`。新用例文件共 13 条，全部通过。
- `tsc -b` 通过，`npm run build` 已重新出 dist。
