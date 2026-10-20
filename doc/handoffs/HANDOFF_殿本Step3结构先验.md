# HANDOFF：殿本 Step3 结构先验——先在 vol04 上开 `layout_prior`，量过再推开

- 交给：做殿本整理（重跑 vol04–10）的会话。
- 交出：切分负责会话。用户 10-19 晚定，**切分的事全部归它**，`colgold_prior`、`yolo_merge`、colgold 金标、`column_counts` 评测都包括在内；原来做 C／D 的会话已停。
- 本文取代 [HANDOFF_colgold_CD_vol04-10.md](HANDOFF_colgold_CD_vol04-10.md)。

## 零、先读这几条

1. **殿本只开 `layout_prior`（逐列格位约束），C（`colgold_prior`）、D（`yolo_merge`）都不开。**
   - 两个表都出自 daizhige 逐列本。C 能用的 13,602 列，格位表全覆盖。
   - C、D 和它同时开时，代码让格位表里有的列跳过 C、D（同列互斥），所以开了 C、D 也没有列可动。D 还要每页多跑一次 YOLO，Step3 慢一倍。
   - 三个开关怎么选，见 [选法表](../segmentation_v2_pipeline.md)「Step3 结构先验：三个开关的名字与选法」。
2. **范围（用户 10-19 定）**：先只做 vol04。验收过了、用户点头，再按同样做法逐册推到 vol05–10。
3. **带任何人裁的列，`layout_prior` 不碰。** 人裁包括逐列字数、切点、钉线、强制正文/小注。原因是人裁按格号记，抬头级数一改格号就错位。这条是代码保证的，vol01 p40–80 上用真人裁核过：154 列人裁列与不开时逐字节相同。
4. **反正要重跑**：`column_gate`、`row_segment` 两步的 code_hash 在 v0.4.6 都变了，各册升级后本来就要从 Step2 交接闸起重算。趁这次把开关打开，不多花一遍工夫。开关关着时，产物与旧版逐字节相同。

## 一、准备

1. **代码**：`rc/v0.4.8` 或之后，`row_segment` 版本 ≥ 1.20（1.19 有抬头错位的毛病，见第五节）。不用装额外依赖。
2. **格位表**：
   ```bash
   python scripts/dzg_layout.py --ws $WS
   # 输出「14982 列 → …/corpus/daizhige/layout_slots.jsonl」
   ```
   - 读的是工作区整理本目录下 `daizhige/` 里的 `0001–0005.jsonl` 和 `page_map.jsonl`；迁过中心库的工作区，这个目录在数据目录里，脚本会自己找。
   - 同一（册、页、列）有多行的整列剔除（vol01 p102 c1）。
   - `corpus/` 归中心库管。要不要 `guji db push` 让别的机器也拿到，按你的授权规矩办，拿不准就问上级。
   - 表内容的 sha 进 Step3 指纹：重新生成而内容不变，不判过期；daizhige 或 `page_map` 改了、表跟着变，各册 Step3 判过期一次。
3. **册配置写法**（vol04 验收通过、用户点头后才写进生产）：
   ```yaml
   params:
     row_segment:
       layout_prior: corpus/daizhige/layout_slots.jsonl
   ```
   开关开着而表不存在时会直接报错，不会静默当没开。

## 二、vol04 怎么量（先在沙箱，不碰生产 `products/`）

用两个并排的沙箱工作区，A 是基线，B 开 `layout_prior`。两边只在 Step3、Step4 不同。

```bash
# A：现行代码、开关全关，跑到 cell_shrink
guji pipeline keben_body_v2 vol04 --to cell_shrink --pages all -w $A

# B：books/ feedback/ corpus/ workspace.yaml 拷自 $A；cache/ 软链到 $A 的 cache/；
#    products/vol04 从 $A 拷一份（Step1–2 共用），只重跑 Step3–4
guji pipeline keben_body_v2 vol04 --from row_segment --to cell_shrink --pages all --force -w $B \
  --params '{"row_segment":{"layout_prior":"corpus/daizhige/layout_slots.jsonl"}}'
```

**两个口径都要报**。只看字数会高估 C、低估 `layout_prior`：C 修字数靠减格数并字，减掉一格之后的格号全部漂移。

- **逐格**：列里每个（slot，夹注 a/b）都和 daizhige 一致才算对。
  ```bash
  GUJI_WS96=$WS python research/dzg_struct_prior/structcmp.py $A/products vol04 --out a.json
  GUJI_WS96=$WS python research/dzg_struct_prior/structcmp.py $B/products vol04 --out b.json
  python research/dzg_struct_prior/flipcmp.py a.json b.json --min-page 4
  # 两个口径各一行：准确率、修好、改坏，再逐列列出改坏的
  ```
  `GUJI_WS96` 指书的工作区；daizhige 目录按整理本目录去找，找不到时可以用 `GUJI_DZG` 直接指定。
- **字数**：用 `guji eval run column_counts`（`scripts/eval_column_counts.py`）。金标是 open-guji-dataset 的 `char-segmentation/column-counts`。
  ```bash
  GUJI_WORKSPACE=$A python scripts/eval_column_counts.py <open-guji-dataset> --books vol04 --no-ensure --show 0 --json-out ca.json
  GUJI_WORKSPACE=$B python scripts/eval_column_counts.py <open-guji-dataset> --books vol04 --no-ensure --show 0 --json-out cb.json
  ```
  `flipcmp.py` 也报字数口径（与 daizhige 比），这一项是与另一份金标的交叉核对。

**参照数**：纯算法、不带人裁，去卷端页，共 1,935 列。

| 口径 | 基线 | `layout_prior` | 修好 | 改坏 |
|---|---|---|---|---|
| 逐格 | 95.40% | 98.29% | 59 | 3 |
| 字数 | 97.16% | 98.45% | 30 | 5 |

带人裁的列不动，所以生产口径下修好的列会少一些，这是正常的。

**改坏的列逐列看图**：`python research/dzg_struct_prior/viewcols.py $A $B out.png vol04:6:2 vol04:8:2 …`，会把列图和 A（红）、B（绿）两边的字框并排画出来。纯算法下 vol04 改坏的 3 列是：

- p6 c2、p8 c2：缩进列首格的框线残渣被切成了字，即多出 slot 1；
- p127 c2：slot 5 的字被并掉。

## 三、vol04 验收

1. **沙箱 A／B**：
   - 两个口径都不降；
   - 改坏的列每列看过图、归了类（框线／印章残渣，金标或 daizhige 错，别的原因）；
   - 改坏的列数不超过修好的十分之一。
2. **用户点头后上生产**：把参数写进 vol04 册 yaml，`guji status vol04 -w $WS` 应显示从 `column_gate` 起过期。然后 `guji pipeline keben_body_v2 vol04 -w $WS` 重跑到 Step7，再 `guji close-check vol04 -w $WS`。
3. **报人审率**：报 vol04 未放行格数，前后各一次，口径同 [人审率分析](../research/人审率分析-vol04-09/README.md)。切分那三类（A1／A3／A4）应该明显少：vol04 上这三类所在的列，约一半在离线结果里被修好。
4. **close-check 2d 整页提示**：2d 会点名「一页 ≥3 列没交代」的页（如 vol04 p130 整页破损、p216–218 拆页），这些页写进 `feedback/lists/vol04-重切清单.tsv`，整页处理。

## 四、vol05–10

vol04 过了、用户点头后，逐册照第二、三节做，每册一行报：两个口径的准确率、修好、改坏、人审率前后。

参照数（纯算法，去卷端页）：

| 册 | 列数 | 逐格 | 字数 |
|---|---|---|---|
| vol05 | 1,656 | 94.38% → 99.03% | 97.58% → 99.21% |
| vol06 | 1,305 | 95.10% → 99.08% | 96.86% → 99.31% |
| vol07 | 1,161 | 95.52% → 98.71% | 97.24% → 99.05% |
| vol08 | 594 | 92.76% → 98.65% | 95.79% → 98.82% |
| vol09 | 2,322 | 95.35% → 98.32% | 96.60% → 98.32% |
| vol10 | 1,548 | 96.51% → 98.97% | 97.42% → 98.97% |

## 五、已知的坑

- **缩进列首格的框线残渣**：这是 `layout_prior` 改坏的主要来源。研究文档 §六·4 有一条「列端窄规则」专治这个，收益约 0.3 个百分点，要动 Step4，还没进代码。看图时这一类单独记数，够多就交回切分负责会话做。
- **整页破损、拆页、Step1 列错位的页**：结构先验救不了，走整页重切。vol05 p55／p123、vol04 p80 已有 `border_detect.column_grid_pages` 可以点名。
- **抬头字不在列图里／低起的列**（vol04 产物包 `cv0.4.7-c1-g-82293e-*` 实测，84:5、65:8、127:1–2）：v0.4.7 按表硬改抬头级数，这几列整列格网错位劈字，84:5 放行了错字。`row_segment` 1.20 起改成表与闸不一致时两种格网都切、取穿字少的，产物 flags 记 `layout_raise_gate`。验收要用 ≥ 1.20 的代码。
- **structcmp 有盲区**：它只比格号集合。抬头字不在列图里、格网整体错一位时，格号集合照样对得上（84:5 在 v0.4.7 被它判成「修好」）。所以逐格口径之外，还要跑 `research/dzg_struct_prior/cutcheck.py`（只看图，数横穿字的格线），差得多的列看图。
- **daizhige 自己没记抬头**：daizhige 漏记抬头时，表里的抬头级数也跟着错。vol07 p44 c5（首字「聖」抬头）就是一例，这一列开了以后要看图。
- **卷端页**（p1–3）没进参照数，开关照样作用在这几页上，看图时留意。
- **夹注列**：只有两半都有字的格才强制拆；段尾单字、行内空格只剩一半的，交给现有判据。
- **下游跟着变**：Step3 一变，Step4 以后（字块、匹配、放行）都会重算。进度靠后的册开之前先问上级。
- **A、B 两边要是同一份代码**：
  - 借 `PYTHONPATH` 用另一个工作树的代码时，进程要在那个工作树里启动。`python -c …` 和 `python -m …` 会把当前目录排在 `PYTHONPATH` 前面，在主检出里启动就会悄悄用上主检出的代码。
  - 全书重跑期间，不要在正跑着的检出里改代码或切分支。每册是一个新进程，会读到改了一半的代码，两边的版本就混了。要改就另开一个 worktree。
  - 两条都是做 C／D 的会话踩过的。

## 六、不在本单

- **C、D 留给别的书**：
  - C 用于整理本分行、但不记格位的书（如光盘版那类）。表里要有可靠的起始格 `start`；`start` 为空的行 C 不收。按图推的 `start` 在全书上风险面大，见设计 19 第八节。
  - D 用于没有整理本的书。
  - 怎么开、怎么量，见 [design/19](../design/19-yolo-release列字数先验与全书评测-总设计.md)，以及旧交接单在 `ed3790da` 时的版本。
- **整理本不分行**的书：先对位分列，再接 C。原型在 `research/dzg_struct_prior/unsplit_colcount.py`，研究文档 §十一。

## 七、交回什么

1. vol04：沙箱 A／B 两个口径的表、改坏列的看图结论、生产重跑后人审率前后、close-check 2d 点名的页。
2. 你的建议：vol05–10 是否照开，要不要先做列端窄规则。

写进对应的 Jira 卡，由用户定。切分算法上的问题（新的改坏类型、规则要改）交回切分负责会话。

研究与实测全文：[切分现状梳理与新方向-2026-10-19](../research/切分现状梳理与新方向-2026-10-19.md)（§六 离线实测、§八 与 C 对比、§十一 不分行、§十二 对照人审率分析）。
