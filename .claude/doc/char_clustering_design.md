# 刻本古籍字符聚类识别系统 — 详细设计

> Phase 4~7：字符提取 → 保守聚类 → OCR 候选 → 上下文排序 → 人工审查 → 反馈训练 → 跨书字形库

## 1. 目标与核心思路

针对**刻本**古籍的一个关键先验：同一书版中同一个字是同一枚刻字反复印出来的，
字形几乎完全一致（差异仅来自磨损、着墨、纸张噪声）。因此可以：

1. 从古籍页面中切出所有单字图块（复用 Phase 3 字符网格的位置信息）；
2. 用**保守聚类**把"确定是同一个字"的图块聚成一类 —— 宁可把同一个字拆成多类（碎片化），
   也绝不把不同的字合进一类（污染）；
3. 对每一类只需识别少数代表样本 → 一次标注/识别惠及全类所有实例；
4. 利用切分时保留的**位置与顺序**信息，把每列还原成候选字格子（lattice），
   用古文语言模型做上下文概率排序；
5. 把可疑字排队交给用户审查，审查结果回灌到聚类阈值、识别器和语言模型；
6. 确认后的"字形-标签"对沉淀为**字形库**，识别下一本书（尤其同一书版/同一刻工体系）时直接命中。

### 设计原则

- **模块化**：每个阶段是独立模块，有明确定义的输入/输出 JSON 契约，可单独运行、单测、benchmark。
- **纯函数核心 + 薄 IO 壳**：算法核心不做文件读写，便于单测；CLI/pipeline 负责 IO。
- **保守优先**：聚类指标以 purity（纯度）为硬约束（目标 ≥ 99.9%），碎片率是可优化的软指标。
- **字形层/语义层分离**：标签、候选、字形库、最终转写全部工作在**字形层**——异体字
  （爲/為、逰/遊…）是不同的字，精确区分、绝不合并；**语义层**（异体字→通行繁体正字的映射）
  只作为辅助注记供语言模型理解上下文与用户阅读，语言模型无权改判异体字形。
- **一切可复算**：每个模块输出带版本号和参数快照，任何一步可用新参数重跑而不影响上游。
- **反馈闭环**：人工确认的标签是全系统最高优先级信号，用于阈值标定、分类器训练、语料扩充。

## 2. 与现有管线的关系

```
现有:  s0 profile → s1~s6 预处理 → Phase2 版面(列结构) → Phase3 字符网格(cells)
                                                              │
本设计:                                                        ▼
  Phase 4  字符提取     phase3 cells + s6 二值图/s4 灰度图 → 单字图块数据集
  Phase 5  保守聚类     单字图块 → 聚类结果 clusters.json
  Phase 6  识别与排序   聚类代表 → OCR 候选 → 列 lattice → 上下文后验
  Phase 7  审查与反馈   可疑队列 → Web 审查 → 标签 → 字形库/阈值/模型更新
跨书持久:  GlyphLibrary  glyph_store/（独立于 output/bookX/，跨书共享）
```

Phase 3 输出的 `cells[]`（`char`/`empty`/`margin`，含 `index`、`y_top/y_bottom`、列号）
天然携带了阅读顺序（列从右到左、列内从上到下），是本系统位置/顺序信息的唯一来源，
Phase 4 之后不再接触整页图像的几何解析。

## 3. 总体架构与数据流

```
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 4: CharExtractor (M1)                                            │
│   phase3_char_grid/*.json + s6/s4 图 → chars/patches/ + chars/index.jsonl │
└──────────────────────────┬─────────────────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 5: Normalizer+Features (M2) → ConservativeClusterer (M3)         │
│   patches → 归一化图 + 特征向量 → 粗分块 → 两两配准验证 → 全连接合并      │
│   输出 clusters.json + 每类蒙太奇图                                      │
└──────────────────────────┬─────────────────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 6: CandidateGenerator (M4) → ContextRanker (M5)                  │
│   每类代表样本 → PaddleOCR top-k + 字形库 kNN → 类级候选分布             │
│   列 lattice + 古文 LM beam search → 每字后验 + 可疑标记                 │
│   输出 candidates.json / ranked.json / suspects.json                    │
└──────────────────────────┬─────────────────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 7: ReviewUI (M6) → FeedbackLoop (M7)                             │
│   审查队列 → 确认/改判/拆类/并类 → labels.jsonl                          │
│   labels → 阈值标定 / kNN 训练 / (可选)rec 微调 / LM 语料 → 重跑 5/6      │
└──────────────────────────┬─────────────────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ GlyphLibrary (M8, 跨书)                                                 │
│   确认标签 → glyph_store/ 字形条目（图块+特征+出处+版本）                 │
│   识别新书时：先 kNN 命中字形库，再回退 OCR                              │
└────────────────────────────────────────────────────────────────────────┘
```

### 反馈信号矩阵

| 信号来源 | 去向 | 作用 |
|---------|------|------|
| M6 确认标签（同类/异类对） | M3 | 标定验证阈值 θ：在标注对上算 same/diff 相似度分布，取满足 purity≥99.9% 的最紧阈值 |
| M6 确认标签（字→图块） | M8 | 入库为字形条目 |
| M8 字形库 | M4 | kNN 第一优先识别源，OCR 降级为回退 |
| M6 确认文本（整列/整页） | M5 | 追加进领域语料，重训 n-gram，提升同类书排序 |
| M5 后验与 OCR 分歧 | M6 | 生成可疑队列（审查优先级） |
| M3 碎片化统计（同字多类） | M2 | 提示特征/配准不足，驱动特征后端升级或参数搜索 |
| M6 拆类操作（人工发现污染） | M3 回归集 | 该对样本进入"永久回归测试对"，防止阈值放松后旧错复发 |

## 4. 核心数据模型

### 4.1 全局字符实例 ID（CharInstanceId）

```
{book}:{page}:{col}:{idx}        例: book1:3:2:14
```

- `page`：页面文件 stem（拆分半页后如 `1_right`）；
- `col`：Phase 2 列编号（从右到左，1 起）；
- `idx`：Phase 3 cell 的 `index`（char 与 empty 共享的编号序列）。

此 ID 是四个 Phase 之间引用字符的唯一外键，天然编码了阅读顺序：
`(page, col, idx)` 字典序即文本顺序（col 需按数值升序 = 从右到左）。

### 4.2 目录布局

```
output/bookX/
  phase4_chars/
    index.jsonl                 # 每行一个 CharInstance（见 5.1）
    patches/{page}/{col}_{idx}.png    # 原始裁切图块（灰度，含少量 padding）
    meta.json                   # 参数快照 + 统计
  phase5_clusters/
    features.npz                # 归一化图块堆叠 + 特征矩阵（与 index.jsonl 行对齐）
    clusters.json               # 聚类结果（见 6.4）
    montage/{cluster_id}.png    # 每类蒙太奇（审查/调试用）
    meta.json
  phase6_labels/
    candidates.json             # 类级候选分布（见 7.3）
    ranked.json                 # 上下文排序后每实例后验（见 8.4）
    suspects.json               # 可疑队列（见 8.5）
    text/{page}.txt             # 当前最优转写（按阅读顺序，保留精确异体字形）
    text_semantic/{page}.txt    # 辅助转写（异体字→通行繁体正字，便于阅读/检索/比对语料）
    meta.json
  phase7_review/
    labels.jsonl                # 人工反馈事件流，只追加（见 9.3）
    session_state.json

glyph_store/                    # 跨书，仓库级目录（可指定路径）
  glyphs.jsonl                  # 字形条目（见 11.1）
  patches/{glyph_id}.png
  embeddings.npz
  lm/                           # 领域 n-gram 语料与模型
  calib/thresholds.json         # 各特征后端标定过的聚类阈值
  regression_pairs.jsonl        # 人工发现的易混字对（永久回归集）
```

### 4.3 代码布局

```
open_guji_cv/clustering/
  __init__.py
  ids.py               # CharInstanceId 解析/排序
  extractor.py         # M1
  normalize.py         # M2 归一化
  features.py          # M2 特征后端注册表（raw / hog / embedding）
  clusterer.py         # M3 分块 + 合并编排
  verify.py            # M3 两两配准验证（纯函数，重点单测对象）
  candidates.py        # M4
  context_rank.py      # M5 lattice + beam search
  lm.py                # M5 语言模型后端（ngram / masked-lm）
  feedback.py          # M7 标签消费：阈值标定、kNN 训练、语料更新
  glyph_library.py     # M8
  synth.py             # 合成刻本数据生成器（测试/benchmark 用）
  review/              # M6 Web 审查（复用 open_guji_cv/web 的 server 骨架）
    server.py
    static/index.html
```

## 5. M1 — CharExtractor 字符提取

### 职责

把 Phase 3 的逻辑 cell 变成物理图块数据集，并固化顺序/位置元数据。**本模块之后，
下游不再需要读取整页图像与版面 JSON。**

### 接口

```python
@dataclass
class CharInstance:
    id: str                  # book1:3:2:14
    book: str
    page: str
    col: int
    idx: int
    bbox: tuple[float, float, float, float]   # 页面坐标 (x0, y0, x1, y1)
    cell_type: str           # "char"（empty/margin 不提取但记录在 meta 统计中）
    ocr_text: str | None     # Phase3 整列 OCR 对位到该格的字（弱先验）
    patch_path: str          # 相对 phase4_chars/ 的路径

class CharExtractor:
    def __init__(self, padding_ratio: float = 0.08,
                 source_step: str = "s4_deskew"):   # 灰度源；二值图仅用于统计
        ...
    def extract_page(self, page_gray: np.ndarray, grid: dict,
                     book: str, page: str) -> list[tuple[CharInstance, np.ndarray]]:
        """纯函数：输入整页灰度图 + phase3 grid JSON，输出实例与图块。"""
```

### 算法要点

- **裁切源用灰度图（s4_deskew 输出）而非二值图**：二值化损失笔画灰度层次，
  归一化和特征提取阶段需要自己控制二值化参数；bbox 来自 Phase 3（其坐标系即 s6/s4 图坐标系）。
- bbox 外扩 `padding_ratio`（默认 8%），并裁到列边界内，避免切掉笔画出头。
- 记录 `ink_ratio`（黑像素占比）、`h/w` 到 index.jsonl，供 M3 粗分块与异常过滤。
- `empty` cell 不产出图块但计入 meta 统计（转写重建时需要占位）。

### 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `padding_ratio` | 0.08 | bbox 外扩比例 |
| `source_step` | `s4_deskew` | 裁切像素来源步骤 |
| `min_ink_ratio` | 0.01 | 低于视为疑似空格，标记 `suspect_empty` 但仍提取 |

### 测试与 benchmark

- **单测**：构造合成 grid JSON + 合成页面图（`synth.py` 渲染），断言图块数量、bbox 外扩、
  越界裁剪、ID 生成与排序正确性。
- **benchmark**：`python -m open_guji_cv.clustering.extractor --bench data/book1`
  报告：提取吞吐（字/秒）、图块尺寸分布、ink_ratio 分布直方图。
- **不变量**：`len(index.jsonl) == Σ page 各列 char cell 数`；ID 无重复。

## 6. M2+M3 — 归一化、特征与保守聚类

### 6.1 M2 归一化（normalize.py）

每个图块 → 标准形态，消除"位置/大小/着墨浓淡"差异，只留字形差异：

1. 灰度 → Sauvola 局部二值化（参数固定，与 s6 解耦）；
2. 去除边缘毛刺：连通域分析，删除面积 < `noise_area`(6px) 且贴边的组件（界行残留）；
3. 以**墨迹质心**平移居中，按**墨迹外接框**等比缩放到 `S×S`（默认 64×64），四周留 12% 空白；
4. 输出两份：二值归一图（供配准验证），及轻度高斯模糊图（供特征提取，抗锯齿）。

### 6.2 M2 特征后端（features.py）

注册表模式，与 analyzers/preprocessors 的注册表一致，便于横向 benchmark：

```python
FEATURE_BACKENDS: dict[str, type[BaseFeature]] = {
    "raw":  RawDownsample,     # 归一图降采样 16×16 展平，L2 归一 —— 基线，零依赖
    "hog":  HogFeature,        # skimage HOG，对笔画方向敏感 —— 默认
    "emb":  CnnEmbedding,      # 小型 CNN 嵌入（可选，见 M7 训练）
}
```

特征只用于**粗分块与近邻检索**，不作为合并依据（合并只信配准验证），
因此换后端不影响正确性，只影响碎片率和速度。

### 6.3 M3 两两配准验证（verify.py）——保守性的核心

```python
def verify_pair(a: np.ndarray, b: np.ndarray,
                max_shift: int = 3, scales: tuple = (0.95, 1.0, 1.05),
                ) -> PairVerdict:
    """a, b 为 64×64 归一二值图。返回 (score, aligned_shift, verdict)。
    score = 最优配准下墨迹像素的 F1（2*|A∩B| / (|A|+|B|)）。
    """
```

- 在 ±`max_shift` 平移 × 3 档缩放的小网格上搜索最优对齐（64×64 上代价极低，可向量化）；
- 相似度用**墨迹 F1** 而非像素相关：对着墨浓淡（笔画粗细膨胀）比较鲁棒；
  另计 `dilated_f1`（双方膨胀 1px 后的 F1）作为磨损容忍度参考；
- 判决三档：
  - `same`：`f1 ≥ θ_high`（初始 0.80，标定后收紧/放宽）
  - `unsure`：`θ_low ≤ f1 < θ_high` —— **不合并**，但记录为"潜在同类对"供审查/标定
  - `diff`：`f1 < θ_low`（初始 0.62）
- **形近字防线**：即使 `f1 ≥ θ_high`，若差异像素集中在某个连通区域
  （`largest_diff_blob_area / ink_area > 0.06`，如"曰/日"“大/太”的一点之差），降级为 `unsure`。
  这是保守性的关键补丁：整体相似度对"局部一笔之差"不敏感。

### 6.4 M3 聚类编排（clusterer.py）

O(n²) 不可行（一本书数万字），采用 **分块(blocking) → 近邻图 → 验证 → 全连接合并**：

1. **粗分块**：按 `(h/w 比分桶) × (ink_ratio 分桶)` 先粗筛，块内用特征向量建
   kNN 图（`sklearn NearestNeighbors`，k=10）——只有近邻对才进入验证，
   避免明显不同的字做昂贵配准；
2. **验证**：对每条 kNN 边跑 `verify_pair`，保留 `same` 边；
3. **合并**：在 `same` 边图上做**全连接校验的凝聚合并**（complete-linkage 语义）：
   两个候选簇合并前，抽查跨簇样本对（≤ `cross_check_k`=3 对）也必须 `same`，
   否则不合并 —— 防止链式传递污染（A~B, B~C 但 A≁C）；
4. **簇代表**：每簇选 medoid（与簇内平均 F1 最高者）+ 最远成员 + 随机成员，
   共 `n_reps`（默认 3~5）个代表，写入 clusters.json；
5. 单例簇（磨损严重/独字）保留，天然流向审查队列。

**clusters.json 结构**：

```json
{
  "params": {"feature": "hog", "theta_high": 0.80, "...": "..."},
  "clusters": [
    {"cluster_id": "c00042", "size": 137,
     "members": ["book1:1:1:0", "..."],
     "reps": ["book1:3:2:14", "..."],
     "cohesion": 0.91,
     "unsure_neighbors": ["c00107"]}
  ],
  "stats": {"n_instances": 18760, "n_clusters": 2210, "singleton_ratio": 0.31}
}
```

### 参数

| 参数 | 默认 | 标定方式 |
|------|------|---------|
| `theta_high` / `theta_low` | 0.80 / 0.62 | M7 用人工标签标定（见 10.2） |
| `diff_blob_ratio` | 0.06 | 用形近字对（回归集）标定 |
| `knn_k` | 10 | 碎片率-速度权衡，benchmark 决定 |
| `cross_check_k` | 3 | 越大越保守越慢 |

### 测试与 benchmark

- **单测（verify.py 为重点）**：
  - 同图平移/缩放扰动后必须 `same`；
  - 合成磨损（随机腐蚀+笔画断裂，`synth.py` 提供）后仍 `same`；
  - 已知形近字对（曰/日、大/太、干/千、王/玉…渲染自繁体字体）必须不为 `same`
    —— 这组是**永久回归集**的种子，人工审查发现的新混淆对持续追加；
  - 链式污染场景：构造 A~B~C 而 A≁C，断言不合并。
- **benchmark（两级）**：
  - *合成集*：`synth.py` 用繁体字体渲染 N 字 × M 份 + 磨损增强 → 真值已知，
    报告 **purity**（簇内多数标签占比，硬指标 ≥ 99.9%）、
    **碎片率**（每个真实字被拆成的平均簇数）、吞吐（对/秒）；
    合成集使 M2/M3 无需人工标注即可回归测试。
  - *真实集*：对 data/bookX 跑全量，purity 由后续人工审查事件回填统计
    （每次审查改判都是一条 purity 证据），报告簇数/单例率/吞吐。
- **指标基线要求**：purity 是发布门槛；碎片率只影响审查工作量，可迭代优化。

## 7. M4 — CandidateGenerator OCR 候选生成

### 职责

对**每个簇**（而非每个实例）生成候选字分布。簇是识别单元 —— 这是聚类带来的
核心收益：一个 137 实例的簇只需识别 3~5 个代表。

### 候选来源（按优先级）

1. **字形库 kNN（M8）**：代表图块特征在 glyph_store 中查近邻，命中
   （`verify_pair` 达 `same`）则直接给出高置信候选 —— 同一书版再印本可大面积命中；
2. **PaddleOCR 单字识别 top-k**：对每个代表图块调用 rec 模型。PaddleOCR 默认只返回
   top-1，取 top-k 的途径（按实现成本排序）：
   a. 直接读取 rec 模型 CTC softmax 输出，对（去 blank 后的）主导时间步取 top-k 字符及概率
      （需要绕过 `TextRecognizer` 后处理，用 predictor 拿原始 logits —— 封装在
      `candidates.py::PaddleTopK`，是本模块唯一"深入 Paddle 内部"的点，单独隔离+单测）；
   b. 回退方案：对代表图块做 t 次轻微增强（±2px 平移、±3° 旋转、伽马抖动）分别识别，
      汇总出现过的字及频次作为伪 top-k；
3. **Phase 3 整列 OCR 弱先验**：CharInstance.ocr_text 对位字，权重最低（对位可能错位）。

### 聚合

簇内多代表的候选分布做加权融合（权重 = 各来源可靠性 × 识别置信度），输出：

```json
{"cluster_id": "c00042",
 "candidates": [{"char": "通", "semantic": "通", "p": 0.83, "sources": ["glyph_knn", "ocr"]},
                 {"char": "遇", "semantic": "遇", "p": 0.09, "sources": ["ocr"]},
                 {"char": "逰", "semantic": "遊", "p": 0.04, "sources": ["ocr"], "surface_uncertain": false}],
 "source_detail": {"glyph_knn": {"hit": "g_000381", "f1": 0.87}, "...": "..."}}
```

- **异体字不合并（字形层原则）**：本系统的标签体系是**字形层**的——"爲/為/为"是三个
  不同的候选，各自独立计票，绝不归并。刻本的异体字字形本身是有价值的信息
  （版本学/刻工特征），必须精确区分并保留。每个候选同时挂一个**语义层**注记
  `semantic`（经 `config/dicts/` 异体字→正字映射表查得的通行繁体正字，查不到则等于自身），
  仅供 M5 语言模型理解语义使用，不参与候选合并与最终标签；
- **OCR 字表覆盖不足的处理**：PaddleOCR 字表可能不含生僻异体字，对异体字形往往输出
  通行正字——此时该候选的 `char` 暂记 OCR 输出，但标记 `surface_uncertain: true`，
  精确字形以人工审查确认为准（M6 确认后入字形库，后续同版书由 kNN 直接给出精确异体字形，
  不再依赖 OCR 字表）。标签允许任意 Unicode 码位（含 CJK 扩展区）。

### 测试与 benchmark

- **单测**：候选融合逻辑（纯函数）：来源加权、异体字合并、空候选兜底；
  `PaddleTopK` 用录制的 fixture（保存一次真实 rec 输出 npz）离线测试，不依赖 GPU。
- **benchmark**：在人工确认过标签的簇上报告 **top-1 / top-5 命中率**、
  字形库命中率、每簇平均识别耗时。命中率按簇加权和按实例加权各报一份
  （大簇识别对了收益更大）。

## 8. M5 — ContextRanker 上下文概率排序

### 职责

利用阅读顺序把候选分布放回文本流，用古文语言模型重排，输出每个**实例**的后验分布
与可疑标记。注意：同簇实例共享候选分布，但上下文不同 → 后验可以不同；
簇级标签的最终裁决取簇内实例后验的聚合 + 一致性检查。

### 算法

1. **重建文本流**：按 `(page, col asc, idx)` 恢复每列字序列（empty cell 作为可断句提示）；
2. **构建 lattice**：每个槽位放该实例所属簇的候选（top-k，含 `<unk>` 兜底）。
   每个候选携带两层信息：`char`（字形层，精确异体字形，最终输出）与
   `semantic`（语义层，映射到通行繁体正字，仅供 LM 打分）；
3. **beam search 解码（语义层打分，字形层输出）**：
   `score = λ·log P_ocr(char) + (1-λ)·log P_lm(semantic | semantic_context)`
   —— LM 的输入输出全部在语义层进行（语料训练前也做同样的正字化归一，
   否则语料中低频异体字会被 n-gram 判为低概率，反而惩罚正确的异体字候选）；
   同一槽位若有多个候选映射到同一 semantic（如"逰/遊"同现），LM 分相同，
   排序由字形层的 P_ocr（含字形库 kNN 的配准分）决定——**字形之争只由字形证据裁决，
   语言模型无权改判异体字形**。beam 宽度默认 8，λ 默认 0.55（标定见 M7）；
   跨列衔接：同页相邻列首尾相连（古文不分词断句，n-gram 直接跨列滚动是合理近似；
   夹注/表格页面例外，按 profile 关闭跨列）；
4. **后验与边际**：对每槽位输出归一化后验 `p(char)`（键是字形层精确字形）及
   `margin = p(1st) - p(2nd)`。

### LM 后端（lm.py，注册表）

| 后端 | 依赖 | 场景 |
|------|------|------|
| `ngram`（默认） | kenlm，字符级 5-gram | 训练语料：开源古文全文（殆知阁/CText 等电子文本，繁体化后）+ M7 回灌的已确认转写 |
| `masked-lm`（可选） | GuwenBERT/SikuBERT 类模型 | 精排：仅对 suspects 二次打分，控制算力 |

### 8.5 可疑标记（suspects.json）

实例进入审查队列的条件（任一命中，带原因标签）：

| 原因 | 条件 |
|------|------|
| `low_margin` | margin < 0.25 |
| `lm_ocr_conflict` | LM 最优 ≠ OCR 最优且两者都不弱 |
| `singleton` | 所属簇 size == 1（无聚类互证） |
| `cluster_inconsistent` | 同簇实例后验最优字不一致（强烈暗示簇污染 → 优先级最高） |
| `unsure_pair` | 所属簇有 `unsure_neighbors`（潜在应合并） |
| `low_ink` / `damaged` | M1 标记的疑似残损 |

队列按 `预期收益 = 簇大小 × 不确定度` 降序 —— 先审大簇，一次确认收益最大。

### 测试与 benchmark

- **单测**：lattice 构建（empty/跨列/缺字对齐）、beam search 正确性（小词表手工可验算例）、
  后验归一化。LM 用 3 行玩具语料训练的微型 n-gram 做确定性测试。
- **benchmark**：在有真值转写的页面上报告：
  重排前后 top-1 准确率提升、suspects 的**召回率**（真实错误中被标可疑的比例，目标 ≥ 95%）
  与**误报率**（审查工作量），解码速度（字/秒）。

## 9. M6 — ReviewUI 人工审查

### 职责

以最小人力消化 suspects 队列，产出机器可消费的标签事件流。复用
`open_guji_cv/web/server.py` 的本地 HTTP 骨架，新增 `clustering/review/`。

### 交互设计（三个视图）

1. **簇视图**（主力）：蒙太奇网格展示整簇 + 当前候选与后验；操作：
   - ✅ 确认标签（一键给全簇 size 个实例打标 —— 审查效率的来源）；
   - ✏️ 改判为其他字（输入或从候选点选）。**标签必须是精确异体字形**：输入某字时
     UI 自动展开其异体字组（来自 `config/dicts/` 映射表 + 字形库中已有字形），
     并排显示各异体字的标准字形与本簇 medoid 图块对照，用户点选精确形体；
     生僻字支持直接输入 Unicode 码位或 IDS 描述式；界面同时以灰字显示 semantic 正字作辅助；
   - ✂️ 拆簇：框选不属于本簇的成员移出（生成 `split` 事件 + 一条回归对）；
   - 🔗 并簇：对 `unsure_neighbors` 并排展示，确认合并（生成 `merge` 事件）。
2. **上下文视图**：点击任一实例 → 显示该字在原页的裁切上下文（前后各 3 字 + 整列缩略），
   解决"孤立看图认不出"的问题；位置数据直接来自 CharInstance.bbox。
3. **队列视图**：suspects 按预期收益排序，显示原因标签；支持按原因过滤。

### 9.3 标签事件流（labels.jsonl，只追加）

```json
{"ts": "...", "op": "confirm", "cluster": "c00042", "char": "通", "scope": "cluster"}
{"ts": "...", "op": "relabel", "instance": "book1:3:2:14", "char": "遇"}
{"ts": "...", "op": "split",   "cluster": "c00042", "moved": ["book1:5:1:3"], "reason": "different_char"}
{"ts": "...", "op": "merge",   "clusters": ["c00042", "c00107"]}
{"ts": "...", "op": "mark",    "instance": "...", "flag": "damaged|empty|illegible"}
```

事件流是唯一真源；当前标注状态 = 重放事件流。好处：可撤销、可审计、
M7 的所有训练数据都从这里派生，且天然增量。

### 测试

- 事件重放器（纯函数）单测：乱序/冲突事件（先 confirm 后 split）的最终状态确定性；
- server 层用 HTTP 集成测试（无浏览器）：队列拉取、事件提交、幂等性。

## 10. M7 — FeedbackLoop 反馈更新

### 职责

消费 labels.jsonl，更新四类下游资产，并驱动重跑。所有更新都是**离线批处理命令**，
显式触发（`update` 子命令），不做隐式魔法。

### 10.1 标签派生数据

从事件流重放得到：`instance → char` 真值表、`same-pair`（同簇确认对）、
`diff-pair`（split/形近改判产生的异类对）。

### 10.2 聚类阈值标定（→ M3）

在 same/diff 对上计算 `verify_pair` 分数分布，选 `theta_high` = 满足
`P(diff | score ≥ θ) ≤ 0.1%` 的最小值；`diff_blob_ratio` 在回归对上网格搜索。
写入 `glyph_store/calib/thresholds.json`（按特征后端分别存）。
**每次标定后必须全量通过 `regression_pairs.jsonl` 回归集才允许生效。**

### 10.3 识别器更新（→ M4）

- **第一档（默认，零训练）**：确认字形入库（M8），kNN 检索天然变强；
- **第二档（可选）**：用标注图块训练小 CNN 嵌入（triplet loss，同字近/异字远），
  升级 M2 的 `emb` 特征后端 → 同时降低 M3 碎片率和提升 M4 kNN；
- **第三档（可选，数据量大后）**：微调 PaddleOCR rec 模型（PP-OCRv5 单字微调），
  独立脚本 `scripts/finetune_rec.py`，产物模型路径写入 config，M4 可切换。

### 10.4 语料更新（→ M5）

确认转写按页导出纯文本，追加进 `glyph_store/lm/corpus_confirmed/`，
重训领域 n-gram（与通用古文语料插值，权重可配）。
**入语料的是语义层文本**（`text_semantic/`，异体字已正字化），与 LM 的打分空间一致；
字形层原文（`text/`）另行归档，不进 LM——LM 只管语义，异体字形由字形证据裁决（见 8 节）。
同时从确认标签中统计**本书的异体字用字习惯**（如全书"遊"一律作"逰"），
存入 `glyph_store/lm/variant_prefs/{edition_tag}.json`，作为 M4 候选的字形层先验：
同版书中某语义字已确认过的字形获得加权。

### 10.5 重跑语义

`rerun` 命令按依赖图最小重算：阈值变了只重跑 M3 合并阶段（验证分数有缓存）；
标签只增不改时 M5 可以只对受影响列重解码。每个 meta.json 记录上游产物的
内容哈希，实现"参数或输入变了才重算"。

### 测试与 benchmark

- 标定算法单测：构造已知分布的 same/diff 分数，断言选出的 θ 满足纯度约束；
- **闭环 benchmark（系统级）**：在合成书或已全标注的真书上模拟审查过程 ——
  按队列顺序"自动人工"（用真值回答），报告曲线：
  **审查次数 → 全书准确率**。这是整个系统的北极星指标：
  好系统应该在审查 < 5% 簇后达到 > 99% 准确率。曲线存档对比每次算法改动。

## 11. M8 — GlyphLibrary 跨书字形库

### 11.1 条目 schema（glyphs.jsonl）

```json
{"glyph_id": "g_000381", "char": "通", "semantic": "通",  // char=精确异体字形, semantic=通行正字
 "book": "book1", "edition_tag": "book1",  // 用户可把同书版的多书标同 tag
 "source_instances": ["book1:3:2:14", "..."], "n_confirmed": 137,
 "patch": "patches/g_000381.png", "feature_backend": "hog",
 "created": "...", "labels_version": "..."}
```

每个 `(char, edition_tag)` 存代表字形（簇 medoid），`char` 是精确异体字形——
"爲"和"為"是两个独立条目，绝不合并；同字不同版也可多条。字形库因此
同时是"某书版的字样档案"（含该版的异体字用字全貌），本身就有版本学价值
（未来可做刻工/书版比对、异体字用字统计）。`semantic` 字段仅用于按正字检索
（"查这本书里'遊'用的什么形体"）。

### 11.2 检索接口

```python
class GlyphLibrary:
    def add(self, entries: list[GlyphEntry]) -> None
    def query(self, patch: np.ndarray, feature: np.ndarray,
              edition_hint: str | None = None, k: int = 5) -> list[GlyphHit]
    # 两级：特征 kNN 粗排 → verify_pair 精验，返回 (char, f1, glyph_id)
```

- `edition_hint`：识别新书时若用户声明与库中某 tag 同书版，则该 tag 条目优先且
  阈值可放宽一档；否则全库检索、阈值保持保守；
- 库只进人工确认过的字形（**不进机器猜测**），保证"命中即高置信"这一性质。

### 冷启动第二本书的流程

M1/M2/M3 照常跑（聚类不依赖库）→ M4 优先查库：同版书大部分簇直接命中 →
suspects 队列显著变短 → 审查只处理新字/磨损差异 → 新确认继续入库。
系统的边际成本随书量递减，这是第 6 条需求的直接实现。

### 测试

- 入库/查询/去重单测（内存小库）；
- **跨书 benchmark**：book1 确认标签入库后识别 book1 的另一半页面（自留验证），
  报告库命中率与命中准确率（命中准确率要求 ≈ 100%，否则收紧精验阈值）。

## 12. CLI 与 Pipeline 集成

```bash
# Phase 4~6 逐步执行（每步可独立重跑）
python -m open_guji_cv chars    data/book1     # M1 → phase4_chars/
python -m open_guji_cv cluster  data/book1     # M2+M3 → phase5_clusters/
python -m open_guji_cv label    data/book1     # M4+M5 → phase6_labels/

# 审查与反馈
python -m open_guji_cv review   data/book1     # 起本地 Web，写 labels.jsonl
python -m open_guji_cv update   data/book1     # M7：标定+入库+语料，打印变更摘要
python -m open_guji_cv rerun    data/book1     # 依赖感知最小重算 5/6

# benchmark（每模块统一入口，输出 JSON 报告到 benchmarks/results/）
python -m open_guji_cv bench extractor|verify|cluster|candidates|rank|loop \
       --data synth|book1 --out benchmarks/results/
```

`GujiPipeline` 增加对应方法（`extract_chars` / `cluster_chars` / `label_chars`），
沿用现有 manifest.json 机制记录执行与跳过。

## 13. 评测体系汇总

### 13.1 合成数据生成器（synth.py）

测试基础设施的核心，让 M2~M5 无需人工标注即可回归：

- 用繁体 CJK 字体（如全字库宋体）渲染指定字表 → 模拟刻本磨损管道：
  随机腐蚀/膨胀、笔画断裂（随机细线擦除）、边缘噪声、着墨不匀（伽马场）、纸纹噪声；
- 同一字的多个实例共享同一渲染 + 不同磨损 —— 精确模拟"同版同字"假设；
- 可生成整"页"（组列成页 + grid JSON），端到端跑通 M1→M5；
- 文本内容从真实古文语料抽段 → M5 的 LM 排序也可合成评测。

### 13.2 指标一览

| 模块 | 硬指标（门槛） | 软指标（优化） |
|------|--------------|--------------|
| M1 | ID/数量不变量 | 吞吐 |
| M3 | purity ≥ 99.9%；回归对零合并 | 碎片率、单例率、吞吐 |
| M4 | — | 簇级 top-1/top-5、库命中率 |
| M5 | suspects 召回 ≥ 95% | 重排提升、误报率（审查量） |
| M7 | 标定后回归集全过 | 审查次数→准确率曲线（北极星） |
| M8 | 命中准确率 ≈ 100% | 跨书命中率 |

所有"准确率/命中率"均按**字形层精确匹配**计算（异体字答成正字算错）；
另附一列语义层准确率作参考——两者的差值即"OCR 字表/字形证据不足导致的异体字损失"，
是衡量字形库价值的直接指标（同版书第二本该差值应趋近 0）。

benchmark 报告统一 JSON 格式（模块、参数快照、数据集、指标、耗时、git commit），
追加存入 `benchmarks/results/`，用 `scripts/bench_report.py` 生成趋势对比表 ——
任何算法/参数改动都能回答"哪个指标变好/变坏了"。

## 14. 实施里程碑

| 阶段 | 内容 | 验收 |
|------|------|------|
| P1 | synth.py + M1 + M2(raw/hog) + M3 | 合成集 purity ≥ 99.9%，book1 全量跑通出蒙太奇 |
| P2 | M4（PaddleTopK + 融合）+ M5(ngram) | 合成端到端；book1 转写初稿 + suspects |
| P3 | M6 审查 UI + labels 事件流 | 真人可用，book1 完成一轮审查 |
| P4 | M7 标定/入库 + M8 检索 | 闭环 benchmark 曲线；book 同版复识验证 |
| P5 | 可选增强：emb 特征、masked-lm 精排、rec 微调 | 各指标对比报告决定去留 |

## 15. 真实数据试验记录（book5《钦定四库全书总目》，刻本，10 页）

无 OCR 环境（stub）跑通 preprocess → layout → 切分 → chars → cluster 全链路。
按发现顺序修复的问题（均已进代码 + 单测）：

| 问题 | 修复 | 效果 |
|------|------|------|
| profile 自动检测 chars_per_line=15（实际 21） | 以 README 先验覆盖 | 切分粘连大减 |
| 图块裹进界行竖线，质心/外接框被拉偏 | 提取水平内缩 + 归一化删贯穿线 | 同字 F1 0.4→0.6 |
| 相邻字残片切入图块，外接框忽大忽小 | 浅入侵清除 + 稳健外接框 + 受限各向异性缩放 | 同字 F1 0.6→0.63~0.93 |
| 着墨浓淡差异（同字笔宽差 2 倍）压垮墨迹 F1 | 笔宽归一（Zhang-Suen 骨架化+统一膨胀） | 关键一环 |
| 投影自由切分对断笔/磨损脆弱（bad_seg 35%） | **grid_segment 严格网格切分**（刻本格式固定：N 等分先验网格 + 投影谷微调） | 切分数与理论格数完全吻合；真字簇覆盖 178→300 |

结论：**"同版同字聚类"假设在真实刻本上成立**——之×6、易×5、其×5、家×3、
言×3、子×3、卷×3 等簇全部零污染（θ_high=0.72）。

### book9《四库全书总目·卷首》试验（与 book5 同版的另一册，整书 206 页，取 10 页入库）

切分算法在更多样本上暴露并修复的规律（grid_segment 迭代）：

| 规律/问题 | 对策 |
|----------|------|
| （中间结论，后被推翻）"跨列行位浮动/字距局部不均" → 曾引入逐列相位与弹性 DP | 领域知识修正（见下行） |
| **刻本整版先划栏格再上字：格高固定、跨列统一；列首/列尾空格占格位但无墨** | 最终模型 = **刚性统一网格**：页级聚合投影拟合一个 (相位, 格高)，每列仅 ±0.12 格微调（板歪/扫描形变），格高绝对一致。网格锚定栏格周期证据而非内容范围——**抬头空格列按内容锚定会整体错位**（"乾隆…"奏折抬头、职名页是真实场景）。此前测得的"列间相位差/字距不均"均为弱信号伪像；刚性模型一举修正全部列（含此前失败的左右边缘列），职名页（每列几字+大片空白）也完全正确 |
| inner_frame 检测偏差可近一格，首末字被裁掉 | 纵向外扩一格；网格真实范围由投影内容决定 |
| 边框横线（3~10 行短游程）、扫描黑边（近满宽实心块）污染内容范围 | content_range 游程过滤：短游程 + 高填充游程剔除；阈值参考用 90 分位（抗边框尖峰） |
| 贯穿竖线（边框/界行残留）给每行投影加常量偏置，**填平字间谷** | 投影前竖直开运算剔线（连续贯穿 ≥30% 列高；字的竖笔 ≤1 字高不误伤） |
| **被错误列边界切残的字残形趋同 → 跨字污染簇**（書/督 实例） | 聚类隔离：归一图块含"独立窄高组件"（界行特征；中/串类通高竖笔与主体连通不误伤）→ 强制单例进审查 |

**列网格拟合**（刚性先验在水平方向的同构复用，替代 Phase 2 自由列检测）：
- `page_column_projection`：形态学剔除界行竖线（垂直投影上的假峰，恰在列边界处）
  与边框横线（常量偏置）后，垂直投影呈纯净周期结构（文字列=台地、列间=谷），
  谷/峰代价模型直接复用 `fit_page_grid`；
- 列格 = 文字带 + 界行缝（完整周期）；文字带在周期内位置刚性固定，
  逐列格测内缩取页面中位统一应用——否则图块裹界行，竖线隔离误伤 57% 字符；
- 附带发现：book9 实际为每半页 9 列（README/profile 曾误抄 book5 的 8），
  自由列检测下不暴露，列数先验一启用立即现形——先验本身就是校验。

结果（行列双网格）：book9 十页 1786 字，切分异常 0、隔离 179；
書/之/各/家×10、有×8、者/大×7 等 **167 个真字多成员簇覆盖 28% 实例**零污染
（演进：投影切分 11% → 行网格 16% → 行列双网格 28%）；
抬头空格页与职名页（每列几字+大片空白）行列全对齐、空白格全部正确判 empty；
此前 Phase 2 列检测受害的左右边缘列全部恢复。

已知余留问题（按优先级）：
1. **Phase 2 列检测**是最大上游瓶颈：真实列宽 60~301 连续分布
   （半列/双列粘连），被劈开的字形成部件碎簇（亻等）。刻本先验同样适用：
   列宽/列距固定，可做列网格拟合（与本模块的行网格同构）。
2. 同字-异字分数带偏窄（同字 0.63+，异字最高 ~0.65）：θ=0.72 下最规整的
   字直接合并，其余落 unsure 带交审查并簇；后续可用弹性配准或 CNN 嵌入拉宽。
3. 无 GPU/OCR 环境未验证 M4 的 ocr 来源与 CTC top-k；候选生成暂靠
   字形库 + prior。

## 16. 主要风险与对策

| 风险 | 对策 |
|------|------|
| Phase 3 切分误差（粘连/切半）传导 | M1 记 ink_ratio/h-w 异常 → 标 `bad_seg` 进审查；审查 UI 支持标"切分错误"反馈给 Phase 3 参数迭代（跨 Phase 信号，不在本系统内自动处理） |
| 形近字仅一笔之差 | `diff_blob_ratio` 局部差异防线 + 永久回归对集 + LM 上下文兜底 |
| 磨损重导致碎片化过高 | 碎片化不影响正确性，只增审查量；用 emb 特征与 dilated_f1 迭代；unsure 对进并簇审查 |
| PaddleOCR 内部 API 变动（top-k 提取） | PaddleTopK 单独隔离 + fixture 离线测试 + 增强投票回退方案 |
| OCR 字表不含生僻异体字 → 首轮只能给出正字候选 | 候选标 `surface_uncertain`，精确字形由人工审查定；确认一次即入字形库，同版书后续由 kNN 直接命中精确形体；`variant_prefs` 用字习惯先验进一步降低复发 |
| 手写体上版的刻本（如 book1"手写体"）字形一致性弱于宋体刻本 | 聚类阈值按书标定；一致性差时系统自动退化为"小簇+多审查"，正确性不受损 |
