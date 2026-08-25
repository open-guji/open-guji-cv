# 字形匹配算法调研：我们在方法谱系里的位置，和四条可走的路

**日期**：2026-08-25　**缘起**：用户「我觉得现在的算法太简单了，去网上找一找，
像这种字符匹配，尤其是中文字符的匹配，而且还要考虑到它的偏移、漂移、缩放，
还有什么更好的算法」。

配套读：[glyph_match_stack.md](glyph_match_stack.md)（四层链条与护栏现状）。
**本篇只谈算法与文献，不谈工程现状**——数字以那一篇为准。

---

## 一、我们现在这层，在文献里叫什么

第 4 层的 `verify_pair_elastic`（软覆盖 + 分块弹性对齐）不是自创的形态，
它是 **IDM（Image Distortion Model）** 的一个变体：允许逐像素/逐块独立位移的
匹配模型，源头是 Keysers 一系在手写识别与医学图像上的工作
（[Eigen-deformations, Pattern Recognition 2003](https://www.sciencedirect.com/science/article/abs/pii/S0031320303000396)；
原始 IDM 在 USPS 手写数字上把最近邻错误率 2.4% → 2.2%）。
我们加的分块约束（16×16 块共享一个位移）比原始的逐像素 IDM 更受限一点。

**所以「太简单」这个判断对了一半**：它在经典方法族里不算浅，但它踩在一个
**有文献记载的已知缺陷**上。IDM 的后续工作
（[Hungarian Distortion Model, ICPR 2004](https://link.springer.com/chapter/10.1007/978-3-540-28649-3_19)）
把这个缺陷说得很直白：

> IDM「忽略了像素位移之间的一切依赖关系，因此是一个**零阶**形变模型」。
> HDM 用匈牙利算法加了全局约束（每个像素至少被匹配一次），位移场更均匀，
> **但相邻像素的位移仍不相互约束，所以 HDM 和它所基于的 IDM 一样是零阶的**。

### 这个缺陷正好解释我们的头号失败族

`triplets` hard 里还排反的 35 例，第一族是**加一笔 / 减一笔**
（面/而 ×2、日/曰、已/巳、七/一、金/全、目/自、太/大）。

零阶模型下，每块独立找补位移——「面」比「而」多的那一横，可以被邻近的块
各自挪一点点**吸收**掉。模型天然分不出两件事：

- 同字异刻的**刻工手抖**：位移场是**平滑**的（整字微歪、某部件偏一点）；
- 形近异字的**多一笔**：制造的是**局部的、突变的**位移需求。

零阶模型对这两者一视同仁。**升到一阶（约束相邻块的位移差）就能把它们分开。**

---

## 二、四条路

### ① 位移场平滑约束：把零阶升到一阶

不再让每块独立取最优覆盖，而是在目标里加一项惩罚**相邻块位移的差异**：

```
max_over_field  Σ_block cov(block, d_block)  −  λ · Σ_(相邻 b,b') ‖d_b − d_b'‖
```

- **不需要任何训练数据**，直接对着那 35 例量；
- 实现代价小：现有实现已经在枚举每块的候选位移，加一个 pairwise 平滑项就是
  一次小的动态规划 / 几轮 ICM（4×4 = 16 个块，候选位移 9 个，规模极小）；
- 风险：λ 太大就退回全局刚性（刚性 F1 上限只有 0.67~0.75，见
  `g3g4_error_analysis.md`），要在 hard/control 上扫。

**优先级最高**，理由是零成本、直击第一族、且失败也能立刻看出来。

### ② Shape Context + TPS（薄板样条）：经典强基线

[Belongie et al., NIPS 2000](https://proceedings.neurips.cc/paper_files/paper/2000/file/c44799b04a1c72e3c8593a53e8000c78-Paper.pdf)
的三步法——形状上下文找点对应 → 正则化 TPS 拟合对齐变换 → 量残差。
在 MNIST 上做到 **0.6% 错误率**（20000 训练样本的 kNN 是 0.63%）。

这其实是①的完整版：TPS 拟合出的形变场**天然全局平滑**，而且能报出
「残差集中在哪」——对「多一笔」这种局部差异特别灵。

代价：TPS 要解 p×p 矩阵求逆，点数一多就不实用（原文明说
impractical for large scale），得配
[Donato & Belongie 的近似 TPS](https://link.springer.com/content/pdf/10.1007/3-540-47977-5_2.pdf)。
另有 [IDSC（Inner-Distance Shape Context）](https://www.cs.utexas.edu/~grauman/courses/spring2008/slides/ShapeMatching.pdf)
用内距离替欧氏距离，对铰接形变更鲁棒——汉字不铰接，这条对我们未必加分。

### ③ 对比学习的度量嵌入：中期最有希望，且有人做过一模一样的事

[**Contrastive Attention Networks for Attribution of Early Modern Print**](https://arxiv.org/abs/2306.07998)（2023）
——任务是**在早期印本里匹配带残损的活字印痕**，要求「对字形的细微差异敏感，
同时对数字化噪声鲁棒」。这跟我们要分 面/而、要认同一副刻版，几乎是同一件事。

**最值得抄的是它解决数据不足的办法：合成训练数据**——模拟印刷缺陷
（弯折 bends、断笔 fractures、着墨浓淡 inking variations）生成带损字形。
我们手上正好有字体字形导入（`glyph_db_expansion_research.md` §6 已实测过
字体字形的匹配力），可以**渲染字体 → 加合成的刻本退化 → 训 Siamese 嵌入**，
不必等人裁标注攒够。

历史文献这一侧的同类工作：
- [甲骨拓片图像检索的开放基准](https://www.nature.com/articles/s40494-025-01859-9)（npj Heritage Science 2025）
- [敦煌残片按笔迹风格拼接](https://www.nature.com/articles/s40494-025-02078-y)（npj Heritage Science 2025）
- [甲骨文识别综述](https://arxiv.org/pdf/2411.11354)、[古文字图像识别综述](https://arxiv.org/html/2506.19208v1)

**风险**：我们的库只有两千级实例、triplets 只有 136 组，纯监督训不动；
合成数据这条路要先验证「合成的退化像不像真的刻本退化」，否则训出来的嵌入
在真图上不迁移。**这是投入最大的一条，不该第一个做。**

### ④ 部件 / 笔画结构比对：对付「偏旁替换」与「部件包含」

[STAR](https://arxiv.org/html/2210.08490)、
[Radical-Structured Stroke Trees](https://arxiv.org/pdf/2211.13518)（Machine Learning 2023）
这一系把汉字分解成 **IDS（表意文字描述序列）**——按 GB13000.1，
394 个部首 + 12 种空间结构就能唯一描述 3755 个常用字；比对用树上的加权编辑距离。

这条对第二三族是对症的：**諭/論 的差别在像素上是局部差异，在结构上是一个
完整部件的替换**（言+俞 vs 言+侖）。像素域里被摊薄的东西，结构域里是离散的。

**但从刻本图块里抽部件本身是个难题**，那等于先做一遍部件分割。
所以有个**便宜得多的用法**：

> **只用 IDS 当护栏，不用它当匹配器。**
> 两个候选字的 IDS 差一个部件 → 直接降档 unsure。

这等于把现在手工维护的 `NEVER_MATCH_FAMILIES`（而/面、七/一、彖/象…）
升级成**全字表自动生成**。IDS 数据是现成的（Unicode IDS 数据库 / CHISE），
不用训练，也不用碰图像。**代价小、覆盖广，适合和①一起做。**

> ⚠️ 有一条既有限制要记住：`NEVER_MATCH_FAMILIES` **要求库里有对家才生效**，
> 无监督聚类拿不到字标签，那条护栏在聚类那一侧用不上。IDS 护栏继承同样的限制
> ——它是**库匹配**那一侧的东西，不解决聚类的脏簇。

---

## 三、建议的顺序与量法

| 序 | 方案 | 打哪一族 | 要不要数据 | 投入 |
|---|---|---|---|---|
| 1 | ① 位移场平滑约束 | 加一笔/减一笔 | 不要 | 小 |
| 2 | ④ IDS 护栏（便宜版）| 偏旁替换 / 部件包含 | 不要（IDS 表现成）| 小 |
| 3 | ② Shape Context + TPS | 全部三族 | 不要 | 中 |
| 4 | ③ 对比学习嵌入 | 全部三族 | 要（靠合成）| 大 |

**量法纪律**：现在只有 `triplets` 那条护栏有牙齿（56 组、35 个明确失败例）。
`pairs` 排掉了 46.4% 的对、`char-clustering` 的退化层只剩 1 个实例，
**这两条暂时只能当参考不能当判决**。上面任何一条做完，以 triplets 的
hard/control 为准，并且 **control 不许掉**。

---

## 四、检索到但判定不适用的

- **随机弹性形变做数据增强**（[CNN + random elastic deformation](https://www.researchgate.net/publication/290568453_Recognition_of_similar_handwritten_Chinese_characters_based_on_CNN_and_random_elastic_deformation)、
  [Multi-grid 2D Elastic Deformation](https://arxiv.org/pdf/2602.03913)）：
  那是**训分类器时扩样本**用的，我们这层是无训练的逐对判据，用不上；
  但③一旦上马，这就是合成退化的现成手法。
- **Eigen-deformations**（[Pattern Recognition 2003](https://www.sciencedirect.com/science/article/abs/pii/S0031320303000396)）：
  用 PCA 学「每个字类的典型形变方向」。**需要每个字类有足够多的刻例**，
  我们库里大多数字头只有个位数刻例（撤库后 639 个字头 / 2061 个实例），
  学不出来。等库长大了可以回头看。
- **部首级零样本识别**（STAR 等）：目标是**识别没见过的字**，我们的问题是
  **判两块图是不是同一个字**，任务不同；只有 IDS 这一层可复用（见④）。
