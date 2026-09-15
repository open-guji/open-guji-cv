# 现代印刷链 `modern_body`：设计、配置与北行日錄实测

> 2026-09-14 立。设计正本在 overview 仓 `项目进展/图片初步数字化/进度/总览/05-三模式管线方案.md`
> （三模式：古籍 / 现代竖排 / 现代横排），本篇记**已落地的部分**与第一本书的实测。
> 横排（原图入口旋转 90°）**尚未接入**，`BookSpec.writing_mode` 只登记不生效。

## 一、一句话

九步一步不删。现代印刷本与刻本的差别只在切分线前三步，各用**新 Step 文件**顶替
（不动切分侧会话正在改的 `border_detect / column_warp / row_segment`，刻本链产物指纹不受影响），
产**同一套产物种类**，Step4 起原样复用：

| 步 | 刻本链 | 现代链 | 差别 |
|---|---|---|---|
| 0 | `preclean`（按需） | **`guji split`**（分页，按需） | 一张扫描页拼两页原书时先裁成逻辑页 |
| 1 | `border_detect`：找版框墨线 | **`line_detect`**：找墨柱 | 无版框界行；产 `borders`（虚拟界行）+ `line_index`（各列类型） |
| 闸1 | `border_detect_gate` | **`line_detect_gate`** | 产同种 `border_detect_gate_manifest` |
| 2 | `column_warp`：射影 + 剥界行 + 削版框 | **`column_crop`**：裁剪 + 去噪 + 抹长横线 | 没有墙可剥 |
| 闸2 | `column_gate` | 同一道，`count_mode=detected`、`width_tol=0.5` | 列数由 Step1 探出；卷题页列位不等距 |
| 3 | `row_segment`：固定 N 格弹性 DP | **`row_segment_runs`**：墨段 + 字身盒模型 DP | 项数不定、标点挤压、字距随列调整 |
| 4～9 | 复用 | 复用 | 字形库按 `edition` 分域（`modern:<book>`，未开工） |

三处与模式无关的**地基**（`core/`）：pipeline yaml 的 `params:` 段（同一 Step 在两条链里默认
参数不同）；`Pipeline.producer_of` / `RunContext.producer`（同一种产物两个产出者，按当前管线查，
`RunContext` 不带管线时按 `Book.edition` 选默认管线）；`load_book` 优先读工作区 `books/`。

## 二、配置

册 yaml（工作区 `books/<id>.yaml`）新字段，旧册不写等于现状：

```yaml
edition: modern              # 选默认管线与字形库域
writing_mode: vertical-rl    # horizontal-tb 尚未实现
frame: none                  # none → Step1 走 line_detect
script: trad
raw_dir: data_full/bxrl      # 逻辑页（split 产物）
page_split:                  # 有这一段才需要 guji split
  mode: two_rows_hline
  source_dir: data_full/bxrl_scan
expected_cols: 17            # 现代链里是上限，不是等式
pitch_prior: 118.0           # 字距兜底
```

管线 `pipelines/modern_body.yaml`：steps 换前三步，`params:` 给 `column_gate` 两个覆盖。

命令：`guji import-pdf <pdf> --out <dir>`（1:1 抽页）→ `guji split <book>` →
`guji pipeline modern_body <book> --from line_detect --to cell_shrink --pages all`。

## 三、算法要点（判据全部来自北行日錄实测，换书要重看）

**分页 `utils/page_split.py`**：分界三级——实线（整行墨占比 ≥ 0.3）→ 淡线/断线（最长连续墨段
≥ 0.1 页宽；文字行再密连续段也 ≤ 0.03 页宽）→ 白带（≥ 60 行零墨）。**淡线必须排在白带前**：
扫描页 4 的白带在淡线下方，先找白带会把淡线裹进上栏，每列底端多一条细横条、Step3 每列多一项。
栏的上下界由「强正文行段」（跨度 ≥ 0.1 页宽、密度 ≥ 0.003）定，弱段（跨度 ≥ 0.02）只有紧挨
（≤ 150px）强段才收——挡住影印本页码（跨度 0.042、离正文 240px+），收进首列高出一字的首字
（末页「獨見李同年」，跨度 0.026、离强段 22px）。书口竖线先抹，否则每行都「有墨」。

**行探测 `utils/line_layout.py`**：列 = 列方向投影 > 0.008 的段；em = 最宽一族宽度中位；
正文列 0.75～1.35 em；两条相邻窄段拼成一字宽 → 双行小注整列（`jiazhu_pair`，Step3 还切不了）；
贴着正文列且 y 在其内的窄段 → 并回（卷题下的小注子列）；块内 ≥ 0.4 块高的窄段 → 小字整列
（`small_col`，脚注）；长竖线外侧或离块 > 1.5 列距 → 书口小字 `margin`。相邻正文列中心距
≈ k × 列距时补 k−1 个 `empty` 列位（卷题页），否则两列共用中线、窗口宽一倍。上下框在块外
0.6 em——要 > Step4 extractor 找框线行的窗口 40px，否则首末字横笔被当框线。

**切分 `utils/run_segment.py`**：按纯白缝切墨段；小于 0.55 em 且靠列右半的小块 = 标点形态；
DP 把连续墨段合成项（跨度 ≤ 1.15 em，且 ≥ 单段最高——em 估小时不至于无解），代价 = 相邻
项中心距偏离本列 pitch（字–字紧、标点两侧松）。`一` 自成一项：并进邻字会让中心距塌成半个
pitch。冒号「︰」两点合一个标点项（都是靠右小块、合跨度 ≤ 0.6 em）。**两遍法**：先每列自估
em/pitch，取页中位；再拿页级值当 hint 重切每列——小字多的列（人名注「張說、張掄、宋鈞」连排）
自估 em 偏小到 87（字身 104），DP 无解退化成「每段一项、无标点」；短列（「二月」）自估不出。
脚注列（small_col）不套页级值。

## 四、北行日錄实测（2026-09-14）

工作区 `D:\workspace\beixingrilu-workspace`（`GUJI_WORKSPACE`），册 `bxrl`：樓鑰《攻媿集》
卷一一九～一二〇《北行日録》现代排印本影印，40 张扫描页 3888×6000（约 600dpi，1-bit），
每张上下拼两页原书，栏间横线；字身 ≈103px、列距 185.5px、每栏 ≤17 列、每列 14～16 汉字 +
2～4 标点（标点挤压、字距 111～132px 随列调整）；卷题下双行小注 1 处、单行小字人名注 46 处、
脚注 ①② 十余处（栏内左端小字窄列）。用户给的校對本 2.4 万字（一行一列、影印页码分块）当证人。

**Step1–3 与校對本对账**（工作区 `scripts/witness_check.py`，按影印页码映射；两边都跳过脚注；【】合并）：

| 指标 | 值 |
|---|---|
| 扫描页列数 + 页内总项数与校對本全等 | **29 / 40** |
| 全书总项数 | 22,137 vs 校對本 22,131（+0.03%） |
| 逐列项数相等 | 1,234 / 1,309 = 94.3%（含校對本自身的换行错位） |
| 全链 Step1→3 单页耗时 | ≈ 0.5 s（Step4 另 1 s） |

**剩下的不等，逐条看过图，绝大多数是校對本的噪声**：换行错位（p39 c13/c14「虜」在图上第 13
列末，校對本放到下一行）、小注前后的「、」「。」被省略（「周邵州、伯駿。」「正字，仲友。」）、
漏字（「甲人依」少「人」）。**我们的已知短板**：挤压成一格的「」「（几何上与「二」无法区分，
p36 c12）；「？」被切成钩+点两项（全书 2 处）；卷题页的双行小注整列切不出来（1 处）。

## 五、Step5：证人标签、字体判定、播种（2026-09-15）

三条新命令，都在 `cli_v2`：

| 命令 | 做什么 | 北行日錄实测 |
|---|---|---|
| `guji witness-align <book>` | 列级证人对齐（`utils/witness_align.py`）：整理本一行 = 一列，Step3 项数与该行字符数相等的列，字位与字符一一对应 → `products/<book>/witness_align/labels.jsonl`。项数不等的列整列不给（不猜） | 1,234/1,309 列对齐 → 20,852 个字位标签 |
| `guji calibrate-font <book> [--manifest … --norm-stroke 3]` | 字体判定（`utils/font_calibrate*.py`）：标签字位在各套字体里检索，recall@1/@5、正确/错误命中 cov 分布、可分性 margin | 见下表 |
| `guji seed-witness <book> --fonts font:iming,font:simsun` | 播种（`utils/seed_witness.py`）：证人字 × 任一字体 top-1 一致 → `admit_instance(provenance="align", edition="modern:<book>")`，来源 `kind=print`。**两阶段**：先全部检索再全部进库——边检索边进库会让 `GlyphDB.query` 的特征缓存每条失效，25 分钟只进 4,101 条 | 17,269 字位 → 进库 16,279（两套都认 14,013、只一套认 2,266）、字体不认 962（5.6%）；1,976 字头 |

### 五.1 字体判定：三种量法，结论一致

候选七套（工作区 `config/fonts/manifest.json`，本书 2,091 字表）：仓内 I.Ming、Jigmo，本机
細明體 MingLiU、宋体 SimSun、Noto Serif TC/SC，另加用户指定的**中华书局宋体**
（github xiangrongjingujiu/ZhongHuaSongFont，古联委托方正制作，三平面 13 万字，本书字表全覆盖）。

| 量法 | I.Ming | SimSun | Noto SC | Noto TC | MingLiU | Jigmo | 中华书局宋体 |
|---|---|---|---|---|---|---|---|
| 经库、原样渲染（recall@1） | 0.915 | **0.917** | 0.869 | 0.854 | 0.827 | 0.832 | 0.818 |
| 直接比对、两边细到 2px | **0.939** | 0.929 | 0.911 | 0.915 | 0.920 | 0.907 | 0.876 |
| 直接比对、两边细到 3px | **0.948** | 0.926 | 0.917 | 0.925 | 0.926 | 0.907 | 0.874 |

三个教训：

1. **原样渲染那一行是在量粗细**：书上字块归一到 64px 后笔画 5.5px，SimSun/I.Ming/Jigmo 渲染
   3.8px，中华书局宋体/MingLiU/Noto 2.7px，排名与笔宽严格同序（`utils/font_calibrate_direct.py`
   `stroke_width_px`）。匹配栈 2026-08-24 起「不做笔宽归一」是给刻本定的，现代印刷同字同体，
   粗细差反而是主噪声；
2. **把字体加粗到书的笔宽再比是假象**：七套字体正确/错误命中 cov 全部 0.998～1.000、刻本 same 闸
   判 644/675——64px 图上 5px 宽的笔画，差一笔的形近字在软覆盖（τ=1.5、块内 ±1px）下也几乎
   全覆盖，比对饱和，只剩 HOG 粗排在起作用；
3. **两边骨架化再统一细化到 3px** 才是在量字形：I.Ming 第一、SimSun 第二稳定；中华书局宋体在
   三种量法下都垫底——**这本书不是用它排的**（它 2020～21 年才造，本书排印年代更早，是铅字/照排
   宋体谱系，SimSun 与之同源）。

七套字体的 margin（p10 正确 − p90 错误）全部为负（细到 3px 时 SimSun −0.003、I.Ming −0.007），
与方案 §一.2 的预判一致：**字体只当候选源与播种的形状证人，不当精确判据**。选定
**I.Ming + SimSun**（前二、字表全覆盖；I.Ming 是自由字体可随仓库走，SimSun 是 Windows 系统字体
只在本机用），其余五套已 `glyph-db drop-edition` 删掉。

### 五.2 书自己的库能不能当精确判据：能，但必须笔宽归一

同书留一法（工作区 `scripts/self_match_bench.py`，模板 = 证人标签字位，查询摘掉自己）：

| 归一 | recall@1 | cov 正确 p10/中位 | cov 错误 中位/最高 | 刻本 same 闸（0.996） |
|---|---|---|---|---|
| 不做笔宽归一（12k 模板、800 查询） | 0.9938 | 0.9993 / 0.9995 | 0.9875 / **0.9996** | 794 对、**2 错**（却→卻、内→內） |
| 骨架化细到 3px（6k 模板、600 查询） | **0.9983** | 0.9992 / 0.9995 | 0.9220 / **0.9220** | 591 对、**0 错** |

所以 `modern_body.yaml` 给 `glyph_match` 两个参数：`norm_stroke: 3`（`load_matcher_from_db` 从
canonical 图块现算带笔宽归一的 norm，不用库里存的 `derived.norm`；查询侧同法）、
`exclude_self: true`（库就是这本书自己的字位，不摘自己就是自证 cov 1.0）。Step5-a 在现代书上
`edition` 缺省 = `modern:<book>`。刻本链两个参数都是缺省值，行为逐位不变——但 `GlyphMatchParams`
多了字段，刻本 Step5-a 产物的 params_hash 会变、显示过期，重跑结果相同。

### 五.3 Step5-a 全书结果（工作区 `scripts/glyph_match_check.py` 对账证人标签）

| 指标 | 值 |
|---|---|
| 字位 / 有证人标签 | 22,197 / 17,419 |
| 档分布 | same 14,109 · unsure 4,428 · diff 3,660 |
| same 档覆盖（有标签的） | 13,283 / 17,419 = **76.3%** |
| same 档与证人一致 | 13,242 / 13,283 = **99.69%**（41 个不一致） |
| 其中同形异码 | 32：強/强 ×4、內/内 ×9、稅/税 ×3、換/换 ×3、戶/户 ×2、搖/摇、衞/衛、卻/却…——书上只印一种形，证人两种码都用了，库被播成了两个字头，谁先命中算谁 |
| 其中真形近误判 | **9**（鐘→鍾、揚→楊、贏→嬴、旦→且、字→宇、宣→直、內/内 之外的）= 9 / 13,283 = **0.07%** |
| 单页耗时 | 库 16k 字块建索引（含笔宽归一现算）≈ 90 s 一次；逐页 ≈ 12 s |

两条结论：**同形异码要走异体归一层**（刻本链的 `variant_form` / `config/variants` 三层表——
播种前先把证人字归到刻本形/通行形其一，或按 `SEMANTIC_MERGED_PAIRS` 的思路把这组当同一字头）；
**真形近误判 cov 也在 0.996 以上**（鐘/鍾 0.9994、旦/且 0.999），same 闸分不开，得靠 Step6 上下文
——与刻本链「形近字对在任何全局相似度下分布重合」的负结果（`g3g4_error_analysis.md`）一致，
只是这次的形近对是印刷字体自己的（鐘/鍾、揚/楊、字/宇），要补进现代字体的 `NEVER_MATCH_FAMILIES`。

## 六、没做的与下一步

- 横排：原图入口旋转 + `to_original()` + 叠图逆旋转（方案 §三），没动；
- `」「`/`？`/双行小注整列：留给 M3；
- 标点字位未播种（`seed-witness` 只收 `kind=char`）；
- 分页的 manifest 记了逻辑页 ← 扫描页的矩形，Step9 回扫描页坐标时用；
- 控制台前端未认识新 Step id（`line_detect`/`column_crop`/`row_segment_runs`），CLI 叠图
  （`guji product overlay`）已支持。
