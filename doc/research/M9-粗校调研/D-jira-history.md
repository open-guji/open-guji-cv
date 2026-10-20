# D. Jira 历史笔记（M8→M9 相关卡）

只读调研，2026-10-20。数据源：Jira GUJI（cloudId 62b93136…），各卡描述＋全部评论。时间均 PDT。
注意：服务器 43.162.109.111 时钟 UTC+8，多条评论把服务器时间误写成 PDT 后又更正（一个反复出现的坑）。

## GUJI-636 M9 平台粗校流程梳理（待办，0 评论）
用户原话要点：细化「找到一册书→跑整个 pipeline→结果上传中心库等→文本整理到 v0.1→给出需人审数据」。1–10 册已测，效果不错。
- 性能已有专家专做，M9 不具体研究，但要想好"要做什么"交给专家。
- 结果存哪：哪些进中心数据库，哪些放 Cloudflare（R2）。
- 目标持续降人审率；多个方向专家负责内容；M9 帮大家把结果整理到一起，定"哪些结果给谁反馈"。
- 流程脚本在哪跑、什么顺序、"跑一段→提质量→再跑下一段"的节奏怎么控。

## GUJI-567 M8 3步整理流程（已完成，5 评论）
- 10-18 经理：拆 33 张任务 GUJI-568～600，编号 M8·1.1～7.4（7 个工作包）。旧卡 554/555/558/560/561/562 关闭指向新卡；548–553、556、557、559 已完成；525、536、541 保留。用户同意：旧员工不再用，全在项目内由子对话执行；glyph_audit 选口径(b)；首本 1.0.0 选 vol01；GUJI-543 只管设计稿。
- 10-17 18:33 Owen 服务器现状（43.162.109.111）：根盘 80G 用 73G **剩 7.2G（92%）**，低水位 4G。~/guji-workspace 22G（四库总目工作区 96mid1ogzk 13G、北行日錄 988g7gsqhd 2.7G…），~/archive 7.7G，~/sandbox 5.9G，open-guji-cv 克隆 7.3G。内存 7557M 总，可用 4909M，2 核。常驻：cv 控制台 :8640（674M，guji-cv-console.service），两个 claude --resume（各 410M），caddy、claude-relay。
  - 正式 glyph.db（四库总目）**约 2.9G**（3086811136 B），5 个来源（v1、v2、vol01、font:jigmo、font:iming），173940 实例；旁边多份 bak（pre-admit3 2.9G、pre-font 232M…）。北行日錄 glyph.db 1.0G。导入字体域使库从 ~232M 涨到 2.9G。
- 10-19 进度：工作包 8（中心库）8.1–8.5 完成；8.7 写入切换完成（用户 10-19 定），guji-workspace **冻结在 6bef1ada**，数据改走 cv rc/v0.3.5 的 `guji db pull/push`；8.6 定时同步取消。vol01：p196 已修，0.1.2 上线（book-text#172，GUJI-622）；cv v0.3.0 对 vol01 差异为 0（GUJI-581）。
- **10-19 M8 收尾**：vol01 出 1.0.0；中心库（Neon＋Worker＋R2）上线；vol04–10 在受控重跑下各有基线入 R2（**vol09 人审 489→399、vol10 312→292**）。摘出 Epic 未关的卡：vol01–03 相关（571、583、584、594–596、598、599、624）、574、575、579、589、610；vol09 13 格放行字对图另开 GUJI-633。复盘：ai-team 通用/里程碑执行经验.md。遗留：151 个过期远端分支交 Ops 删。

## GUJI-525 vol01 待审上服务器审阅平台（已完成/被取代，43 评论）
- 底子 4324e4b 交付态：24401 格＝放行 23889、排除 222、待审 290；去 p196(37)、p205(17)＝236。待审原因：ctx_garble_shape/库里没有此字约 42、occluded 16、己已巳 7。
- 现网工作区 siku-zongmu vol01 当时待审 **1534**（口径对不上），另起沙箱 vol01-4324e4b。
- 平台"缺口A"：排除格里旧人裁失效的会被放回并预勾；实际多出 99 格（因沙箱绑定表按新切图重算，旧裁绑不上）。最终 357 条/350 格＝待审 236＋排除 114。构成：confirm 295、seg_defect 42(+2)、not_a_char 4、damaged 1、needs_review 7。用户约 45–50 分钟（每张 10–12 秒）。
- 切坏 44 格，31 格集中在职名页 p89–132（双行小注被当正文切）→ GUJI-536。
- **性能问题（审阅平台）**：载入清单 8 格冷启动 36.6 秒；cProfile：decided_view→book_bindings 9.4s，load_pipeline 522 次/load_book 175 次，yaml 解析 697 次共 6.5s；EventLog.read 534 次、pydantic 校验 6.2 万条 2.2s。PR #68 后冷启动 3.4s；全册按页冷启动 23.7s、热 4.5s（siku-zongmu 事件 1.47 万条）。前端重复请求（每敲一字发一次 cards）→ #70–#73 修；#74–#76 余项。
- 175:1:10 用户定「无字」但产物放行成「一」→ GUJI-415 回放纠正。
- 10-17 Eldon/Owen 复核：rev-64c4 工作区 vol01 待审 63（可见 34＋切线闸挡 29），p196 占 36；去 p196 剩 27（23 仍待审＋4 新增）。n_auto 24093、n_excluded 245、n_review 63。10:7:10 被切线闸挡（7:11 有 6 种切法待 review）。
- 平台无"服务端载入名单"，页范围存审阅人浏览器 localStorage → 摘 p196 只能靠审阅人填页范围 `1-195,197-204,206`。
- H 道原则（Eliot）：不写假"人裁"事件来摘队列（会污染对账）。
- 10-18 关闭：被 GUJI-573 及 589–593 取代。
- 问题模式：同一册多个工作区/沙箱（siku-zongmu、vol01-4324e4b、rev-64c4）待审数各异（1534/290/63/2085 快照），口径混乱；时区误写反复。

## GUJI-536 44 格切坏诊断：按分型出修法（**待办**，4 评论）
- 来源 GUJI-525：用户标 seg_defect 42 格＋p10:7:10/11 共 44 格（vol01）。不改 cv，诊断＋方案；验收口径：改动页外 vol01–10 字节差异 0。关联 #61 夹注 a/b、#53 窄对合并、p196 column_gate_period_edge.diff、PR-B（GUJI-47）。
- 10-17 Eldon（B 号备用团队）中间结果：
  - ⚠ **沙箱缺 torch 会静默退回旧切缝规则，框会变**（装 torch 后 row_segment sha256 与事件锚点逐位相同）。
  - 21 页重放：16 页 sha 一致；p89/p105/p107 只差 ±4–16px（cell_shrink）；p90、p184 实质不同（旧格号在现 main 不存在），需当时代码重放。
  - 分型：A 夹注双行并一格 10；A′ 夹注已拆 a/b 但分界不对 7（A+A′=17，职名页 p89–105，夹注列判定问题）；B 单字切碎/碎片 16；C 两字并一格/正文粘旁注 7；D 页首框边 boundary_ink 4。B/C/D 27 格不是整页问题。
  - 下一步（补丁沙箱重放、每型修法）**未见后续**，卡仍待办。M8 收尾时 536 未列入摘出名单（推测：被 622/579/623 吸收或悬空）。

## GUJI-541 定稿后增量修订流程设计（已完成，21 评论）
- 结论：下游一律按**格号**挂（不按字序/字符串）；格号变必须有「旧→新」对照表（Eliot 的 `team/整理/GUJI-541/revision_cells.py`，diff 模式按框配对，输出 char/state/geom/moved/split/merge/added/removed/shift 行）。
- 修订四类：A 改字、B 放行态变、C 重切（格号变）、D 整页补入。修订编号 `<册>-r<n>`（vol01-r0 为基线），对照表 `<册>-r<n-1>_to_r<n>` 长期保存。
- 实测：vol01 现行产物对 4324e4b：未压缩 5661 行，3074 格 moved 压成 403 行 shift；其中 **307 格框对上了字却不同**（多在职名页 p89–132）。用户两批裁决＋505：351 行，下游出字有变 246 格（待审→放行 190、待审→排除 46、排除格人给字 9、放行改字 1）。
- 前提（Eliot）：diff 需要旧版定稿 products，products 不进 git、服务器/容器会丢 → 每次定稿要打快照包（→ 后来 GUJI-559 自动快照）。
- GUJI-543 新流程：标点、专名等 1.0.0 之后才开工；0.x 不得有 punct/entity（book-text#148 F-OV-04/06）。0.1.x 阶段修订只需对照表、重出 pending.json、重挂公众意见（精校页意见带 rev 按格号记，每日导入要映射，GUJI-552）。
- punct：002.punct.json 6774 条 source=glm 6463/rule 158/claude 153，无 human:*；写入约定：人工校订落盘 source 改 `human:<人>`。
- 专名：book-text#163 migrate_anchors.py＋模拟（册002 1739 条/人判 550、册003 888 条/人判 307，人判丢失 0）。book-text#149 F-OV-02 伴生层同版本也核锚点。
- 遗留：真实 vol02/03 批次实测、标点线迁移后补。

## GUJI-554 P1-1 CV 版本：首个正式 tag＋cv_version 护栏＋rerun --stale＋override 缺口（已关闭＝被 574–580 取代，14 评论）
- 出自 GUJI-543 §13 P1。负责 Mila（协 Owen、Ethan、Eliot）。
- Ethan：「复核一致」口径要写死：19 步 code_hash 逐位＋seed_admit params_hash（需钉标准字形库 ws da2b5ff4d＋rebuild --no-replay，human_fingerprint 0683d128f1e7a4a5），否则 hash 随字形库漂移；cv_version 建议只进产物元数据、不进指纹（进了 tag 一打十册全过期）。
- 服务器 2 核跑不了整册 → 整册复核在 Ethan 云端沙箱跑。
- tag 争议：规矩 0.x 阶段 code_hash 变才升 MINOR；实测 c7c2c4a9 与 cv-v0.1.0（26657f84）19 步 code_hash 逐位相同（窗口甲代码早已在树里）。最终仍打 **v0.2.0**（tag 对象 f5630ee4 → main 4a9388ac，公开 Release，被自动权限拦一次后用户放行）。19 步 code_hash 基线：seed_admit c8f497bf23b3e708、group_decide dede73c401d3987d。
- vol01 已按 v0.2.0 等价重落（cv main cfa5edce，旧 9587e67c 作废），book-text#161 同步 pending 的 cv_version/cv_commit。
- 规矩：以后每合一个 PR 打 tag（Mila/CV 登记 code_hash＋版本号，Owen 打），只 MINOR 建 Release。
- Mila 10-17 巡检：cv#101/#102 指纹已核，统一窗口合并（前提 vol01/vol04 验证过）；夹注方案 A cv#107 draft 缺省关，只 seed_admit 指纹变（c8f497bf→e28112ad）；vol02 backfill R1+R3：R3 只新增约 1 格待审（75:4:21）；R2（10-02 新裁补锚）Eliot 窗口内做。
- 10-17 Mila 收工（用户决定整理线交另一对话）；交接 ai-team team/CV/交接-Mila至备用团队-10-17.md（d11266d）。

## GUJI-555 P1-2 重跑各册：首个 tag 下整册重跑，vol04 第一本完整走粗校（已完成，**144 评论**）
### 分工与环境（10-16）
- 范围：四库总目 vol01–10（北行日录、qtw 不算）。分册：Ethan 云端跑 vol02/03/05/06（后串行 vol03→vol02→vol05→vol06），Owen 服务器跑 vol04、vol07–10，Lucian 对 vol04 走粗校。
- **正式 products 真源**在用户本地 Windows `D:\workspace\guji-workspace\<书>\products\`（不进 git，只用户能进）。服务器 products 是 09-30 搁置后的备份（四库 vol01–10 共 1010M，vol01 最近 10-13，其余停 09-27～30）。服务器快照 `/home/sheldon/archive/products-1017/products-siku.tar` 959M 等。用户 10-16 定：由 Owen 在服务器上跑（放开"服务器不跑重算"规矩），单进程 --jobs 1，guji-batch.slice。
- 云端会话：4 核 15G，磁盘剩约 4.5G（一册产物＋缓存约 1–2G，一次只能放一册）；字体域导入后 glyph.db 涨到约 3G → 磁盘冲突；删 glyph.db.old1009（2.9G）被会话权限分类器拦（不可逆删除），需用户放行。
- 字形库口径：ws 标准库 `glyph-db rebuild --no-replay`；human_fingerprint 从 0683d128f1e7a4a5 → **48a5d599b9dd566e**（ws ee5146442，18480 实例；Eliot 10-16 把服务器 glyph_store 还原 git HEAD、删 87 个污染文件、重建）。replay 依赖 char_patch 缓存，缓存为空静默跳过 → 云端与服务器结果会不同。
### vol01 服务器重落（10-16 23:09–23:27，seed_admit 一步 206 页 19 分钟）
- cv cfa5edce、ws ee5146442，yaml 带 shadow_veto:true/shadow_conf 0.8。params_hash 206 页全 8ed5eb04000d1c01；19 步 code_hash 与参考 fp_9587e67c 全一致。
- relanding_diff 退出码 3（触发系统性阈值）：154/206 页变，格数 24672 不变；**待审→放行 278**（human 155、iron 123）；**放行→待审 587**（context 488、match_ref 79…）；**放行字被改 30 格**（判读页要求 0）。
- 原因：重落前产物是 09-27 旧一代（code 32b9c2b/54d08d3，params 62aff2a7 无法复现——缺当天排除名单、台账、feedback），比 10-09「四库标准开关批 v1」早一代（缺 50 个字段：context_guard 族、iron 护栏、lane_*、shadow_veto…）。488 格 context 下调＝护栏首次落地（shadow 只差 1 格），422/488 在职名页 p89–132。按"换代"记，不算回归。
- 12 格「人裁放行→机判改字」：9 格是 9 月旧人裁事件无锚（unanchored）、挂邻格键，rekey 后回到真格（新结果对）；58:8:-1、133:5:1 glyph.db 里人裁标签「大」实为「天」（错的人裁标签会污染放行，Eliot 处理）。
- iron 新放行 123 格（105 在职名页）：两次抽 20 格，Eliot 16 对 4 不确定，Owen 19 对 1 错（109:2:2 iron 判口实为日；整理本与 iron 同错，闸结构抓不到）。口径「iron 新放行误放应为 0」——不扩大抽样不加护栏，个别人裁修（list:vol01-iron-recheck）。
- p109 第 2 列局部多切碎片（日上半、居劈两半）属职名页上游切线问题。
- runbook 改进建议（Ethan，Mila 同意只改 doc PR）：S6 加 rebuild --no-replay 并核 human_fingerprint；新增「重落/重跑已交付册」一节（products_snapshot → manifest_cmp → relanding_diff）；S5 写对 `guji step` 用法（无 --from/--to/-b）；脚本归位（products_snapshot/manifest_cmp/relanding_diff 在 ws 分支 claude/relanding-cmds-ethan，dump_params/fp_dump 在 ai-team/overview）→ 移入 cv scripts/；S1 新 kind cell_review 旧 cv 校验整批报错。
### vol04 服务器整册重跑（v0.2.0 4a9388ac，ws ee5146442，221 页）
- 10-17 02:41 开跑 `pipeline keben_body_v2 vol04 --to seed_admit --pages all --jobs 1`。每页：page_survey 0.0s、border_detect 1.4s、border_detect_gate 0.6s、column_warp 0.4s、column_gate 0.1s、row_segment 2.9s、cell_shrink 1.2s；前 8 步约 24 分钟；glyph_match 7.3s/页（03:05–03:34）。
- **rare_candidates 卡住**：进程内存涨到 3.0G 顶 guji-batch.slice MemoryHigh 3G，内存压力 82%、缺页 370 万次，每页 240 秒（35 页跑 1h40m）。外套 scope 无效——`enter_batch_slice()` 会 exec 回 slice；改带 `GUJI_NO_BATCH_SLICE=1` 自限 5G 后正常。**结论：服务器整册跑 rare_candidates 之后几步进程需 4～4.5G**。
- Maren：关 rare_candidates 开关会改 params_hash，须 Mila 定；不要为了跑通改开关。
- 05:41 跑完。快照 `snap/96mid1ogzk/vol04/20261017T1243`（ws 23676b12），13 步×221 页，2886 文件约 91MB；13 步 code_rev/params_hash 全一致；status 全新鲜。看图判错（vision_flag）待人审 **63 格**（报告项）。耗时：前 9 步约 53 分钟，align_ref→seed_admit 约 11.5 分钟（不算被卡的 rare）。
### vol03 云端（Ethan）
- 110 页，Step1–4 jobs 4，row_segment 约 1.1s/页，比 runbook 估 5s/页快。字体域导入（font:jigmo、font:iming 约 +3GB）受盘限。runbook S5 粗估：Step1–4 约 5s/页、Step5–7 约 25–30s/页（4 核）；vol02 188 页、vol03 110、vol05 188、vol06 150。
### vol04 重落前后对账＋粗校（10-17）
- 重落前 vol04 是 09-27～29 混杂产物（前 9 步 6 种 code_rev；seed_admit 只有 p1–30），只有 p3–30 共 28 页可比；格数前 4358、后 **34602**。待审→放行 174（rare_ref 72、match_ref 47、seal 24…）、放行→待审 23、放行字被改 42（35 格改判印章、7 格真改字）。按"换代"记。
- **内存真相**：rare_candidates 单步峰值仅 385MB/14.5s；吃内存的是 `pipeline` 单进程连跑多步累积（到 align_ref 后约 4.5G）。cv#92 `--isolate-steps` 后整册 39 分钟、3G slice 内跑完，各子进程峰值：page_survey 89M、border_detect 264M、column_warp 151M、row_segment 473M、cell_shrink 428M、glyph_match 390M（无字体域）、rare 376M、align_ref 1.34G、context_decide 1.64G、seed_admit 2.24G；13 步逐页 sha256 与单进程 0 差异。
- **带字体域**（glyph.db 约 3.09G，5 来源 173940 实例）：glyph_match 峰值 **3.73G**、17s/页（无字体域 7.3s）；rare_candidates 3.83G（vol03）/**4.31G**（vol02）；3G slice 跑不动（vol03 被压 3 小时只跑 2 页，耽误约 3.5h）。Emerson 分析：每例约 14.5KB（图块 4KB＋HOG 7KB），17.4 万例≈2.4G，`_feats` list 与 `_F` 矩阵双份再 +1.2G；省法 B1（`_feats` 换行视图）＋B2（fetchall 改流式），输出逐位不变但改 code_deps → glyph_match/seed_admit 指纹变 → 建议并窗口；后取消、交 Eldon。
- **服务器正式 glyph.db 原来没有字体域**（fonts:{}）→ vol04 10-17 那次 Step5–7 不带字体域，不符 runbook S6 标准。决定：0.1.0 不撤，统一窗口后带字体域重落。⚠ 导入字体域前后 **params_hash 不变**（ac7cbf33a3b25786）——指纹看不出带没带字体域。
- 字体域导入：jigmo 11m48s（requested 102998，入库 98682，缺 4316），iming 6m53s（入库 56778，缺 46220），峰值 RSS <160MB。字体来源 cv 仓 fonts/（git 跟踪）。export_store 跳过 kind='font'，不会当漂移。顺序必须先 rebuild 再导字体（rebuild 会洗掉字体域）；后来 Eldon 论证正式库可跳过 rebuild（rebuild 删库重建可能丢未导出人裁）。
- v0.2.1 tag（01ae158c→d5c84d8b），19 步 code_hash 同 v0.2.0。
- **Lucian vol04 粗校 R1–R5（05:43 起，约 1.5h）**：R1 过（13 步×221 页全新鲜）；R2 过（三道闸 3 页＋11 列失败，看图确认无正文）；R3 **待审 466/34523＝1.35%**（目标<1%，不挡）：其他 195、库缺字 90、遮挡 51、近形字 50、己已巳 32、整理本替换对齐 26、参照冲突 20、异体 2；看图判错 63。R4 过（异常表 15 行）；R5 close-check 只差「待审清零」→ **设计冲突**：粗校阶段 R5 永远过不了 → Maren 定加「粗校档」，cv#96 `close-check --tier rough`。
- 用时：R1 约 8 分钟（导入 53 秒＋重建字形库 128 秒）；R2 约 25 分钟；R4 约 25 分钟；R5 导出 16 秒＋close-check 131 秒。**最大卡点：引擎坐标 x 与原图 PNG 左右镜像（x'＝页宽−x）**；快照导入器无视 GUJI_PRODUCTS_DIR（cv#93 修）；容器盘 7G 低于 cv 抓取 10G 门槛（用 GUJI_FETCH_MIN_FREE_GB=3）。
- R3 根因（442 格）：近形字/库不确定 197（45%，真难点）；窄切 98（22%，p80 第5列 37、p217 第2列 36，伪竖线切窄大字列，GUJI-572）；夹注小字 46（10%，p216/p218）；印章/遮挡 38（p130 前 8 格被斑驳底纸误判遮挡）；库缺字 36；己已巳 27。约 40% 是 CV 几何/判据问题，修后待审率 1.35%→约 0.8%。
- 442 vs 466 差 24 格口径：12 格放行字但 vision_flag（cv#97 导出标 review:pending）、8 格印章区放行空字、4 格 p3 遮挡无字（runbook S17 文档说明，cv#98）。精校待审以控制台/close-check 队列为准，不以 proof.json 为全集。
- **book-text#162 vol04 0.1.0（proofing:true）10-17 10:58 合 main（fd4a5d39）**；版本口径 cv 0.2.0（4a9388ac）＋ws 快照 23676b12＋事件库 ee514644。CI 首轮红：index total_chapters 与 manifest chapters_total 需 3→4。网站发布由 Mason 线。vol04 先不开精校页（无 pending_file）。
- Emerson CV 产出：cv#101 窄切 merge_narrow_pair（缺省关，border_detect/gate/column_gate 3 步指纹变，vol04/vol07 开）；cv#102 occluded_rescue_ink（p130 遮挡 128→51；cell_shrink、seed_admit 变；vol03 p3 真印章页开了会误救）；cv#103 夹注诊断（31/40 是 nonchar_gate 因 rule_bar 撤回，方案 A seed_admit 参数）。老问题：CLI `--params` 在 `--jobs>1` 时被并行 worker 丢掉，但指纹记了覆盖值。
### vol03 / vol02（10-17）
- vol03：Ethan 云端 Step0–4（容器每小时左右被回收，进程被杀，靠指纹续跑），快照 snap/…/vol03/20261017T1324；Owen 服务器沙箱 Step5–7（带字体域，--isolate-steps，glyph_match 17s/页，合计约 48 分钟，不含被 slice 卡的 3.5h），快照 snap/96mid1ogzk/vol03/20261017T1825（6763d819）。收尾闸 1 格（39:8:3 元）＋人裁≠放行 2 格（旧裁"钉在移位格"）→ 用户在 v3cg-6763 格级审阅页亲裁，Eliot 写事件（4d6b7f5dc）。⚠ 裁决写入 glyph.db 后 human_fingerprint 48a5d599→7d7303d8，seed_admit params_hash 随之变，**只改 3 页导致另 107 页"过期：参数变了"→全册重算**。新快照 snap/v3cg-6763/vol03/20261017T2040（工作区 id 进了分支名）。
- `guji status` 不带 `--pages all` 默认只看 11 页（坑）。
- vol02：188 页，13 步一致；close-check **2b ✗：已定字没出字 82 格，人裁字≠放行字 58 格**，待审 108；快照 snap/96mid1ogzk/vol02/20261017T2040（99cca4df），带字体域；glyph_match→seed_admit 约 83 分钟。
- vol01 现状快照 snap/96mid1ogzk/vol01/20261017T1826 不是统一一代（seed_admit 10-17，上游 09-2x，无 page_survey，无字体域）。
- 正式库字体域导入流程（Eldon 定命令、Owen 执行、逐步核数；B 侧云会话不发服务器凭据）：步 0 基线 sources 3/instances 18480/exemplars 18397/human N₀ 4373/fingerprint 48a5d599；盘剩 11G。导入期间锁库，审字须停（控制台是共用服务，没人有权停 → 协调成本高）。
### 正式库字体域导入执行（10-17 13:48–14:30）＋vol02 2b 诊断
- 停控制台 8640（systemctl --user stop，Restart=always 不能杀）→ 备份三份 sha256 一致 → import jigmo 12m19s（峰值 158MB）→ iming 6m54s → 核数：sources 5、instances 173940（刻本 18480 不变）、N₀ 4373、fingerprint 48a5d599 不变；glyph.db 231915520→3086802944 B；**盘 11G→7.5G**。控制台停机约 45 分钟。
- `store check` 会把库导出到正式工作树再比 git → 库与真源不一致时会把真源写脏（Eliot 10-17 上午踩过）；这次 Owen 没看到提醒先跑了，结果无变化。store check 报「25 个文件有改动」＝库先于 git 真源的老差异。`guji store commit` 会把整个工作树其它未提交文件一并提交（坑）。
- **vol03 0.1.0**：Eamon 粗校 R3 待审 **0.07%**（13 格），R2/R4 过；本地 R1/R5 FAIL 因本地字形库缺 glyphdb_admit → human_fingerprint 不同 → seed_admit 110 页「参数变了」（环境假象）。带/不带字体域对照逐字节相同。book-text#167（方案 B：cv-proof 与 default/003 1.0.0 并存）合 5e025b6f；0.1.1 #168（p57「見矣」手补）1e9fba5c。
- **vol02 2b=82/58 诊断**：带/不带字体域 5 页 25 对产物逐字节相同；旧代码 4324e4b vs d5c84d8b 只 p3 两格多 doubts；切分 188 页没变。58 mismatch＝(a) **绑定表 backfill 丢新裁 27 格**（10-01/10-02 shiftfix/ctxfix 脚本批 anchor 只有 product_key 无 bbox → unanchored；unanchored 仅当 ts ≥ 现行 Step3 manifest 才采信，vol02 Step3 是 10-17 重写 → 新裁全丢，09-08～10 旧裁顶上；rebound 跨格整列移位）＝**真缺陷**；(b) shape↔规范字口径 16（埀/垂）；(c) 己已巳族 15。gaps 82 全是本就要人处理（p3 书题「欽定四庫全書總目卷」被判遮挡 8；excluded 5 格「已定字却被排除」）。
- 修法：R1 新事件取代同格旧事件、不可用回待审；R2 63 条 pk_only 补锚（追加 feedback/anchors，改 human_fingerprint→整册 seed_admit 重算，统一窗口 Eliot 执行）；R3 rebound 加闸（ctx=differ→review；整列同量偏移无旁证→review；vol02 只新增约 1 格待审）；2b 判等加规范字等价（只改 verdict_view）。jys 不算同字。
- 旧压新下界（真绑定表）：vol01 2、vol02 39、vol03 0。
- 用户亲确认写入：vol03 105:4:3 師、107:8:17 所入正式 glyph.db（7a05390fc）；**human_fingerprint 48a5d599→a0abb2dfac7c06b3 → vol01/02/03 seed_admit 全部过期**。vol04:3:3:3 𩔖 事件已落但遮挡格按规则不入库。
- 10-17 16:2x 各成员收工（用户决定整理线交另一对话）；21:32 Eliot 停工总结（用户令「停下来」）。GUJI-589 卡在服务器没有 CELLREVIEW_TOKEN（需用户本人发令牌）。
- 10-18 关闭：由 GUJI-581～585（M8·3.1～3.5）取代，「不代表剩余各册已重跑」。
- 服务器备份 glyph.db.bak-20261017-pre-admit3（3G）删除条件未满足；盘剩 18G（10-17 21:33）。

## GUJI-556 P1-3 粗校出口：R1–R5 一键出报告（已完成，11 评论）
- R1–R5 口径（ai-team team/整理/设计/文本整理三阶段流程.md §3.3）：R1 所有页所有步骤跑完、按固定 cv 指纹不过期（stale=0）；R2 三道闸每个失败列有去向（修/override/待审）；R3 人审率报出来，目标<1%，不卡出口但写原因；R4 异常清单成片问题都有结论；R5 导出过格式检查（close-check exit 0；后改 `--tier rough` 粗校档不计待审清零）。总判全 PASS（R3 不卡）才可出 0.1.0。
- 命令核对：`eval/rate_history.py` 不存在，改 `guji check rate`；`gate_summary` 无 CLI（gates/query.py）。
- 交付：Eamon 的 collect.py（ai-team team/整理/GUJI-556/）→ 移植 open-guji-cv#100（scripts/zhengli/）。vol04 对数一致。环境前提（缺则 R1 假 stale）：torch、sklearn 1.9.1、`glyph-db rebuild --no-borrow`。失败不静默（缺命令/超时/产物缺落 FAIL）。
- vol01：GitHub 上无 vol01 产物，现状快照非统一一代 → R1 如实 FAIL。
- 坑：rev-64c4 工作区字形库被改过（实例 18482 比正式库多 2）→ progress 显示 206 页 stale；close-check 110 秒没跑完被终止。

## GUJI-558 P1-5 自动检查：glyph_audit 口径、align_ref 差异、排除名单对账、F1 两类（已关闭→586–588，21 评论）
- align_diff.py（ai-team team/整理/GUJI-558/）：vol01 字位 23945，差异 1163＝同整理本 1081／定字异于整理本 63／无定字 15／待审 4。vol04 本机 align_ref 33869 字位、差异（replace）1292。
- F1 两类：decision v0.2（guji-format#19 f28cc6e3，book-text#153/#154）条目层加 reason（unclear/seg_bad/seg_recut/seg_missing_page）、route（recut/list/add_page，seg_* 必填）、route_ref。f1_stats.py 违规退出码 1。
- 排除名单对账 exclusion_reconcile.py（ai-team team/CV/GUJI-558/）：vol01 人裁应入 26、名单 25，无遗漏无多余，1 格原因不一致（53:2:17）。
- glyph_audit_gate.py：vol01 体检是 09-26 的（库已重建 18480）→ 过期；未交代强怀疑 194（挡）+50（不挡），已交代 2；多为 鐘/鍾、查/杳 近形/异体对 → 逐条人裁不现实。用户 10-18 定口径 (b)：**只挡同字离群（outlier）**。
- pending 的 why/cls（待审原因机器码）与 decision 的 reason/route 不重叠。

## GUJI-559 P1-6 快照：并 main 自动推 <册>-r<n>（已完成，17 评论）
- ai-team team/整理/GUJI-559/：snapshot_push.py（登记表 snapshots.tsv→校验→推 ws 别名分支 `snap/<册>-r<n>`，只做别名不复制数据，幂等，默认 dry-run）、check_changes.py（只读 CHANGES.md：带「→版本」且有快照哈希的行必须写 r 号和 cv commit 前 8 位）。
- 已推：snap/vol01-r1（e7f093a2，0.1.0 #150 cv 9587e67c）、snap/vol01-r2（5eb6fa04，0.1.1 #151）、snap/vol04-r1（23676b12，0.1.0 #162 cv 4a9388ac）。每次 --apply 写 ws 仓都要用户当面同意。
- 自动触发选方案 C（校验自动、推送人批）：book-text#166 check-changes CI（只读、非必需、仅 CHANGES.md 变动触发）；全自动（B 服务器定时，令牌不出服务器）等用户同意。登记表仍手填（可改为从 CHANGES 解析，低优先）。
- vol04 #162 CHANGES 漏写 r 号 → book-text#164 补。三项＝文本版本↔r 号↔cv 版本（设计 §7）。

## GUJI-560 P1-7 vol02/vol03 补锚→补精校（已关闭→594–596，5 评论）
- Thaddeus 收对照表（TSV 格式见 541）做册002/003 实体迁移；补锚要等首个 tag 下重跑产物（vol02 产物 cv 4324e4b、vol03 更早）。补锚前置事项在 GUJI-583（vol02 R2）。

## GUJI-563 M7 形近字优化算法（**待办，长篇故事，用户「我的关注」**，3 评论）
- 用户设计：先按字形识别归哪个形近字组；两类：异体字（走 IDS 结构拆分，如彝 6 异体都上中下，可只在本组几十个刻例上训小 U-Net 切分，每段二选一）、形近不同义（走上下文两层：L1 静态词组/正则（如 xx月xx【】→日）100% 确定才给字；L2 大模型、每组专用提示词）。上下文＝前后各 20 字，遇段首段尾停。每组指定解法（可两种）。
- Emerson 总设计 cv#104（草稿）`doc/design/M7-形近字优化算法-总设计.md`，v2 获用户批准：第一批四组＝yi_560（彝组，IDS）、日曰、己已巳、入人八（上下文两层）；L2 两家各跑一遍一致才给字；配置 config/groups/<组>/（ids.yaml、rules.yaml、prompt.md）；不改 Step、19 步 code_hash 不变；**接入 seed_admit 属 S2，等窗口**；项目独立，验收后再集成。
- 块 A 完成（groups/ids.py、IdsResolver、注册表 kind/solvers/config_dir、groups/context.py）；C2 切线页 42 格发用户点；下一步 C3 切分器、D 块 L1 词组挖掘。cv#106 muse m7 l2 结果已合；Dana 的 Gemini l2 结果在分支。
- 10-18：负责人改为本项目子对话；只取 vol01 样本；GUJI-534（形近字）并入。
- 与 M9 关系：己已巳（vol02 jys 15 格、vol04 R3 32/27 格）、彝组（GUJI-626 vol04 45 堆）都在 M7 范围；人审率中"近形字/库不确定"占 vol04 R3 45%。

## GUJI-571 [M8·1.4] vol03 seed_admit 重算复核（**待办**，2 评论）
- 库指纹 48a5d599→a0abb2df（師/所入库）。10-18 用户：師/所不重要、近期只跑 vol01 → 推后。GUJI-569 结论保留師/所。按用户 10-18 采纳的**冻结基线规矩**（ai-team PR #22 `domain/CV/规范/冻结基线与重跑分级.md`）：人裁进库导致的 seed_admit 过期只登记（L0）不重算。建议 GUJI-601 冻结模式落地后改为「vol03 登记冻结基线」并关闭。

## GUJI-574 [M8·2.2] vol04 验证（带字体域，从 border_detect 重落）（**待办**，1 评论）
- 用 book yaml（context_single_stroke_review: true），不用 --params；验收改动页外字节差 0。10-18 用户同意近期只跑 vol01 → 推后（原是统一窗口前提，已放宽）。

## GUJI-575 [M8·2.3] 核 19 步指纹后合并 cv#101/#102/#107/#109/#110（**待办**，1 评论）
- 工具 team/CV/工具-Eldon/fp19.py。10-18：**v0.3.0 已发，含 #101（窄对合并）**；#102（遮挡救回）、#107（夹注方案 A，基于旧 rc/v0.3.0）、#110 暂搁；#109 可进下一版。v0.3.0 相对 v0.2.1 有 4 步 code_hash 变：border_detect、border_detect_gate、column_gate、seed_admit。

## GUJI-576 [M8·2.4] 发下一个正式 cv tag 并登记（已完成，3 评论）
- 门：tag 发出前任何册不整册重跑。tag 一律 vX.Y.Z。
- 用户 10-18 定（冻结基线规矩，GUJI-601、ai-team PR #22）：**每个 cv 正式版附一份 L1 影响报告**——`guji exp run` 以各冻结册的发布快照为上游，只从 code_hash 变了的步跑到 seed_admit，报每册放行格变化数、待审格变化数；放行格变化 0 的册不重跑；服务器部分经 send.py 交 Owen/Eliot。
- v0.3.0（714b0a2）L1：vol01 206 页 seed_admit 与 v0.2.1 逐字节相同（差异 0）。云端沙箱跑，装 scikit-learn（vol01 开 shadow_veto，缺它**会悄悄关掉**）。seed_admit 新增 M7 开关 m7_groups/m7_l2_tables 缺省关。
- **v0.4.0**（main 9a8bd0b，对比 v0.3.5 34035c1，10-18 21:55）：只含 GUJI-609（字形库指纹改为各步实际读取内容的哈希）；seed_admit、rare_candidates code_hash 变（判定逻辑不变）；未冻结册这两步及下游要重算一次；冻结册 close-check 1a 对快照比较不受影响。全量测试 3204 过。
- 版本线：v0.2.0(4a9388ac)→v0.2.1(d5c84d8b)→v0.3.0(714b0a2，含 #101)→v0.3.1/v0.3.2(rerun --stale)→…→v0.3.5(34035c1，db pull/push)→v0.4.0(9a8bd0b)。

## GUJI-578 [M8·2.6] guji rerun --stale（已完成，2 评论）
- cv#125：`guji rerun <册> --stale` 只收集各步 manifest 显式 invalidated 的页，从最早一步起逐步跑，上游产物没变的页不往下传；**只因 cv 升版过期的页不跑**。支持 --dry-run/--pages/--to/--jobs/--json；过 cv 版本护栏（--allow-cv-mismatch）。随 v0.3.2 发。

## GUJI-579 [M8·2.7] override 缺口拆卡（**待办**，1 评论；子卡 618–621 均待办）
- 读 cv main 3930d46（v0.3.0）：设计 §5.3 的 5 个缺口都没合上。职名页已能用 `row_segment.roster_pages` 逐页写；「整列重切接 recrop」不对（recrop 是单格改 bbox），要另开事件。
- 子卡：618 A 整列重切 column_recut（14–18h）、619 B 逐页页型 page_type（6–8h）、620 C 补格/删格/并格 slot_edit（16–22h）、621 D 版框/列框坐标 border_offset/head_raise（8–12h，可砍）。合计 **44–62h**。顺序 A∥B→C→D，只改 column_warp、row_segment、border_detect_gate 三步 code_hash；MINOR，原计划 rc/v0.4.0（v0.4.0 实际只发了 609）。
- 跨卡风险：重跑要 torch，真页验收在服务器（经 send.py 交 Owen/Eliot）；**`feedback/*` 不进 code_deps，改绑定表会悄悄改 seed_admit**；override 落专用分片，不读评测金标。文档 ai-team PR #25 `team/CV/GUJI-579/override缺口拆卡.md`。
- 对 M9 的含义：切分缺陷（职名页夹注、p196 列距、p80/p217 窄切、p109 碎片）目前没有人工 override 通道，只能等代码修或手补阙文。

## GUJI-581 [M8·3.1] vol01 新 tag 下整册重跑（已完成，2 评论）
- 按冻结基线规矩不因 cv 升级整册重跑；v0.3.0 L1 差异 0 → 关闭，vol01 走 573→597。

## GUJI-582 [M8·3.2] vol04 重跑并补待审清单＋预裁图（已完成/被取代，2 评论）
- 10-18 用户：近期只重跑 vol01；方向：已出 0.1.0/1.0.0 的册一般不再整册重跑，只对需人审的格或后几步按需重跑。
- **10-19 收尾：本项目范围改为只做 4–10 册（1–3 册交其他项目）**。vol04 由「受控重跑」完成：**基线 v0.4.6-cujiao 设为 main**，实验 R1/R2 及三个对照包都在 R2（Cloudflare R2）；计划与记录见 guji-workspace 实验报告和 ai-team `domain/CV/规范/受控重跑方法论.md`。

## GUJI-583 [M8·3.3] vol02 重跑（含 R1+R3、R2 补锚 63 条）（**待办**，2 评论）
- R2 补锚改 human_fingerprint → seed_admit 重算，属冻结基线规矩 L2/L3；开跑前先按 L1 `guji exp` 看放行格变化数，只合并待审格改进，放行格改动走人裁事件。推后。（vol01–03 已交其他项目）

## GUJI-584 [M8·3.4] vol03 新 tag 下重跑（**待办**，2 评论）
- 改为先出 L1 影响报告；放行格变化 0 则只登记。推后。

## GUJI-585 [M8·3.5] vol05–vol10 登记排期（已完成，1 评论）
- 被「4-10册重跑计划」取代并执行完：**vol04、05 基线 v0.4.6-cujiao；vol06–10 基线 cv0.4.7p9-c2-g-82293e-baseline**，均已入 R2；**vol09 人审 489→399、vol10 312→292**；记录在 guji-workspace PR #21、#22。

## GUJI-586 [M8·4.1] glyph_audit 重跑体检，口径(b)出闸（已完成，2 评论）
- glyph_audit_gate.py 按 (b) 改好（ai-team 8b59a93）：只挡 human/align 通道未交代的 outlier；rival 只报告；退出码 0 过/3 不过/4 体检过期。
- vol01 体检重跑：`guji glyph-db selfcheck` **1740 秒（29 分钟）**，峰值约 0.5G；findings 731；本册相关 339（离群 26／近形对 313）；**未交代且挡出口 23**（human/align）、不挡 3；已交代 0（decisions.jsonl 仍是 09-26 老裁决）→ 23 个要用户在字形库页「体检」tab 裁。卡关闭但闸未过（推测：转入 597/1.0.0 前人裁）。

## GUJI-588 [M8·4.3] F1 两类单列（已完成，2 评论）
- cv 导出器不写 decision → 补生成器 ai-team team/整理/GUJI-588/decision_build.py（阙文/待审按最新用户 confirm 归类，seg_defect→②，待审无人裁→①）。
- vol01 服务器 dry-run：132 条＝② 切分类 93／① 看不出 39；**无候选 5 格**（52:2:1 71:6:16 74:1:3 75:3:3 89:7:9，09-06 seg_defect 格，align_ref 里根本没有这个格）。离线阙文 137 格＝用户 seg_defect 97＋待审无人裁 40。
- 待定口径：「看不出→不写事件」导致审过与没审分不出，F1「至少过一遍人」需审阅记录证明。

## GUJI-589 [M8·5.1] GUJI-552 真实导入前补验（读回/去重/限速/管理读）（**待办**，7 评论）
- 服务器**没有 CELLREVIEW_TOKEN**（需用户本人发）→ 站点四项复核（同格去重与覆盖、限流、管理员读取、回读）未做——这是卡仍待办的原因。
- vol01 pending（rev 001-r2）63 格＝23 格用户 10-16 已裁 seg_defect（未进 crop_exclusions）＋p196 36 格（不上公众页）＋**4 格真正待公众审**（9:7:17、10:7:16、90:1:3a、90:1:17a）。book-text#169 把 001.pending.json 收窄到 4 格。
- 绑定换号：90:2:1/90:2:2 的 seg_defect 事件被 rebound 一格。
- 公众意见空跑：数据在 `open-guji-core/guji-workspace-data` 分支 claude/web-opinions-vol01-1018 的 `96mid1ogzk-001-r2.jsonl`；收到 4 条，剔测试 2，真实 2。脚本修 2 处 bug（站点 ts 是毫秒整数；shown="□" 被当成与产物字不符）。⚠ triage 用 rev-64c4 快照，没有用户 10-16 的裁决 → 差点写出冲突 quality（**快照口径与正式事件不同步**）。
- 公众意见第一批（H-web-vol01-2026-10-18，guji-workspace#3）、第二批（用户本人投剩下 3 格，#4）都**不经服务器**，本机按 001-r2 快照重建后用引擎写入函数算锚点写事件。vol01 公众页 4 格全部有裁决。
- 公众页「看不清」记 choice=unsure，存档 feedback/web/，作为 F1「审过但看不出」记录。

## GUJI-597 [M8·7.1] 首本 1.0.0：vol01 逐条核 F1–F5（已完成，10 评论）
- F1 待审格至少过人；F2 自动检查过；F3 抽检暂不卡；F4 公众意见池清零；F5 固定 cv 版本下指纹不过期（冻结基线）。
- 用户定：vol01 剩余约 27 格待审**等公众回路**（AI 按公众意见落裁决，存疑才给用户）——后来用户直接投了。
- 用户 10-18：「有一整页都还没有切好，那是不能去升级到1.0.0的」→ p196 必须先重切、导出、新待审格审完（GUJI-622）。
- 排除名单只收非字（not_a_char/damaged），切坏 seg_defect 不进名单（--with-seg 口径未入 122/无人裁 65 是口径非漏）。「23 格补进排除名单」被误判后作废（流程里的误判传给用户→用户同意→再作废）。
- **vol01 0.1.3（book-text#173）**：□ 102→26，pending 4→0。原因：**9-07 人裁 seg_defect/damaged 按格位记，10-16 新切已切好，但旧裁决仍按排除挡住**，75 格显示 □；用户逐格看对照图，72 格写成 confirm（guji-workspace#5）。→ 流程漏洞「重切后旧 seg_defect 裁决应作废或转人复核」→ GUJI-623。
- **vol01 1.0.0（10-19，book-text #194 0.1.6 14 格改字、#199 1.0.0，b38df4bb）**：F1 待审 0；**66 格在重切清单上**（cv 切不对的列，字已**手改入文本**：p10:7、p89/90/101/105/107/119/130 职名表、p196），decision.json 为空；F2 close-check（cv rc/v0.4.7 4654191d）机器项全过（2c：□ 67 个都在重切清单；2d：对不上列 424 列全已交代）；F4 未处理 0；F5 冻结基线快照 snap/96mid1ogzk/vol01/20261019T2303，cv 0.4.5（004bc889），2678 文件，册 yaml 写 `freeze:`，中心库同步。人裁事件 139 条已进中心库（用户 10-19 定的 128 格＋9 切坏＋66:2:8 玉）。
- B 已修 v0.4.6 row_segment 缺省参数使冻结 1a 误报（rc/v0.4.7 #238）。
- 出口还差：通知标点、专名开工；归档 guji-workspace 这本书（GUJI-598）。
- 注意：1.0.0 文本含"手改入文本"的字（cv 切不对）→ 产物与文本存在人工分叉，后续重切要能对回（推测：依赖 541 修订对照表）。

## GUJI-598 [M8·7.2] 书影归档后的落点定论（原图 vs WebP）（**待办**，0 评论）
- 设计 §8：原图不进 git；IA 原图取回已在 vol03 演练通过；需定正式落点及 1-bit WebP 是否够用。无进展。与 M9「结果放哪（中心库 vs Cloudflare）」直接相关。

## GUJI-601 [M8·2.9] 冻结基线（已完成，3 评论）
- 用户 10-18 规矩（ai-team PR #22 `domain/CV/规范/冻结基线与重跑分级.md`）：到 0.1.0/1.0.0 的册登记冻结基线，不随 cv 升版重跑；告警按 stale_reason 分级，冻结册只报「快照被改」「册配置被改」。
- cv#124：册 yaml `freeze:`（at、cv_version、snapshot/manifest）；冻结册 close-check 1a 比对基线（产物变/缺/册配置变才 FAIL，只因 cv 升版过期记数不报，新人裁事件列明细）；`guji archive fetch <tag> --out`（dataset release 下载校验 sha256，实测 archive-96mid1ogzk-vol03-0.1.0-1：214.8MB，20737 项）。cv#123：manifest 写 cv_version/cv_commit。19 步 code_hash 不变，随 v0.3.2。

## GUJI-607 [M8·8.6] 只读镜像（git→中心库定时）（关闭＝不做，2 评论）
- 用户 10-19 决定写入直接切中心库，git 冻结在 6bef1ada，不再需要定时同步。

## GUJI-608 [M8·8.7] 写入切换：先写中心库（已完成，3 评论）
- 10-19 用户点「切」：guji-workspace 停写，最后提交 6bef1ada 灌进 **Neon main**：rev 1346→1356，verify 0 差异；**正式桶（R2）30,558 张图**。git 冻结只用来拿原图。
- cv rc/v0.3.5：`guji db pull -w <ws> --full`、`guji db push -w <ws>`：push 拿库锁先比版本号，拉取后有别人写过（导入、push、Worker events）整次拒绝；台账少行/整文件丢拒绝（--allow-delete 放行）；新图先经 Worker 传正式桶。无 GUJI_DATA_PG_DSN 时从 NEON_DATABASE_URL 自动起 443 桥。实测 qtw-draft 空目录 pull --full 还原 33 文件、6,506 张图，**约 7 分钟**。细则 cv doc/datastore.md 第六节。
- Worker `MAIN_WRITES_ENABLED="true"`（guji-workspace-data PR #6）。新规矩写进 ai-team `通用/中心库设计.md`、`process/子会话须知.md`。
- guji-workspace PR #12（main 3665a586）：workspace git 只留原图，数据全在中心库（verify rev 1378 零差异）。通知云服务器 Console/Ops 升 v0.4.0 后 `guji db migrate --dry-run`。

## GUJI-609 [M8·8.8] 指纹改用库内容哈希，字体域进指纹（已完成，1 评论）
- cv PR #172（rc/v0.4.0 9500acf）：指纹用各步实际读取内容的哈希而非 rev（rev 跨机器不同、未推的本地裁决无 rev、push 改 rev 不改内容）。seed_admit.human_fingerprint＝排序后的 (instance id, glyph char)；rare_candidates 增 db_font_fingerprint（来自 import-font 写的 font_manifests 表，不导出）；glyph_match 不变（软参数）。解决了"导入字体域前后 params_hash 不变"的问题。
- 冻结册不受影响；未冻结册两步过期一次、判定不变。全量 3204 过。

## GUJI-610 [M8·8.9] 国内通道：网站内容导出到 COS，国内意见入口转发中心库（**待办**，0 评论）
- 定时把网站内容从中心库导出静态文件到腾讯云 COS/EdgeOne；国内公众意见先进国内入口再转发 guji-data。国内页面不直接访问 Cloudflare/Neon。需国内网络实测。无进展。

## GUJI-611 [M8·8.10] 中心库备份与恢复演练（已完成，5 评论）
- Worker `/v1/backups`，备份在正式桶 `backup/<日期>/`。cv `python -m open_guji_cv.datastore backup`、`restore-check --endpoint`（cv #165）。首次演练：main rev 1356，**26 张表、189,964 行**；备份 27 文件 12MB 用时 31 秒；恢复到 ci 分支 39 秒，逐表一致。每日 02:52 备份保留 30 天，每周日恢复演练。
- `guji db sync -w <ws> [--watch N]`（cv #166）：pull+merge+push 一步；追加型台账双方新行都保留，其他文件双方都改则 SyncConflict。cv #167 删旧 git 同步脚本（glyph_store_sync.py、snapshot_glyph_store.py、store_merge.py）。v0.3.5 main 34035c1。
- 冻结后 guji-workspace 仍收到 #11（11 个 book yaml）→ 补导入中心库 rev 1378。guji-workspace #12 删 32,229 个中心库保管文件，加 `.central.json`。
- 后续 v0.4.1（拉图提速约 7 倍、锚图还原）、v0.4.2（push 删除检查覆盖锚图）。

## GUJI-618～621 579 子卡（均**待办**，0 评论）
- 618 A 整列重切 `column_recut`（14–18h，含 `guji events add` 底座约 4h）：几何由 column_warp._windows() 读，切法（period、n_slots、layout）由 row_segment 读。真页验收 vol01 p196 第 2/6/8 列 period=115 → 每列 21 格。需 torch，服务器经 send.py。
- 619 B 逐页页型 `page_type`（6–8h）：border_detect_gate 自动判型后读，记 flag「人定 X，原判 Y」；不读评测金标。风险：改成 skip 会让该页已有人裁全部失效。
- 620 C 补格/删格/并格 `slot_edit`（16–22h，含绑定表 4–6h）：第一版只支持正文格，夹注拒绝。风险：改 feedback/bindings.py 不进 code_deps，会悄悄改 seed_admit；文本侧要出旧→新格号对照（541 C 类）。
- 621 D 版框/列框 `border_offset`（只收 22 条带 abs 坐标的，206 条相对坐标不收）、`head_raise`（8–12h，可砍），册级开关缺省关。风险：这些分片同时是评测金标。

## GUJI-622 [M8·3.0] vol01 p196 整页切分缺陷修复（已完成，4 评论）
- 原因：p196 闸2 页级 period＝80px，卡在自相关窗口下界 int(115×0.7)；Step3 第 2/6/8 列「弹性 DP 无解」0 格。
- 修法：cv 闸2 加参数 `period_prior_pages`（缺省空，点名页直接用书级 period_prior）＋缺省关 `period_edge_fallback`；随 v0.3.2（cv#134）。补丁在 ai-team team/CV/GUJI-622/；全册整页扫描脚本 `whole_page_scan.py`（失败列、闸2 拒页、period 贴下界、列格数偏离）。
- **按用户要求改在云端做（服务器任务撤回）**：p196 云端单页重跑 column_warp→seed_admit，九列各 21 格，69 字全放行，待审 36→0。全册同类排查：整页级问题只有 p196。
- vol01 0.1.1→0.1.2（book-text#172，89b2bdb，只换 page 196）。close-check 要整册新鲜度，云端无正式整册产物没跑。
- 用时：10-17 22:05 开工 → 23:45 关卡，约 1h40m（从诊断现成到上线）。

## GUJI-623 重切后旧「切坏」裁决不作废，仍按格位挡住新切结果（**待办**，1 评论）
- vol01：9-07 人裁 seg_defect/damaged（批次 vol02-61-70-decide）按格位记；10-16 重切（001-r2）后格已切好、机器读出字，但 seed_admit 仍按 `excluded: human:seg_defect` 排除 → 75 格显示 □；用户手工逐格确认补上（guji-workspace#5，book-text#173 0.1.3）。
- 要修：一格重切后（bbox 或 content_sha 与裁决锚点不同），旧 seg_defect/damaged 裁决视为过期，放回 admit 闸重判，判不了进待审。vol02–04 需扫。注意 bbox_page 的 x 镜像。
- **同类第二例：字形库体检结果过期**（10-19）：用户在控制台体检页裁 vol01 离群卡，9 张「错得离谱」（64:3:4 卡上「懽」图是「誠」）——卡上字全是同列下一格的字。原因：findings.jsonl created_at 2026-09-26，vol01 刻例 09-27 按新切图重排编号，体检没重跑，控制台照样拿旧结果出卡。GUJI-586 闸挡的「23 个离群」也出自这份旧结果，需重算。要修：体检结果带字形库指纹，出卡前比对，不一致提示过期不出卡；glyph_audit_gate 同样。
- 模式：**派生结果（裁决、体检、绑定）不带上游指纹 → 上游重切/重排后静默错位**。

## GUJI-624 四庫總目 vol01 职名页阙文与错切：重切核字（**待办**，7 评论）
- 用户 10-19 线上指出职名阙文（「□□講起居院掌院□太子太保…」）。文本 0.1.4 全册剩 25 个 □，23 个在职名页 89–131；还有漏字、重字、字序颠倒（如 89:7「經□□日講居注官管吏吏刑部事太太太太…」）。
- **D 自承漏检**：align_ref 的 `coord_fallback`（格与整理本 N 字对不上）全册 **423 列**，64 列现文与整理本不同，分布 39 页，职名页占 40 列。0.1.0 闸门没看这个信号，GUJI-587 差异交代也只比逐格对上的字。
- **用户 10-19 23:07 拍板：0.1.0 和 1.0.0 放行硬项（各册适用）**：①每个 □ 进人审页或重切清单；②人审页加「切坏格」一类，附书影，直接录字；③和整理本对不上的列（coord_fallback）每列交代（重切/改字/写原因）。
- CV 窗口落地：close-check 新增 **2c**（□ 有去向：在 `--pending NNN.pending.json` 或 `feedback/lists/<册>-重切清单.tsv`）、**2d**（coord_fallback 每列在 `feedback/lists/<册>-对不上列交代.tsv` 或重切清单）；cv rc/v0.4.5（#199）；collect_exit.py 透传 --pending。kaiyuanguji-web#504（待审单 cls:"seg_defect" 显示「切坏格」，先给书影裁图）——当时未合。两张单在数据目录，随 `guji db sync` 进中心库。
- D 改字：book-text #179（文本 0.1.4→0.1.5，标点/实体 0.1.1→0.1.2），职名 26 列里 24 列改成整理本文字；按整理本行序重建双行小注格号，cord 在原列框内按行近似分格。**整理本≠真值**：95:3 原书「史夢琦」（现文「時」、整理本「𤦺」都错）；90:3 英廉整理本多三官衔；106:4 金士松保持。→ GUJI-240 book-index 人名档「史夢時」应改「史夢琦」。
- 423 列核完：拿文本和代字阁逐列本整列全文比，402 一字不差，21 列看原书图，16 列确认切图出错（抬头字出框没切到 32:4 實…；漏切「一」；一字切两格；框线碎片当字；目→自）。□ 25→0。交代表 425 行（一致 381、改字 40、说明 4）。「一致」＝整列全文能在逐列本找到同一行，不代表逐列对位核过。
- **中心库 Worker 429 / Cloudflare 1027：当天请求额度用完**（UTC 0 点重置），后用户升级数据服务才推上（rev 1509→1511）。
- 用户 10-18 规定：**服务器只做 tag 和 release**；1.0.0 由 D 在云端同步最新产物后自己重跑。
- 同步提示：vol01-cutline-split_char.jsonl 与 vol01-cutline.jsonl 有 14 个事件 id 重复，两份都入库。
- vol01 重跑对比：用户在「第一册重跑对比定字」页定 128 格＋9 切坏＋66:2:8＝139 条（H-rerun-diff-vol01-1019、H-rerun045-vol01-1019b），14 格改入 book-text #194。重跑 v0.4.5，冻结快照 20261019T2303。
- 卡仍待办：职名页"按 p196 办法重切"未做（文本已手改，cv 产物仍错）。

## GUJI-625 CV：四联叶拆页改为按版心界行定裁线（**待办**，0 评论，标签 CV/拆页）
- 四庫總目 IA「四联叶」（一张扫描四个半叶），拆页表 `doc/formats/samples/guji_page_v0.2/split_table_siku.json` 裁线没落在版心 → 右半叶丢一整列或多裁两列，Step1 切偏整列丢字。已发现：vol04 第 216 叶（页 216–219，IA 06061303）、vol07 第 128 叶（IA 06061306）、vol09 第 258 叶（IA 06061308）。这 9 张手工重裁（版心界行 ±8px），由线程「重跑 vol04–10」处理。
- 要做：拆页自动探测版心界行；拆完自检每半叶列数（9）和列宽偏离中位 ≤25%，不合格报出不悄悄交下游（参考线程工具 `widthscan.py`，读 border_detect 列宽已能报出这三张）；全书扫一遍。参考 ai-team `team/整理/重跑vol04-10/README.md`「整页、整列丢字」、vol04 异常表第 17 行。
- 对 M9：「找到一册书」环节的原图拆页质量没有自动闸。

## GUJI-626 第四册异体码位细判：彝组与 45 堆未裁（M8 交来，M7 子卡，**待办**，1 评论）
- vol04 r1 重跑产物同一异体组的格被拆到不同码位（彝组拆成 彛/彝/彞/𢑱/𢑴）。按图分堆，用户 10-20 裁 44/89 堆，其余交 M7。材料 ai-team `domain/CV/交接/vol04异体码位/`（README、img、cards.jsonl、verdicts.jsonl）。
- M7（Emerson）已回 m7_verdicts.jsonl（19a26bf）：57 堆＋12 单格给码位（NFC 归一，如 旣 U+65E3）；12 格 verdict="out" 码位待补审；彝组 3–5 堆为 𢑱；埤𡌨 统一为 埤，已写进各册 codepoints。M8 收回后写进第四册册配置并重跑（卡仍待办＝待落地）。

## GUJI-627 中心库数据两处不一致（**待办**，0 评论）——**直接挡 M9 第一步**
- 10-19 晚云端新容器给 siku-zongmu 跑 `guji db pull`、再跑 vol04 Step0–5a 测速（open-guji-cv PR #255 页级并行提速）时发现。
- ① **R2 缺 121 张锚图**（全部是 feedback/anchor_patches/，字形库刻例图不缺）：vol04 20、vol05 19、vol06 6、vol07 23、vol08 11、vol09 42；共 121/2205。`guji db pull` 第 124 张时 CentralError 404 → **整次拉取中止、什么都不落盘** → 任何新机器/新会话都拉不下这个工作区。猜测 GUJI-605 上传锚图漏传，或 608 切换后新锚图只进库没传 R2。建议补传＋materialize 缺图时报清、可选跳过。
- ② **语料库 v1 钉选漂移**：glyph_match 报 `CorpusDrift: 语料库 v1 的清单与当前文件不符（改了 2）：ws:config/groups/freq.json、ws:config/groups/l2/jys.json`（中心库 rev 10279）。要么 `guji corpus build` 出新版改钉，要么改回；现在只能 `GUJI_CORPUS_DRIFT=warn` 绕过。（推测：M7 的 jys/groups 改动写进了中心库但没 build 新语料版本——跨项目写同一份配置无协调。）
- 验收：新容器 pull 不加绕过能完整拉完；pipeline 到 glyph_match 不设 GUJI_CORPUS_DRIFT 能跑。

## GUJI-633 vol09 基线：13 个放行字变了的格对原图核对（**待办**，0 评论）
- vol09 在 cv0.4.7p9-c2-g-82293e-baseline 下人审 489→399，但 13 格放行字与旧基线不同未对原图确认。记录 guji-workspace #22、项目文件 受控重跑/vol09/。不属于 GUJI-567。

## 附：guji-workspace 实验记录（Jira GUJI-582/585/633 指向；open-guji/guji-workspace main `96mid1ogzk-…/experiments/<册>/<标签>.md`，PR #21/#22）
标签格式 `cv<版本>-c<语料库号>-g<字形库号>-<改动名>`；产物包 `guji products pack push/fetch`（存 R2）；方法 ai-team `domain/CV/规范/受控重跑方法论.md`、cv `doc/受控重跑.md`。各册 main 仍是 `v0.4.6-cujiao`（这些新包都"不标 main"）。
共同跑法：从 v0.4.6-cujiao 包起，切分 Step1–4 不动，`--from glyph_match --to seed_admit --force --isolate-steps --jobs 4`（glyph_match 字形库指纹是软参数，不加 --force 新库不生效）；人裁指纹 h1:3448:82293ec0aec56bf2；中心库 rev 11307。

| 册 | 页 | 格 | 送审 前→后 | 人审率 | 放行字变 | 包 | 关键耗时（分钟，最后一轮） | 备注 |
|---|---|---|---|---|---|---|---|---|
| vol04 R1 new-glyphs | 221 | ≈34.5k | 279→273（卡评）/记录表 279→279 | 0.81%→0.79% | 19（16 对，3 错：蒙→𫎇、彞→彝 异体码位） | 2888 文件 10.7MB | glyph_match 34.2、seed_admit 15.7、row_segment 32.0、border_detect 14.9 | cv0.4.7 c1；摘要与自动结果行不一致（推测：自动对比的基线取错） |
| vol04 R2 control | 221 | | 273 | 0.79% | — | 10.8MB | row_segment 14.8 | 对照组 |
| vol04 R2 layout-prior | 221 | | 273→256 | 0.79%→0.74% | 2 | 10.9MB | row_segment 9.6 | 切分变 51 列，约 32 好 10 坏（抬头字出版框没截到） |
| vol05 R1 new-glyphs | 188 | 28998 | 271→247 | 0.94%→0.85% | 10（蒙→𫎇 3、呂→吕 1 异体） | 2458 文件 9.0MB | | cv rc/v0.4.8@fee8a2e，浅克隆读不到 tag→标签 cvunknown |
| vol06 baseline | 150 | 23517 | 231→218 | 0.98%→0.93% | 8 | 1813 文件 5.5MB | glyph_match 12.4、seed_admit 7.4、row_segment 17.5 | 人裁 2→50；db pull 遇一次 R2 404 重试通过 |
| vol07 baseline | 135 | ≈21.3k | 203→166 | 0.96%→0.78% | 9（6 异体、4 需看图） | 1769 文件 6.4MB | glyph_match 13.9、rare 3.6、seed_admit 7.2 | R2 缺 121 锚图时本机补丁跳过，后补齐重拉 |
| vol08 baseline | 69 | 10710 | 197→180 | 1.84%→1.68% | 8（含实质变字 嶓→儒、姚→姓、變→𠮓、辜→事、隷→𨽾） | 911 文件 3.3MB | glyph_match 15.3、seed_admit 4.2 | 人审率最高 |
| vol09 baseline | 265 | ≈42k | 489→399 | 1.16%→0.95% | 20（13 非异体未看图→GUJI-633） | 3459 文件 12.6MB | glyph_match 64.0、seed_admit 17.7、row_segment 43.7 | 容器重启，glyph_match 从 122 页续跑；读到 110 格新人裁是送审下降主因 |
| vol10 baseline | 175 | ≈28.9k | 312→292 | 1.08%→1.01% | 13（另 7 人裁后字变；3 格需看图） | 2289 文件 8.5MB | glyph_match 44.4、seed_admit 10.2、row_segment 26.6、border_detect 5.8 | c1 下语料漂移→改钉 c2 重跑 |
- 共同观察：送审下降主要来自**新进库的人裁落地**（vol06 人裁 2→50、vol07 2→66、vol09 0→110），而非算法改进；放行字变多为**异体码位混用**（刊/刋、呂/吕、清/淸…）等 GUJI-626/M7；每册都有少量需看图的实质变字，没有统一的"放行字变必看图"闸。
- glyph_match（带字体域）是最慢一步：vol09 64 分钟、vol10 44 分钟（--jobs 4 云端）；row_segment 次之。

## 补读（与 M9 衔接的周边卡）
- **GUJI-605 刻例图与锚图上 R2**（已完成）：正式桶 guji-assets 10-18 传完：31,777 来源文件（刻例图 29,838＋锚图），按 sha 去重 **30,558 对象、90,950,937 字节**；键 `sha256/<前两位>/<sha>.png`；经 Worker `/v1/assets/sign-batch`。来源 guji-workspace 888cd82。之后 10-18～19 新写的锚图（608 切换后）有 121 张没进 R2 → GUJI-627（推测）。原图上不上 R2 仍等 GUJI-598。Worker 免费额度是约束（"为省 Worker 免费额度没有再全量重跑"；624 遇 429/1027）。
- GUJI-627 的状态：实验记录显示 vol07/08/09/10 跑时「R2 缺图已补齐」「db pull 缺图 0」，cv #258 加了缺图跳过，语料改钉 c2——**实质已解决但 Jira 卡未关**（推测需要有人核验收后关卡）。
- GUJI-573（vol01 待审上线并由用户裁完，承接 525）已完成。GUJI-577 cv_version 护栏（progress/step 版本≠册配置即拒绝）已完成。GUJI-580 `--params` 在 `--jobs>1` 丢参已修。GUJI-572 清理沙箱/备份已完成。GUJI-562 归档脚本已完成。
- **GUJI-599 vol01 真实归档到 open-guji-dataset（待办）**：脚本 team/整理/GUJI-562/archive_plan.py；脱敏扫描 0 命中、事件条数与锚图张数对账、恢复演练重导 char.json 逐字节一致，Release 名 archive-<书>-<版本>-<n>。10-18 前置：store check 报库先于真源 23 文件差；正式工作区 10-11～13 老未提交文件归属未定（中心库切换后此前置可能已变）。
- GUJI-594/595（vol02/03 补锚后精校，待办）、596（vol03 替换旧 003 时标点/实体锚点迁移方案，待办）——均归 vol01–03 线（已交其他项目）。
- 性能 JQL 结果：CV 侧没有单独的"性能专家"卡（专家团队 GUJI-635 为空 Epic，无描述、无子卡）；性能相关的是网站阅读页性能（GUJI-628–632，「Claude 阅读页性能会话」）。CV 提速线索：cv PR #255「页级并行提速」（GUJI-627 测速时发现问题）、cv#92 --isolate-steps、#68 审阅平台卡片冷启动 36.6s→3.4s、v0.4.1 拉图提速约 7 倍。（推测：CV 性能专家以项目线程形式存在，未在 Jira 建卡。）
- 人审率相关历史卡（未细读）：GUJI-412「待审成因表与分母口径定稿（分母 1752 交付态重数）」、GUJI-137「CV放行规则：待审成因表→批量改算法」、GUJI-134「体检表 v3 自动出表＋每册预计人审分钟」。

---
# 汇总（调研者归纳）
## 各册数字
| 册 | 页 | 格/字 | 人审（最新） | 版本/基线 | 耗时要点 |
|---|---|---|---|---|---|
| vol01 | 206 | 24672 格（交付态 24401） | 待审 290→236→63→0；1.0.0 时 66 格在重切清单（字手改入文本） | 1.0.0（book-text #199），冻结快照 snap/96mid1ogzk/vol01/20261019T2303，cv 0.4.5 | 服务器 seed_admit 一步 19 分（2 核 jobs1）；体检 selfcheck 29 分 |
| vol02 | 188 | — | close-check 2b：没出字 82、人裁≠放行 58；待审 108 | snap …/vol02/20261017T2040（v0.2.1，带字体域）；未出 0.1.0 | Step5–7 服务器 83 分 |
| vol03 | 110 | — | 待审 13（0.07%） | cv-proof 0.1.1（#168），与旧 003 1.0.0 并存 | Step5–7 48 分（+被 slice 卡 3.5h） |
| vol04 | 221 | 34523 字 | 0.1.0：466（1.35%）；main v0.4.6-cujiao 279（0.81%）；实验 273 / 256（layout_prior） | book-text #162 0.1.0（cv 0.2.0）；main v0.4.6-cujiao | 服务器单进程前 9 步 53 分＋rare 被内存卡 1h40m；--isolate-steps 整册 39 分 |
| vol05 | 188 | 28998 | 271→247（0.94→0.85%） | main v0.4.6-cujiao；实验 cvunknown-c1 | — |
| vol06 | 150 | 23517 | 231→218（0.98→0.93%） | 基线 cv0.4.7p9-c2-g-82293e | glyph_match 12 分 |
| vol07 | 135 | ≈21k | 203→166（0.96→0.78%） | 同上 | glyph_match 14 分 |
| vol08 | 69 | 10710 | 197→180（1.84→1.68%） | 同上 | glyph_match 15 分 |
| vol09 | 265 | ≈42k | 489→399（1.16→0.95%） | 同上；13 格待对图 GUJI-633 | glyph_match 64 分 |
| vol10 | 175 | ≈29k | 312→292（1.08→1.01%） | 同上 | glyph_match 44 分 |
