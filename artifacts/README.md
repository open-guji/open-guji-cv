# Artifact 登记处——审查页面的 URL、快照与再生方法

本项目的人机协作靠一组发布在 claude.ai 上的交互审查页（Artifact）。
**URL 是持久资产**：用户的书签、页面里的浏览器本地状态都锚在 URL 上，
更新内容必须**重发布到同一 URL**（发布时带 `url` 参数），千万别新开。
本目录存各页的 HTML 快照（可离线看、可回滚），README 是唯一的 URL 台账。

## 活跃页面（vol01 进库工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **种子审查页**（逐页进库人裁）| https://claude.ai/code/artifact/98d441fc-b27e-482a-a0c0-1cf1f72d170d | [vol01_seed_review.html](vol01_seed_review.html) | `scripts/export_seed_review.py output/vol01 --page 41,…,50`（逗号分隔可多页一批）。当前 41~50 页 131 条待审；**发布一律覆盖同一 URL**（用户 2026-08-26 定，不必再问）|
| **字形库体检**（/glyphdb-audit）| https://claude.ai/code/artifact/a9509695-aaa5-4842-a496-a09e164b5417 | `output/glyphdb_audit/review.html`（随库提交）| `scripts/audit_glyph_db.py run` |
| **对勘复审**（我的定字 × 整理本，可改判/打印）| https://claude.ai/code/artifact/33403492-4d1c-4b32-bb2b-c66e01971684 | `output/vol01/phase9_seed/collation_review.html` | `scripts/export_collation_review.py output/vol01` |

## 切分审查（G1/G2 工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **切分朱批·图块流**（紧裁版逐块审）| https://claude.ai/code/artifact/5406db9c-76da-46a6-a3d9-6b55e2965f81 | 图块数据即产物；**朱批真源** [marks/patch_review_marks.json](marks/patch_review_marks.json)（302 条）| `scripts/build_patch_review.py --pages vol01:38,70,88,50 vol02:18,31,41,43,52,67,73,77,89,92,97,108,124,137,153,155,152` + 壳模板 [shells/patch_review_shell.html](shells/patch_review_shell.html)（`__PAGES__`/`__MARKS__` 占位注入）。**HTML 快照不入库**（4.2MB，图块本来就在 output/ 里）。图块为**无损 PNG**（曾用 JPEG q52，整页 13.9MB；产物本是二值图，JPEG 既臃肿又生振铃），页面**自动保存**（停手 20 秒、切标签页各冲一次），朱批不再靠人手点。当前第十四轮 = **只装 vol01:50,60 两页**（用户 2026-08-26「让我看看 50 60 两页切分效果」），512KB、手机上秒开；页级尺子/逐列相位/穿边额度三修后的产物。**朱批不受影响**：`STATE.marks` 是一张按 `book/page:col:idx` 的平表，与页面装了哪几页无关，264 条原样带着、自动保存照写回。换页集前照例做过两件事：读回线上 `marks-data`（与仓库真源逐条相同，用户没有未导出的朱批）、查重切漂移（本轮改动的 8 页里**没有一页带朱批**，无需重键）。要装回 21 页就把上一版的 `--pages` 再跑一遍。

**第十三轮（2026-08-26 晚，截断根治后）**：读回线上 `marks-data` 得 **302 条**
（比仓库真源多 38 条——用户第二轮实审在 vol01/50、60、70 上新点的，
已并入真源）。逐条查漂移：**8 条需重键**，`vol01/27:2:18 → 2:17` 与
`vol01/50 c1` 的 7 条（clip_refit 把该列相位整体重定，首端 margin 变字格，
其后 idx 全体 +1）。按规矩把旧图块与位移后的新图块并排逐个看过：
庫/書/內/朕/欽/定/在/旨 一一对上，**没有一条是猜的**。
另有 6 条（`vol01/50 c5/c7/c9`、`vol01/60 c6/c7/c9` 的 idx 0）**键不变**
——那几格正是这一轮修好的首字，格位没动、只是重新框准了。

**第十四轮（2026-08-26 深夜，用户复审「第50页还有两个小问题」）**：
用户点名 c1:21、c7:21 两格，图块渲染出一条黑杠——不是字，是页级下
边框线卡在这两格的中部（`clip_refit` 挪格之后常见后果），加了
`border_rows` 判据后归空。读回线上 `marks-data` 277 条：27 条是用户
自己清掉的（对应上一轮已修好的列，用户逐格看过确认无误后点掉的）、
2 条新增（`vol01/27:2:18` 与 `vol01/50:7:21`）。`27:2:18` 是上一轮
重键过的 `27:2:17` 在客户端本地存储里弹回了旧键——按同一条已核实的
重键关系（青字位移一格）重套，未改判据；`50:7:21` 正是用户这次点名
的黑杠格，页面重发布后应显示为空白占位，用户下次可自行清标记 |
| 切分朱批·整页叠框（V1，看框位）| https://claude.ai/code/artifact/46681969-bd3f-46fe-915c-0ecd5a376f32 | 数据即产物（2026-08-24 重建轮已刷新）| `scripts/build_seg_review.py --pages vol01:20-39 vol02:1-20 --quality 62` + 壳模板 [shells/seg_review_shell.html](shells/seg_review_shell.html) |

标记经页内「导出」产 `GUJI-SEG-REVIEW` JSONL 回流。

| **页面级快速审阅**（正文页里疑似有问题的页，页型/列行/严重度免标注）| https://claude.ai/code/artifact/7ec62645-d07d-4527-8d59-1ae40658a19d | 数据即产物 | `scripts/build_seg_review.py --pages <书:页,页,…> --scale 0.4 --quality 65 --out …`（`page_severity` 复用 truncation/seam 两把尺子挑页，见脚本 docstring）。当前装的是 2026-08-27 全书扫描出的 22 张**正文**疑似问题页（vol01 87/88/90/107/171/182/183/185/196/205、vol02 3/107/108/119/133/135/141/149/179/180/181/182）——同一次扫描还测出 vol01 87~131 区间一批**职名页**截断偏高，按「只调正文」策略未收进此页，记在 pipeline_handbook 待办。用户已用导出流程反馈 vol02/135、108 共 20 处切错，均落在已知「浓墨粘连」区（见 char_clustering_design.md「与 seam 打架的两页」），等下一轮浓墨粘连专项处理。

**⚠ 重切/重扫之后，朱批也会漂。** 朱批键在 `book/page:col:idx` 上，跟
`char-segmentation/instances` 一样是**会漂的**。2026-08-25 文字带窗口救援
让 vol01/70 整列多出一行，挂在它上面的 11 条朱批全体错位一格。规矩与
金标一致：**先查漂移，再谈数字**——逐条比 bbox 找出最佳位移，再把旧图块
与位移后的新图块并排渲染**逐个看**，确认是同一个字才改键。那一次 9 条
确认重键（紫/香/對/設/冠/粉/署/徵/其），2 条看不出对应关系就摘掉、
等用户在新一批里重标，绝不猜。

真源存在 [marks/patch_review_marks.json](marks/patch_review_marks.json)，
每次发布前**必须先 `Artifact action:"read"` 读回页面里的实时 `marks-data`**
并以它为准——用户可能有还没导出的朱批，直接拿旧文件重发会盖掉。

朱批口径：点一下=切错、两下=无误、三下=存疑、四下=清除。**自检橙边
默认关**（用户 r7「自检太多了我就没消除」），要看点工具栏「自检框」，
状态存在浏览器本地。

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
| 裁边失手体检 | https://claude.ai/code/artifact/717b2081-3e9f-4ea3-818c-50a184abb1b2 | [crop_review.html](crop_review.html) | vol02 抽样 14 页 s3_crop 中间产物：133/135/107 三页裁剪失败残留大片空白，根子在 content_bounds 边框线检测阈值（2026-08-27，浓墨粘连截断专题的新根因线索，待修）|
| 版框线批量检测 | https://claude.ai/code/artifact/7d730326-db8f-4046-bbee-8162950da09d | **HTML 快照不入库**（4.8MB，5 页整页图内嵌 base64）| `scripts/find_border_lines.py --pages vol02/133:9 vol02/135:9 vol01/33:9 vol01/90:9 vol01/171:9 --root <s3裁剪跳过s4增强产物根目录> --report report.html`。5 个样本页跑 `peak_line_search`（半高宽匹配度 + 位置角度联合搜索，见 [peak_line_search.md](../.claude/doc/peak_line_search.md)）：正文/目录 3 页干净，抬头页（vol01/33）顶部边框被抬头小框干扰、职名页（vol01/90）顶/底边框搜出退化结果（宽度=1px，疑似 s3 裁剪已把边框裁掉）——两处已知局限都在报告页标红。附带发现 vol02/133 底部边框比 `border_detect.py` 生产算法的检测偏了 41px（2026-08-28）|

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
