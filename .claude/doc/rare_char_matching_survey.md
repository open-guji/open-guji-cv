# 生僻字匹配调研：5a 没有精准匹配之后，那条路现在长什么样（2026-09-21）

> 用户问：「5a 没有精准匹配时，在更大的字形库里搜索可能字形的手段」——先看
> 文档、了解现在的流程。本文是**盘点 + 缺口 + 建议**，不动一行算法代码。
>
> 口径声明：凡标「实测」的数字**一律抄自已有文档/模块头**，出处逐条给到
> 文件与小节；凡标「本轮核到」的，是这次读代码用 grep/阅读直接确认的事实。
> 本机（云端容器）**没有 torch、没有 workspace、没有 cache/**，所以本轮
> **一个实验都没跑**，没有新数字。

---

## 0. 一句话

**这条路早就修通了，而且比设计稿走得远**——Step5-b `rare_candidates` 已是正式
Step，三源 RRF（库字体域 + CNN 分类头 + CNN embedding 对全字表模板检索），
按册配基集/阶梯/白名单，整页批处理 1.5 s/179 字。真正的空白**不在算法，在三处
接线**：5a 与 5b 没有级联、下游（Step6/C1）根本不读 5b 的候选、**人裁过的真刻例
进不了 5b 的模板**；外加一条从未落地的能力：**IDS 结构检索（L2）与无码字出路**。

---

## 1. 现在的流程（代码级，本轮逐个文件核过）

```
Step4 cell_shrink ─ 字块 patch
   ├─ 5-a  glyph_match     库匹配（真刻例）→ same / unsure / diff + cov 证据
   ├─ 5-b  rare_candidates 生僻字候选 top-k          ← 本文主角
   ├─ 5-c  ocr_candidates  RapidOCR CTC top-k
   └─ 5-d  align_ref       整理本对齐
Step6 context_decide  上下文裁决（读 5-a + 5-c，**不读 5-b**）
C1    seed_admit      进库准入（读 5-a/5-c/5-d/Step6，**不读 5-b**）
```

### 1.1 5-a 判什么才叫「没有精准匹配」

`steps/glyph_match.py` 模块头：

| 档 | 条件 | 规模参考 |
|---|---|---|
| same | cov ≥ 0.996 且 wmax ≤ 12；或共识升档（cov ≥ 0.99 + 甩开异字 0.03 + 该字 ≥3 例人裁） | vol01 稳态 cov ≥ 0.99 占 **92.5%**（external §5.9）|
| unsure | 0.85 ≤ cov < 0.996 | 候选带 cov 当先验交 Step6 |
| **diff** | 全部 kNN 候选 < 0.85 | **「库里多半没这个字」——5-b 要接的正是这一档** |

「没精准匹配」的量级是**随册衰减**的：vol01 人审率 1.94% → 0.11%，vol02
8.78% → 2.17%（variant_strategy 2026-09-08 台账）。但**换一本书库从零开始，
所有字一开始都是 diff**（pipeline_review_2026-09-04 §4.1），这才是 5-b 的主战场。

### 1.2 5-b 实际做的事（`steps/rare_candidates.py` → `clustering/rare_panel.py`）

1. **取哪些字位**：整页全部 `cell_type=="char"` 的格，**不看 5a 判决**
   （前端注释明写「不逐字位限定，全字位批处理」）。格级复用 `core/reuse.py`。
2. **归一化**：`normalize_patch` → 64² 二值，与 5-a 同一把尺子（`norm_stroke` 随册）。
3. **三路检索**（`rare_panel._fuse`）：
   | 源 | 查的是什么库 | 字表边界 | 权重 |
   |---|---|---|---|
   | `font` | `glyph.db` 里**本册标定的字体域**（`font.editions`，走 `GlyphMatcher`，与 5-a 同一套 kNN）| 字体 cmap | `CNN_WEIGHT` |
   | `cnn` | CNN 分类头 logits | **只在 4,654 classes 内** | `cls_gate_weight` 动态门控 |
   | `emb` | CNN 256-d embedding 对**模板矩阵**做余弦 | 基集 ∪（低分时）升级档 | `EMB_WEIGHT`（现 4）|
   融合用 RRF（只看名次，不看分数——余弦与 softmax 不同量纲）。
   `HOG_WEIGHT=0`，CNN 可用时**根本不跑 HOG**（vol01 1,934 字实测零差异）。
4. **模板矩阵怎么来**（`cnn_candidates._emb_index`）：每个字 = **5 个字体档**
   （I.Ming ＋ Jigmo 1/2/3 ＋ TypeLand 康熙字典体，`FONT_ORDER` 三个目录）渲染出的
   embedding 均值，落盘 `emb_<key>.npz`。
   外部真刻本模板 `EMB_EXTRA_SPECS` **现为空元组**（2026-09-08 起改用康熙体 OTF）。
5. **字表三件事**（`charset_spec.py`，2026-09-17 加，按册配）：
   - `base` 基集 = 候选的**可达性上界**（缺省 `unicode-cjk-a` 27,584 + 整理本 + 异体展开）；
   - `escalate` 阶梯 = 基集 top-1 分数 < 阈值时**追加**扩B（42,720），**按分数归并**同台排序；
   - `allow` 白名单 = OpenCC `s2t(ch)!=ch` 判简体并否决，本册语料用过的字无条件放行。
6. **候选修饰**：IDS 拆字 / 本书频次 / 码点 / gloss 释义首句 + 拼音 / 整理本对应正字
   `std` / zi.tools 深链——就是为了消掉用户「开字统网查一趟」那个动作。
7. **产物与指纹**：`products/<book>/rare_candidates/p####.json`；指纹带
   checkpoint mtime + 模板集 stamp + `book.font`（阈值不进指纹曾导致全书
   「新鲜，跳过」的静默失效，已修）。
8. **界面**：`/api/rare/{book}/{page}/{col}/{slot}`、`/api/rare/batch`，控制台
   Step5-b 面板；审字卡片候选固定位次 **1 整理本 · 2 库最佳 · 3 生僻字算法 · 4/5 库次选**
   （variant_strategy 2026-09-06（五））。

---

## 2. 「更大的字形库」现在有几层（资产盘点）

| 层 | 规模 | 落点 | 谁在用 | 备注 |
|---|---|---|---|---|
| 本书真刻例 | vol01/vol02/zongmu/book9 四份 jsonl | `glyph_store/`（随仓）→ `glyph.db` | **5-a 唯一放行依据** | 跨书共享刻例库**尚不存在**（CLAUDE.md 已记）|
| 字体域（库内 `kind='font'`）| I.Ming + Jigmo（Unihan 十万字）| `fonts/` 字体档随仓，确定性重建 | 5-b `font` 源 | Jigmo CC0 / I.Ming IPA，可再分发；**康熙体是商业字体**（TypeLand），进可分发产物前须确认授权 |
| CNN classes | **4,654 类** | `models/glyph_cnn_r5/best.pt` | 5-b `cnn` 源 | **类外 top-1 恒 0**，扩字表收益全由 emb 兑现 |
| emb 模板字表 | 基集 ≈29 k / 升级档 42.7 k / 全档 **70,304** | 字体渲染现算 + `emb_*.npz` | 5-b `emb` 源 | **这才是「最大的那个库」** |
| IDS 拆字表 | **102,032 字**（yi-bai/ids，MIT）| `config/ids/ids_lv1.txt` | **只当护栏**，不检索 | 见缺口 G4 |
| 释义/正字 | gloss 69,835 字、variants 47 k 关系 | `config/gloss/`、`config/variants/` | 候选修饰 | |
| 外部真刻本图 | 字统网 43,081 张 / 自切康熙 32,899 张 | `D:\data\glyph-sources\`（**不在仓，本机没有**）| 曾进模板与 r4 训练，**模板路已下线** | 授权已裁定可自由使用（external §6）|
| MTHv2 / TKH | 2.2 万页级 | 未下载进本项目链路 | — | 科研授权，glyph_db_expansion §8 |

---

## 3. 实测账（只抄有出处的，注意口径互不可比）

| 靶子 | n | 指标 | 值 | 出处 |
|---|---|---|---|---|
| `unseen`（bench，**100% 落在 classes 内**）| 1,327 | emb top-1 严格 | r4 95.4 → **r5 96.9** | `cnn_candidates.DEFAULT_CKPT` |
| **`oov_bench` 类外真刻例** | 314 | emb top-1 / top-10 | r4 67.8/89.2 → **r5 73.2/90.4** | 同上；集的来历见 `scripts/build_oov_bench.py` |
| 北行 383 条**用户裁决** | 383 | 不升级 top-1/top-10 | 75.5 / 94.3 | `charset_spec` 模块头阈值扫描 |
| 同上，阶梯 0.85 | 383 | top-1/top-10 | **76.8 / 96.3** | 同上（甜点） |
| 同上，**换 r5 之后** | 类外子集 | 册配置门 top-1 | **40.6**，平字表不设门 53.6 / top-10 97.1 | `experiments/metric_loss/calib_escalate.py` 模块头 |
| `rare-char` | 21 | top-10 | 100 | external §5.3；**已知全落 classes 内，参考价值有限** |
| 组内定形 `fixed_form` | — | 放行率 / 错 | r5 + gap 0.03：**77.4% 零错** | `cnn_candidates.DEFAULT_CKPT` |
| C 刀验收（历史） | rare-char 真难题档 | top-10 召回 | 0% → **78.6%**，命中时中位名次 1 | pipeline_review_2026-09-04 §0 |

**两条读法纪律**（沿用 step5_step6_benchmark）：
- 5-b 的 KPI 是 **top-10 命中率**，不是 top-1——它只出候选，永不放行；
- 报数必须分层：**「5-a 给不出、OCR 够不着」那一档才是真难题**，混进常用字会虚高。

⚠️ 上表第 3/4 行与第 5 行**不能连读**：前者是 383 条全体（含类内）且是 r4 时期的
阈值扫描，后者是 r5 下的类外子集。**换 checkpoint 必须重标 `escalate_threshold`**
（bxgb 已由 0.85 改 0.95）——这是这条线最容易出的口径事故。

---

## 4. 已经证伪的路（别重走，全部有实测案底）

1. **字体渲染不能当精确判据**：四套字体「对/错」f1 分布完全重叠，无阈值可分
   → `GlyphKnnSource` 锁死 `kinds=("woodblock",)`（glyph_db_expansion §6.2）。
2. **大表直接并进小表**：rare-char 21 条上 top-1 **43% → 29%**；本书频次加权
   top3 67→33；异体身份加权 67→62；相似度闸控扩表从不触发（`routers/rare.py`）。
3. **阶梯用拼接不用归并**：阈值 0.80→1.0 扫一遍**一个点都不涨**（RRF 只看名次）。
4. **「最高分低才升级」单独不成立**：命中 p10=0.798 vs 未命中 p90=0.896，重叠。
5. **康熙收字表挡不住简体**（国/学/体/这/说 都在表里带页码）；有判别力的是 OpenCC。
6. **HOG 在 CNN 可用时零贡献**（vol01 全量逐字比对零差异）。
7. **度量损失（ArcFace/CosFace/纯余弦头）在真刻例上一律为负**；真正涨点的是
   训练轮数 160 → 60（`experiments/metric_loss/README.md`）。
8. **类外评测集靠字典源撑大会把结论带反**（大集 margin 为正、真刻例集为负）；
   **字统网模板不限书体会变成跨书体识别**（基线被压到 34.7%）。
9. **自切康熙扫描图 ≯ 康熙字典体 OTF**：96.0 vs 96.4，赢在覆盖率 100% vs 76%，
   不是还原度；但**康熙体不能单用**（只留它掉到 94.5%）。
10. **CNN 不能替代 OCR 当第二路**：两路同错 3.2%，在 dual 场景会一致地错 → 静默误放行。
11. **IDS 当匹配器/放行判据不行**，只当护栏；形近题上字形层 top-1 64.3% **低于**
    多数类基线 76.0%（confusable-context 154 题）。

---

## 5. 缺口（本轮读代码核到的，按影响排序）

**G1 · 5-a 与 5-b 没有级联，产物也没有分层标记。**
设计稿写的是「只在三种情况调用：库 unsure 且 cov<0.95 / OCR 不可达 / 用户点生僻字」
（pipeline_review §4.3 L1），实现是**全字位无条件跑**。算力上无所谓（1.5 s/页），
问题在**量不出来**：`RareRec` 里没有该字位的 5-a 档位/cov，于是「真难题档 top-10」
这个 KPI 没法从产物直接算，只能另起脚本对账（`experiments/metric_loss/reconcile_bxgb.py`
就是这么干的）。

**G2 · 下游一行都不读 5-b。**
`grep -rn "rare_candidates\|PageRare"` 全仓核过：消费者只有测试、backfill 脚本、
两个实验脚本和前端面板；`context_decide` 与 `seed_admit` **都没接**。也就是说
5-b 目前**只降低人裁耗时，不提高自动率**——而 `rare_candidates.py` 模块头写的
预期是「Step6 融合与 Step7 通道才能直接读它」。这是文档与实现的一处落差。

**G3 · 人裁过的真刻例进不了 5-b 的模板。**
`_emb_index` 的模板只有字体渲染（`EMB_EXTRA_SPECS` 空）。后果：一个生僻字被人
裁过一次，5-a 在**本工作区**能认它，但 5-b 的排序照旧靠字体模板；换一本书、
换一个工作区，这份人裁经验对候选召回**完全不起作用**（跨书刻例库也还不存在）。
零样本调研把这条列为「**最高杠杆，一天**」的 A 项（zero_shot_ccr_survey §五.A），
至今未做。

**G4 · IDS 只有护栏，没有检索（L2 从未落地）。**
`ids_guard` 提供 `ids_of / components / structure / component_distance / is_near_form`，
**没有倒排索引**。所以「⿰言?」式的结构召回、部件一致性重排（zero_shot §E 的
Top-30 精排，标价半天）、以及「候选里一个都不对时人怎么办」都还是空白。

**G5 · 无码字没有出路。**
设计里的「IDS 编辑器 → 待造字表」没实现；方向已定为**不造 PUA、用图像 + IDS 记录**
（variant_strategy §1.2）。`report/witness.py` 现在只在输出流里留 PUA 缺字符占位。

**G6 · 靶子太薄，且不在仓里。**
`rare-char` 只有 21 条且全落 classes 内；`oov_bench` 314 条在 `cache/`（不进 git）；
**最真实的靶子是北行 383 条用户裁决，但它没有登记成金标分片**。step5_step6_benchmark
§3.2「缺口 3：生僻字没有任何测试集」这条**只补了一半**。

**G7 · `fonts/genmin/` 三套字体全仓零引用。**
`GenRyuMin2TC / GenWanMin2TC / GenYoMin2TC`（源流/源云/源样明朝，传承字形）躺在
`fonts/genmin/` 里，**`FONT_ORDER` 没有它、全仓 grep 一处引用都没有、文档也没提**。
而这条线上已有的实测恰恰说「多套字体『同字多写法取平均』的作用一套顶不了」
（只留康熙体会从 96.4 掉到 94.5，`font_candidates.FONT_ORDER` 注释）。加三套进模板
是**改一行常量 + 重建索引**的事，值不值得要量一下（也可能是当初有意排除，但没留记录）。
⚠️ 该目录**没有随附 LICENSE**，启用前先补授权文本。

**G8 · 阈值绑 checkpoint × 绑册，重标脚本还在 `experiments/`。**
`calib_escalate.py` 不是生产命令，没有 `eval`/CLI 入口。换书或换模型时若忘了重标，
表现是**候选静默变差而不是报错**（r5 上类外 top-1 因此少 13 个点）。这类
「降级路径不出声」的病，这条线上已经犯过至少四次（`cnn.available` 悄悄 False、
空 emb 索引落盘、字体目录按 cwd 找、阈值不进指纹），值得单列一条纪律。

---

## 6. 建议路线（按性价比排；每条给验收口径，都不碰放行纪律）

| 序 | 动作 | 工作量 | 主指标 | 护栏（不许退） |
|---|---|---|---|---|
| R1 | **5-a 档位写进 5-b 产物**（`RareRec` 加 `match_verdict`/`cov`），报数按 diff / unsure<0.95 / 其余分层 | 半天 | 真难题档 top-10 可从产物直接算 | 候选内容零变化（位级比对）|
| R2 | **真刻例原型进 emb 模板**：每字模板 = 字体渲染均值 ⊕ 库内人裁刻例均值；模板源取 `glyph_store` 全书而非当前工作区 | 1 天 | `oov_bench` 314 条 emb top-1（现 73.2）；北行未审段 top-10 | `unseen` 严格 top-1 ≥96.9 不掉；模板集进指纹 |
| R3 | **下游消费 5-b**：Step6 把 5-b 候选并入候选池（只补池、不投票）| 半天 | 人审率；候选可达率 | **5-b 与 5-a 同源（都看图），不得互证放行**；harmful_flip ≤1.2% |
| R4 | **L2 便宜版：Top-30 部件一致性重排**（IDS 倒排 + 部件头一致性打分）| 半天–2 天 | 真难题档 top-1 / top-10 | 不改任何自动放行决定；K≥30 才不丢召回 |
| R5 | **把北行 383 条 + `oov_bench` 登记成 `rare-char` 分片**（分层：类外 / 三路无候选 / 有码无候选），`calib_escalate` 提成正式 `eval` 子命令 | 1–2 天 | 换册换模型一键重标 | 金标分层报（human / align 不混）|
| R6 | **试 `fonts/genmin/` 三套进模板**（G7）：`FONT_ORDER` 加一项、重建 emb 索引 | 1 小时 + 一次评测 | `oov_bench` / 北行 top-1 | `unseen` 不掉；先补 LICENSE |
| R7 | **无码字通道**：IDS 描述 + 图像落账，不造 PUA | 观察 | 无码率 | 只记录，不进字表 |

顺序建议 **R1 → R5 → R6 → R2 → R3 → R4**（R6 最便宜，顺手做）：先让数能量出来（R1/R5），再动模板（R2），
最后才谈接进决策链（R3/R4）。这与 handbook §3 P1「先建集再动手」一致——R2 之前
如果没有 R5 的分层靶子，涨没涨只能靠感觉。

---

## 7. 一条口径提醒

这条线上所有「候选质量」的数字，**都必须连着可达性一起读**：候选排得再好，
答案不在字表里就是零（北行换基集前 22.5% 的答案压根不在池子里，
`scripts/build_charset.py` 管这叫**可达性上界**）。所以评 5-b 要报三个数而不是一个：

```
可达率（答案在 base ∪ escalate 里吗） × top-10 命中率（在池里能不能捞到）
                                      × 真难题档占比（这一档有多大）
```

---

## 附：本轮读过的东西

代码：`steps/rare_candidates.py`、`steps/glyph_match.py`、`steps/seed_admit.py`、
`clustering/rare_panel.py`、`clustering/cnn_candidates.py`、`clustering/font_candidates.py`、
`clustering/charset_spec.py`、`clustering/ids_guard.py`、`console/routers/rare.py`、
`console/routers/glyph_match.py`、`console/frontend/src/pages/Step5Page.tsx`、
`pipelines/keben_body_v2.yaml`、`experiments/metric_loss/*`。

文档：`step5_step6_benchmark.md`、`pipeline_review_2026-09-04.md`、
`external_glyph_sources_experiment.md`、`glyph_db_expansion_research.md`、
`zero_shot_ccr_survey.md`、`glyph_set_roadmap.md`、`variant_strategy.md`、
`glyph_db_first_design.md`、`glyph_match_stack.md`。
