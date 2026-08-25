# Artifact 登记处——审查页面的 URL、快照与再生方法

本项目的人机协作靠一组发布在 claude.ai 上的交互审查页（Artifact）。
**URL 是持久资产**：用户的书签、页面里的浏览器本地状态都锚在 URL 上，
更新内容必须**重发布到同一 URL**（发布时带 `url` 参数），千万别新开。
本目录存各页的 HTML 快照（可离线看、可回滚），README 是唯一的 URL 台账。

## 活跃页面（vol01 进库工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **种子审查页**（逐页进库人裁）| https://claude.ai/code/artifact/98d441fc-b27e-482a-a0c0-1cf1f72d170d | [vol01_seed_review.html](vol01_seed_review.html) | `scripts/export_seed_review.py output/vol01 --page 4,5,…,24`（逗号分隔可多页一批）。当前 4~24 页 184 条待审 |
| **字形库体检**（/glyphdb-audit）| https://claude.ai/code/artifact/a9509695-aaa5-4842-a496-a09e164b5417 | `output/glyphdb_audit/review.html`（随库提交）| `scripts/audit_glyph_db.py run` |
| **对勘复审**（我的定字 × 整理本，可改判/打印）| https://claude.ai/code/artifact/33403492-4d1c-4b32-bb2b-c66e01971684 | `output/vol01/phase9_seed/collation_review.html` | `scripts/export_collation_review.py output/vol01` |

## 切分审查（G1/G2 工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **切分朱批·图块流**（紧裁版逐块审）| https://claude.ai/code/artifact/5406db9c-76da-46a6-a3d9-6b55e2965f81 | 数据即产物（2026-08-24 重建轮已刷新）| `scripts/build_patch_review.py --pages vol01:20-27 vol02:1-8 --quality 70` + 壳模板 [shells/patch_review_shell.html](shells/patch_review_shell.html)（`__PAGES__`/`__MARKS__` 占位注入）|
| 切分朱批·整页叠框（V1，看框位）| https://claude.ai/code/artifact/46681969-bd3f-46fe-915c-0ecd5a376f32 | 数据即产物（2026-08-24 重建轮已刷新）| `scripts/build_seg_review.py --pages vol01:20-39 vol02:1-20 --quality 62` + 壳模板 [shells/seg_review_shell.html](shells/seg_review_shell.html) |

标记经页内「导出」产 `GUJI-SEG-REVIEW` JSONL 回流。

## 归一化（G3 工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **笔宽归一复核台**（撤除笔宽归一，golden 重冻的人工目视门）| https://claude.ai/code/artifact/cd2fee67-fb9d-4519-870a-41413b9c87d3 | [norm_stroke_review.html](norm_stroke_review.html) | `scripts/build_norm_stroke_review.py --dataset ../open-guji-dataset/char-normalization` |

改 `normalize_patch` 会让 char-normalization 的 37 张 golden 全部出容差，而那层
按规矩是**人工目视门**（「输出本身就错的绝不冻成 golden」）。本页把
原图 / 现 golden / 新输出 三联并排，裁决经页内「复制裁决」按钮回流。

## 说明页（静态，讲清楚管线怎么运作）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **从版面到字块**（切分层分步算法 + 每步测试集 + 标注去向盘点）| https://claude.ai/code/artifact/2a8475ed-dc47-454c-b1fc-049a89be0b7a | [seg_layer_explainer.html](seg_layer_explainer.html) | 手写，随管线改动更新 |

## 匹配裁决（G4 工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **形近误判裁决台**（排序倒挂逐例人裁，手机优先，**页面自存**）| https://claude.ai/code/artifact/9e45a22b-da42-4bd5-9486-378fd714a80a | [match_inversion_review.html](match_inversion_review.html)（快照）· 卡集 [match_inversion_cards.jsonl](match_inversion_cards.jsonl) · 裁决 [match_inversion_verdicts.jsonl](match_inversion_verdicts.jsonl) | `scripts/eval_match_pairs.py ../open-guji-dataset/glyph-match/pairs --dump /tmp/pairs.npz` → `scripts/build_match_inversion_review.py --dump /tmp/pairs.npz` |

triplets 的 hard 子集是**人裁**出来的（「用户亲眼裁定本例标签没错」才收），
扩集的瓶颈从来不是挖不到候选，是没人过目。本页挖的是 pairs 集里最尖锐的
一种失败形态：对同一实例，最高分的**异字**邻居压过了最高分的**同字**邻居
（202 例 / 5279 个双边齐全的实例）。四个裁决键分别对应四种归宿——
可入集（进 triplets hard）／标注有误（回流标注层）／异体字（归 P0 异体字
关系层）／拿不准（两边都不收）。

**这一页会自己存。** 它声明 `artifact` 能力，裁决改动 6 秒防抖后用 files 形式
把 `index.html` 重发一版（files 形式不重载本视图，用户可以一直点下去），裁决就
嵌在页里的 `#data` 里。收割方式：`Artifact action:"read"` 读回 HTML，取
`#data` 的 `verdicts` 字段。localStorage 是即时兜底，「复制裁决」按钮留着当退路
（顶栏那颗标记会说当前存到哪了：已存／待存／仅存本机／只读）。

> **重发这一页前必须先 read 回来把 verdicts 并进 `match_inversion_verdicts.jsonl`**，
> 否则一次覆盖就把用户没收割的裁决全抹了。

**卡号是稳的。** 裁决按卡号（T000…）记，而挖掘结果会随金标改判、随排除名单变，
所以卡集冻在 `match_inversion_cards.jsonl`：老 anchor 保号，同一实例金标改判过的
刷字头并打「已订正」，不再倒挂的打「已解决」、图块被移出数据集的打「已排除」——
都不删，新冒出来的追加新号。重跑构建脚本不会让任何一条已有裁决错位。

**2026-08-25 第二轮**：数据集清理之后（排除名单 r2）重挖，倒挂率从 202/5279
降到 **82/4335** —— 一半的倒挂本来就是切分损伤造成的。卡集 202 → 220
（新增 18 张），页面默认只显示「待裁」的 **37 张**，那批才是真正的判据失败。

## 图块质量（G1/G4 回流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **图块出库裁决台**（逐块判能不能用，四层分层，**页面自存**）| https://claude.ai/code/artifact/69cdfc83-3117-496f-8209-265887e963af | [glyph_evict_review.html](glyph_evict_review.html)（快照）· 卡集 [glyph_evict_cards.jsonl](glyph_evict_cards.jsonl) | `scripts/build_glyph_evict_review.py` |

形近误判裁决台第一轮 132 例里 73 例判「标注有误」，用户看完的结论是**大量图块
本身带残留**（界行线、版框条、邻字整块混入、格线上飘切了半截），标签错只是症状。
但现有 `crop_quality` 判据锚在图块外边界上，拿这 132 例扫只中 35/73，keep 里还
误报 6/57；换了几组新特征（墨框纵横比 / 投影干净缝 / 孤立连通体外扩量）AUC 全在
0.43~0.60——**靶子不对**：`bad` 判的是字头错没错，不是图脏不脏。所以先收一批
逐块的图像质量金标。

候选分四层，**误报率与漏检率必须分开报**：`missed`（判了 bad 但现有判据没旗标的
38 块，判据盲区）/ `flagged`（全池 606 个旗标块分层抽 49）/ `newrule`（只被新规则
命中的 25）/ `control`（全池随机、任何旗标都没有的 40——**没有这层就只能证明判据
说对了什么，证不出它漏了什么**）。页面**不显示**卡片属于哪层、被哪条判据挑出来，
顺序也打乱：显示了就等于提前给答案，那批裁决就没法拿来量漏检率了。

**第一轮结果（151/152，2026-08-25）**：出库 29 / 进测试集 10 / 留着 112。分层读：

| 层 | n | 缺陷率 |
|---|---|---|
| `missed`（定向富集，不可读作率）| 38 | 57.9% |
| `flagged`（全池占 9.96%）| 49 | **26.5%** |
| `newrule` | 24 | 12.5% |
| `control`（全池占 90.04%）| 40 | **2.5%** |

→ **全池缺陷率约 4.9%**（≈298/6086）；现行 `crop_quality` 召回约 54%、
**精确只有约 27%**。所以不做全库自动出库——按这个判据清一遍会误伤四分之三。
候选新规则（墨框宽高比/投影干净缝）12.5% 比对照层高但远不如现行判据，不进。
唯一强到可以按规则批量处理的是**列尾格位**（idx=20：抽到的 6 块里 4 块有缺陷）。
151 条已并入 `open-guji-dataset/char-segmentation/instances`（带 `stratum`
与 `stratum_weight`）。

## 总览

| 页面 | URL | 快照 | 说明 |
|---|---|---|---|
| **字形匹配栈现状** | https://claude.ai/code/artifact/51e7647f-ab90-439a-b36f-5adc6aee084b | [match_stack_status.html](match_stack_status.html) | 四步链条 / 六个测试集的当前数字 / 卡在人裁那侧的五件事。乱了先看这张 |

数字随基线变，**改完护栏记得重发到同一 URL**；真源是
`.claude/doc/glyph_match_stack.md` §三 的基线表。

## 分析报告（静态，作决策依据引用）

| 页面 | URL | 快照 | 说明 |
|---|---|---|---|
| 三信號進庫策略 | https://claude.ai/code/artifact/bbea2607-799d-4ab2-a97f-4c35fd485f87 | [signal_policy.html](signal_policy.html) | 529 条人审难例的三信号交叉标定（R1~R4 规则的依据）|
| vol01 對勘記 | https://claude.ai/code/artifact/cda67c8c-b5e9-48ac-99cb-f769652d71f4 | [vol01_duikanji.html](vol01_duikanji.html) | 三栏对照（原图/我的整理/整理本）|

## 历史页面（早期会话，无本地快照，URL 备查）

- 總目卷一（vol01）審查總覽 c82aa38f / 卷二（vol02）0bdcc21f
- vol01 · 頁型 0668c3f7 / 版面 ddab1f03 / 圖塊 fe3a22ce / 認字 1855f6f9
- vol02 · 頁型 d1bae796 / 版面 6ccd3a43 / 圖塊 ddb3e784 / 認字 19d34055
- book9 分步審查 d306fc16、錯判圖譜 ec62393b、並行作業總表 59a120cb、
  四庫總目字勘 2f1913aa（兩冊版 ec914d9a）
  （完整 URL 形如 `https://claude.ai/code/artifact/<uuid>`，uuid 见上）

## 纪律

- **同 URL 重发布**：会话内用同一文件路径重发即可；跨会话发布带
  `url` 参数指向上表 URL。发布前先读回最新存档（页面会自存用户事件），
  别覆盖没收割的裁决。
- **快照更新**：审后流程收尾时把最新导出的 HTML 拷回本目录一并提交
  （体检页与对勘页真源本就在仓库内，不必拷）。
- **事件回收**：所有审查页共用 `GUJI-SEED-EVENT` 前缀三层持久化
  （persist_js.py），从 artifact 存档提取事件行即可回收。
