# HANDOFF S：vol03 / vol02 只含 seed_admit 的 Step7 重算包（2026-09-30）

分支 `claude/S-seed-recompute-0930`（cv，基于 main `75f1a90`），**没合 main**，未改代码、未改 ws、未写正式 products。
只交这份 HANDOFF；两个包在 cv 仓 `snaptmp/…` 分支上。

## 1. 包

| cv 分支 | 提交 | 内容 |
|---|---|---|
| `snaptmp/96mid1ogzk/vol03/20260930T0338` | `a7ddef8` | seed_admit，110 页（111 文件，4.1 MB） |
| `snaptmp/96mid1ogzk/vol02/20260930T0339` | `d53170a` | seed_admit，188 页（189 文件） |

manifest：`format guji-snap/1`、`mode replace-steps`、`page_scope full`、`steps [seed_admit]`、
`cv.commit 75f1a906c0546d525b671d56c64dbd6050b89a51`、`code_revs.seed_admit ["75f1a90"]`、`compatible_with []`、
`allow_downgrade false`、`supersedes []`、`glyph_db_fingerprint f75099253ad7ff74`（云端按 ws main a8e15142 重建的库）。
转 ws 时分支名改回 `snap/96mid1ogzk/<vol>/<同一时戳>`，提交原样。先 `--dry-run` 过（dry-run 未建分支、未推，核对了）；
真 pack 用 `--ws-repo <空 git 库> --no-push` 再 fetch 成 snaptmp 推上来（同 #279）。

## 2. 重算账

- 环境：venv 装 `.[torch]`（torch 2.14）；ws main = `a8e15142`（含 codepoints 即→卽/歷→厯 与 vol03 `context_guard_pages`）。
- 沙箱：把 ws 书目录整份拷进 scratchpad，`GUJI_WORKSPACE` 指过去；`glyph-db rebuild` 重建 `glyph.db`。ws 一个文件没动。
- 快照：`guji snap import` 导入 vol03 `T0450`+`T0451`、vol02 `T1023`+`T1024`（导入到沙箱）。
- **导入后 glyph_match…context_decide 判"参数变了"过期**（快照在 K238 路径参数出指纹之前算的）。用
  `fp-migrate --trust --apply --steps glyph_match,rare_candidates,align_ref,context_decide` 只在沙箱里重写指纹（产物不动；
  故意不迁 seed_admit）。之后 Step1–6 全新鲜（glyph_match 只剩软参数"漂移"，因为云端库指纹≠快照时的）。
- **char_patch 缓存**：快照不带图。在 products 的**副本**（`GUJI_PRODUCTS_DIR`）上 `step cell_shrink --pages all --force`，
  缓存写进沙箱 `cache/`（vol03 110 页 2 min、vol02 188 页 3.5 min；char_patch 19168 张属 vol03）。
  副本上重算出的 cell_shrink 产物与导入的**逐文件字节相同**（只有 manifest 时间戳不同）——说明缓存是对的、没改 Step4。
- 跑 `step seed_admit --pages all`：vol03 7.2 min、vol02 12.4 min，全 ok。
- `guji status`：**seed_admit vol03 110/110、vol02 188/188 新鲜，其余 12 步全部新鲜不变**（glyph_match 仅软漂移 110/188）。
- 缓存确实被读到：`context_head_nonchar` 全书 vol03 = **0** 格、vol02 = **1** 格（vol02:16:9:2），远小于"上千"的失效线。
  vol03 为 0 是因为 p107/p110 的 context 放行已先被整页护栏退回，别的页没有列首非字。

## 3. 量化对比（新 vs 服务器 09-29 值守数字）

基线复现：我在沙箱里导入的旧 seed_admit 产物数字与值守数完全相同——vol03 放行 17071 / 待审 299 / 排除 52，
vol02 放行 29728 / 待审 583 / 排除 192，所以对比可信。

| | 放行(n_auto) | 待审(n_review) | 排除 |
|---|---|---|---|
| vol03 旧 → 新 | 17071 → **17054**（−17） | 299 → **316**（+17） | 52 → 52 |
| vol02 旧 → 新 | 29728 → **29727**（−1） | 583 → **584**（+1） | 192 → 192 |

**vol03 逐格变化共 27 格**（id 级比对，其余 17395 格 admit/字都不变）：

| 来源 | 格数 | 说明 |
|---|---|---|
| `context_guard_page`（整页护栏） | **12** | 放行→待审：p110 9 格（字同，原 context 通道放行）、p107 3 格（**字也变了**：禎→禮、癸→奏、酉→西，即原先放行的是错字，本来就该拦） |
| `context_head_nonchar` | 0 | |
| 即/卽·歷/厯 归一 | **0 个 admit 变化可归因于它** | 没有格因 codepoints 变而翻转放行/待审；唯一带 卽/即 的变化是 97:6:3，见下"非 cv 代码来源" |
| H-seal 撤库（遮挡格） | 8 | p3 c4 的 `-1、6a…8b` 8 格：旧为 human 放行，新为待审+`occluded`。ws `glyph_store/evictions.jsonl` 里有这批的撤库记录（7 条 v2:vol03:3:4:*），human 通道没了→遮挡闸生效。是 H 的改动，不是 1.11 |
| 服务器人裁比 ws 新 | 7 | 见下拿不准 1 |

**vol02**：只有 1 格变——`vol02:16:9:2` 冊：context 放行 → 待审 `context_head_nonchar`（列首前两格护栏，唯一一格）。

## 4. p110 印章：`occluded_min_cells` 6 的结论——**不该改**

vol03 全册（110 页）跑 `occluded_cells`，其余参数保持 min_density 4 / min_cols 3 / min_peak 8 / min_contrast 2.5，只把 `min_cells` 12→6：

- 现行 12：命中页只有 p3（136 格）。
- 改 6：命中页 **10 页**，除 p3 外多出 **9 页**：p11(9) p14(7) p15(8) p28(6) p60(8) p68(6) p97(6) p107(6) p108(6)。
  **不是"只多 p110"，而且 p110 自己根本没命中**（0 格）。
- 原因不在块大小：p110 全页只有 5 个格密度 ≥4（3,21/6,1/9,21/4,4/3,1，最高 5.3），互不成块，`min_cells` 降到 3、`min_cols` 降到 1 也是 0。
  印章那块（cols3–5 × slots3–5）的密度多在 3.1–3.7，低于 `min_density=4.0`。把 `min_density` 降到 2.5 且 `min_peak` 降到 4，才能圈出一个 7 格块（col3–5，slots 3–5），
  但 min_peak 8→4 会放松最要紧的"印章芯子是一大片斑点"那道闸，我没在全册上验证误报，不敢建议。
- **建议：不要在 vol03.yaml 加 `occluded_min_cells: 6`**（会白多 9 页误报候选而 p110 仍漏）。p110 要么走 `context_guard_pages`（已配 [49,107,110]，
  现在 p110 那 9 个 context 放行已被退回）+ 人裁，要么 D 另行标定 min_density/min_peak（需要全册误报量）。

## 5. 拿不准 / 发现的问题

1. **服务器人裁比 ws glyph_store 新（最重要）。** vol03 旧产物里 `vol03:53:7:18 㫖`、`65:9:14 彞`、`97:6:3 卽` 是 human 通道；`events/vol03-shadow-review-0929.jsonl`
   有对应 confirm，但 ws main 的 `glyph_store` instances/admissions 里查不到这三格（服务器的 glyph.db 已消费该事件，ws 还没同步）。
   我的 db 里它们就走自动通道成了 旨/彝/即（放行→放行，字变，另 `108:7:4 采→釆`、`108:5:6`、`108:6:13`、`108:9:12` 是 all-decide 事件里的新人裁，
   ws 里有、服务器 09-29 值守数字时没有）。**这 3 格如果照包导入会把人裁字冲成自动字**；且 seed_admit 指纹里含 `human_fingerprint`/`ledger_fingerprint`，
   我的与服务器现役库不一定相同，导入后有可能仍判过期。请总管在服务器上先确认 ws glyph_store 是否已含 shadow-review-0929 的入库，再决定是否导，或让服务器就地跑 `guji step seed_admit vol03`
   （这一步 7 min，比导包更稳）。vol02 无此问题（只 1 格差）。
2. `compatible_with` 留空（同 #279）。
3. 沙箱 `fp-migrate --trust` 只是为了让 Step1–6 在沙箱里判新鲜、能单跑 seed_admit；`--trust` 不验代码/参数是否变过。快照 Step1–6 是在 cv `b961082` 算的，与 main 不同，但 Step1–6 相关代码 1.11 没动，任务书也这么说。
4. 沙箱 db 指纹 `f75099253ad7ff74`，与 #279 时的 `4224b3b…` 不同（ws 又改过），不影响 seed_admit 判定，仅记账。
5. `align_ref.py:170` 等处有 yaml `label` 的 `#` 截断警告（书 yaml 里 `daizhige逐列本（P#195…`），已由 D 加警告，是 ws 书 yaml 待加引号，我没动。
6. p3 c4 那 8 格里 `-1` 号（讀）在旧包是 `no_glyph_lib` 的 human 放行，evictions 只列了 7 条，第 8 格的撤销依据我没细查。

## 6. 文件
沙箱脚本在 scratchpad，未入库；本 HANDOFF 是唯一交付文件。
