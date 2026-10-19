# HANDOFF：殿本 vol04–10 开 Step3 的结构先验（逐列格位约束／C／D），看效果

交给：跑殿本 vol04–10 的会话。交出：做 C／D 的会话（open-guji-cv#204，已合进 `rc/v0.4.6`）。2026-10-19。

**要你做的**：在 vol04–10 上把 Step3 的结构先验开起来跑，跟不开的比，报每册「修好几列、改坏几列」。改坏的列逐列看图。最后建议哪个开关写进册 yaml。

> **范围（用户 10-19 定，经 layout_prior 会话转达）：先只在 vol04 上开 `layout_prior`，量过再推到其余各册。**
> 所以第一步只做 vol04：三个变体并排比，交回证据，等用户点头。用户点头后，vol05–10 再照同样的做法逐册跑。
> 下面写 vol04–10 的地方，都按这个顺序理解。
>
> **10-19 晚更新：先读这段。** 逐列格位约束 `layout_prior`（open-guji-cv#227）也合进 `rc/v0.4.6` 了。
>
> - **殿本首选 `layout_prior`，不是 C。** 殿本的整理本（daizhige）是逐列、带格位的，[选法表](../segmentation_v2_pipeline.md)（「Step3 结构先验：三个开关」一节）定的就是 `layout_prior`。
> - **开了它，C、D 在殿本上几乎没列可动。** 两个开关同时开时，格位表里有的列自动跳过 C、D。格位表覆盖了 C 能用的全部 13,602 列。
> - **下面第二节 C+D 的数，只在不开 `layout_prior` 时成立。**
> - **那边的离线实测**（纯算法，vol04–10 去卷端页，10,521 列）：字数 97.03% → 98.81%，错列 503 → 139；逐格 95.22% → 98.68%。我这边 C+D（沙箱、带当时的人裁）是 96.41% → 97.73%，错列少了 140 个。两边口径不同，不能直接相减，所以要你在同一口径下并排量。
> - **变体就三个**：A 基线；B 只开 `layout_prior`；C C+D。准备与跑法见第三、四节的补充。
>   - 「`layout_prior` + `yolo_merge`」不用跑，它和只开 `layout_prior` 等价：vol04–10 的 10,645 个过闸列里，格位表覆盖 10,574 列；剩下 71 列，我那次 C+D 全书实测里 D 一列也没动。
> - **逐格口径**（那边 vol04+05 去卷端页、纯算法）：
>   - C 按字数口径修好 32 列，其中 28 列 `layout_prior` 也修好了。另外 4 列（vol04 p6 c6、p8 c4、p79 c7、p130 c9）只是字数对上了，格子仍是错的：列首残渣留着，末字被并掉。所以**按逐格口径，C 修好 0 列**。
>   - `layout_prior` 逐格修好 136 列、改坏 3 列；按字数口径改坏 5 列，多是缩进列首格的框线残渣被算成了字。
>   - 所以只看字数会高估 C、低估 `layout_prior`，**两个口径都要报**。

**开不开由用户定**（[开关登记表](../开关登记表.md) 的规矩）。你交的是证据（每册对比表、改坏的列看图结论），不要自己改册 yaml。

设计与全部实测记录：[design/19](../design/19-yolo-release列字数先验与全书评测-总设计.md)（第八节是变更记录）；对比调研：[research/yolo_release_comparison.md](../research/yolo_release_comparison.md)。

## 一、C、D 是什么（各一句话）

| | 参数 | 做什么 | 依赖 |
|---|---|---|---|
| **C** | `row_segment.colgold_prior` | 本列切出的字数与金标差 1–2 个时，按目标格数重切一次，**重切后字数恰好对上才采用**，否则原样保留并记 `colgold_conflict` | 金标表 `corpus/daizhige/colgold.jsonl`（见第三节） |
| **D** | `row_segment.yolo_merge` | yolo_tool 字框模型整页推一遍；同一个字框盖住本列相邻两格（一字被切成两半，典型是「三」切成「一」＋「二」），就把目标字数减一重切，对上才采用 | yolo_tool 的 ONNX 模型、`pip install -e ".[yolo]"` |

- 两个都开时**先 D 后 C**。
- 两个开关都**缺省关**，关着时 Step3、Step4 产物与 main 逐字节相同。
- 夹注列、**带任何人裁的列**都不动。人裁包括 `column-slots`、切点、钉线、强制正文/小注。

## 二、我量出来的数（你复现时对照）

**沙箱口径**：guji-workspace 10-19 的册 yaml 与人裁，现行代码从 page_survey 全量重跑；基线与 C+D 的差别只在 Step3／Step4。

- 当时 vol04–10 没有任何人裁事件。你的生产工作区若已有人裁，那些列 C、D 不动，数字会跟下表有出入，这是正常的。
- 金标是 open-guji-dataset `char-segmentation/column-counts`，共 14,987 列。
- 评测命令：`guji eval run column_counts`，即 `scripts/eval_column_counts.py`。

| 册 | 列数 | 基线 | C+D | 修好 | 改坏 |
|---|---|---|---|---|---|
| vol04 | 1,932 | 96.79% | 98.03% | 24 | 0 |
| vol05 | 1,659 | 96.93% | 98.55% | 27 | 0 |
| vol06 | 1,309 | 96.56% | 97.78% | 16 | 0 |
| vol07 | 1,173 | 96.42% | 97.02% | 8 | **1** |
| vol08 | 611 | 93.94% | 95.74% | 11 | 0 |
| vol09 | 2,334 | 96.23% | 97.81% | 37 | 0 |
| vol10 | 1,563 | 96.48% | 97.63% | 18 | 0 |
| **合计** | 10,581 | **96.41%** | **97.73%** | **141** | **1** |

- **唯一的改坏**：vol07 p44 c5。首字「聖」抬头在 -1 格，金标 `start` 却记 0（daizhige 没记这处抬头）；列尾又刚好有一条框线落在金标格位段里，C 数成 22 字，并错一格。
  - dataset 里这条已改正，但 `dzg_import colgold` 是从源数据重新生成的，生成的表里仍是 0。
  - 处理办法：在控制台对这一列做一次逐列字数人裁（`column-slots`）。有人裁的列 C、D 都不碰。
- **C、D 分开开**：只在测试 B（vol04／05 抽 100 页、900 列、纯算法）上量过。基线 97.0%；C 98.1%（修 10）；D 97.8%（修 7）；C+D 98.44%（修 13、改坏 0）。全书没分开量过；要分开看就跑三个变体。

## 三、准备（按顺序）

1. **代码**：`rc/v0.4.6` 或之后（含 #204）。
   - 装可选依赖：`uv pip install -e ".[yolo]"`（onnxruntime），然后 `python -c "import onnxruntime"` 自检。
   - row_segment 的 code_hash 是 `a9f270b156c01af1`，比 v0.4.5 变了。各书 Step3、Step4 会判一次过期，开关不开内容也不变。
   - 如果 layout_prior（#227）已经合进来，版本是 1.19、hash 另算；它命中的列 C、D 也不动。
2. **YOLO 模型**：`add_repo(open-guji, yolo_tool)` 后 clone。模型在仓里 `model/type/best.onnx`（约 104 MB）、`model/slide/best.onnx`（约 12.5 MB），`yolo_model_dir` 指向 `model/` 目录。
   - 开关开着但模型不在，会直接报错。
   - 指纹按两份 onnx 的内容算，换模型 Step3 判过期。
3. **金标表**（C 用）：
   - **release**：`add_repo(open-guji-core, file_archive)`，release tag `siku-qiefen`。仓是私有的，直接下浏览器链接只会拿到 9 字节的 Not Found；要走 API：`GET https://api.github.com/repos/open-guji-core/file_archive/releases/assets/<asset id>`，请求头 `Accept: application/octet-stream`。解压得到 `96mid1ogzk/<卷序>/text.jsonl.gz`。
   - **daizhige 语料**：工作区的 `corpus/daizhige/`，含 `0001–0005.jsonl`、`page_map.jsonl` 等。迁过中心库的工作区在数据目录里，`dzg_import` 会自己找。
   - **生成**：
     ```bash
     python scripts/dzg_import.py colgold --ws $WS --release <解压目录>/96mid1ogzk
     ```
     应输出 `{"pages": 1677, "cols": 14989, "agree": 14931, ..., "dup_cols": 2}`，表写在 `corpus/daizhige/colgold.jsonl`。不加 `--export`，不要改 dataset。
   - `corpus/` 归中心库管。要不要 `guji db push` 让别的机器也拿到，按你的授权规矩办，拿不准就问上级。
   - 开关开着但表不在，会直接报错。

4. **格位表**（`layout_prior` 用）：`python scripts/dzg_layout.py --ws $WS`，输出 `corpus/daizhige/layout_slots.jsonl`。参数写 `{"row_segment":{"layout_prior":"corpus/daizhige/layout_slots.jsonl"}}`。和金标表一样，表不在会报错，表一变 Step3 就判过期。做法与实测见 `doc/research/切分现状梳理与新方向-2026-10-19.md` 第六节。

## 四、怎么跑、怎么比

我用的是**两个并排的沙箱工作区**，不碰生产 `products/`。`guji exp` 的报告目前只比 seed_admit，Step3 的效果要用 `eval_column_counts` 量。

```bash
# 基线工作区 $A：现行代码、开关全关，跑到 cell_shrink
guji pipeline keben_body_v2 vol04 --to cell_shrink --pages all -w $A

# C+D 工作区 $B：books/ feedback/ corpus/ workspace.yaml 拷自 $A；cache/ 软链到 $A 的 cache/；
#                products/<册> 从 $A 拷一份（Step1–2 共用），只重跑 Step3–4
P='{"row_segment":{"colgold_prior":"corpus/daizhige/colgold.jsonl","yolo_merge":true,"yolo_model_dir":"<yolo_tool>/model"}}'
guji pipeline keben_body_v2 vol04 --from row_segment --to cell_shrink --pages all --force -w $B --params "$P"

# 量（两边各一次），再按列 id 比
GUJI_WORKSPACE=$A python scripts/eval_column_counts.py <open-guji-dataset> --books vol04 --no-ensure --show 0 --json-out a.json
GUJI_WORKSPACE=$B python scripts/eval_column_counts.py <open-guji-dataset> --books vol04 --no-ensure --show 0 --json-out b.json
python - <<'EOF'
import json
a, b = json.load(open("a.json")), json.load(open("b.json"))
wa, wb = {w["id"] for w in a["wrong"]}, {w["id"] for w in b["wrong"]}
print(f"基线 {a['ok']}/{a['cols']}  C+D {b['ok']}/{b['cols']}  修好 {len(wa-wb)}  改坏 {len(wb-wa)}", sorted(wb-wa))
EOF
```

- **只开 C**：`P` 里去掉 `yolo_merge` 那两项。**只开 D**：去掉 `colgold_prior`。
- **只开 `layout_prior`**：`P='{"row_segment":{"layout_prior":"corpus/daizhige/layout_slots.jsonl"}}'`。它还改格位：抬头级数、空格、夹注拆法都按表定。所以字数之外还要看逐格。
  - 逐格怎么量，见上面那份研究文档的第六节。
  - 字数口径照样用 `eval_column_counts`。
- **时间**：开 D 每页多一次 YOLO 推理。4 核云机上 Step3 大约 10–20 秒一页，比基线慢一倍左右，一册约 30–60 分钟。
- 各册可以并行，但同一台机器开两三个就到头了。
- **看哪动了**：Step3 产物 `cells.columns[].flags` 里有 `colgold_prior：字数 a→b（格数 m→n）`、`yolo_prior：…`、`colgold_conflict：…`、`yolo_conflict：…`。
- **改坏的列要出图看**：列图在 `cache/<册>/column_image/pNNNNcMM.png`，把两边的格框画上去并排比。dataset README 的规矩是：据此下结论的改动，翻转的列要全部人看。

## 五、交回什么（验收）

1. 先交 vol04 一行：三个变体（基线、只开 `layout_prior`、C+D）各自的准确率与修好／改坏数，字数口径、逐格口径都报。用户点头后，再逐册补 vol05–10。
2. 每个改坏的列：看图结论，归到下面三类之一：
   - 金标错：像 vol07 p44 c5，修 dataset 并记 `history`；
   - 框线／印章等残墨被算成字；
   - 别的原因。
3. 你的建议：每册开哪个，`layout_prior`、C+D 或都不开。写进 overview 的卡，由用户定；定了再在 [开关登记表](../开关登记表.md) 那两行填「哪些书开」。

## 六、已知的坑（都踩过）

- **残墨被算成字**：上版框线、列尾残墨落在金标格位段外时，C 原先会把它算成字，然后并掉两个真字。现在有三道防线：格位段外的格要和段连着、墨 ≥ 0.08、列图上像字。但框线**落在段内**挡不住，vol07 p44 c5 就是这样。新错多半出在这一类。
- **印章页**：印章格会被算成字，C 不一定改坏，但"修好"可能只是碰巧。看到 `colgold_prior` 落在有印章的页，要看图确认。
- **开 C 后列首格号会挪**：C 重切改了格数，人裁若事后才加，按格号绑定的人裁要对着新格号下。已有人裁的列 C、D 都不动。
- **只在殿本上量过**：D 吃的是管线的灰度图，`binarized_input` 的书是二值图，和 yolo_tool 训练时的彩图不同。别的书要开，得先在该书上重量误并。
- **Step3 变了，下游跟着变**：开关一开，Step4 及以后（字块、匹配、放行）都会重算。整理进度靠后的册，开之前问上级。
- **金标表每次重新生成，指纹都会变**，Step3 跟着判过期。不要频繁重生成。
