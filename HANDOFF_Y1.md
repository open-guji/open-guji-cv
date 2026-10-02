# HANDOFF_Y1 — YOLO 收框复核闸 + 列探测核对（Y1 道，overview#373）

分支 `claude/Y1-yolo-1002`。**两个闸都做完了、都默认关**；结论是：收框闸量小、精度低，列探测核对不达标没接。
下面先说结论，再说怎么开、量法、没做的。

## 一、结论

| 项 | 结果 | 判 |
|---|---|---|
| Step4 收框复核闸（`cell_shrink.yolo_gate` + `seed_admit.yolo_box_review`） | 标定集 vol02 188 页 + vol03 106 页（4.6 万格，印章页 p3 弃权、过期的 p105–108 排除）。X=0.05 命中 38 格（0.083%，每页 0.13 格）；目视这 38 格约 1/4–1/3 是 CV 真错，其余是 YOLO 框连碎墨一起框了；人裁线索召回仅 3–8% | **实现、默认关；不建议整册开**。要开就 X=0.05，代价是每册 ≈ 25 格新增待审 |
| 列探测核对（YOLO 版面列数 vs CV 列数） | column-split 60 页人裁：**召回 0/4，误报 0/56**（门槛 ≥2/4 且 ≤3/56） | **没接**（不达标）。脚本留着 |
| YOLO 框兜底（改框） | 没做 | 见 §五 |

**与 F1 报告的出入（重要）**：`doc/yolo_tool_segmentation_review.md` §4.2/4.6 说「抽 30 个 CV 漏墨全是 CV 错，闸精度 30/30」。
我这边**复现不出来**：按 F1 的 25% 门槛，现行快照上命中 0 格。两处原因，都量过：

1. **版框那一侧的墨不是字**。不跳过时 X≥0.15 命中 61 格，目视几乎全是**列末格**——CV 紧框正好框着字，YOLO 框把下版框碎墨也框了进去，
   「多出的墨」是版框。按「列首格不看上侧、列末格不看下侧」跳过后，X≥0.15 一格不剩，最大值 0.14（`flag_x015_noskip_*.jpg` 是跳过前的 61 格）。
   真要抓的「把版框线当末字」是版框线在 CV 框里、字在**上方**，那一侧不跳，所以没误伤这一类。
2. F1 的「墨被谁漏掉」是两框并集里**双向**数、且用原图整页坐标；本闸只看「YOLO 比 CV 多出」的单向，更窄。我没去还原 F1 的 51 格，
   不能说他的数错——只能说**这个判据在这批快照上没有那么多可抓的**。F1 点名的 vol03 p49 夹注列被切半宽，本闸也没命中（YOLO 框也是半宽）。

## 二、怎么开（默认全关，关着产物逐字节不变）

```yaml
# books/<book>.yaml 顶层 params:（或 --params）
params:
  cell_shrink: {yolo_gate: true, yolo_extra_ink: 0.05}      # 打 yolo_box 旗
  seed_admit:  {yolo_box_review: true}                      # 带旗的格不放行、落人审，doubt=yolo_box
```

- 装可选依赖：`pip install -e .[yolo]`（只要 onnxruntime，CPU；装后 ~62 MB，不要 torch）。
- 权重**不进本仓**：`GUJI_YOLO_WEIGHTS=<yolo_tool>/model/slide/best.onnx` 或参数 `yolo_weights`；版面模型默认取并排的 `../type/best.onnx`（或 `yolo_layout_weights`）。
  权重 12.5 MB（单字）+ 104 MB（版面）。
- 指纹：`yolo_weights` / `yolo_layout_weights`（路径）走 `StepSpec.path_params` 不进指纹；两份权重**内容**的联合 sha256 前 16 位进指纹（`yolo_weights_fp`，
  `RunContext.params_for` 里自动填，同 `witness_fingerprint` 的做法）。已验证：内容相同、路径不同 → 参数哈希相同；闸关 → 哈希与加字段前相同。
- 弃权（一律不报错）：没装 onnxruntime／权重不在／读不开／推理异常；印章页（`page_occluded` 命中格 > `yolo_max_seal`=2，vol02/vol03 各只有 p3 一页）；某格 YOLO 没出字；坐标映射失败；夹注 a/b 半格、人裁/排除/遮挡格（seed_admit 里它们先于本闸）。
- **只打标、只送审、不改框、不改字**：去掉 `yolo_box` 旗后与关闸产物逐字相同（vol03 p39/p73 验证）。

## 三、怎么量的

- **喂法**：照 yolo_tool 原生——整页喂版面模型出列条 → 裁条 → 单字模型，跑在原图上（`utils/yolo_boxes.detect_page`）。
  我先做过「在 Step2 列图上喂单字模型」的版本，**比整页喂法差得多**（框差一大截、几乎不命中），弃用。
- **判据**：同格里 YOLO 框比 CV 紧框多包进的墨 ÷ 两框并集里的墨；只数本格格线 ±6px 内的墨（邻格笔画不算）；首/末格跳版框侧（见上）。
  匹配：YOLO 框中心落在本格页坐标矩形内、与 CV 框 IoU 最大。「一」「二」这类单笔字 YOLO 框偏大但墨不多，不会误报。
- **标定**（`scripts/experiments/yolo_tool_probe/y1_calibrate.py` → `y1_analyze.py`，用的就是生产函数）：

  | X | vol03 命中 / 新增待审 / 人裁线索命中 | vol02 命中 / 新增待审 / 人裁线索命中 |
  |---|---|---|
  | 0.03 | 44 / 31 / 9 of 79 | 100 / 93 / 7 of 169 |
  | **0.05** | **17 / 9 / 6** | **21 / 16 / 5** |
  | 0.08 | 4 / 0 / 3 | 2 / 1 / 1 |
  | 0.15 | 0 | 0 |

  「新增待审」= 命中且原本被 seed_admit 自动放行的格（命中但本来就待审的不增加人工）。X=0.05 下 vol03 106 页新增 9 格、vol02 188 页新增 16 格。
  「人裁线索」= `feedback/events` 里 vol02/vol03 的 `quality: truncated/contaminated`、`defect: truncated`、`not_a_char`（341 条，落在已量页的 248 条）。
  **召回只是线索**：这些裁决是对当时的产物做的，之后切分改过；且人只看了一部分格。命中里有人裁线索：vol03 6/17、vol02 5/21，是精度下限。
- **目视**（我看的，不是用户裁的）：X≥0.05 的 38 格拼图 `scripts/experiments/yolo_tool_probe/y1/flag_x005_vol02_vol03.jpg`（红=CV，蓝=YOLO）。
  真 CV 错约 8–10 格：「言」只框了下半（vol03 73:6:10、28:1:21、11:7:5 等）、「益」只框上半（vol03 39:9:3）、「藏內」夹注两字合一格（vol02 6:6:9、59:4:9）、「採山」合一格（vol03 88:1:7）；
  其余是 YOLO 框带了碎墨/邻字笔画。这个 1/4–1/3 的数字是我肉眼数的，样本小，别当精度的精确值。
- **耗时/依赖**：CPU（4 核容器）单页 ≈ 2–3 s（版面模型整页 ~1.8 s + 每列单字模型 ~0.2 s×9）；整册 190 页 ≈ 8–10 分钟。依赖：onnxruntime（装后 62 MB）+ 两个权重 116 MB（仓外）。内存没单独量。

## 四、列探测核对（任务 2）

`y1_colcheck.py`，对 `column-split` 60 页人裁（56 对 / 4 错：vol01/87、vol02/45 `extra`，vol02/69、177 `miss`）：

- 当前 Step1（沙箱里对这 60 页重跑 border_detect）+ 版面模型整页。判据四种：YOLO 列数≠CV 列数、某 CV 列里 ≥2 个 YOLO 簇、某 YOLO 簇横跨 ≥2 个 CV 列、CV 竖线穿过 YOLO 正文框。**四种都是召回 0/4、误报 0/56。**
- **4 个错页在现行 Step1 上已经不错了**（9 列、YOLO 也 9 列，目视叠图两页确认线都落在缝上），人裁是 2026-09-02 对当时的 Step1 判的，之后 Step1 改过（三段折线等）。
  所以**这个金标现在量不出召回**，不是 YOLO 抓不到。要量得重新标一轮当前 Step1 的错页。
- 一个坑：版面模型会把**版心条**当 text（置信 0.4–0.6），不排除版心时 vol01 40/58/72 会「多一列」误报 3 页；按「只数 CV 最外两条线之内的簇」排除后 0 误报。
- **盲测补一刀**（无人裁）：vol03 快照 106 页，空间判据命中 3 页：p49（F1 点过的 CV 列有问题的页，**YOLO 抓到了**）、p51（双行夹注密集页，YOLO 出了一堆窄簇，CV 没错，误报）、p2（题名页）。
  列数≠的另有 p1/p57/p58/p110（封面、近空页、YOLO 自己没出列），都不是 CV 错。
- 判：金标上不达标，**不接**。若以后要接，只能用空间判据（不用列数），且对双行夹注页和近空页要弃权；脚本里 `through`/`split`/`span` 已写好。

## 五、没做 / 待定（供总管排）

1. **YOLO 框兜底没做**。YOLO 框在原图页坐标，字块要在列图坐标重裁；`ColumnMapper` 只有列→页的正向映射，页→列要自己对各带的单应取逆（可以做，没做）。
   而且收框闸本身精度只有 1/4–1/3，拿它直接改框风险大于收益；建议先观察闸送审的格人裁后到底多少是 YOLO 对。
2. **Step4 全书会显示「过期」**：`cell_shrink.py`（及 `seed_admit.py`）源码变了，`code_hash` 随之变；产物内容不变（见 §二，关着逐字相同），但引擎会判过期要重跑一遍 Step4（含 `core/step.py` 的 `params_for` 新增一步，其它步参数不受影响）。
   合入前要知道这一点；不想全书重跑 Step4 的话，合入后在服务器上不要点「重跑过期」，或接受一次 Step4 重算。
3. 快照对不上的一页：vol03 p88 的 Step4 产物与现行 main（改动前）逐格输出就不同（夹注 a/b 排序），与本改动无关，没追。
4. 全量测试 `tests/`：2584 过、30 跳过、1 败 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`——**改动前的 main 上同样败**，与本改动无关。云端装了 httpx 才跑得起 `test_console_auth`。
5. 样本口径：沙箱里 `GUJI_WORKSPACE` 指四庫工作区（git archive 解出的 data_full/books/feedback），products 用快照 `vol03/20260928T1708-full`、`vol02/20260929T1023|1024`。
   vol01 没有快照，任务 2 里 vol01 的 30 页是我在沙箱里单独跑了 Step1。
6. 阈值 X=0.05 是在这 294 页上标的，没有留出集；召回线索偏弱。要进生产应先用它给 vol04–vol10 出一批待审、人裁后再定。
7. `y1/` 下的拼图是证据快照（目视结论的出处），不是回归数据。

## 六、改动清单

- `open_guji_cv/utils/yolo_boxes.py`（新）：onnxruntime 推理（单字/版面/整页原生喂法）、NMS、权重指纹、`extra_ink_ratio`、`match_yolo`。缺件 → `YoloUnavailable`。
- `open_guji_cv/steps/cell_shrink.py`：`yolo_*` 参数（关着时不进 dump）、`path_params`、`_YoloPage/_yolo_ratio`、`run_page` 里打 `yolo_box` 旗。
- `open_guji_cv/steps/seed_admit.py`：`yolo_box_review`（关着不进 dump）、`_yolo_box_review()`、`yolo_box` 进 `_RARE_REF_HARD`（防被 rare_ref／影子升级再放行）。
- `open_guji_cv/core/step.py`：`_with_yolo_fingerprint`。
- `pyproject.toml`：extra `yolo`。
- `tests/test_yolo_box_gate.py`：14 条，全自造数据（判据、版框侧跳过、弃权、指纹=内容非路径、关着时参数哈希不变、seed_admit 闸）。
- `scripts/experiments/yolo_tool_probe/y1_*.py` + `y1/`：标定与列核对脚本、证据拼图。
