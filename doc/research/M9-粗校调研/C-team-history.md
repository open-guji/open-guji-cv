# M9 调研 C：团队历史（ai-team / overview / 本地仓只读）

> 2026-10-20 洛杉矶。只读调研，未改任何仓库。
> 缩写：AT=/home/user/ai-team，OV=/home/user/overview，WS=/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本，BT=/home/user/open-guji/book-text/Book/g/z/k/96mid1ogzk，CV=/home/user/open-guji-cv（main a00dbdb）。
> 「推测」＝我的推断，未核实。

---

## 0. 关键出处一览

| 主题 | 文件 |
|---|---|
| 三阶段设计 v0.8（GUJI-543） | AT/team/整理/设计/文本整理三阶段流程.md |
| 待审单改走中心库（10-19 v0.1，已上线） | AT/team/整理/设计/待审单与公众意见走中心库.md |
| 定稿后增量修订（GUJI-541，§7 细则） | AT/team/整理/设计/定稿后增量修订.md（未细读） |
| 重跑 vol04–10（10-19，M8） | AT/team/整理/重跑vol04-10/README.md ＋各册 粗校报告／异常表 |
| M8 受控重跑基线记录（10-20） | WS/experiments/<册>/<标签>.md（guji-workspace main 422f1d5） |
| 冻结基线、受控重跑规范 | AT/domain/CV/规范/冻结基线与重跑分级.md、受控重跑方法论.md |
| M8 复盘 | AT/通用/里程碑执行经验.md |
| 10-20 交接（vol01 18 列、vol01 收尾、vol02/03 补精校） | AT/domain/CV/交接/vol01重切18列-交接-10-20.md；AT/domain/文本/交接/*.md |
| 10-17 交接 | AT/team/整理/交接-Lucian-10-17.md；AT/team/整理/GUJI-543/交接清单-10-17.md；AT/team/CV/交接-Owen-10-17.md、交接-Eldon-20261017.md、交接-Mila至备用团队-10-17.md |
| 粗校出口脚本 | AT/team/整理/GUJI-556/（README、exit_report.py、Eamon上手指引.md）；已移入 CV/scripts/zhengli/{collect_exit.py,exit_report.py} |
| book-text 现状 | BT/default/index.json、BT/default/CHANGES.md（浅克隆，main ffbf1d49） |
| 各册 cv 版本登记（停在 10-17，已过时） | AT/team/CV/各册产物cv版本登记.md |
| override 缺口拆卡 | AT/team/CV/GUJI-579/override缺口拆卡.md |
| guji-proof 0.2 字段（待审单格式） | AT/team/CV/guji-proof-0.2-字段表-GUJI-557.md |
| 开新书手册（旧，09-28） | OV/项目进展/新书整理/开书手册.md |
| 四庫整册整理总计划（10-12，旧口径数字） | OV/项目进展/四庫整册整理/计划/总计划.md |
| 路线图 v3（10-13） | OV/项目进展/总调度/路线图/路线图.md |
| 机器清单（09-27/30） | OV/机器清单.md |

---

## 1. 各册现状（vol01–10）

### 1.1 book-text（BT/default/index.json＋CHANGES.md，实测）

| 册 | 页 | 格（char.json 计） | □ | 文本版本 | proofing | 关键 PR |
|---|---|---|---|---|---|---|
| 001 | 206 | 24,364 | 0 | 1.0.0 | true（仍是 true） | #150 0.1.0（10-17）→ … → #194 0.1.6 → #199 1.0.0（10-19） |
| 002 | 188 | 30,478 | 0 | 1.0.1 | — | #22 1.0.0（10-07 旧定义）→ #184 1.0.1（10-19，34 处改正之一） |
| 003 | 110 | 17,370 | 0 | 1.0.2 | — | #22 1.0.0 → #184 1.0.1 → #191 1.0.2（lane 字段）；另 cv-proof/003 0.1.0/0.1.1 并存（#167/#168） |
| 004 | 221 | 34,515 | 262 | 0.2.2 | true | #162 0.1.0（cv v0.2.0）→ #182 0.2.0（rc/v0.4.5 从原图重跑）→ #189 0.2.1 → #198 0.2.2 |
| 005 | 188 | 28,950 | 256 | 0.1.1 | true | #183 0.1.0 → #188 0.1.1（p55、p123 整列） |
| 006 | 150 | 23,488 | 220 | 0.1.1 | true | #185 0.1.0 → #186 0.1.1（p88 七字） |
| 007 | 135 | 21,174 | 182 | 0.1.0 | true | #197 |
| 008 | 69 | 10,698 | 181 | 0.1.0 | true | #190 |
| 009 | 265 | 42,022 | 453 | 0.1.0 | true | #193 |
| 010 | 175 | 28,929 | 281 | 0.1.0 | true | #195 |
| 合计 | 1,707 | 261,988 | | | | |

### 1.2 vol04–10：粗校出口（10-19，AT/team/整理/重跑vol04-10/vol0X-粗校报告.md）

| 册 | 页 | 格 | 待审（R3） | 率 | 报告头 cv | 待审单 rev | seg_defect | 对不上列（一致/说明/重切） | 重切清单 |
|---|---|---|---|---|---|---|---|---|---|
| vol04 | 221 | 34,515 | 303 | 0.88% | e92c8be5（v0.4.5-12） | 004-r3（异常表写 280 格、□262） | 75 | 47（10/8/29） | 33 列（README） |
| vol05 | 188 | 28,950 | 275 | 0.95% | 448d5824（v0.4.5-9） | 005-r2（271 格） | 19 | 48（17/17/14） | 14 列 |
| vol06 | 150 | 23,488 | 231 | 0.98% | 568d1c2d（v0.4.5-7） | 006（231 格） | 41 | 44（7/9/28） | 29 列 |
| vol07 | 135 | 21,174 | 203 | 0.96% | e92c8be5 | 007-r2（203） | 26 | 21（2/3/16） | — |
| vol08 | 69 | 10,698 | 197 | 1.84% | 448d5824 | 008-r1（197） | 16 | 20（6/5/9） | — |
| vol09 | 265 | 42,022 | 489 | 1.16% | e92c8be5 | 009-r1（489） | 62 | 48（9/3/36） | 36 列 |
| vol10 | 175 | 28,929 | 312 | 1.08% | e92c8be5 | 010-r1（312） | 21 | 20（1/1/18） | — |

R3 分类（class_counts，「根因未逐类核」）：
- vol04：其他120、印章遮挡52、库缺字41、近形34、整理本替换对齐23、参照冲突16、己已巳13、异体4；看图判错70
- vol05：其他115、近形37、库缺字34、替换对齐28、参照冲突23、己已巳16、遮挡15、异体7
- vol06：其他72、参照冲突39、替换对齐39、库缺字30、己已巳18、近形18、遮挡11、异体4
- vol07：其他77、遮挡32、替换对齐28、己已巳21、参照冲突15、近形13、异体9、库缺字8
- vol08：参照冲突73、其他42、替换对齐19、遮挡18、近形16、库缺字16、己已巳8、异体5（书类存目整理本书名卷数多处不同）
- vol09：其他155、参照冲突76、替换对齐68、近形46、库缺字46、己已巳45、遮挡43、异体9、form_open1
- vol10：其他122、替换对齐49、库缺字36、遮挡31、近形31、参照冲突21、己已巳16、异体6

**口径冲突**：vol09 报告文字「遮挡 272 格占待审一半以上」、vol10「遮挡 262 格占八成以上」，但同一报告 class_counts 里「印章遮挡」只有 43、31；异常表 vol09「遮挡272、己已巳149」、vol07「遮挡148、己已巳64」——疑是 flag 计数（一格多 flag）与分类计数混写（推测）。
**vol04 数字漂移**：466（10-17，cv v0.2.0，含 12+8+4 口径差；导出 pending 442→454）→ 437/34522＝1.27%（README 10-19 早）→ 303/34515＝0.88%（报告 15:02）→ 280（异常表 004-r3）→ 279（M8 main 包 v0.4.6-cujiao 0.81%）→ 273（new-glyphs）。vol05：289/28927（README）vs 275/28950（报告）vs 271（005-r2）。

耗时（README）：vol04 拉库4.5分、Step1–4 约40分、字体 jigmo7.3＋iming4.3分、rare index 18.6分（只建一次）、Step5–7 67分、导出15秒、close-check 约9分、对不上列看图约1小时；vol05 Step1–4 27分、Step5–7 67分、收尾约25分、出口8.5分；vol06 26/55分、收尾40分；vol07 26/59分、重跑 Step1 7分；vol08 25/46分；vol09 65/51分、出口12分；vol10 38/79分。并跑「本册 Step5–7 jobs4＋下册 Step1–4 jobs1」一册墙钟约2.5h→1.5h。10-19 夜 db sync 后 vol04–10 全 stale，--from rare_candidates 重跑 vol10 16分、vol07 12分、vol04 17分。

### 1.3 vol04–10：M8 受控重跑基线（10-20，WS/experiments/）

所有包的「基线（存包时该册 main）」都是 `v0.4.6-cujiao`；**新包一个都没标 main**（都等 GUJI-626 异体码位）。

| 册 | 包标签 | cv | 语料 | 人裁指纹 | 中心库 rev | 送审 前→后 | 率 | 放行字变 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| vol04 | cv0.4.7-c1-g-82293e-new-glyphs | 0.4.7 23df9921 | c1 | h1:3448:82293e | 9916 | 279→273（结论）；结果表写 279→279 | 0.81% | 19（16 对、3 错：蒙→𫎇、彞→彝×2） | 表与结论自相矛盾 |
| vol04 | …-control / …-layout-prior | 0.4.7 | c1 | 同 | — | 273 / 273→256 | 0.79%→0.74% | 2 | layout_prior 正文 4 列变坏，交 B CV，不标 main |
| vol05 | cvunknown-c1-g-82293e-new-glyphs | rc/v0.4.8 fee8a2e（浅克隆读不到 tag） | c1 | 同 | 9989 | 271→247 | 0.94%→0.85% | 10 | 28998 格 |
| vol06 | cv0.4.7p9-c2-g-82293e-baseline | 0.4.7+9 6f32d001 | c2 | 同 | 11307 | 231→218 | 0.98%→0.93% | 8 | 23517 格；人裁 2→50 |
| vol07 | 同上 | 同 | c2 | 同 | 11290/11307 | 203→166 | 0.96%→0.78% | 9 | 人裁 2→66 |
| vol08 | 同上 | 同 | c2 | 同 | 11307 | 197→180 | 1.84%→1.68% | 8 | 10710 格 |
| vol09 | 同上 | 同 | c2 | 同 | 11307 | 489→399 | 1.16%→0.95% | 20（13 格非异体待看图） | 110 格新人裁是主因；另开 GUJI-633 |
| vol10 | 同上 | 同 | c2 | 同 | 11307 | 312→292 | 1.08%→1.01% | 13 | 需看图 3 格 |

- 所有基线「字形库钉号」一栏为「—」（glyph_pin 没用）；切分 Step1–4 均未动（只从 glyph_match 起 --force）。
- vol04、vol05 仍是语料 c1；vol06–10 是 c2（c1 清单与 freq.json、l2/jys.json 对不上，用户定升号）。
- **book-text 里 004–010 的文本来自 10-19 的 v0.4.5/0.4.6 运行，不是这批 M8 基线**；中心库待审单 rev 也对应 10-19 那一轮（推测：M8 基线的送审下降尚未反映到 book-text 与待审单）。

### 1.4 vol01–03（10-20 用户定：不再由本项目整理，AT/domain/文本/交接/*）

| 册 | 现状 | 未结 |
|---|---|---|
| vol01 | 1.0.0（#199）；冻结基线 snap/96mid1ogzk/vol01/20261019T2303（cv 0.4.5 004bc889，12 步 206 页）；人裁 139 条；待审 0（66 格在重切清单，字已手改进文本）；册 yaml 有 freeze: | 18 列重切（p10:7；89:7,9；90:2,6,7；101:2；105:1；107:4；119:3,7；130:9；196:1,3,4,5,7,9）——格 id 与 book-text 手拼列对不上；重切后 9 页 row_segment→seed_admit、重导、重打冻结快照；通知标点专名开工；归档 guji-workspace。CV 窗口与接手窗口都被叫停，无人领 |
| vol02 | 1.0.1；rc/v0.4.6 整册重跑；用户裁 vol02 后 64 条事件（批次 vol02-rerun-review-1020）；v0.4.7 导出待审 191→64 | 事件与清单因 443 桥连不上**只在材料目录未进中心库**；seed_admit 重跑；close-check；排除名单先于人裁（124 格）；113:1、28:8 整列错位一格 |
| vol03 | 1.0.2；待审 21；裁定页 artifact 用户未裁（33:2:1、59:4:9） | 57:1「見矣」整列没切出、100:7 首字列图外、59:4:9 夹注并格等；旧 default/003 与 cv-proof 并存的替换未定 |

### 1.5 旧口径（10-12 前，OV/项目进展/四庫整册整理/计划/总计划.md §三）

vol04 221页/34,152格/待审521(约1.5%)；vol05 188/28,212/363；vol06 150/23,510/1,279(5.44%)；vol07 135/21,171/1,316(6.22%)；vol08 69/10,699/821(7.67%)；vol09 265/42,087/3,080(7.32%)；vol10 175/29,007/2,573(8.87%)；合计 1,203 页、约 15.9 万格、约 9,900 待审。人审估 5 秒/格。
更早（09-28 开书手册 §9）：vol02 1.68%→vol03 3.45%→vol04 4.37%。

---

## 2. 设计稿（GUJI-543 v0.8）粗校段

- §0/§1：平台粗校＝脚本＋CV 管线＋少量 AI 分诊，人登 cv console 看结果反馈算法；数据在 guji-workspace（现已改中心库）；出口文本线 0.1.0；人审率目标 <1%（不是硬标准）。
- §2：0.1.0＝粗校完成可并 main（带 banner）；0.x.0＝精校中每批人裁升 minor；1.0.0＝精校完成；2.0.0 出版级。`proofing: true` 显式开关，文本 major＝0 默认 true。
- §2a 每书固定一个 CV 版本：开工选正式 tag（不用 rc、不用 +N），册 yaml `cv_version: "0.2.0"`（不带 v），Jira 卡标题写「cv X」；默认不跟升级；升级理由三类（成片错、override 能力、bug）；升级只重跑 code_hash 变的 Step；收尾判据＝在固定版本下指纹不过期；装的版本≠册配置就拒跑（护栏，GUJI-577 起有：pipeline/step 拒跑，status/close-check 只提醒）。出口记录写「cv 版本（commit）＋ws 快照＋事件库 commit」。
  - 实际后来被 10-19 用户规矩修正：「只要在当时的 cv 版本下新鲜，不要求最新」；v0.4.7（#243）起 close-check 1a 对非冻结册接受「只因代码变而过期且 manifest 记正式 cv_version 的页」（混跑口径），`--strict-cv` 回旧口径（受控重跑方法论 §六）。**设计稿 §2a「不用 rc」与 vol04–10 实际用 rc 分支未打 tag 提交跑（e92c8be5 等）不一致。**
- §3.1 输入：书影、册配置、页清单、固定 cv 版本。
- §3.2 过程：全管线（page_survey→border_detect→column_warp→row_segment→cell_shrink；glyph_match→…→seed_admit）；三道闸（border_detect_gate 页级、column_gate、row_segment_gate 列级，gate_summary 出过闸率），定字端无闸由 seed_admit 放行/转人审；人看结果开 CV 卡；AI 分诊不写裁决。
- §3.3 完成标准（全满足才出 0.1.0）：
  - R1 全页全步按固定 cv 版本指纹不过期（guji progress/status stale＝0）
  - R2 三道闸每个失败列有去向（修好／override／待审）
  - R3 人审率报出来（目标 <1%，不卡出口，写原因）
  - R4 异常清单成片问题都有结论
  - R5 导出过格式检查：close-check 粗校档退出码 0（`--tier rough`，不计第 2 项待审清零；Maren 10-17 定）
  - R6（用户 10-19 加）整页、整列不丢字不错位；零散切分问题进重切清单、1.0.0 前修。查法：闸1 页级跳过页逐张看图；colgap.py（3 字片段对代字阁行）；widthscan.py（列宽偏离中位 25%）。修法：body_pages、column_grid_pages、四联叶按原图重裁。
  - 出口动作：导出 char/cord/norm＋待审清单与预裁图 → PR 进 book-text main（0.1.0，proofing:true）→ 网站 banner/精校页；打快照；保留工作区。
  - cv runbook close-check 表另有 0.1.0 硬项：2c（□ 有去向：待审单或重切清单）、2d（整理本对不上的列有交代：列交代单或重切清单）（CV/doc/runbook/整理一册书.md:385-387）。TSV 格式：`<册>-重切清单.tsv`（位置\t原因）、`<册>-对不上列交代.tsv`（页\t列\t处理\t说明；处理∈重切/改字/说明/一致）。
- §4.4 精校 F1–F5（出 1.0.0）：F1 §4.1 的格至少过一遍人（「看不出」→decision.json status=open；「切分没修没法判」→ reason=seg_bad＋route，单列，不得混；生成器 GUJI-588/decision_build.py）；F2 §4.3 自动检查过（字形库互查口径 b 只挡同字离群 outlier、整理本对照、裁决落地对账、排除名单对账、旧裁失效、close-check）；F3 抽检先不定；F4 公众意见池清空；F5 固定 cv 版本下指纹不过期。
- §5 override：一律带锚人裁事件、优先于算法、作训练标注；§5.2 审阅入口与 H 道写入必须同一版产物；消费者副作用落正式工作区；无锚老裁决重跑切分就不再采信；裁决不进指纹、product_invalidate 只标不跑（要 `guji rerun --stale`）；排除名单改了会让全册 seed_admit 过期。
  - §5.3 缺口：补格、删格、版框/列框坐标（border_offset 无 Step 读、head_raise 不读事件）、逐页页型、整列重切（recrop 未接入）；正文/小注整列批量写法。GUJI-579（10-18 读 3930d46）：5 个缺口一个都没合上；逐页职名页已能写（roster_pages）；「整列重切→接 recrop」是错的，要新 kind `column_recut`；建议合成 v0.4.0（MINOR）。override 事件写在 overrides/<名> 分片，原图绝对坐标。
- §6.2 待审清单：骨架 proof.json；册级 pending.json 只含待审格，由整理导出端生成（不放 CV 服务器）；guji-proof 0.2 字段（why、cls、lib_top、lib、ctx、conf、ref、ocr、stale、occ、img、ctximg、ex、alt）；预裁雪碧图 WebP 96×96 按页；坐标原图左上原点 xywh。**10-20 已改**：待审单存中心库 `feedback/lists/proofing/<书>/<章>.pending.json`，kaiyuanguji-web proofing-sync 每日发 COS `proof/`；book-text 的 pending_file 已删（book-text#200）。公众意见 → KV → Action 写中心库 `feedback/lists/web/<书>/<rev>.jsonl` → H 道 AI 落裁决（批次 H-web-<册>-<日期>，每批用户点头）。
- §13 拆卡：P0 骨架（vol01 跑通一圈）、P1 基本方案（CV 版本护栏、rerun --stale、override 缺口、各册首 tag 下重跑、R1–R5 一键报告、guji-proof 0.2、自动检查、快照、vol02/03、第三段、归档）、P2 以后（人审率<1%、AI 分诊、抽检、讨论区…）。M8（GUJI-567）承接 543 关闭验收，P1 旧卡拆成 GUJI-568～601。

---

## 3. 历次交接/复盘的问题与踩坑（按主题）

### 3.1 版本与指纹
- 10-16 时所有册都不在正式 tag 上；vol04 一册混三个旧提交（a985daa/d0bce83/ef38b01）（设计 §2a-9）。vol01 产物 9587e67c 后判作废、按 v0.2.0 等价 cfa5edce 重落（各册产物cv版本登记.md）。
- 人裁进库改 human_verdicts_fingerprint → 所有共用库的册 seed_admit 过期；10-19 20:31 一次 db sync 让 vol04–10 全 stale、R1 不过（重跑 README「10-19 夜」）。钉 glyph_pin 可避免，但 M8 基线全未钉。
- 新开关缺省值让旧册判「参数变了」：v0.4.6 row_segment（#238 修）；冻结 1a 误报 v0.4.7 修（文本交接）。
- 合进已发版 rc 分支的 PR 丢失：#184/#192（v0.3.5）靠 #206 补回 rc/v0.4.5；#242/#253/#260/#263 靠 #265 补回 rc/v0.4.8（domain/CV/经验.md；M8 复盘）。
- 两份版本号规矩冲突：AT 定稿「默认输出变＝MAJOR」vs cv 仓版本号规矩（GUJI-579 §0-4）。
- `--params` 在 `--jobs>1` 时被丢、指纹却记 override（Mila 交接）。
- 反馈模块不进 code_deps：改 bindings.py 会悄悄改 seed_admit 行为、指纹不变（GUJI-579）。
- 环境缺件致假 stale：没装 torch → row_segment 裁判指纹空串；没建 glyph.db → status 建 0 字节库（GUJI-556 README）。glyph_match 的 db_path 进 params_hash、换库只报漂移要 --force（开书手册 §7）。
- 包标签 cvunknown（浅克隆读不到 tag）（vol05 实验记录）。
- 导出器 char.json version 恒 0.1.0，出补丁前要改回线上版本再 bump_original（重跑 README）。
- 语料库 c1 清单与文件对不上 → 升 c2（vol06–10 实验记录）。
- 出口检查前必须 `guji db sync` → `guji status <册> --pages all`；Step1 在 cv 改 border_detect 前跑的要补跑（vol09 261 页全判过期）。

### 3.2 数据同步
- 中心库前：并发写丢事件（并行分工 §一）；`guji store commit` 会把整个工作树一起提交；store check「31 个文件」是预览差（GUJI-543 交接 §八、CV 经验）；服务器正式库 glyph.db 可能比 git 旧（设计 §8）；decisions.jsonl 10-18 新增 29 行只在服务器（GUJI-586 README）。
- 沙箱写的 not_a_char 未进正式排除名单，5 格回待审（设计 §5.2-2，GUJI-364）。
- 中心库后：本机 db sync 443 桥连不上，vol02 64 条事件滞留材料目录（文本交接 10-20）；db sync 在册 yaml 被别人改过时冲突（vol01 交接）；R2 缺图 404／121 张锚图（vol07/vol09 实验记录）；改过文件没推 → close-check 第 8 项不过（vol08）。
- book-text 并行 PR 同改 CHANGES.md 冲突，须串行合（重跑 README）；book-text partial clone 只更新 FETCH_HEAD（Lucian 交接）。
- guji-workspace 旧布局检出不能 db migrate（会改它），须新建空工作区目录＋.central.json（vol01 18 列交接）。
- 产物只在个人沙箱：562 归档包在 Eamon 沙箱一度是唯一硬卡点；vol01 无 pack（`pack list` 为空），真源曾在「用户本地」。

### 3.3 切分缺陷
- 整页误跳过：vol06 p88、vol07 p90（卷末叶判封面／书签）→ cv#217 body_pages。
- 整列漏切／切偏：vol05 p55、p123（漏界行）；vol04 p80（假竖线，38 字）；vol08 p2、p47（列界错位）→ cv#218 网格模式；vol04 p63（右框只下 1/3 有墨）→ cv#219。
- IA 四联叶裁偏：vol04 p216–218、vol07 p128/130 各丢一整列或多两列；vol09 p258–261 裁得对；按原图在版心重裁（guji-workspace#13、cv#221，用户 10-19 同意替换原图）。
- 三道闸、2c、2d、R2、collate 都拦不住整列问题；colgap.py、widthscan.py 是线程工具，**在 AT 与 CV 仓都找不到这两个脚本**（find 实测）。
- 夹注双行切分是 vol04–06 最集中一类（vol06 12 列）；抬头字在版框上方漏切；一字切两三格；列首/末「一」与版框线互判；空白叶 row_segment_gate「DP 无解」须写异常表才过 R2；collect_exit 异常表行号须纯数字。
- close-check 第 12 项只查报告文件在不在，旧报告也能过 → 收尾先 `guji export md`、`guji collate`。
- vol01 p196 整页切坏（闸2 格距下界）→ v0.3.2 period_prior_pages；vol01 18 列仍待重切。
- layout_prior 试验：273→256，但正文 4 列变坏（抬头字、低起列）（vol04 实验记录）。
- 历史评测：Step2 列矫正命中 62.8%、Step3 格线 ±3px 30%（09-30 云端评测基线）。

### 3.4 字形库
- 异体码位混用（蒙/𫎇、彞/彝、呂/吕、刊/刋…）：M8 各册「放行字变」大半是这类，GUJI-626 未定 → 所有新基线不标 main（WS/experiments；domain/CV/交接/vol04异体码位 已交 M7，用户裁 44/89 堆）。
- 带字体域库约 3.09 GB，glyph_match 峰值 3.73 GB、rare_candidates 4.3 GB、seed_admit 单进程可到 6.6 GB；别并跑两册 seed_admit（OOM）（Owen 交接、重跑 README）。
- 重建用 `glyph-db rebuild --no-replay`（默认重放缺图静默跳过 vol01 656/676）；算绑定前先 cache warm（缺图把 3000 多条老裁决判 unanchored）（设计 §8 v0.8）。
- 遮挡块表里的格 glyphdb_admit 不入库（vol04:3:3:3「𩔖」）。
- 字形库互查闸 vol01 退出码 3（23 个 human/align 离群未交代）（GUJI-543 交接 §十）。
- 库缺字成批作 □（vol05「巻」）；圈号○/✕ 整理本不录、库无。

### 3.5 人裁回流
- cell_review 只是意见，H 道转 confirm/seg_defect 才是裁决；H 道只由 Eliot 写，Eldon 写权已用完（交接清单 §六）。
- 无锚老裁决重跑切分一律不采信（vol01 682 条）；vol02/03 补精校前须补锚。
- 绑定表 backfill「旧压新」：vol02 27 格新裁被丢、rebound 跨格；R1（新事件取代旧）、R3（rebound 加闸）在 cv#110，开关 GUJI_BINDINGS_STRICT 缺省关（Eldon 交接）。
- vol02 在 v0.4.6 重跑后掉 172 格人裁（122 格人裁字与机器同）（受控重跑方法论 §四）。
- 排除名单先于人裁：名单里的格有人裁字也出不了（vol02 124 格）（文本交接 10-20）。
- 快照后来一条人裁 → 要重跑 seed_admit 并重打快照，否则冻结 1a 报参数变（vol01 交接）。
- 审阅入口与写入必须同一版产物（锚按写入时现行产物算）。
- 人裁事件写法：`console.routers.feedback._api_events(EventsIn(... kind="confirm", consume=True))`；seg_defect 需 quality=truncated（vol01 交接）。
- override 缺口 5 项 cv 未合（GUJI-579 拆卡，计划 v0.4.0；Mila 10-21 12:00 给工时，设计 §5.3）。

### 3.6 机器与环境
- 云会话 4 核 15 GB；工具后台任务 30 分钟会被杀 → `setsid nohup … & disown`；机器重启悄悄杀后台任务；杀进程用 PID 别 pkill -f（CV 经验、重跑 README）。
- 新会话准备：bootstrap 47 秒；原图稀疏克隆约 30 秒；db pull 7分45秒（1.9 万张刻例图）；rare 索引冷建约 20 分（--jobs 4）→ pack fetch-index 约 4 秒；字体域导入约 11 分；整册产物 pack fetch 几十秒（受控重跑方法论 §七）。
- 服务器 43.162.109.111：2 vCPU、7.4 G、80 G 盘常 >90%；guji-batch.slice 3G；控制台 8640；09-30 起「搁置」但 10-17 仍在用（Owen 交接；OV/机器清单.md）。本地 Windows 5800X/32G/RTX3080。
- 云会话连库要 psycopg[binary]、websockets；Neon 走 443 桥（vol01 18 列交接）。

### 3.7 协作
- 账号 A/B 互叫不醒；A 侧额度见底整线交接（10-17）；转述不算用户批准；师/所写入收到三条互相矛盾转述（交接清单 §五）；会话地址在名册查不到（§十）。
- 执行员 IDLE 数十轮「防闲置自检」（队列.md 10-17）——推测：空耗额度。
- 卡做完不关、151 个过期分支（M8 复盘）。
- 范围两次变：M8 中途改只做 4–10 册（1–3 交另一 Project），10-20 用户又定 1–3 册不再整理；vol01 18 列重切三易其手仍无人领。
- vol01 1.0.0 在重切清单未修时放行，违背用户 10-19 R6 规矩，事后「保留 1.0.0、补重切」（vol01 交接）。
- 同一工作区两会话 `git commit` 带走对方暂存（数据边界 §8-7）。
- 子对话结论写 Jira、长文档只放链接、rc 分支＋缺省关并行发 PATCH、取消 PR CI 改本地 local_check（M8 复盘「做得好的」）。

---

## 4. 开一本新书（非四庫總目）

- OV/项目进展/新书整理/开书手册.md（09-28，部分过期：服务器导入、overview issue 工作流都已废）：全新书前置链＝只读调研 → 立 Book（book-index draft，目录总管 promote）→ 选影像源（单半叶、无水印、字格接近）→ 选整理本（逐字比对定准确率）→ 先下 10–20 册测试集 → 沙箱试跑 → 冷启动策略（空库对齐恒 0 全落人审；借库只当候选不进本书库；关 context∧diff）；主链＝Step0 页面预检拆页 → 书 yaml 标定 bottom_gap/period_prior → Step1–4 → Step5–7 → 体检表 → 放行抽检（Clopper-Pearson 上界）→ 人审 → 入库自举 → Step9 → 回传。判准：全新书人审率过高停扩量。
- 全唐文（qtw-draft）：09-27 用户令暂停扩量（借四庫库后人审率 26.72%/26.02%）；测试集 23 件约 356 MB；Kanripo 整理本对影像 99.30%。WS 仓有 `qtw-draft/`。
- 北行日錄（988g7gsqhd，bxgb）：已整理完、冻结成全书测试集（并行分工 §3.3½）；设计 §9 写「待查进度后归段」。
- guji-workspace README：先有 book-index ID 再开工；目录名 `<id>-<书名>`；整完即删；10-19 起只存原图。
- 路线图 v3（10-13）：M3＝四庫總目 40 册文本；「全唐文、四庫全书整理：四庫總目整理完成之后」；社区校对等整理好几册再开。
- **guji-workspace 里四庫總目只有 vol01–vol10 原图**（data_full/zongmu 实测）；没找到 vol11–40 的下载或书单。
- 整理 目标.md 长期 4：「开一本新书＝照 runbook 建工作区、配 books/*.yaml、云端出包、看图复核、Step9 交付」；长期 5：全唐文在四庫流程稳定后再开、先用自有字形库。
- **没有找到 10-17 之后的、针对非四庫總目新书的流程或书单**。

---

## 5. 结构性问题与建议（多为推测）

1. **粗校出口口径散在多处、互有缺口**：设计 R1–R6＋cv close-check 2c/2d；collect_exit.py 只做 R1–R5；R6 靠线程工具 colgap/widthscan，两仓都没有提交。→ 建议把 R6 检查进 cv（widthscan 可在 Step1 后跑，最便宜），close-check 粗校档一条命令覆盖 R1–R6＋2c/2d。
2. **cv 仓 runbook 依赖 ai-team 脚本**：pending_list.py、alt_build.py、sprite_build.py、ex_build.py、decision_build.py 都在 AT/team/整理/，cv runbook 直接引用（CV/doc/runbook/整理一册书.md:275-281）。与 10-20「长期文档/工具进资源仓」相左 → 建议迁入 cv scripts/zhengli/。
3. **「每册固定 cv 正式 tag」在实践中没做到**：vol04–10 跑在 rc 分支未打 tag 的提交上，一册内混多提交（vol07 1bdf412/448d582/2a23683/568d1c2）；靠 #243 混跑口径兜底。设计 §2a 未同步。→ M9 要明确：粗校开工钉什么（tag？rc？），册 yaml cv_version 写什么，混跑何时允许。
4. **同一册的「当前数字」没有单一真源**：vol04 有 6 个以上不同的待审数；遮挡 272 vs 43 口径不清；vol04 new-glyphs 记录结论与结果表矛盾；cv 版本登记表停在 10-17。→ 建议每册一行台账（中心库或 Jira），由脚本从 close-check/experiments 生成。
5. **book-text、待审单与最新基线脱节**：M8 新基线（vol09 399、vol10 292 …）未标 main、未回写 book-text 和中心库待审单；人审若按旧待审单做，会裁到已被机器放行或已改字的格（推测）。GUJI-626 是共同卡点。
6. **人裁指纹耦合**：任何会话 db sync 都让所有草稿册 seed_admit 过期；glyph_pin 机制已有但没用。→ 粗校期钉 glyph_pin，攒批升号。
7. **0.1.0 判据偏松／与 1.0.0 边界不清**：R3 不卡出口（vol08 1.84% 照出）；零散切分问题推给 1.0.0 前，但 vol01 的例子显示 1.0.0 时又被放行、事后补。→ 建议把「重切清单清零」作为进入精校前或 1.0.0 的硬闸，并让 close-check 机器判。
8. **override 缺口仍未合**（GUJI-579），粗校期遇整列/页型问题只能靠册 yaml 参数（column_grid_pages、body_pages）或改原图；补格/删格无事件。
9. **新书路径缺现行文档**：开书手册停在 09-28 服务器时代；没有书单；四庫 vol11–40 原图未下载。若 M9 范围含「找到一册书」，需先补「选书/立 Book/下载/Step0 预检」现行版（推测应放 cv doc/runbook）。
10. **数据卡在本机或沙箱的风险**：vol02 64 条事件、vol01 无 pack、562 包曾只在沙箱。→ 每步「产出物必须入中心库或 R2 才算完成」写进验收。
11. **协作成本**：多次交接、额度、转述冲突、IDLE 自检。→ M9 流程最好一个线程持一册跑批位到 0.1.0，减少交接。
