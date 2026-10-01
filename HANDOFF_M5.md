# HANDOFF M5：近形决胜（𫎇/蒙 类「永远拿不准」）

分支 `claude/M5-near-shape-1001`（基于 origin/main `2fa4e4e`），**未合 main**，等验收。
范围遵守 #300：只在四庫/北行日錄的字形库真源（重建的 glyph.db）和 open-guji-dataset 测试集上开发，
没跑整册、没打包、没碰正式 products。

## 一句话

做了一个**默认关闭**、开了以后自动触发的近形决胜：当首选与次优异字的 cov 差 < 0.03 时，取两字的
**人裁刻例**做模糊＋平移对齐，逐像素算 Fisher 比，得到「两组系统性不同、组内又稳定」的差异区域，
在这块区域上比较查询离哪一组的原型更近；再用库内留一自检和两道安全闸决定是否放行。
四庫库人裁刻例按页分组留一：**决出 70 例，70 例全对**，其中 45 例原本是无护栏的「拿不准」，现在可以升 same。
char-clustering 回归 same 档精度保持 **1.0000**，覆盖 +10/+8/+33。写死的四对 `_SHAPE_BOX`
**这次不能删**（数据不够，见 §5）。

另有一个比算法更直接的发现：**四庫库里的「蒙」被 𫎇 形污染了**——8 条「蒙」刻例中，有 5 条机器进库（align/match）
的其实是 𫎇 形（§3）。这也是用户看到 0.984 对 0.979 打平的主因之一。

## 1. 方法（`open_guji_cv/clustering/near_shape.py`）

1. **触发**（`trigger_pair`）：首选 c1 与次优**异字** c2 的 cov 差 < `margin`=0.03（与 `consensus_margin` 口径相同）；
   首选 cov ≥ `cov_min`=0.97，否则弃权 `cov_low`；第三个异字距首选 ≥ 0.03，否则弃权 `third_close`，
   即只在两个字之间决胜。
2. **原型**：每个字取库里与查询特征最像的至多 40 条**人裁**刻例（`admissions.provenance='human'`，
   口径同 `human_confirmed_counts`），排除查询自身所在的物理格。任一字少于 3 条 → `few_exemplars`。
3. **差异区域**：σ=1.5 高斯模糊 → 每条刻例 ±2px 平移对齐到两组均值的中点 →
   逐像素 Fisher 比 `(μA−μB)²/(合并方差+0.05)` → 取前 12% 的像素作为区域 W。
4. **局部分**：`s = (d_B − d_A) / Σ W(μA−μB)²`。查询等于 μA 时 s=+1，等于 μB 时 s=−1。
5. **放行**需同时满足：
   - 库内留一正确率 `loo_acc ≥ 0.9`（这一对在本库里自己能分开），否则 `loo`；
   - `|s| ≥ 0.8`，否则 `low_score`；
   - **离群闸** `fit ≤ 1.0`：查询到胜者原型的区域距离不超过胜者组留一距离的 90% 分位，否则 `outlier`。
     这道闸防的是「真字根本不在这一对里」；
   - **翻盘闸**：判次优胜（推翻 cov 排序）只在两者 cov 差 < 0.01 时允许，否则 `flip_blocked`。

后两道闸是 char-clustering 回归逼出来的：第一版在 vol02 把 入 判成 人（入 不在字对里），
cross-seed 把 世 翻成 但（cov 差 0.027）。加闸后两例都弃权，四庫的数字没有损失（§4）。

**接入**
- `GlyphMatcher(near_shape=NearShapeConfig|None, trusted_ids=set|None)`：只改 unsure/diff 档的候选顺序，
  把胜者挪到首位，并写入 `MatchResult.near_shape` 证据；`verdict/char/guard/cov` 一律不动。`None` 表示关闭，此时走原来的 `_match`，行为逐位不变。
- `seeding.load_matcher_from_db / cached_matcher_from_db(near_shape=)`：开启时从 admissions 读人裁 id 作为 `trusted_ids`。
- Step5-a `GlyphMatchParams.near_shape: dict|bool|None = None`。yaml 写 `params: {glyph_match: {near_shape: true}}`
  或 `{near_shape: {tau: 0.9}}`。开启后：
  - 证据落 `MatchRec.near_shape`（字对、胜者或弃权理由、s、loo_acc、fit、n、区域外接框）；
  - 匹配器**没判护栏**的 unsure 格，如有胜者就升 same，`via="near_shape:<s>"`。
- **关闭时逐字节不变**：`near_shape` 为 None 时，参数与产物的 `model_dump` 都不含该键（model_serializer 剔除）。
  已与 origin/main 对比：参数指纹同为 `e008abd788ff73a6`，MatchRec JSON 逐字节相同。见 `tests/test_near_shape.py`。

**为什么选「单独一条升档路径」，而不是只调排序让 consensus 接手**：触发条件是差 < 0.03，consensus 要求差 ≥ 0.03，
两者天然互斥，只重排 consensus 永远不会接手（𫎇 的 cov 还都 < 0.99）。0.03 闸本身没有动。
护栏格（never_match/conflict）只重排、不升档：`allow_guarded=False`。护栏格实测 25/25 全对（§4），
但护栏本来就是为这些字设的，要不要放开交用户裁。

## 2. 为什么能绕开前人的负结果（拿数据说话）

前人负结果（match.py 注释）：用字体渲染**两两**弹性对齐求差异框，残差铺满 64×64，求不出紧凑框。
本方法的区别是用**两组真刻例**的组间/组内方差比：笔粗和错位进了分母（组内方差），只有系统性差异留在分子。

- **可视化** `artifacts/m5_near_shape/diff_regions.png`，每行一对，从左到右六列：μA、μB、Fisher 图、W 叠加、字体两两残差、单例刻例两两残差。
  Fisher 图落在语义差异处：大/太 只亮那一点，日/目 是中间两横，人/入 是顶部交接，曾/會、𫎇/蒙 是字头。
  两两残差则沿每一笔铺开。
- **消融**（同一流程、同一组 423 个触发样本、按页分组，只把 W 的来源换掉）：

  | 差异区域来源 | 决出 | 正确 | 精度 |
  |---|---|---|---|
  | **两组人裁刻例 Fisher 比（本方案）** | 80 | 80 | **1.000** |
  | 字体渲染两两残差（前人路线） | 68 | 64 | 0.941 |
  | 单例刻例两两残差 | 67 | 64 | 0.955 |

  （消融用的是加离群闸和翻盘闸之前的版本，三行口径一致。）
- 前人另一个坑也绕开了：原型只取**人裁**刻例。用全部刻例时，「蒙」的均值长成 𫎇（§3），Fisher 图最亮处跑到右下角，成了伪差异。

## 3. 𫎇/蒙 结果

四庫库（`glyph-db rebuild` 自 `output/glyph_store/`）：𫎇 有 16 条刻例，全部人裁；蒙 有 8 条，人裁 3 条，align 3 条，match 2 条。

- **库污染**：`meng_library_exemplars.png` 第三行和 `meng_heads_zoom.png` 都能看出来。3 条人裁「蒙」
  （v2:vol02:132:8:17 / 134:3:5 / 78:6:14）是「艹」头；5 条机器进库的 `vol01:10:1:15`、`vol01:86:4:3`、
  `vol01:143:3:10`（align）以及 `vol01:133:8:6`、`vol01:149:3:17`（match）都是「业」头，也就是 𫎇。
  整理本写的是「蒙」，align 照抄。**建议用 glyphdb-audit 撤库或改判这 5 条**，这比任何算法都直接。
  本方案只拿人裁刻例当原型，不受这 5 条影响；但这 5 条仍在 kNN/verify 里给「蒙」抬 cov。
- **按页分组留一**（同页刻例不进原型）：16 条 𫎇 查询中，2 条本来就是 same；剩下 14 条里，
  **8 条决出、8 条全对**（含 2 条把错的首选「蒙」翻回 𫎇：167:8:7 s=−1.13、40:8:19 s=−0.87），
  5 条 `low_score`（s 都是 +0.35~+0.74，方向对，但没到 0.8），1 条 `few_exemplars`（134:2:21，同页有一条人裁蒙，被排除后只剩 2 条）。
  3 条蒙查询全部 `few_exemplars`：库里只有 3 条人裁「蒙」，留一后剩 2 条。**0 错、弃权 6/14**。
- 也就是说，用户在本地遇到的 𫎇 新格，大约一半可以自动决出。人裁「蒙」攒到 ≥4 条以后，蒙这一侧也会开始自动决。

## 4. 全回归

| 评测 | 基线（关） | 开 near_shape | 说明 |
|---|---|---|---|
| 四庫人裁刻例按页分组留一（3528 查询） | 自动 same 231 | 决出 **70/70 对**；无护栏升档 45、护栏格重排 25 | 按卷：vol01 42/42、vol02 26/26、vol03 2/2 |
| 同上，按格留一（生产口径） | 231 | 决出 **72/72 对**；无护栏升档 47 | |
| char-clustering `eval_db_match` incremental vol01 | 219/3018，精度 1.0000 | **229**/3018，精度 **1.0000**（近形 10/10） | 新增 `--near-shape` 开关 |
| 同上 incremental vol02 | 371/2897，1.0000 | **379**/2897，**1.0000**（8/8） | 未加闸时 382、0.9974：入←人 |
| 同上 cross-seed vol01→vol02 | 445/2897，1.0000 | **478**/2897，**1.0000**（33/33） | 未加闸时 481、0.9979：世←但 |
| glyph-match/triplets hard | 141 例，rank_acc 0.2766 | 不变（构造上不变） | 评的是 `verify_pair_elastic` 两两打分，不经过匹配器 |
| glyph-match/pairs | P≥0.999 时 recall 0.2056（闸 0.9925） | 不变（构造上不变） | 同上 |
| char-clustering 聚类 purity | 0.99967 | 不变（构造上不变） | 聚类器不调用 GlyphMatcher |

说明：任务书写的 triplets「hard 132 现 0.250」，现在的数据集是 141 例、0.2766，以现跑为准。
这三个两两评测本方案改不动，原因是本方案要求**两组各 ≥3 条人裁刻例**，单对样本上没有组可言。
它们不降，但也不会升。

单测：`tests/test_near_shape.py`（8 条，合成字形：按头部决胜、差异区域只在头部、同形两组弃权、样本不足弃权、
离群弃权、触发规则、关闭不变、翻盘闸、指纹和产物不变）+ `tests/test_glyph_match_step.py` 全过。全量 pytest 结果见末尾。

## 5. 写死的四对 `_SHAPE_BOX`：**不能删**

| 库 | 强/強 | 却/卻 | 回/囘 | 并/幷 |
|---|---|---|---|---|
| 四庫 人裁例数 | 1/0 | 2/0 | 3/3 | 4/0 |
| 北行日錄（bxgb）人裁例数 | 2/2 | 1/6 | 3/0 | 4/2 |

新机制要求每侧 ≥3 条，只有四庫的 回/囘 够格。对两侧的刻例做留一（`min_exemplars=2` 放宽到每侧 2 条）：
新机制决出 3/6，3 条全对，另外 3 条弃权；旧机制 6/6 对。在 bxgb 上新机制全部 `few_exemplars`，强行降到 2 条时 并/幷 全部 `loo`。
旧机制靠字体兜底、没有弃权：bxgb 上 强/強 3/4、却/卻 5/7、并/幷 5/6、回/囘 3/3。它会错，但能出结论。

结论：现在删 `_SHAPE_BOX` 会让这四对退回「全拿不准」，代码简化了但覆盖降了，不符合「不降」。
**建议保留**，等两侧人裁刻例各 ≥3 条后再用新机制复测，再删。两者可以同时开，但两个都开时，
旧重排会把 Dice 分写进 candidates 的分数位，之后的近形触发会读到它。这是边角情况，若决定并存，建议改成旧机制只在新机制弃权时才生效。

## 6. 会从「拿不准」变成「能决」的字对（四庫，按格留一，前 20）

格式：字对 决出/正确（人裁例数 A/B）

大太 14/14 (21/16) · 論諭 11/11 (13/20) · 日目 8/8 (18/9) · **蒙𫎇 8/8 (3/16)** · 人入 5/5 (15/28) · 曾會 5/5 (11/7) ·
未朱 3/3 (8/10) · 入八 2/2 (28/5) · 共其 2/2 (4/6) · 玉王 2/2 (6/10) · 彝𢑴 2/2 (6/4) · 剛副 1/1 · 刪剛 1/1 · 巳巴 1/1 ·
曰目 1/1 · 未末 1/1 · 决次 1/1 · 三王 1/1 · 諸講 1/1 · 遺還 1/1 · 間閱 1/1

其中 大太、論諭、人入 多数在 never_match 护栏下，当前默认只重排、不升档。按卷核对（vol03 是最新的人裁）：
vol03 2/2、vol02 26/26、vol01 42/42。

为什么覆盖不高（1843 次触发只决出 72）：`cov_low` 1018 次（首选 cov < 0.97）、`few_exemplars` 339、
`third_close` 253、`loo` 81、`low_score` 76、`outlier` 4。最大的两块是首选整字都不太像，以及人裁刻例不够；
人裁积累起来后覆盖会自然上升。`日/曰`、`已/巳/己` 这类高频对基本卡在 `loo`：在本库里，它们的人裁刻例在像素层面本身就分不开，
这和 g3g4 的核心负结果一致。

## 7. 建议默认值

- **代码默认：关**（任务要求，且保证产物逐字节不变）。
- 建议四庫先在一册试开：`params: {glyph_match: {near_shape: true}}`，参数用 `NearShapeConfig` 的默认
  （`tau 0.8 / loo_min 0.9 / fit_max 1.0 / flip_margin 0.01 / cov_min 0.97 / min_exemplars 3`），`allow_guarded` 保持 false。
  这些阈值是在同一批 423 个触发样本上挑的。附近有平台：`tau 0.6` 时决出 103、错 1；`tau 0.8` 时决出 80、错 0。
  所以 0.8 留了一档余量，但不算独立验证；char-clustering 是唯一的独立集，上面 0 错。
- 先撤掉 §3 那 5 条错标的「蒙」。
- 是否对 never_match 护栏格放开升档（实测 25/25）、是否删 `_SHAPE_BOX`，交用户裁。

## 文件

- 新增 `open_guji_cv/clustering/near_shape.py`、`tests/test_near_shape.py`、`artifacts/m5_near_shape/`（三张图 + 复现脚本，
  脚本里的 scratchpad 路径要改；`dump.py` 导库到 npz → `harvest.py` → `trig.py` → `online.py` / `ablate.py`）
- 改动 `clustering/match.py`（`_match` + `_apply_near_shape`）、`clustering/seeding.py`（透传和 trusted_ids）、
  `steps/glyph_match.py`（参数和升档）、`products/kinds/recog.py`（`MatchRec.near_shape`）、`scripts/eval_db_match.py`（`--near-shape`）
- 没写 overview issue：这个 session 申请 `open-guji-core/overview` 的写权限被拒，所以只写了本 HANDOFF。
