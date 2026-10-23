# Step5 / Step6 / Step7：现在各做哪些操作

> 2026-10-18，Emerson，依据 `open_guji_cv/steps/*.py` 模块头与 `SeedAdmitParams`。只读代码整理，没有跑实验。步骤编号取自 Step 的 `title`（有些旧文档编号不一致，以代码为准）。

## 总览

```
Step4 字框收缩
  ├─ Step5-a glyph_match     字块 ↔ 字形库比对            →「形状」证据
  ├─ Step5-b rare_candidates 字体模板+CNN 生僻字候选      →「生僻字」证据
  ├─ （Step5-c ocr_candidates 已删（2026-10-18，sheldon 定））
  └─ Step5-d align_ref       定字串对位整理本             →「文本」证据
Step6  context_decide        候选 + 同列前文 → 门槛化重排
（Step6b group_decide 已删（2026-10-18，sheldon 定））
Step7  seed_admit（C1 进库准入） 综合所有信号 → 放行 / 送审
```
Step5 三路（原四路，5-c 已删）互相独立、并行收集证据；Step6 只在候选内重排；**只有 Step7 决定放行与否**。

## Step5：四路取证（不做定字）

| 步 | 做什么 | 要点 |
|---|---|---|
| **5-a `glyph_match`** | 字块与 GlyphDB 已验证字形比对：HOG kNN＋弹性对齐验证＋形近家族护栏 | 三档：same（cov≥0.996 且 wmax≤12）、unsure（0.85≤cov<0.996，进候选）、diff（<0.85，库里多半没有）。**共识升档**：unsure 里 top 字 cov≥0.99、比次优异字高≥0.03、且该字已有≥3 例人裁，升 same。产物指纹带库内容指纹，库变了会过期 |
| **5-b `rare_candidates`** | 字体模板＋CNN 分类＋CNN embedding 三源 RRF 融合 top-k | 整页批处理；checkpoint 缺席不炸，退回纯字体候选；指纹带 checkpoint 与模板集 |
| ~~**5-c `ocr_candidates`**~~ | **已删（2026-10-18，sheldon 定）**。原：RapidOCR（PP-OCRv4）CTC top-k＋简→繁扩展 | 下游 5-d／6／7 的 OCR 一路恒缺席（等价于原先开关关着）|
| **5-d `align_ref`** | 把定字串对位到整理本，出逐字位 `{align_char, align_op, ref_run}` | 现役两种：①8-gram 锚定＋`difflib`；②`align: coord` 坐标对位（按列→行、按几何行号逐格配字，印章压住时也能配，格数对不上退回①）。锚定串取每位 glyph_match（5-c 已删，原还比 ocr）里信度最高者，不依赖 Step6 |

## Step6：上下文裁决 `context_decide`
- 输入：库候选＋同列前文（OCR 候选随 5-c 已删），输出 `context_decision`。
- 两条铁律：**字形层不可改写**（只在候选内重排）；**门槛化**（语义 margin 过 0.70 才动手，不做全局重排）。
- 语言模型：本书 3-gram 0.9＋通用 0.1 线性插值；上下文只看前文，按阅读顺序（夹注先 a 后 b），跨列不接。指纹带语料。
- 可选线上大模型（缺省关）：`gated_ngram` 过不了 margin 才问；**只调候选顺序，不自动放行**；每次调用记日志。
- ~~**Step6b `group_decide`**~~：**已删（2026-10-18，sheldon 定）**。原为形近字组 `group_clf/1` 答案表出口，只出证据、缺省关、无书开、无下游读；答案表读法留在 `groups/backends.GroupClfTableBackend`。

## Step7：`seed_admit` 放行判定

### 核心
包的是 `clustering/seeding.admission_decision`（十条通道，逐轮由 2600+ 条真实裁决定型）。四条原则：整理本在场有一票否决权；OCR 只供候选；库匹配按 cov 分档采信（0.99 是拐点）；凑双信号要误差独立（文本×形状可以，OCR×形状不行）。

### 通道（已知的，非穷举）
`match_solo`（无整理本＋cov≥0.99）、`match_ref`、`match_replace`、`dual`（OCR×整理本）、`ref_lib`、`ref_ctx`、`context`、`iron`（铁证：与人裁过的别格实例比对）、`human`（事件里人裁）、`match_margin`，另有下面「补放」通道。

### 补放与规则（多数缺省关，按册开）
| 类 | 开关 | 作用 |
|---|---|---|
| 异体 | `variant_tie`（`variant_tie_extra`） | 异体并列放行，见前文 |
| 数字卷 | `juan_rule` | 数字＋「卷」放行 |
| 待审补放 | `lane_witness3`、`lane_coord`、`lane_seal`、`seal_lib_agree` | 三证人一致、坐标对位兜底、印章区 |
| 形近字组 | `ji_yi_si_*`、`ry_group`、`rr_clf`、**`m7_groups`／`m7_l2_tables`／`m7_bars`** | 己已巳、日曰、入人八的各路；M7 上下文路与量横 |
| 稀见 | `rare_ref`、`rare_cp_ctx_review` | 5-b×整理本放行；罕用码位×context 落审 |

### 闸（拦放行或转人审）
遮挡/印章（`occluded_gate`，缺省开）、context 乱码/空白/窄格/单笔画等护栏、`ref_lib_variant_guard`、`variant_indirect_guard`、铁证的整理本互证与形近闸、`shadow_veto`、`approx_gate`、`always_review`（己已巳不采信字形/OCR 通道）。

### 产物与回流
落成 numeric 产物，供审查页与 `glyphdb_admit` 消费；人裁事件（Step8）回流后会让 Step7 对应格判过期重算。

## 与 M7 的位置关系
- 上下文路、量横、`variant_tie` 都在 Step7，且都排在「正常通道未放行」之后。
- IDS 路未接任何一步（离线脚本）。
- 改 Step7 的开关会让 `seed_admit` 的 `code_hash` 变。
