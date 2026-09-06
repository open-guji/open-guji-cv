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

## 历史（2026-02 下发，已归档）

- Volume 1（ce01）OCR pipeline 与夹注检测：已完成。
- Volume 2：已处理，等 guji-platform merge。
- Volumes 2–10（06064238.cn ~ 06064246.cn）：挂起。
