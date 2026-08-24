# 字形相似度匹配栈——现状、算法、测试集（优化专题的交接文档）

**写给接手「两个字符图块相似度匹配」优化的会话。** 看完这份即可开工。
2026-08-24 由体检人裁实锤「同字看着更像、算法却判异字更近」立项。

## 一、被测对象：四层链条

两个原始灰度图块 → 相似度分数（cov）与判决，依次经过：

| 层 | 代码 | 做什么 | 关键参数 |
|---|---|---|---|
| 1 存储归一 | `clustering/canonical.py` `to_canonical` | 256×256 灰度、**只缩不放**、墨迹质心居中、边缘残渣清理。库真源统一格式（2026-08-24 起 admit/refresh 内部强制）| CANON_SIZE=256, MARGIN 0.12 |
| 2 匹配归一 | `clustering/normalize.py` `normalize_patch` | Sauvola 二值 → 去噪/贴边杂点清理 → 墨迹外接框**等比缩放填满内容区** → 质心居中 → 64×64 {0,1} | NORM_SIZE=64, MARGIN_RATIO=0.12, 笔宽归一 stroke_width=3 |
| 3 特征粗排 | `clustering/features.py` `HogFeature` | HOG（8×8 cell / 9 方向 / 2×2 块 L2 归一，纯 numpy/Sobel），内积相似度取 kNN top-k 进精验 | k=10（GlyphMatcher）|
| 4 逐对精验 | `clustering/verify.py` `verify_pair_cov` | **有界位移覆盖率**：scales×(±MAX_SHIFT)² 网格搜最优对齐（按 F1），最优位下双向 5×5 膨胀覆盖 → `cov = 1 − (漏墨A+漏墨B)/(墨A+墨B)`；12×12 boxFilter 残差窗最大值 `wmax` 作形近护栏 | MAX_SHIFT=3, SCALES=(0.95,1,1.05), COV_HIGH=0.992, COV_LOW=0.85, MISS_WMAX=12 |

判决（`clustering/match.py` `GlyphMatcher.match`）：cov≥COV_HIGH 且
wmax≤MISS_WMAX → same；≥COV_LOW → unsure 候选；另有 never-match
形近家族护栏（`NEVER_MATCH_FAMILIES`，命中即降档 unsure）与多字
same 冲突护栏。**下游所有准入通道（match_ref/match_solo/match_solo_ocr）
和体检（audit.py）比的都是这里的 cov。**

设计依据：coverage 判据是对「同字异刻天然带 2~3px 局部笔画位移」的
回应（刚性 F1 上限 0.67~0.75），标定过程在 `g3g4_error_analysis.md`。

## 二、主测试集：glyph-match/triplets（排序金标）

`open-guji-dataset/glyph-match/triplets`——**同字形必须比形近异字更匹配**：

- 三元组 (anchor, same 同字刻例, other 形近异字刻例)，金标性质
  `cov(anchor,same) > cov(anchor,other)`；
- **hard 38 条**：体检 rival 旗 × 用户白名单二次确认（= 当前算法的
  已知失败，用户亲眼裁定「本例标签没错」）。基线 **rank_acc 0.079，
  mean_margin −0.016**——失败都是压线级，不是彻底错乱；
- **control 60 条**：良例抽样，基线 1.000 / +0.068，**不得回退**；
- 图块是**原始灰度 patch**——第 1、2 层归一化都在被测范围内；
- 量法：`PYTHONPATH=. python scripts/eval_match_triplets.py
  ../open-guji-dataset/glyph-match/triplets`（`--report` 逐条）。

## 三、回归护栏（改任何一层后都要绿）

| 集 | 量法 | 守什么 |
|---|---|---|
| glyph-match/triplets control | eval_match_triplets.py | 良例排序不回退 |
| char-clustering 三分片 + hard_pairs | eval_clustering.py | 聚类 purity ≥ 基线（0.99967/0.99967/0.98901），难例对 never-make-worse |
| char-normalization golden | eval_normalize.py | 归一化回归门 33/33（改 normalize 时）|
| 库匹配协议基线 | eval_db_match.py | 检索式匹配的召回/精度基线 |
| 单测 | tests/clustering/{test_verify,test_match,test_audit}.py | 判据契约 |

⚠️ 阈值联动：COV_HIGH/MISS_WMAX 同时是**进库准入**的闸
（seeding.py 各通道、MATCH_SOLO_COV=0.99、MATCH_SOLO_OCR_COV=0.95
都以当前 cov 分布标定）。改变 cov 的**数值分布**（不只是排序）时，
这些阈值要用人裁回放重标（回放脚本手法见 seeding.py 通道注释）。

## 四、已知失败形态（优化切入点）

1. **hard 集的压线失败**（margin ±0.05 内为主）：覆盖率对「整部件
   替换型形近字」不敏感——差一个偏旁的墨量占比小，膨胀覆盖把它抹平
   （揀/棟 cov 0.9802 实锤；wmax 护栏只逮到一部分）。
2. **MAX_SHIFT=3 + 3 档缩放的对齐搜索很粗**：canonical 化前它还要
   吸收存储偏移，现在真源已质心居中，可考虑更细的对齐或弹性配准。
3. **HOG 粗排召回**：全局 top-10 里同字有时挤不进（audit 里靠补验
   同字 top-3 兜底）——粗排特征与精验判据的失配本身值得量。
4. 历史结论（别再走的死路，g3g4_error_analysis.md §18）：密度自适应
   半径、骨架失配否决、部件失配否决对整部件替换家族**实测无效**。

## 五、体检回流（测试集会长大）

每轮 `/glyphdb-audit` 的 rival × 白名单新案例经
`scripts/build_match_triplets_shard.py` 回流 hard 子集（control 抽样
seed 固定）。改进落地后基线数字更新进分片 `results/` 与 README。
