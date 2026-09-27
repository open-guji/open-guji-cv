> **2026-09-04 第二轮 review**：`doc/pipeline_review_2026-09-04.md`。结论：切分不再是瓶颈；
> 人审 152 条里 65% 能被「整理本 × 库」通道吃掉（v2 没接 `align_char`），锚定串改用库 top1
> 覆盖 83.8% → 98.1%；真正要人的是生僻字。四刀：A 接整理本通道 → B LLM 判形近 + 三方一致
> → C 生僻字候选（字体模板 kNN / IDS 护栏与检索 / 部件模型）→ D 读文定字 UI。
> 复现：`scripts/survey_review_queue.py`。

# open-guji-cv 近期任务

> 来源：overview 项目下发（2026-09-03 更新）。此前 2026-02 下发的「Volume 1 / Volume 2」任务
> 已完成或挂起，归档在文末。
> **算法层**的待办仍以 `.claude/doc/pipeline_handbook.md` §3 与 `segmentation_v2_pipeline.md`
> 「下一步」为准；本文件只放 overview 下发的**架构层**任务。

## 🎯 全流程 review 下发（2026-09-03 晚）：Step 1–4 冲 100%，Step 5/6 接进 v2

正本 [doc/pipeline_review_2026-09-03.md](doc/pipeline_review_2026-09-03.md)——六步现状实测、
字位损失预算、四阶段方案。**目标（用户定）：Step 1–4 达 100%；Step 5 可略低；Step 6 靠上下文与 AI 选字。**
四把尺子 R1 产出率 / R2 格线穿字 / R3 格数正确 / R4 紧框被切。
**别再抄数进文档**——控制台总览页「四把尺子」按钮直接测当下值
（`/api/rulers`，口径在 `eval/rulers.py`）。2026-09-04 vol01 dev_set：
100% / 可改善 0.14%（真粘连 2.63% 另计）/ 0 列 / 0.51%。

### 阶段 A — Step 1–4（四刀互相独立；A4 的金标是验收尺子，先做）
- [ ] **A1** Step3 穿字 11.6% → <2%：先分解剩 462 条；真粘连换判据（period 窗内找连通体颈部）；
      `lo_ratio` 硬约束 0.7 改软（硬 0.6 + 二次惩罚）。金标：控制台逐格「格线是否在字缝」二选一
- [ ] **A2** 格数逐列自估：接 Step1 `raised`→`n_raised`；顶格型查首格之上有无 ≥0.3 格高字墨；正文低格起不动
- [ ] **A3** Step1 下版框根修：`find_horizontal_border` bottom 选峰加半高宽 ≤10px 闸；外框反推；
      `BOTTOM_PAD` 40 → 12 当保险。尺子：14 页金标 bottom 7.0 → <2px；dev_set 残留 52 列 → 0
- [ ] **A4** Step4 v2 金标：8 879 条 `instances` 按 `bbox_page` + 图像指纹重键；迁不动的新标 rand 层 200 格；
      去掉夹注 a/b 合成再拆；复验 v1 绝对像素阈值
- 验收：vol02 全书 R1 ≥99%、R2 <2%、R3 =100%、R4 =0；rand 层 400 格 Wilson 下界 ≥99%

### 阶段 B — Step 5 接进 v2
- [ ] **B0** `steps/_v1_bridge.py`：`PageChars`→`CharInstance`；`seeding`/`glyph_db` 抽 `InstanceSource`，v1 路径不改
- [ ] **B1** 四个新 Step：`normalize`（cache）/ `glyph_match`（指纹含 glyph.db sha）/
      `ocr_candidates`（needs=engine）/ `context_decide`（指纹含语料 sha）
- [ ] **B2** 金标重键：char-ocr 1 404、context-correction 1 681、glyph-match 71 497 对
- [ ] **B3** `uv pip install rapidocr-onnxruntime`

### 阶段 C — Step 6 + 进库闭环
- [ ] **C1** `seed_admit` Step：十条通道→自动发 `confirm`（路由已有 `glyphdb_admit`）/ 待审进队列
- [ ] **C2** `review/seed_export.py` 包进 `review/shell.py`，收割→路由→进库
- [ ] **C3** `ContextDecider` 加 `llm` 策略，门槛化不变
- [ ] **C4** vol02 全书六步端到端，报字位定字准确率

### 阶段 D — 非正文版式
- [ ] `keben_roster.yaml`（vol01 p90–132 职名 41 页）；目录页双行小类注；无界行页

### 控制台
- [ ] yaml 加五步；产物视图字块 + 候选 overlay；审查视图定字页 / 格线二选一 / 紧框拖框；heavy 评测器解锁

风险：穿字真粘连是图像极限（按「能分开的都分对、分不开的都标出」收）；v1→v2 重键格位不一一对应；
`tests/clustering/` 本机 pytest 崩溃，B0 前先跑通；启发式判据先复核再投事件（今日 127 条误报教训）。

## 🎯 架构：控制台 + 四个抽象

设计全文：[doc/console_architecture.md](doc/console_architecture.md)。
四个抽象 Step / Product / Gold / Event，上面架一个本地控制台。按 P0 → P4 推进，
每阶段单独可交付，旧 CLI 始终可用。

两条硬约束（用户 2026-09-03）：
- **只建模 v2 链**（Step1 边框 → Step2 单列矫正 → 交接闸 → Step3 切格 → Step4 字框收缩 → 下游）。
  v1 的 s1..s6 / phase2 / phase3 不包壳、不注册；phase2..phase9 产物目录 P3 时清掉。
- **数值长期、图像即算**（设计 §3.8）：Step1 只存线，Step2 只存 warp 参数 / 文字带 / border_class，
  Step3 只存字格，Step4 只存紧框 + flags；列图、字块、归一图块一律走 `ctx.materialize` 的本地缓存
  （LRU、有上限），缺了现算。长期存图的只有原始扫描和人裁过的图（金标 assets、GlyphDB 范例）。

### P0 骨架 —— ✅ 已落地（2026-09-03，分支 `feat/console-p0` 提交 `d63d1b4`；记录见设计 §8.1）

- [x] `core/`：spec.py、step.py、book.py、pipeline.py、engine.py（指纹、stale 沿 DAG 下传）、anchor.py
- [x] `products/`：store / manifest / cache（LRU 20 GB）/ kinds（borders、column_windows、gate_manifest、cells、char_index + 三种缓存图）
- [x] `steps/`：五个薄适配 + `_warpmap.py`（列图 → 原图逆映射，含三段折线）
- [x] `pipelines/keben_body_v2.yaml`；`books/vol01.yaml`、`vol02.yaml`（各 12 页 dev_set）
- [x] `console/`：FastAPI + 无构建前端（总览矩阵 / 运行 + SSE 日志 / 产物叠图）；`guji-cv console`
- [x] CLI：`guji-cv pipeline | step | status | cache`，`guji` 独立入口；旧命令原样
- [x] 验收：vol01 第 24 页全链 2.4 s；dev_set 12 页 35.6 s；第二遍全跳过；改参数只下游过期；
      产物目录只有 JSON，列图 / 字块在 `cache/`；`tests/test_core_v2.py` 9 条全过
- [ ] P0 尾巴：包 `page_type_gate` / `grid_prior`；`when` 求值；Step4 直接喂半宽夹注框（现在合成满宽格再拆一次）
- 环境：`venv/` 已死（Store Python 3.13 被卸），用 `uv venv .venv --python 3.12` +
  `uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented`
- 算法层待办（P0 跑出来的）：vol01/119 页级周期估成 70 → 9 列 DP 无解；vol01/60 c8 DP 无解；vol01/42 被 L1 列宽拦下（已知）

### P1 反馈 —— ✅ 已落地（2026-09-03，提交 `6130449`；记录见设计 §8.2）

- [x] `feedback/`：events（信封 + 只追加日志 + 幂等记账）、harvest（四种旧格式）、
      routes（kind × step → 消费者）、consumers（gold_add 已实现）
- [x] `gold/`：统一金标信封 + 分片仓（upsert / retire / mark_stale / summary）
- [x] `review/batches.py` 批次登记（含「发布前必须先收割」的闸）+ `review/shell.py` 双传输
- [x] 控制台审查视图 + 7 个 API；CLI `batch` / `events` / `gold`
- [x] 验收：真实 column-split 60 条裁决走完 收割 → 路由 → 金标，分布 ok 56 / extra 2 / miss 2
      与分片 README 一致；重复收割与重复消费不产生副本。19 条测试全过，全量 627 条零失败
- **修掉三处格式对齐 bug**（各有回归测试）：GUJI-SEG-REVIEW 前缀在 `t` 字段里且 `t` 非时间戳；
  marks 值是 `{"s":N}` 且 2/3 语义反了；续裁要 `{id:{"v","t"}}` 不能传扁平串
  （`build_border_gold_reviews.py --verdicts` 至今仍有这个 bug，迁它时一并修）
- [ ] P1 尾巴：`glyphdb_admit` / `glyphdb_recrop` 两个消费者（现在照旧走 `seed-ingest`）；
      把「界行切分裁决台」真改成 server 模式跑一轮真人裁；`column-split` 分片补 metadata.json

### P2 金标 —— ✅ 已落地（2026-09-03，提交 `aef2e2f` + 数据集仓 `0d53f92`；记录见设计 §8.3）

- [x] `gold/adapters/`：五种旧载体读取器（samples_dir / flat_expected / verdicts / cases），
      **35 个分片、8879 条金标全部可读**（唯一为 0 的 truncation 是统计型分片，本就无条目金标）
- [x] `gold/drift.py`：图像指纹漂移检查，**沿用 migrate_column_warp_gold 已标定的判据**
      （容差 6.0 灰阶；不用内容哈希、不用算法一致性）。column-warp 实测 keep 110 / recheck 4
- [x] **全部 34 个分片迁完**（8879 条），旧文件保留并存；`scripts/verify_gold_migration.py --all`
      逐条校验**零差异**，迁移前后评测基线一字未变（instances 50%/82%、layout 91.4%、page-type 99.5%）
- [x] 控制台金标视图（分片表 / 迁移 / 漂移检查）；CLI `gold migrate | drift`
- [x] 15 条测试全过，全量 642 条零失败
- **迁移查出的四个问题**（都已显式处理，见设计 §8.3）：samples/NNN 冒充分片；报告式
  expected 的阈值名被当条目 id；instances 有 3 处真矛盾（同字位两轮判不同类，已标 uncertain
  并记 history 待人裁）；coord_space 等文档字段混进了 expected
- [x] **P2 尾巴已做完**：27 个评测脚本包进控制台（`eval/` 三件套，脚本一行没改）。
      17 个可跑全部跑通（12 通过 + 5 回归门失败）；其余 10 个如实标出前提。
      避掉一个大陷阱：十个脚本的 `--out` 是**产物根目录**不是报告路径，传错会静默扫 0 页
      然后报「回归门：通过」——假通过比失败危险。详见设计 §8.4。
- [ ] 仍缺：`metadata.json` 字段公约不统一（known_limitation 单复数、sampling 四种写法、
      instances 的 total_samples 写 392 实际 562）；instances 与 border-detection 补图像指纹
      （前者 patches/ 已有 909 张 PNG 可直接算）

### P3 增量与存储 → P4 扩展

见 doc/console_architecture.md §8 的表。要点：P3 用 `guji pin` 把数值产物钉进 git 的 `pins/`
后再把 `output/`、`data_full/` 移出 git 并清 v1 目录；P4 切到 v2 Step4 时 GlyphDB / seed 队列的
`instance_id` 要按内容一次性重键到 v2 口径（右上、从 1）。

### 已裁定（用户 2026-09-03，见设计 §9）

- 快照仓：**本地**（仓库外目录，`GUJI_SNAPSHOT_DIR`），只给自己和少数开发者看，存免费的地方；
  `github_release` 只作可选免费镜像，不引入付费桶。
- git 历史：**稳定后重写**（P3 落地、分支收敛后跑 filter-repo）。
- 控制台：**先跑本机**（Windows 开发机），iPad 走 Tailscale。
- 数据集仓：**不合并**，独立存在，GoldStore 走 `../open-guji-dataset`。
- 锚点规范坐标：**右上角原点** `raw_page_px@top-right`（古籍从 top-right 起）；v1 左上原点只作遗留声明；
  `core/anchor.py` 负责与 cv2 互转。

### 与 overview 的约定

- 每阶段完成后更新本文件与 overview `项目进展/图片初步数字化/todo.md`。

---

## 🎯 字形套（glyph sets）下发（2026-09-06）

正本 [doc/glyph_set_roadmap.md](doc/glyph_set_roadmap.md)。架构已定：**一个共享度量网络 +
多个可插拔原型库（套）**，套放索引层不放网络层，加套/换套/加权都不碰网络权重。
E1–E5 与学习曲线小实验都已跑完并入档，**结论是现在不要动算法**：

- E1 本书原型 1-shot 只 +0.6，权重给到 4 反而掉；
- E2 字体形关度加权无收益，只用最像的单一字体反而差 1.2 点（多样性 > 相似度）；
- E3 线性适配器无效——刻本与字体在现役网络里已经对齐，没有风格鸿沟可填；
- §4 学习曲线：真刻例从 25% 加到 100%，分类头退化 4.3 点、检索与三源融合纹丝不动。
  **真刻例的正确用法是当原型，不是当训练样本。**

因此七条动作按「现在做 / 等第二风格再做」分档。**分档的判据**：套机制的收益只在
"网络没见过的风格"上兑现，武英殿一种刻本时动作 4/5/7 是空转。

### 现在做

- [x] **G2 填 `sources` 元数据**（overview 2026-09-06 代填）：`collection/title/volume/
      script_style/era/cols_per_page/chars_per_col/pipeline_version/notes` 已落库；
      vol01 与 v2 都是《欽定四庫全書總目》武英殿刻本、woodblock_kai、乾隆、9 列 × 21 格。
      **坑（已避）**：`v2` 不是第二册，是与 vol01 同书同页的 v2 管线实例源；
      `edition_tag` 是 `glyphs` 的连接键（`bench_font_glyphs.py:48` 靠它 join），
      **改不得**——vol01/v2 合并还会在 229 个字种上撞 `UNIQUE(edition_tag,char)`。
      套的归属暂用 `collection` 表达，真要统一到 `wuyingdian_zongmu` 见 G8。
- [ ] **G1 vol02 全 186 页按 SOP 跑**（roadmap 动作 1）。已跑 dev_set 12 页 + p10–21，
      自动放行对整理本 3,257/3,257 = 100%，人审率 5.1%（vol01 0.5%）。
      **要的产出不是算法改进，是那 96 条人审的账**：94 条「库 unsure + 上下文 margin 不足」、
      85 条 OCR 首选与整理本不一致——先定是 OCR 还是切分的账，再谈动算法。
- [ ] **G3 异体偏好表按套导出**（动作 3，半做）。`scripts/build_book_variants.py` 已产出
      `config/variants/books/wuyingdian_zongmu.json`（92 组 / 32 单形 / 60 多形），
      但那是异体字策略线的产物，不是 roadmap 层 4 的 `<edition_tag>.json`。
      **只差把两者对齐**：确认 key 用 edition_tag、能被读文定字当默认 `reading` 消费。

### 等第二风格再做（**触发条件**：库里进第一个非武英殿刻本的套——抄本 / 影宋本 / 别本）

- [ ] **G4 真刻例原型进模板索引**（动作 4）：`cache/glyph_sets/<set_id>_<ckpt指纹>.npz`。
      现在做只值 +0.6，等新风格进来才是 EASA 那种 24 → 92 的处境。
- [ ] **G5 `scripts/glyph_set_similarity.py`**（动作 5，E2 的逻辑落成脚本）：
      套间形关度 = 共有字上原型的平均余弦。**只有一种风格时算出来也没得比**。
- [ ] **G6 套权重表**：当前书 4 / 同版本其它册 2 / 同时代同字体 1 / Jigmo 0.5。
      E1 已证当前书权重不要超字体太多，**初值从 2 起调，不要按 roadmap 写的 4**。
- [ ] **G7 vol03+ 备图与整理本对齐检查**（动作 7）。
- [ ] **G8 `edition_tag` 迁移**：把 source 级的 `vol01`/`v2` 与套级的 `wuyingdian_zongmu`
      拆成两个字段（或给 sources 加 `set_id`），这样第二个套进来时 glyphs 才挂得住。
      **G4 的前置**——原型库按套聚合，现在的 edition_tag 表达不了"同套多 source"。

**不做**（roadmap §5）：每套一个网络；大骨干；笔画序列；Slot Attention；
在只有一种风格时调套权重表。

**风险**：同书迁移好（vol02 100%）不代表跨风格好，别外推到抄本；
异体偏好表只有 6 组，作先验不作规则；`己已巳` 仍按用户规矩强制人审。

---

## 🎯 对齐先归简体再 difflib——已测，结案不实施（2026-09-11，协调者直接测完）

正本 [overview/项目进展/图片初步数字化/进度/Step5-字符识别/06-对齐要不要先归语义层.md](../../overview/项目进展/图片初步数字化/进度/Step5-字符识别/06-对齐要不要先归语义层.md)
第六节。

背景：多处文档说对齐前「先归语义层再 difflib」，实测 `clustering/align_label.py:209`
根本没有这层，是转述时把 `variant_strategy.md` 里另一件事（145:8:4 厯/一踩坑）串了过来。
用户裁定同意测「OpenCC 统一到简体再比较」，协调者直接测了（未派子任务、未改代码）。

**结果：净损，不实施。** 用 vol01/vol02 真实 `ocr_candidates`（RapidOCR 原始 top1，
294 页锚定成功）重放 align_label 同款逻辑：equal 段 43635→43402（**-233**），
过闸 replace 段 2559→2795（**+236**）。只有 10 个字位真的从 replace 修正成 equal，
却拖累 247 个字位从 equal 退化成 replace——净亏 237。根因：`OpenCC("s2t")`
是无上下文字表映射，对「一简对多繁」的字（云→雲、占→佔、咸→鹹、里→裏、凶→兇、
于→於）不分场合硬转，而本项目语料本身已是传承字形，很多时候「云/占/咸/里/凶/于」
就是正确的独立传承字，转了反而错——`s2t` 表是为「现代简体转繁体」设计的，不适配
「OCR 噪声 vs 传承字形语料」这个场景。

`clustering/align_label.py` 维持现状不改。以后若要再探，方向应换成**本项目字符集专用、
人工校验过的异体字/通假字对照表**，而非通用简繁转换表。

---

## ✅ `find_vertical_lines` 在灰度扫描上挑错线——已修：网格模式 + 关折线（2026-09-16）

**先订正 2026-09-16 上午那版诊断**：「全书 47.4% 竖线切在字上、p20 也错 18 条」是**反的**——
我拿墨占比判线，而界行在空白缝里墨少、字身墨多，选出来的「真界行」全是字身中线。
按正确判据（细线 + 两翼是纸）重测，改动前 81% 是对的。**判线对错只能叠图看**（已记进记忆）。

**真根因三层**（正本 overview `北行日录古本/01-step2界行识别.md`）：
1. `expected_cols` 写 20，实际 **19**（9 + 版心 + 9）——每页被迫多收 1 条假线；
2. 本书是 254 级灰度、界行淡且**有的半叶没印**（p41 左半叶整片空白），自由模式在缺线槽位
   只能拿字身假峰凑；四庫總目是 1-bit、界行实黑从不缺线，所以 14 页金标 0.05px 没事；
3. `fit_vlines_polyline` 的判弯量 w80 在淡断线上量的是「线有多断」，平直页中位 41（阈值 7）
   整页判弯，折点找不到墨就全页齐刷刷平移 33~39px（p40/p41），闸2 只剩 1/19。

**修法**（默认全关，四庫總目 14 页金标逐位不变、584 tests 过）：
- `find_vertical_lines_grid`：版框对按列距先验 + 槽位支持数选；逐槽 ±18px 联合精搜，
  分数 ≥20 且半高宽 ≤12 才算探到（余量 >10×：探到最低 29.6、拒掉最高 2.8）；缺槽线性插值，
  `borders.vline_filled` / `line_index` 旗标 `rule_interpolated` 标出。候选池抽成 `_vline_pool` 共用。
- `fit_vlines_polyline(fit=False)` 只量 w80 不拟合。
- `BookSpec.column_grid / col_pitch / vline_polyline`，进 `border_detect.book_deps`，step 1.1→1.2。
- bxgb.yaml：`expected_cols: 19`、三个开关；`pitch_prior: 119` 那条是误用（那是现代链字距）已删。

**结果**：Step1 0/1080 条线在字上、版心 col10 54/54、插值 7 条；闸2 过 18/19 的页 43→**51**/54。

**2026-09-16 续：模块化 + 阈值归一化已落地**（commit `12a2935ef5`，正本 overview
`北行日录古本/03-竖线探测模块化.md`）：
- 网格模式拆成三个纯函数 `select_frame_pair` / `verify_slots` / `interpolate_missing`，
  外加 `is_thin_rule` 把「哪些候选算数」收敛成唯一一把尺子（原先两处各写一遍）。
- 阈值不再是绝对像素：`grid_thresholds(col_pitch, frame_height)` 按本书先验换算
  （slot_tol / max_width 跟列距成正比，min_score 跟框高成正比，pitch_tol 无量纲）。
  新增 `BookSpec.frame_height` + `measure_book_frame_height()`，进 `border_detect.book_deps`。
  ⚠️ 没有一本书写这个字段（全 None、输出逐位不变），但**指纹变了**——siku 504 页 +
  bxgb 55 页 Step1 连同下游一次性过期重跑，是有意付的代价。
- 回归：bxgb 54 页 + 四庫總目 14 页金标（自由/网格两种模式）全部**逐位相同**，215 passed。

⚠️ **网格模式不是自由模式的超集，不能当唯一路径**（本轮实测推翻的假设）。
两本书 394 页：381 页两模式逐位相同，差异集中在「版框一端只有粗外条」的页。
病因在**选版框对**（不在插值）：那一端落到外框上，隐含列距被拉伸，漂移沿槽位线性累积，
末几槽超出 `GRID_SLOT_TOL` 就验不上 → **明明印着线却被插值到字上**。
- vol02/176：无 `col_pitch` 时选中列距 **93.22**（真值 ~185，半列距），10 条线全挤到页面
  右半边齐刷刷穿字；`col_pitch=184` 就选对了。自由模式同页 10 条全对。
- vol02/3 卷題頁：列距 188 vs 184，末两槽漂移 24/31px，第 9 槽插值落到字上。
→ **自由模式不退役**，`column_grid` 保留；网格模式**必须配 `col_pitch`**，它是唯一的安全带。

**已排除的死路**（别再走）：
1. ~~等距网格不成立（版心窄）~~ **理由不成立**——版心只窄 2px，等距模型完全够用，网格模式就是它。
   （但「网格模式可以当唯一路径」是另一回事，**已被 394 页实测否掉**，见上。）
2. 纯墨脊阈值挑线不行——54 页只 1 页恰好 21 条。
3. **二值化救不了**（2026-09-16 实测 8 种：固定 128/160/185、Otsu、adaptive mean/gauss、Sauvola×2）
   ——分数是 proj/半高宽，二值化只改墨量不改邻域形状；抬到 200 界行才连上但字全糊成一坨
   （单列连通域 28→19、最大块 1.2k→11k px）。

**还欠着**：
- [ ] 折线拟合的判弯量：w80 在淡线上失灵，`vline_polyline: false` 是绕开。真修要换成量曲率
      （直线 vs 三段残差改善），拿 `open-guji-dataset/border-detection/vline-polyline` 金标回归。
- [ ] 闸2 剩 3 页 17/19（p8/p33/p40 各拒 1 列）；period 二次谐波 5 页是 `estimate_period` 那条。

---

## 🎯 `estimate_period` 搜索窗口写死 70–160，锁 2x 谐波（2026-09-16 查清+修法已验证，未改码）

正本 [overview/项目进展/图片初步数字化/进度/北行日录古本/02-step3周期谐波.md](../../overview/项目进展/图片初步数字化/进度/北行日录古本/02-step3周期谐波.md)。

`utils/row_boundaries.estimate_period` 的 `lag_lo=70, lag_hi=160` 是按《四庫全書總目》
（period ~113~115）标的。北行日錄刻本字格高真值 **70.6px 正顶在 lag_lo=70 下界上**，
窗口对 2x 谐波 141px 敞开——逐列自相关在 70 和 141 两处都有峰，锁哪个看运气。

`estimate_shared_period` 取逐列**中位数**，两堆各半时中位落进中间空档，给出
**物理上不存在的值**（p20 = 106.5，没有任何一列估出过它），Step3 弹性 DP 拿它当先验必然无解。

**不是 3 页的问题**：全书 884 列里 **269 列（30.4%）锁到 2x 谐波**；已翻车 3 页
（p20/p27/p38），另有 **17 页谐波列占比 ≥35%**，其中 6 页已到 0.44——再翻一列中位就过半。
现在只坏 3 页是运气不是稳，别看数字好看就当没事。

**修法（已离线验证，未落地）**：窗口由 `Book.period_prior` 派生
`lag_lo,lag_hi = int(prior*0.7), int(prior*1.4)`；没配 prior 的册保留现默认、逐位不变。
实测 bxgb 谐波 30.4%→0%、54 页页级中位偏离>10px 归 0；zongmu vol01/vol02 各抽 12 页
**中位逐页相同**（prior 115/113 → 窗口 [80,161]/[79,158]，与现默认几乎重合）。

⚠️ **死路：别用固定窄窗**。试过 `[55,100]`，bxgb 好了但四庫總目当场全毁——115 被
上界截成 99，抽的 12 页里 10 页中位都变。窗口必须跟着书走，不能换一组写死的数。

落地前：过 `border-detection`（14 页金标）+ `column-split`（60 页人裁，现 93.3%）全量回归。

---

## 🎯 glyph_db 的 semantic 列该不该存——用户质疑，仅记录（2026-09-11）

正本 [overview/项目进展/图片初步数字化/进度/Step7-放行判定/06-语义列该不该存.md](../../overview/项目进展/图片初步数字化/进度/Step7-放行判定/06-语义列该不该存.md)。

背景：己已巳任务收尾时用户问"db 删 column 的事做完了吗"，答复是 `glyph_db.py` 的
`semantic` 列删不掉——它是整个异体字/正字归一系统（卽/即、隸/𨽾、鍾/鐘……）共用的字段，
不是只给己已巳用的。**用户不认同这个答复**："我觉得不该这样，这是繁体字归一的问题"。

理解（未经用户确认，仅供接手人参考）：`clustering/variants.py::VariantMap.semantic()`
本身是**现算的归一函数**（懒加载 `config/variants/variants.json` + 用字账），但
`glyph_db.admit_instance()` 把每次调用结果又**持久化进了 instances/glyphs 表的
semantic 列**——用户可能觉得"正字是什么"不该在字形库里逐实例存一份静态快照，应该
永远现查归一表；也可能是别的意思，需要用户进一步说清楚要往哪个方向改。

**只记录问题，不预设方案**——具体需要厘清什么、从哪里开始，见正本三点。
与上一条「对齐先归简体再 difflib」的结论相关：那条测出「通用简繁表不适配这本书的
传承字形语料，该用本项目专用异体字表」，而 `VariantMap`/`variants.json` 正是那张
专用表——这条任务要问的是「专用表算出来的结果该不该被字形库持久化存一份」，是下一层
的问题。

---

## 阶梯升级在 vol02 上不出手：9/9 扩B 目标全被高分近形挡住（2026-09-17 实测，给字表那一道）

`charset_spec` 的阶梯判据是「基集 top-1 余弦 < `escalate_threshold`(0.85) 才追加升级档」。
模块头已经写明「**『最高分低才升级』这个判据单独用不成立**——命中 p10=0.798、未命中 p90=0.896
两个分布严重重叠」。vol02 上这句话再次应验，而且更极端：

拿 vol02 全书对勘里「整理本用字 + 字形库没有该字头」的 46 条做可达性实测
（现役 r5 + 已提交的 `charset_spec`，`rare_for_batch(book='vol02')`）：

| | |
|---|---|
| 46 条整体 | top-1 20% · **top-10 78%**（改造前这批是 0%，压根不可达） |
| 其中 37 条基集内（cjk-a） | 全部进 top-10 ✅ |
| 其中 **9 条扩B** | **全部进不了 top-10** ❌ |

9 条扩B 的基集 top-1 分数：**0.944 ~ 0.977，无一例低于 0.85**，所以升级档一次都没被追加：

```
𢦤 ← 基集top1 成 0.9498      𠤎 ← 七 0.9695      𤯝 ← 眚 0.9563
𨒪 ← 速 0.9766 / 0.9755 / 0.9679（三处）
𢰅 ← 擙 0.9477 / 撰 0.9469 / 㨠 0.9441（三处）
```

机制很清楚：**基集里存在一个高分近形**（𨒪 的近形是 速、𠤎 的是 七），
分数高不代表答对，只代表"基集里有个长得像的"。北行日錄标 0.85 时，
那批漏字的近形在基集里可能不那么像，所以阈值管用；vol02 这几个字的近形太像，
阈值就整个失效。

**这不是要改阈值**——模块头已经证过分数分不开命中/未命中，把 0.85 提到 0.95
只会让升级率飙到接近 100%，等于取消基集（而基集存在的理由是防抢答，实测 −2.1 top-1）。

可能的方向（都没验证，留给你判断）：
- 升级判据不看绝对分，看**基集 top-1 与 top-2 的差**（近形扎堆时 margin 小）；
- 或按**字形复杂度/笔画数**：扩B 多是繁复异写，基集近形往往笔画更少；
- 或干脆对「库里没有该字头且 db_verdict=unsure」的位无条件升级（这批只占全书 0.15%，
  代价可控）。

复现：`scratchpad/sub_other.json` 是那 46 条的明细（本会话产物，非仓内文件）；
判据是 `not ref_in_pool and ref not in glyphs.char`。

---

## 历史（2026-02 下发，已归档）

- Volume 1（ce01）OCR pipeline 与夹注检测：已完成。
- Volume 2：已处理，等 guji-platform merge。
- Volumes 2–10（06064238.cn ~ 06064246.cn）：挂起。
