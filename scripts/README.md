# scripts/：散脚本索引

> 2026-10-06 cv 大清理（overview#413）生成。**整理一册书请走 `guji` 子命令和 [doc/runbook/整理一册书.md](../doc/runbook/整理一册书.md)**；
> 这里的脚本参数约定互不统一，除了下面「runbook 点名」的几个，日常整理不要直接调。
> 实验和一次性研究在 [../research/](../research/)。
> 新增脚本时在本文件对应分组加一行；一次性脚本用完请放进 `research/<题目>/`，不要留在这里。

## 整理一册书会用到的（runbook 点名）

- `check_pages_json_boxes.py`：pages.json 抽字核对（A2 验收，F3 overview#398）：抽 N 个格，把框画回原图，出一张对照图 + 对位量。
- `render_guji_markdown.py`：Step9 结果整理 · 坐标转字符位：命令行入口。
- `snapshot_glyph_store.py`：字形库快照：output/glyph.db → output/glyph_store/（真源，进 Git）。
- `export_guji_format.py`：CV 产物 → guji-page → guji-format 一章（A2：`NNN.pages.json` 生成；F3，overview#398）。只读产物，不改现有导出。
- `glyph_store_sync.py`：字形库 store ＋ 人裁事件/裁决定时导出：db → output/glyph_store/，

## 评测（`guji eval run` 调用或手动跑；对真书数据的质量量法，不是测试）（51）

- `eval_align_replace_gate.py`：Step5-d `replace` 段采信闸评测：长度闸（现役） vs 代价闸（emb 余弦 ⊕ IDS/异体关系）。
- `eval_char_drop.py`：丢字普查：单字墨段有没有被**字格**接住（char-segmentation/char-drop）。
- `eval_char_ocr.py`：char-ocr 评测：在冻结图块上量各引擎的 top1 / top5 / 异体字子集。
- `eval_clustering.py`：保守聚类 purity benchmark（open-guji-dataset/char-clustering）。
- `eval_column_warp.py`：拿 column-warp 金标量 Step2（单列矫正 + 界行清除）的准确度。
- `eval_confusable_lm.py`：形近对消歧的 n-gram 语言模型臂。
- `eval_confusable_recall.py`：校准形近对表（overview#128）：拿实测混淆对量召回，报表大小/门槛。**只读**——
- `eval_context_correction.py`：context-correction 评测：在冻结候选上量「通用 LM 低权重 + 本书 LM 高权重」。
- `eval_context_guard.py`：context 通道护栏（`seed_admit.context_guard_*`，overview#333）的评测。
- `eval_crop_margin.py`：s3 裁边残留：裁剪之后图像四边还剩多少空白纸边（char-segmentation/crop-margin）。
- `eval_db_match.py`：字形库匹配基准（glyph_db_first_design.md §5：库匹配是 G4 的新位置）。
- `eval_degradation.py`：固定退化协议（任务卡 2026-09-22 T5③）：同一批真刻例，加一组**固定**扰动，分因素报各路的稳定性。
- `eval_font_fallback.py`：字体字形当「兜底候选源」值不值：在真实待审字位上量。
- `eval_frame_residue.py`：Step2 版框残留：按 `column_border_trim` 自己的判档（a/b/c/d/e）分桶计数，
- `eval_frame_strip.py`：评测列端格「去框后」的干净度（char-segmentation/frame-strip）。
- `eval_geometry.py`：版面几何 benchmark（v2 链口径）：界行有没有被列框圈进去 + 列带里界行还歪多少。
- `eval_guard_ceiling.py`：覆盖率天花板：硬约束 precision ≥ 0.999 下，闸能开多低、recall 有多少。
- `eval_instance_quality.py`：评测管线对切分缺陷的自检能力（char-segmentation/instances）。
- `eval_jiazhu_tail.py`：夹注段端收编回归（char-segmentation/jiazhu-tail）。
- `eval_layout.py`：行列识别（列型判别）评测：当前管线 vs 金标。
- `eval_llm_context.py`：跑 llm_context 评测集：真调用（有 key）或 --mock（没 key 也能跑通全链路）。
- `eval_match_pairs.py`：匹配判据的**操作点**基准（glyph-match/pairs）。
- `eval_match_triplets.py`：匹配三元组基准：同字形必须比形近异字更匹配。
- `eval_normalize.py`：归一化 golden 回归门（open-guji-dataset/char-normalization）。
- `eval_oov.py`：类外评测：金标字在 CNN `classes` **之外**时，各候选源能给出什么。
- `eval_oracle_llm.py`：接生产评测：`oracle_llm` 策略（外部 LLM 答案表）vs 纯 `gated_ngram` 基线。
- `eval_pagetype.py`：页型判别 benchmark。
- `eval_rare_char.py`：量 `rare-char` 集上的候选召回：现状 vs 加了字体模板之后。
- `eval_recrop.py`：review_recrop 分片回归：**切分算法自己**的框 vs 人工拖框金标。
- `eval_row_boundaries.py`：Step3 格线位置 vs 人工金标：逐像素误差（char-segmentation/row-boundaries）。
- `eval_seam.py`：切缝墨率：格线是不是切在字上（char-segmentation/seam）。
- `eval_side_rule.py`：评测侧边界行残余剥离（char-segmentation/side-rule）。
- `eval_step7_replay.py`：Step7（seed_admit）放行判定 · 人裁事件回放评测（只读，不写任何事件 / 产物 / 库）。
- `eval_struct_heads.py`：Step A（结构头 + 槽位部件头）的验收：在 oov_bench 上量三件事。
- `eval_struct_rerank.py`：M0 零训练结构重排的验收：在 oov_bench 上量「开 / 关」的 top-1 / top-5 / top-10。
- `eval_t4_variant.py`：T4 变体形模板：在四庫「shape≠reading」异体分歧冻结子集上报 GW 开关前后的 top-1/5/10。
- `eval_text_band.py`：文字带窗口够不够装下一整列（char-segmentation/text-band）。
- `eval_touching_cuts.py`：粘连格线：现役 Step3 切点 vs 人工理想切点（char-segmentation/touching-cuts）。
- `eval_truncation.py`：字身截断率：格线切进字身多深（char-segmentation/truncation）。
- `eval_zero_shot.py`：零样本识别评测：字形库 unseen 档上，比较「整字 HOG 检索」与「拆字重排」。
- `eval_zero_shot_fusion.py`：零样本正面对比：HOG 字体检索 vs CNN 分类 vs 两者融合。同一批样本、同一字表。

## 构建数据集、审查页、字表、对照表（38）

- `build_book_variants.py`：本书用字账：从产物 + 字形库 + 整理本语料派生 ``config/variants/books/<edition>.json``。
- `build_border_bottom_review.py`：生成「下版框存墨判读」审查页：某页的下内框到底印上了没有 + 版框几何统计。
- `build_border_gold_reviews.py`：Step1 的三个金标标注页（列探测 / 抬头 / 外框外延）。
- `build_char_ocr_gold.py`：建 `char-ocr` 金标分片：单字 OCR 的验收集（换引擎时的尺子）。
- `build_char_review.py`：按字复核页：把指定几个字的**全部**字位排成一页，大图 + 上下文，**当场就能改**。
- `build_charset.py`：字表标准：把「字体 cmap ↔ Unicode」与 Unihan 异体字关系固化成两份表。
- `build_clustering_dataset.py`：生成保守聚类 purity 数据集（open-guji-dataset/char-clustering）。
- `build_collation_report.py`：⚠️ **已退役（2026-09-27）**——用 `guji collate <book> --strips` 代替。
- `build_column_border_review.py`：Step2 上下版框残墨的金标标注页（`char-segmentation/column-warp` 的第二部分）。
- `build_column_warp_review.py`：Step2（单列射影变换 + 去噪 + 界行清除）金标标注页。
- `build_confusable_families.py`：从**字体字形**建形近家族全对表（1214 字 × 全对 = 736k 对，4 分钟）。
- `build_confusable_pairs.py`：从 IDS 拆分生成「形近对表」（overview#128，2026-09-28）。
- `build_confusable_set.py`：形近对上下文消歧测试集：从已积累的裁决里抽出形近家族字位。
- `build_context_correction_dataset.py`：构建 context-correction 测试集：冻结候选 + 逐槽位金标，按页存、按列组织。
- `build_context_correction_v2.py`：context-correction v2：在 v1 冻结候选上重标「金标可达性」，剔掉构造痕迹口径。
- `build_exclusion_recheck_review.py`：排除名单复核页：名单上每个格，用**现在**的图块问人「还切坏吗」。
- `build_gloss.py`：构建单字速查释义表 config/gloss/gloss.json。
- `build_glyph_bench.py`：从字形库建「拆字识别」基准集：seen / unseen 两档，附 IDS。
- `build_glyph_evict_review.py`：图块出库裁决台：逐块判「这块图能不能用」，人裁定出全库清理的判据。
- `build_glyphwiki_catalog.py`：建 GlyphWiki 变体形目录：dump → 「关联字 ∈ 字表、非别名」的字形 → kage 渲染 64² 二值图。
- `build_label_suspect_review.py`：疑似错标裁决台：一个实例反复只跟同一个字撞，多半是它自己标错了。
- `build_llm_context_evalset.py`：从 context-correction 金标里挖「外部 LLM 有机会赢」的题。
- `build_match_inversion_review.py`：形近误判裁决台：把「异字邻居压过同字邻居」的排序倒挂挖出来做成审查页。
- `build_match_pairs_dataset.py`：构建匹配**阈值标定**集（glyph-match/pairs）。
- `build_match_triplets_shard.py`：从字形库体检的人裁结果构建匹配三元组金标（glyph-match/triplets）。
- `build_normalization_dataset.py`：生成归一化 golden 回归集（open-guji-dataset/char-normalization）。
- `build_note_lexicon.py`：版本注词表：从整理本语料派生 ``config/jiazhu/version_notes.json``。
- `build_ocr_carrier.py`：生成 OCR 对齐载体：逐图块 RapidOCR top-1 + s2t → carrier jsonl。
- `build_oov_bench.py`：建**类外评测集**：金标字落在 CNN `classes` 之外的真刻例。
- `build_patch_review.py`：生成「切分朱批 V2」数据：按列排布的**最终图块流**。
- `build_rare_char_set.py`：建 `rare-char` 测试集：生僻字候选召回的验收集。
- `build_recrop_shard.py`：把审查页的人工重切回流成 char-segmentation/instances 的切分金标。
- `build_seg_cases.py`：生成「格内净化」benchmark 样本（label_origin=synth）。
- `build_seg_review.py`：生成「切分审查」工件的数据：整页叠框图 + 格位点击区 JSON。
- `build_semantic_variants.py`：语义层派生：从关系层 + 本书用字账生成 ``config/dicts/variants.auto.tsv``。
- `build_side_rule_shard.py`：从产物里挖「侧边界行残余」测试集分片（char-segmentation/side-rule）。
- `build_struct_gold_review.py`：结构金标裁决台（任务卡 2026-09-22 T3 / 设计稿 M2）：300 条真刻例，人裁「IDS 拆法与图上写法符不符」。
- `build_variants.py`：P0 异体字关系层：把三个公开数据源合并成「字 ↔ 异体字」无向关系表。

## 导出（格式、审查材料、金标）（11）

- `export_border_review_cards.py`：为 Step1 的三个金标标注页一次性备料（探测跑一遍，出三种卡片素材）。
- `export_collation_review.py`：导出对勘复审页：我的定字 × 整理本的差异，逐条可改判、可打印 PDF。
- `export_column_border_gold.py`：把「单列矫正·上下版框核校」的人裁结果并进 column-warp 金标。
- `export_column_warp_gold.py`：把「单列矫正·文字带核校」标注页里的人裁结果导成 column-warp 金标。
- `export_confusable_prompt.py`：把形近对消歧集导成**不含答案**的题面，供大模型（或人）盲测。
- `export_guji_format.py`：CV 产物 → guji-page → guji-format 一章（A2：`NNN.pages.json` 生成；F3，overview#398）。只读产物，不改现有导出。
- `export_guji_page.py`：CV 产物 → guji-page v0.2（每字带坐标的页面文本）。只读产物，不改任何现有导出。
- `export_seed_review.py`：导出「种子审查」单页 HTML（glyph_db_first_design.md §3.5 页面侧）。
- `export_step3_input.py`：把 Step2 已经处理好、且**过了金标**的列推给 Step3 当输入。
- `export_train_bundle.py`：把本机才有的训练/评测数据打成一个包，给没有工作区的机器（云端会话）用。
- `export_wikisource.py`：Step9 结果整理 · 一键导出维基文库 `Page:` 页 wikitext。

## 字形库维护（12）

- `glyph_codepoint_census.py`：码位习惯普查：内/內 这类「同字两码」在库、人裁、OCR、整理本里各用哪个（字形库 11，只读）。
- `glyph_codepoint_review_select.py`：按形区分四对（强/強、却/卻、回/囘、并/幷，字形库 11 §〇）的逐例复核——**选样**这一半。
- `glyph_codepoint_unify.py`：书级码位统一：把库、人裁裁决里「书级指定」对（字形库 11 §〇：别/別、内/內
- `glyph_crosscheck.py`：字形库 × 工作区记录 对账：库里的刻例，与这一格现在的裁决、排除名单、管线决定、字块图是否还对得上。
- `glyph_near_forms_sync.py`：体检里人判「形近 / 异体」的字对 → 形近字人裁表 `config/confusable_human.json`（任务书 H §四·5）。
- `glyph_rekey_drift.py`：重切之后，把库里「id 已指到别的字」的刻例挪回它现在所在的格（字形库 08，2026-09-26）。
- `glyph_store_sync.py`：字形库 store ＋ 人裁事件/裁决定时导出：db → output/glyph_store/，
- `glyph_triage.py`：字形库机器分诊（2026-09-25）：OCR + CNN 两路独立识别 + 整理本对齐字，对照库里定的字。
- `glyph_triage_sheet.py`：分诊结果出联系表：每卡一格 = 本例 | 本书对手 | 字体(定的字) | 字体(OCR1) | 字体(CNN1)，下注文字。
- `glyph_v1_map.py`：四庫 v1 旧管线刻例 → 现在的格：按形状找，不再按「格号 = idx+1」猜（字形库 08，2026-09-26）。
- `glyph_v1_rekey.py`：四庫 v1 旧刻例 → 现格号：按 `glyph_v1_map.py` 的形状对照表，一次性改 instance_id（字形库 12 / 任务书 H §二）。

## 金标与数据迁移（一次性，留作出处）（6）

- `migrate_column_warp_gold.py`：上游改了 Step1 之后，把 column-warp 金标**能迁的自动迁、不能迁的挑出来**。
- `migrate_font_fingerprint_keys.py`：把用「字体 mtime」算出来的旧 `emb_*.npz` 按新 key（字体内容）改名，不重建。
- `migrate_labels_after_resegment.py`：重切分之后把旧裁决平移到新字位，避免重复校对。
- `migrate_manifest_eol.py`：把「只因行尾翻转而过期」的产物记录迁到行尾归一后的指纹（一次性，2026-09-20）。

## 审计（一次性核查）（5）

- `audit_glyph_consistency.py`：字形库自洽审计：放行错了，库自己把它揪出来。
- `audit_glyph_db.py`：刻本字形库体检：形离群 + 竞争字 + OCR 异议 → 审查页人裁。
- `audit_iron_evidence.py`：铁证审计：每个字位只拿**人裁实例**当字形库比对，看「铁证」给的字与现在放行的字是否一致。
- `audit_iron_recheck_0927.py`：D 铁证复核（2026-09-27 任务书）：把当前 cv main（含 `iron_ref_guard`）跑出来的
- `audit_ji_yi_si_0927.py`：D 铁证复核（2026-09-27）第 5 条：己/已/巳 一族在 `split_ref`/`ji_yi_si` 通道系统性

## 标定（4）

- `calibrate_admission.py`：准入规则标定：用全部历史人裁回放，找「本可自动确认」的空间。
- `calibrate_elastic.py`：elastic 判据的刻度标定：把原始分搬回 coverage 的数值刻度上。
- `calibrate_margin.py`：context-margin 准入阈标定（glyph_db_first_design.md §3：context provenance）。
- `calibrate_variant_form.py`：「义定形未定」定形阈值标定（`clustering/variant_form.py` 的五个常数）。

## 测量（4）

- `measure_context_ink_gate.py`：D 铁证复核（2026-09-27）第 3 步：context 通道空白弃权闸的阈值要从全书墨量分布
- `measure_frame_geometry.py`：版框几何常数实测：内框线宽 / 外框条宽 / 内外框间距，按边分开统计。
- `measure_gutter_straightness.py`：界行「直不直」的指标：把整条界行往 x 轴投影，看峰有多高、多窄。
- `measure_llm_online_accuracy.py`：CLI 封装：`open_guji_cv.eval.llm_online_accuracy.compute_report` 的

## 其他（85）

- `_review_shell.py`：人裁审查页的公共壳：设计令牌 + 状态/自存/复制/进度那一套。
- `_v2_step4.py`：M1 道 C 组共用件：评测读**现行 v2 链**（Step1→Step4 cell_shrink）的产物。
- `ablate_elastic.py`：弹性判据的旋钮消融：在 triplets 上扫 block / local / max_shift / scales / tau。
- `add_inversion_triplets.py`：把形近误判裁决台的人裁结果并进 glyph-match/triplets 的 hard 子集。
- `add_labelconf_triplets.py`：把「疑似错标裁决台」裁出来的 67 条**确认没标错**收进 triplets。
- `apply_crop_exclusions.py`：按排除名单把已进库的坏图块撤库。
- `apply_exclusion_recheck.py`：按复核裁决撤排除名单（配 build_exclusion_recheck_review.py）。
- `backfill_anchors.py`：老裁决补锚：给没有锚的逐格裁决事件写一份持久补锚档（设计见 `feedback/anchor_backfill.py` 模块头）。
- `bench_font_glyphs.py`：字体字形 vs 刻本字形：分来源的匹配力实测。
- `book_lib_auto.py`：机器高可信格进书级库（`source: auto`），与人裁刻例分开记、可整批撤回（H 道，2026-09-27 全唐文 #64）。
- `book_lib_sync.py`：书级字形库增量回收：人裁事件 → 本书自有库（H 道，2026-09-27 全唐文 #64 起）。**可重复跑、幂等**。
- `canonicalize_glyph_db.py`：把 GlyphDB（output/glyph.db）里的实例真源统一成 canonical 格式。
- `canonicalize_glyph_store.py`：把 glyph_store/patches/ 一次性迁移到 canonical 统一格式。
- `check_grid_offpage.py`：普查：行网格是否跑出页面（跑出去的格必然装不下字，还会挤歪真字）。
- `check_pages_json_boxes.py`：pages.json 抽字核对（A2 验收，F3 overview#398）：抽 N 个格，把框画回原图，出一张对照图 + 对位量。
- `check_stale_human.py`：查「切分改动后过期的人裁字位」——人裁钉住的那一格已经不是当初看的那一格。
- `column_warp_v2.py`：column-warp 金标 ↔ 现行 v2 链（keben_body_v2 / column_warp Step）的对接层（M1·A 道，2026-09-30）。
- `compact_glyph_db.py`：提交前压库：丢掉可重算的派生缓存 + VACUUM。
- `correct_admission.py`：改判已入库人裁字位的**释读**——不碰字形，不是重新裁决图块。
- `demo_norm_layer.py`：规范层（norm）方案演示：共享归一表 + 页上逐位例外 → 三档阅读文本（只读，不改输入）。
- `diff_grid.py`：比两份 phase3 网格目录：骑线比 + 每列格线位移 + 复切列清单。
- `dzg_import.py`：daizhige 逐列整理本导入（overview#195 P 道）。
- `evict_v1_conflict_human_reading_errors.py`：v1 重键 `conflict_human` 里「v1 把字形记成了读法」的例子：撤 v1 实例（不动人裁）。
- `find_border_lines.py`：投影峰匹配找版框线：批量跑竖直界行/边框 + 上下边框，画到图上，出报告页。
- `freeze_bottom_offset_gold.py`：把 `border-detection/bottom-offset` 的 68 条人工金标转成**绝对页面坐标**并冻结。
- `harvest_shadow_review.py`：把「影子≠现字」审查页（Artifact）上的人裁收回来，写成人裁事件。幂等。
- `ia_download_zongmu.py`：下载武英殿刻本《钦定四库全书总目》全套扫描（Internet Archive）。
- `ingest_cutline_flip_verdicts.py`：切分裁决台（A/B 盲裁）的裁决 → `char-segmentation/touching-cuts` 金标。
- `kage_render_glyphwiki.py`：把 GlyphWiki 的 KAGE 字形离线渲染成位图——给「Unicode 未收字」造模板的原型。
- `kangxi_crossval.py`：康熙字典字頭切圖的交叉驗證：把「可能標錯的字」全部挑出來人審。
- `kangxi_headwords.py`：康熙字典（CADAL 12 冊 DjVu，中華書局影印同文書局本）字頭切圖。
- `make_sample_store.py`：从真字形库抽一个小样本库，留在引擎仓供测试。
- `mine_hard_triplets.py`：从字形库挖新的匹配三元组（hard / nearmiss），直接补进 glyph-match/triplets。
- `mojibake_census.py`：H 道乱码普查（2026-09-27）：全库扫 `feedback/events/*.jsonl`，找出 `shape`／
- `pagetype_model_train.py`：训练页型「正文/非正文」闸模型（P1 道）。
- `patch_identity.py`：字块金标 ↔ 现行 v2 链（cell_shrink）的对接与「人当时看的图块还在不在」判据（M1·A 道，2026-09-30）。
- `prepare_corpus.py`：语料预处理：外部古文语料 → 可直接训 n-gram 的单文件（可选简→繁）。
- `probe_struct_heads.py`：Step A′：冻结现役 CNN 主干，只在它的 256-d embedding 上训结构头 + 槽位部件头（线性探针 / 小 MLP）。
- `reconcile_lines_anchors.py`：锚点对账（F3，overview#398）：CV 产物 → guji-page → lines.md，再数 lines.md 推锚点，与 CV 格 id 逐位比。
- `reflow_md.py`：Step9 结果整理 · 9.2' 文本版分段 + 标点：命令行入口。
- `regen_step2_columns.py`：用 Step 1 的新结果重算 Step 2 的输入（单列矫正图）。
- `rekey_instances.py`：切分层重建后的金标重键（(col,idx) 按格位面积重叠映射到新网格）。
- `rekey_triplets_by_patch.py`：三元组集按**自带的图**重键到当前管线（不借外部映射表）。
- `relabel_vol01_48_2_neg1.py`：`v2:vol01:48:2:-1`：库里存的字是「王」，目视核对后应为「聖」——改字命令。
- `remap_cutline_gold.py`：切线金标按列窗几何**精确重映射**：旧列图行号 → 页面坐标 → 新列图行号。
- `render_guji_markdown.py`：Step9 结果整理 · 坐标转字符位：命令行入口。
- `render_guji_page_overlay.py`：guji-page 校验图：把字框画回一张图（本页图、源叶、缩放档都行），并量一下对没对准。
- `render_self_assess.py`：把自评样本渲染成判读表：〔语境图（红框=紧裁框）｜成品图块〕。
- `repair_seed_queue.py`：种子队列体检 + 修复：唯一性、幽灵行、上下文错位。
- `replay_recrops.py`：把数据集里的人工重切框重新贴回产物（整册重跑之后必跑）。
- `report_collate_group.py`：Step8 复核报告：把某一类人裁结论逐处列出（带图、字对、前后各 10 字上下文），出 md + html（+ pdf）。
- `report_intrusions.py`：版面线侵入全书扫描 → 回流上游（G2 行列识别 / G3 字符网格）的证据报告。
- `research_split_scan.py`：调查脚本：全册扫描 _split_touching 的工作面（P2 #12 曲线切分前置量面）。
- `reshift_cutline_gold.py`：切线金标坐标整体平移：Step2 列窗上界变了，把金标搬到当前坐标系。
- `resync_human_verdicts.py`：把字形库里的人裁记录对齐到**最新**人裁事件：改判被幂等闸挡住的，撤旧进新。
- `round_check.py`：一轮审阅的体检（命令行外壳）。判据与阈值在 `open_guji_cv/eval/round_check.py`。
- `run_llm_context_eval.py`：一条命令：出题 → 调外部大模型 API → 算分 → 出报告。
- `sample_live.py`：无偏 rand 抽样 + **现场提取**（不依赖 phase4 产物，免整册重建）。
- `sample_self_assess.py`：分层抽样出「切分正确率」判读样本（无偏 rand 层 + 定向富集层）。
- `scan_inverted_bands.py`：扫一册书，找可能的反色带（Step0 预清理的候选页）。
- `scan_step2_corpus.py`：全语料跑一遍 Step2，把每一列的诊断量收成一张表——扩金标和改算法都要先有这个。
- `seg_harness.py`：Step3 切分离线复现台：不重跑管线，直接在金标列上量任何改动。
- `shadow_gate_eval.py`：影子放行闸的离线评估：对一份已落盘的 seed_admit 产物，统计「若开 shadow_veto 会降级哪些格」。
- `shadow_gate_train.py`：训练影子放行闸的模型文件（带元数据 + 指纹）。
- `siku_volume_extract.py`：四庫總目整册标点层（A4）＋实体层（A5）流水线。逻辑在 `open_guji_cv/render/siku_extract.py`。
- `snapshot_glyph_store.py`：字形库快照：output/glyph.db → output/glyph_store/（真源，进 Git）。
- `snapshot_recognize_profile.py`：recognize-profile 全量样本巡检（**脚本，不是 pytest 测试**）。
- `stat_verdict_evidence.py`：只读统计：各书现有人裁事件里带 anchor / bbox / 图像指纹 / 产物版本的比例。
- `struct_gold_residual.py`：结构金标：把 300 张卡按「模型预测 vs IDS 表全部拆法」分三类，只把真有分歧的留给人裁。
- `survey_review_queue.py`：人审队列普查：谁在队列里、为什么、哪路信号对、哪条新通道能吃掉多少。
- `test_vol02_extract.py`：四库总目第二册 (vol02) 标点、分段与实体链接抽取测试脚本。
- `track_review_rate.py`：人审率台账：每册每次重跑记一行，用来 track「审得越多、后面越省」到底有多快。
- `train_font_cnn.py`：**单字体** CNN：一套字体一个模型，用时多模型各出候选再比较。
- `train_glyph_cnn.py`：拆字识别 v2：学到的特征。小 CNN + 部件多标签辅助头 + 字体合成补类。
- `upload_wikisource.py`：把 `export_wikisource.py` 出的逐页 wikitext 上传到 zh.wikisource `Page:` 页。
- `verify_cloud_glyphdb.py`：云端字形库重建通道体检（Step5a-库验通道，2026-09-09）。
- `verify_gold_migration.py`：校验金标迁移无损：items.jsonl 读出来的，与评测脚本从旧文件读的**逐条相同**。
