# 字形相似度匹配栈——现状、算法、测试集（优化专题的交接文档）

**写给接手「两个字符图块相似度匹配」优化的会话。** 看完这份即可开工。
2026-08-24 由体检人裁实锤「同字看着更像、算法却判异字更近」立项，
同日第一轮优化落地（**elastic 判据**，hard 0.079 → 0.684），
实测记录与代价见 §六，遗留见 §七。

## 一、被测对象：四层链条

两个原始灰度图块 → 相似度分数（cov）与判决，依次经过：

| 层 | 代码 | 做什么 | 关键参数 |
|---|---|---|---|
| 1 存储归一 | `clustering/canonical.py` `to_canonical` | 256×256 灰度、**只缩不放**、墨迹质心居中、边缘残渣清理。库真源统一格式（2026-08-24 起 admit/refresh 内部强制）| CANON_SIZE=256, MARGIN 0.12 |
| 2 匹配归一 | `clustering/normalize.py` `normalize_patch` | Sauvola 二值 → 去噪/贴边杂点清理 → 墨迹外接框**等比缩放填满内容区** → 质心居中 → 64×64 {0,1} | NORM_SIZE=64, MARGIN_RATIO=0.12, 笔宽归一 stroke_width=3 |
| 3 特征粗排 | `clustering/features.py` `HogFeature` | HOG（8×8 cell / 9 方向 / 2×2 块 L2 归一，纯 numpy/Sobel），内积相似度取 kNN top-k 进精验 | k=10（GlyphMatcher）|
| 4 逐对精验 | `clustering/verify.py` `verify_pair_elastic` | **软覆盖 + 分块弹性对齐**（§1.1）| ELASTIC_TAU=1.5, ELASTIC_BLOCK=16, ELASTIC_LOCAL=1, MAX_SHIFT=3, SCALES=(0.95,1,1.05), COV_LOW=0.85, MISS_WMAX=12；same 闸分两档：库匹配 **ELASTIC_COV_HIGH=0.992**、聚类 **ELASTIC_CLUSTER_COV_HIGH=0.988** |

判决（`clustering/match.py` `GlyphMatcher.match`）：cov ≥ same 闸且
wmax ≤ MISS_WMAX → same；≥ COV_LOW → unsure 候选；另有 never-match
形近家族护栏（`NEVER_MATCH_FAMILIES`，命中且**库里有对家**即降档
unsure）与多字 same 冲突护栏。**下游所有准入通道（match_ref/
match_solo/match_solo_ocr）和体检（audit.py）比的都是这里的 cov。**

### 1.1 第 4 层：elastic 判据（2026-08-24 起默认）

前身 `verify_pair_cov`（coverage 判据，仍在，`--verify-method coverage`
可整体切回）：全局刚性对齐后，把「B 的墨落在 A 的 **r=2 硬膨胀**邻域内」
都算命中。它的毛病是**两件事拧在一个半径里**：

- 半径要大，才吃得下同字异刻的局部笔画位移（刚性 F1 的上限只有
  0.67~0.75，标定见 `g3g4_error_analysis.md`）；
- 半径一大，整部件替换型形近字缺的那一笔也被抹平（揀/棟 cov 0.9802
  实锤），形近字跟着沾光。

elastic 把这两件事拆开，**距离容忍收紧成软的，位移容忍放宽成局部的**：

1. **软覆盖**：命中权重 `w(d) = exp(-(d/1.5)²)`——2px 外仍算命中但只
   算 0.17，形近字缺的笔画不再白拿满分；
2. **分块弹性对齐**：全局 `(scale, dx, dy)` 之上，每 16×16 块（64 归一
   图 = 4×4 块）再各自搜 ±1px。同字的逐部件刻痕位移每块自己找补；
   形近字缺的部件挪到哪儿都还是缺，块内位移救不了。

`cov = (Σ_A w + Σ_B w) / (|A|+|B|)`，最优对齐取**弹性覆盖率本身**最大
者（平局取最居中的位移；报告里的 `shift` 是全局刚性那一份，真实位移
= shift ± ELASTIC_LOCAL）。`wmax` 仍是 12×12 窗口内未覆盖量的最大值，
只是「未覆盖」从 0/1 变成 `1-w`。

### 1.2 刻度校准与两档 same 闸

`scripts/calibrate_elastic.py`：elastic 的原始分分布与 coverage 不同
（同字对 ~0.90 而非 ~0.99），而 COV_LOW / MISS_WMAX、seeding 的
`MATCH_SOLO_COV=0.99` / `MATCH_SOLO_OCR_COV=0.95` / `FONT_COV_GATE=0.95`
全是按 coverage 的分布标的。所以在 char-clustering 两大分片的 kNN 对群
（42806 对）上做**单调分位映射**，把 elastic 搬回 coverage 的刻度：
同分位同数值，既有阈值的**放行比例**原样保留，变的只是**放行谁**。
锚点表 = `verify.py` 的 `_CAL_*` 四行，重标就是重跑脚本、替换四行。

same 闸则**按各自的量尺重新钉**，两个消费方分开——它们的证据强度和
错的代价都不一样：

- **库匹配 0.992**：一条 same 边就直接继承库里的字，没有共识机制兜底，
  错一次就是把错标写进库；硬约束是 `eval_db_match` 的
  `match_precision ≥ 0.999`。0.992 是三个协议全 1.0000 的点。
- **聚类 0.988**：合并要过多代表一致性与抽查，单条边误判有兜底，漏并
  只是多一个碎片、进审查队列，所以能松一档。char-clustering 三分片扫
  0.980~0.992，0.988 是唯一 never-make-worse 的点（0.985 起 vol02
  purity 破 0.999，0.992 则碎片率和 human 分片同字难例对都退步）。

## 二、主测试集：glyph-match/triplets（排序金标）

`open-guji-dataset/glyph-match/triplets`——**同字形必须比形近异字更匹配**：

- 三元组 (anchor, same 同字刻例, other 形近异字刻例)，金标性质
  `cov(anchor,same) > cov(anchor,other)`；
- **hard 38 条**：体检 rival 旗 × 用户白名单二次确认（= 建集当时算法
  的已知失败，用户亲眼裁定「本例标签没错」）；
- **control 60 条**：良例抽样，**不得回退**；
- 图块是**原始灰度 patch**——第 1、2 层归一化都在被测范围内；
- 量法：`PYTHONPATH=. python scripts/eval_match_triplets.py
  ../open-guji-dataset/glyph-match/triplets`（`--report` 逐条，
  `--method coverage` 切回旧判据对照）。

| 判据 | hard rank_acc | hard margin | control rank_acc | control margin |
|---|---|---|---|---|
| coverage（建集基线）| 0.079 | −0.016 | 1.000 | +0.068 |
| **elastic（现行）** | **0.684** | **+0.005** | **1.000** | +0.068 |

⚠️ 数据集 README 与 `results/baseline.json` 里记的还是 coverage 那行
（那个仓库本轮没动），下次动它时一并刷新。

## 三、回归护栏（改任何一层后都要绿）

| 集 | 量法 | 守什么 |
|---|---|---|
| glyph-match/triplets control | eval_match_triplets.py | 良例排序不回退 |
| char-clustering 三分片 + hard_pairs | eval_clustering.py | purity ≥ 基线，难例对 never-make-worse |
| char-normalization golden | eval_normalize.py | 归一化回归门 33/33（改 normalize 时）|
| 库匹配协议基线 | eval_db_match.py | same 档 `match_precision` **≥ 0.999 硬约束**；覆盖率是另一本账 |
| 单测 | tests/clustering/{test_verify_cov,test_verify_elastic,test_match,test_audit}.py | 判据契约 |

**elastic 落地后各护栏的数**：

- triplets：control 1.000 持平，hard 0.079 → 0.684；
- char-clustering（聚类闸 0.988）：
  purity 0.99967 / 0.99967 / 0.98901 → **1.0 / 1.0 / 1.0**（human 分片
  的 諭/論 脏簇没了）；碎片率 2.99 / 3.45 / 3.00 → 2.97 / 3.38 / 3.04；
  难例对 40/80、34/74、14/65 三个**总数全持平**——003 分片内部换了构成
  （diff/cluster_leak 3/5 → **5/5**，same/confirm_same 11/60 → 9/60）；
- char-normalization：33/33（本轮没动 normalize）；
- eval_db_match（库匹配闸 0.992）：三协议精度全 **1.0000**（旧判据是
  1.0000/1.0000/1.0000，但字形精度里带着 詳←羣 一条），**覆盖率
  10.4/16.6/21.8% → 6.2/11.4/13.5%**——本轮唯一的负向，机理与取舍
  见 §六；
- 单测 421 passed（另有 2 个 s2t 用例因环境缺 opencc 失败，与本轮无关）。

⚠️ 阈值联动：same 闸同时是**进库准入**的闸（seeding.py 各通道、
MATCH_SOLO_COV=0.99、MATCH_SOLO_OCR_COV=0.95 都以 cov 分布标定）。
改变 cov 的**数值分布**（不只是排序）时，要么像本轮这样做分位校准把
分布搬回来，要么用人裁回放重标（回放手法见 seeding.py 通道注释）。

## 四、已知失败形态（下一轮的切入点）

1. **hard 剩下的 12 条**（`--report` 逐条可看）：已/巳 ×4、日/曰、
   朱/未、傳/傅、右/古、康/廣、識/議、闡/闌、紛/給——全是**整字近似、
   只差一个开合或一横**的家族。软覆盖 + 块内位移能拉开的已经拉开了，
   剩下的差异在 64×64 + 笔宽归一 3px 之后**在像素上就不存在**了。
2. **笔宽归一（stroke_normalize）是当前最大的一块信息损失。** 实测：
   同样用软覆盖打分，`normalize_patch(..., stroke_width=None)` 的
   hard 能到 **0.71~0.74 而 control 仍 1.000**（64×64，容差 3~4）；
   分辨率提到 128 是同量级收益。骨架化 + 膨胀到 3px 会把 已/巳 那个
   开口直接糊死；当年引入它是为了给**刚性 F1** 抗着墨浓淡——软覆盖
   本来就不吃这一套，它现在是净损失。
   **为什么本轮没做**：`normalize_patch` 的输出被两个数据集**冻结**着
   （char-normalization 的 33 张 golden 是逐张目视确认后冻的；
   char-clustering 的 crops 是冻结的归一图），改它要连带重建两个集 +
   人工复核，属数据集侧的活。这是下一轮最高性价比的一步，而且很可能
   顺手把 §六 那个覆盖率的坑一起填上——**「笔画挤到一起」既是 hard
   剩余失败的成因，也是覆盖率下滑的成因**。
3. **HOG 粗排召回：量过了，不是瓶颈**（2026-08-24）。在 char-clustering
   两个大分片上，对「本分片里确实存在同字他例」的实例统计 HOG 近邻里
   有没有同字：

   | | top-1 | top-3 | top-10 | top-20 | top-50 |
   |---|---|---|---|---|---|
   | 001-vol01（n=2607）| 0.9056 | 0.9528 | **0.9716** | 0.9762 | 0.9812 |
   | 002-vol02（n=2677）| 0.9294 | 0.9615 | **0.9780** | 0.9828 | 0.9869 |

   现行 k=10 已经把 97% 的同字送进精验，加到 top-50 只多 1%。也就是说
   **精验拿到正确候选的机会有 97%，却只把其中 6~13% 判成 same**——
   缺口全在第 4 层的绝对阈值上，不在粗排。加大 k 是浪费算力。
4. **块尺寸/局部半径还没到头**：blk=12/loc=2 与 blk=16/loc=1 在
   triplets 上同分（0.684），但更细的块会不会在聚类侧多并错，没量过。
5. 历史结论（别再走的死路，g3g4_error_analysis.md §18）：密度自适应
   半径、骨架失配否决、部件失配否决对整部件替换家族**实测无效**。

## 五、体检回流（测试集会长大）

每轮 `/glyphdb-audit` 的 rival × 白名单新案例经
`scripts/build_match_triplets_shard.py` 回流 hard 子集（control 抽样
seed 固定）。改进落地后基线数字更新进分片 `results/` 与 README。
体检本身（audit.py）已随匹配栈换成 elastic——**体检必须和匹配器用同
一把尺**，否则打的旗是匹配器早已不犯的错。

## 六、第一轮优化的实测记录（2026-08-24）

### 扫过什么

| 方向 | 做法 | hard / control |
|---|---|---|
| 收紧硬半径 | r=2 → r=1 / 1.5 | 0.58 / **0.967**（control 破，否）|
| 软距离权重 | 高斯 / 指数 / 线性剖面全扫 | 最好 0.58 / 1.000 |
| 方向池化 | pool / min / geo / mean | 差别 ≤0.03 |
| 放宽全局搜索 | max_shift 4、5 档缩放 | +0.02，边际 |
| **分块弹性 × 软权** | blk 8~32 × loc 1~2 × tau 1~3 | **0.684 / 1.000**（采用 tau1.5/blk16/loc1）|
| verify 层再变换输入 | 再骨架化 / 再腐蚀 | ≤0.684，且多半掉 control |
| **去掉笔宽归一** | `stroke_width=None` | **0.71~0.74 / 1.000**（最大杠杆，受冻结集约束，见 §四.2）|
| 提高归一分辨率 | 96 / 128 | 与上一条同量级，同样受冻结集约束 |

参数落在一片平台上而不是刀尖上：tau 1.5~2.0 × blk 12~16 × loc 1~2
都在 0.63~0.68，选的是平台中间且 control margin 最大的那点。

### 实现代价与后来的提速

逐对精验 **1.2 ms（coverage）→ 4.0 ms（elastic 首版）→ 3.2 ms**（64×64
单核，真实访问模式）。

首版就已经把算法本身写紧了：全局位移与块内位移合成后仍是一个平移，
所以先把所有合成位移的**块和**一次算完（一次 gather + `np.add.reduceat`
段和），49 个全局位只是在小张量上取 max/求和；朴素写法（每个全局位各自
搜块内位移）要 17 ms。

2026-08-24 又做了一轮**纯提速**（结果逐位不变，5000 对逐位比对过）：

| 手法 | 省下什么 |
|---|---|
| 位移网格（offsets/pick/radius）模块级缓存 | 只依赖 (size,block,local,max_shift)，是常量却每次重建 |
| 图块预处理按**内容**缓存（`ELASTIC_PREP_CACHE`，LRU 512 条 ≈18 MB）| 权重场/分块排序/三档缩放只依赖图块自己，而库匹配是「一个 query 打 k 个候选」、聚类是「几万对反复撞同一批图块」|
| `_elastic_align` 顺手交出胜出档的 `b_s` | 调用方不必再 `_rescale` 一遍 |
| `np.pad` → 预分配零 + 切片赋值 | 每对要调 6 次，np.pad 的 Python 层开销比数据搬运还大（约占逐对总耗时 8%）|

实测（vol01 分片）：聚类式遍历 3.85 → 3.25 ms/对，库匹配式 4.06 →
3.21 ms/对。缓存上限提到 2048 只再快 3%，不值那 4 倍内存。

**试过但没用的**：索引数组改 int32 反而更慢（numpy 花式索引内部要 intp，
多一次转换）；砍掉 0.95/1.05 两档缩放不行——63% 的对最优档不是 1.0，
砍掉最多掉 0.095 分。

**剩下的大头动不了**：核心 gather/reduceat ~1.4 ms 是算法本身；wmax 那
一段 ~1.0 ms（25%）**在判决用不到它的时候本可以跳过**（cov < 0.95 时
没有任何下游会读），但 wmax 是随判决一起落盘的**证据**（match.py 的
证据纪律：库条目改判要靠它重放），填个假值会毒化重放，所以没做。

### 库匹配这一侧付了代价——覆盖率

`eval_db_match` 三协议的 same 档覆盖率 / 计门精度：

| 配置 | incr. vol01 | incr. vol02 | cross-seed vol02←vol01 |
|---|---|---|---|
| coverage@0.992 w≤12（旧）| 10.4% / 1.0000 | 16.6% / 1.0000 | 21.8% / 1.0000 |
| elastic@0.988 w≤12 | 11.3% / 1.0000 | 18.4% / **0.9982** | 22.1% / **0.9970** |
| elastic@0.988 w≤7 | 8.6% / 1.0000 | 15.2% / 1.0000 | 18.4% / **0.9982** |
| **elastic@0.992 w≤12（采用）** | 6.2% / 1.0000 | 11.4% / 1.0000 | 13.5% / 1.0000 |

**0.988 为什么不能用**：漏两条形近——朱←宋（cov 0.9918，wmax 8.35）、
匕←七（0.9917，wmax 4.80）。把窗口残差闸收到 7 能拦下前者，拦不住
后者：匕/七 虽在 never-match 表里，但跨册时库（vol01）里根本没有对家
「匕」，护栏是**条件版**（`partners & self._char_set`）所以点不着——
这正是 match.py 注释里早就记着的残余风险，elastic 只是把它顶到了
阈上。`match_precision ≥ 0.999` 是硬约束，只好退到 0.992。

**覆盖率为什么掉**：elastic 的**绝对分随笔画密度走低**。vol01 分片按
ink_ratio 分档，同字最优 cov 能过 0.992 的实例比例：

| ink_ratio | n | coverage | elastic |
|---|---|---|---|
| <0.10 | 150 | 0.513 | **0.600** |
| 0.10~0.14 | 718 | 0.248 | 0.216 |
| 0.14~0.18 | 1009 | 0.180 | **0.058** |
| 0.18~0.25 | 612 | 0.150 | **0.025** |

笔画少的字 elastic 反而更好；笔画密的字（64×64 上笔画本来就快挤到
一起）无论配得多好都够不到高档——软权 tau=1.5 对每一笔的微小偏差
都要扣分，笔画越多扣得越多。**排序不受影响**（triplets 是同一个
anchor 比两个复杂度相当的候选，所以 hard 一路涨），**绝对阈值判决
受影响**。出路是 §四.2。

## 七、本轮遗留

1. **库匹配覆盖率的坑**（§六）：same 档覆盖率掉了约三到四成，机理已
   定位，修法在 §四.2。在那之前，若某次更在乎吞吐而不在乎排序质量，
   `--verify-method coverage`（聚类 / eval_db_match）与
   `GlyphMatcher(verify_method="coverage")`（库匹配）可整体切回旧
   判据——两套阈值都还在，切回去是无损的。
2. **把 never-match 护栏改成无条件**能立刻换回一大截覆盖率：实测
   `elastic@0.988 w≤7` + 无条件护栏 = 8.6% / 15.2% / 18.4% 且三协议
   精度全 1.0000（唯一错配 匕←七 正是被条件版放过的）。**本轮没做**
   ——现行的条件版是写进设计并有单测钉着的
   （`test_never_match_partner_absent_no_demotion`），改它是一个独立
   的设计决定，代价是命中家族字（大/人/日/未…共 30 个）的实例都要走
   候选+上下文。要不要换，交给下一轮人裁。
3. **人裁标定的准入闸欠一次回放**：`MATCH_SOLO_COV=0.99` /
   `MATCH_SOLO_OCR_COV=0.95` / `FONT_COV_GATE=0.95` 当年是拿人裁回放
   标的（seeding.py 通道注释里的 81/81、75 条家族 35/35）。分位校准
   保住了「放行多少」，没保「放行谁」——严格说该在新判据下重放一遍。
4. **数据集侧的数没刷**：`glyph-match/triplets` 的 README /
   `results/baseline.json`、`char-clustering` 的基线数字仍记着
   coverage 那版（本轮只改了 `open-guji-cv` 仓）。
