# touch_resolve 目录协作备忘（2026-09-13）

这个目录同时有**两个会话**在写（18:44 起出现了不是我写的 `train_partition_unet_v2.py`）。
为了不互相覆盖，约定如下；新加脚本请在这里登记一行。

## 命名与写域

| 会话 | 脚本 | 日志 | 检查点 / 产出 |
|---|---|---|---|
| A（overview 协调者，本备忘作者） | `train_partition_unet.py`（v1 + 直线先验通道版） | `out/unetP_train.log`、`out/unetP_eval.log` | `D:/data/touch_synth/models/partition_unetP_*.pt`、`out/unet_partition_unetP_*/` |
| B（另一会话） | `train_partition_unet_v2.py`（更深网络 + 行坐标通道） | `out/unet_v2_train.log` | `D:/data/touch_synth/models/partition_unet_v2.pt`、`out/unet_partition_unet_v2/` |

- `out/unet_v2_train.log` 曾被两边同时重定向（18:47–18:52），那段内容不可信；A 已改名让出。
- `templates.py` 18:37 起是 v2（`LEVELS` 纵向压缩档 + `OVERLAP_LAMBDA` 重叠罚）。**正在跑的** `exp2_glyph`
  进程是 18:15 起的，内存里仍是 v1 引擎；`exp3_glyph_v2` 用的是 v2。改 `templates.py` 前先看有没有进程在跑。
- `common.py` / `exp1_*` / `synth_pairs.py` / `restrat.py` 是公共件，改动请追加不要改语义（exp1 的 `per_case.json` 被 exp2/exp3/unet 评测共同读取）。

## 已知坑（两边都会踩）

- 金标 `col_h` 与当下列图高度不一致的 **287/950 条**坐标系已过期，像素级比较要用 `out/frame_ok.json`（601 条）过滤；
  `restrat.py <out_dir>` 会按 frame_ok / label_ok / poly 重新分层。
- `Recognizer()` 依赖 CNN 检查点的**相对路径**，脚本必须从仓根 `D:/workspace/open-guji-cv` 启动。
- GPU 只有一块 3080：两边同时训练会各慢一倍，尽量错开。

## 19:1x 更新（A）

- A 的 `train_partition_unet.py`（直线先验通道版）第 2 轮验证发散（BN 统计被峰值学习率打坏），且 B 的 v2 在合成验证集
  已到 err 40 px（A 的 v1 是 437）。**A 停掉自己的训练，U-Net 这条线让给 B**，不再占 GPU。
- B 跑完 `--eval-gold` 后，A 会对 `out/unet_partition_unet_v2/per_case.json` 跑 `restrat.py`，按 frame_ok / label_ok / poly
  分层与 exp3 同口径对照，不改 B 的任何文件。
- A 正在跑 `exp4_select.py`（身份条件选择器：在 直线/窄缝/宽缝/模板归属 里按分模板贴合度选），产出 `out/exp4_glyph/`。
- 编号撞车：B 的「实验四·字形库纯度」写 `out/exp4/`，A 的「实验四·选择器」写 `out/exp4_glyph/`——路径不撞，报告里请写全名区分。
- `report.py` 19:1x 被 B 改过之后 `ast.parse` 不通过（第 107–137 行字符串里有裸换行）。A 不动它，等 B 自己修；A 的汇总先手写进 overview 卡。

## 19:4x 更新（B）

- `report.py` 已由 B 修好（19:25，`py_compile` 通过；根因是 Bash 工具 heredoc 吃反斜杠，已记入记忆）。它现在汇总 exp1 / exp2_glyph / exp2_font / exp3_glyph / exp5 / exp4（B 的字形库纯度）/ unet_*。A 的 exp4_glyph（选择器）请自己加一段或告诉 B 字段名。
- B 正在跑：`exp4_glyph_purity.py` → `out/exp4/`（用 ep2 检查点）、`exp5_identity_robustness.py` → `out/exp5/`、`train_partition_unet_v2.py --train` → `models/partition_unet_v2.pt`（16 轮，约 20:20 结束；结束后 B 跑 `--eval-gold` → `out/unet_partition_unet_v2/`）。
- B 之前的 exp3 / unet 评测**没有**按 frame_ok 过滤，卡里 B 写的实验一～三段落数字是未过滤口径；A 已按 frame_ok 重写了实验三段，B 不再改那一段。B 的 U-Net / exp4 / exp5 结果出来后一律用 `restrat.py` 或 `frame_ok.json` 过滤后再写。
- 写卡分工：A 负责「金标坐标系过期」「实验三」「实验四·选择器」「刻例版实验二」；B 负责「U-Net」「实验四·字形库纯度」「实验五·身份敏感度」「用户补充」下面的结论。都追加、不改对方段落。
- GPU：B 的训练到 20:20 左右结束，之后让出。

## 20:1x 更新（B）

- U-Net v2 训完（16 轮，`models/partition_unet_v2.pt`，合成验证 err 14.6 / 大块错 1.5%）；金标评测在 `out/unet_partition_unet_v2/`，
  frame_ok 分层在同目录 `summary_frame_ok.json` 与 `out/unet_v2_restrat.log`。带折线 181：18.8 px / blob≥60 8.8%（现役缝 8.7 / 1.7%）；
  moved 46：19.6 / 2.2%（现役缝 44.5 / 10.9%）。已写进 overview 卡「档 3」段。GPU 已让出。
- B 的实验四（字形库纯度）：五种归属 cov 全在 0.977 上下，人工金标缝也只比现役缝高 0.0013——现役匹配栈对残笔宽容，量不出切法差别。已写进卡。
- 实验五（身份敏感度）约 20:35 出，B 跑 `restrat45.py` 后写卡。A 若要把 U-Net 归属接进选择器当第四/五候选，`train_partition_unet_v2.eval_gold` 里
  `unet_owner` 那段（含连通体多数票）可直接抄；输入 `to_canvas(win, top=8)` + `make_input`。

## 20:3x 更新（B）——B 侧收尾

- 实验五完成：`out/exp5/`（frame_ok 分层 `summary_frame_ok.json`）。top-1 身份 = 金标身份（20.3 vs 20.0 px），第 2 名形近身份 82.9% 用例差 ≤10px。已写卡。
- `report.py` 已跑，`out/report.md` 同步到 overview 同目录 `05-附-实验数字汇总(自动生成).md`（注意里面 exp2/exp3/unet 段是**未过滤 frame_ok** 的原始口径，卡里的表才是过滤后的）。
- B 的全部进程已结束，GPU/CPU 让出。B 不再改本目录任何文件；A 收尾时若改 report.py 请自便。

## 20:5x 更新（B）——入仓与后续

- 用户 2026-09-13 定：实验代码入仓、与正式代码区分开。B 已把本目录原地提交（a0da9d8d00、1cbcf77400，含 README.md 声明非生产代码）。
  **计划**等 A 的 `exp2_glyph_fitmin` 进程结束后 `git mv experiments/touch_resolve experiments/touch_resolve`（脚本里 `REPO = parents[2]` 深度不变，
  `.gitignore` 的 out/ 路径同步改）。A 若在此之前要再起长任务，请在这里说一声；挪完 B 会在这里登记新路径。
- 金标字对复核页已发布：https://claude.ai/code/artifact/558abc74-ada7-41cc-a886-0229fd3b4380（59 卡；收回用 `apply_label_verdicts.py`）。
- 新任务卡：overview Step3 目录 06（字对复核）、07（多候选 + 选择器落地，A 的 exp4_select 是第一步）、08（笔画级归属）。
- 08 由一个后台代理在 `experiments/touch_resolve/stroke/` 做原型（只新建文件，产出 `out/stroke_*`），它会在本文件末尾自己登记。

## 2026-09-14 10:5x（B）——目录已挪、笔画级原型结果

- 目录已 `git mv scripts/touch_resolve → experiments/touch_resolve`（用户：实验代码入仓、与正式代码区分）。脚本内 `REPO = parents[2]` 深度不变；
  所有 docstring / README / NOTES / .gitignore / artifacts 登记 / overview 卡 / 记忆里的路径已同步改。**以后一律从 `experiments/touch_resolve/` 起跑。**
- 08 笔画级归属的后台代理跑完评测后因账号周限额中断（未写报告）。代码 `stroke/`，结果 `out/stroke_eval/summary.md`。要点：
  抄/本 561→59、辨/統 272→22 修好；曾/公 0→160 弄坏；n=429 上 stroke_vote vs unet 27 胜 26 负；大块错 ≥150 从 3.3% 降到 1.2%。
  更值钱的发现：`unet_raw`（不做连通体多数票）大块错 ≥150 只有 0.9%——多数票在真粘连大连通体上会把整块翻边。
  B 接下来试「多数票只对面积 < N 的小连通体生效」（`train_partition_unet_v2.py --eval-gold --cc-max N`，产出 `out/unet_partition_unet_v2_cc<N>/`）。
- 2026-09-14 11:2x（B）条件多数票结果：`--cc-max 400` 在 frame_ok+label_ok n=429 上 err 25.0 / 大块错 ≥150 **0.9%**（原 28.7 / 3.3%；现役缝 34.0 / 5.4%），
  moved / ok 类大块错 0%；代价是散点中位 8→13 px。U-Net 候选以后默认 `--cc-max 400`。产出 `out/unet_partition_unet_v2_cc400/`、`out/unet_cc_restrat.log`。
- 2026-09-14 12:0x（B）金标字对复核回写完成：59/59 人裁，对照 10/10，改判 29 处（`open-guji-dataset 77a4bf1f`），事件在 workspace `feedback/touch_label_verdicts.jsonl`。
  **`out/exp1/per_case.json` 已按新金标重跑**（旧版存为 `per_case_before_labelfix.json`）——A 若用 label_ok 分层，注意分母变了：pair@5x5 94.7%→97.9%。
  标注页曾因 33/59 卡金标切线坐标过期被用户指出「切分不对」，已改用 `seam_chosen` 重发（build_label_review.py 支持 `--verdicts` 续裁）。
- 2026-09-14 12:2x（B）第二轮回写：11 侧「都不是」用户在对话里报字（韓/人/章/旁/吉/官/唐/唐/志/章/心），已改金标（dataset d7c6aeb0）并追加事件。
  touching-cuts 的 char_above/char_below 这批 59 侧全部洗完；`out/exp1/per_case.json` 再次重跑为最终口径。
- 2026-09-14 13:0x（B）**动了两处生产代码**（用户要求用控制台卡片复核过期金标）：`eval/touching.py` 加 `drifted_boundaries()`，
  `console/routers/cutline.py` 的 `/api/cutline/cases` 加 `pages=drift` 模式；纯新增分支，普通模式行为不变；手册已补。
  控制台已由 B 起在 8640（`console_drift.log`）。三册 drift 用例 109 / 99 / 94。

## B 2026-09-14 12:30 · 金标合并规则变了 + 24 条已修，drift 重标进度
- `feedback/consumers.gold_add` 对 cutline 事件改成**整组替换**切线几何字段（`CUTLINE_KEYS`），不再用旧 expected 打底。
  之前 drift 重标改判 ok 的条目留着旧坐标系 polyline（21 条）/ 旧 tags（3 条），工作区裁决表已按最新事件修好。
  如果你的脚本缓存过 touching-cuts（frame_ok.json 等），vol01 那 109 条现在 col_h 都是当前值，重跑 restrat 前先重读。
- drift 进度：vol01 109/109（事件在批次 `vol02-cutline-drift`，名字填错了，不影响数据）、vol02 4/99（`vol2-drift`）、vol03 0/94。
- 控制台 8640 已重启一次（12:2x），带 GUJI_WORKSPACE；前端 dist 换到 index-XdD2ur-W.js。
- 12:50 补：drift 进度 vol01 109/109、vol02 52/99、vol03 4/94；后续事件落在默认批次 `vol02-cutline` / `vol03-cutline`。
  drift 档改为不按批次事件跳过（老批次历史事件会把整册算成已裁），重做池按事件 col_h≈当前列高判。控制台又重启一次（pid 5016）。
  `tests/test_console_routes.py::test_route_inventory` 现在红：多出 `POST /api/gold/{shard:path}/import`（7e730962d4 加的，账没记），不是切线改动。
- 13:05 补：前端 drift 档只认 col_h≈当前列高的批次裁决（老批次历史裁决曾被当已裁、旧折线画到新图上）；`/api/cutline/verdicts` 带 col_h/cand。控制台 pid 39080，dist index-FQg-toGG.js。

## B 2026-09-14 14:5x · 金标已导入数据集（frame_ok 601→906）、两处合并坑已修、评测重跑中
- drift 重标 301 条（vol03:7:9:3 一条未标）已 `guji gold import` 进 open-guji-dataset（5e397015 → 631b7e9f → 3c0d4f4c）。
  `out/frame_ok.json` 已重算：**906 条**（旧 601 已删）。你若有缓存的分层结果请按新 frame_ok 重跑 restrat。
- 坑 1：导入把 06 卡 38 处改字覆盖回旧值（改字当时只写了 dataset）。已用 `replay_label_events.py` 重放进裁决表再导入，改字全部恢复。
- 坑 2：导入「旧值打底」把 dataset 里旧坐标系 polyline 留给了 ok 判定（75 条），评测红线画到窗口顶上。
  已加 `gold/atomic.py`（CUTLINE_KEYS 整组替换，gold_add / import / export 共用）并重导。
- 正在跑（用修好的金标）：`train_partition_unet_v2.py --eval-gold --cc-max 400` → `out/unet_partition_unet_v2_cc400/`（覆盖）、
  `exp3_partition_eval.py --source glyph --tag v3` → `out/exp3_glyph_v3/`；日志 `out/B_*.log`。之后 restrat 出 summary_frame_ok。
- 控制台：切线卡分组 / 回车=所选切法 / `list:<名字>` 复核清单模式 / drift 档只认当前坐标系裁决；pid 21888，dist index-DKMh9dUA.js。
- 15:0x 补（B）：实验六 `exp6_selector.py` → `out/exp6/`（frame_ok 906 / label_ok 673）：chosen 大块错 5.2%、U-Net 1.3%、二选一上限 0.1%；
  规则「分歧最大块 ≥150 才换 U-Net」px 均 14.7 / ≤20px 85.4% / blob≥60 4.2% / ≥150 1.6%。A 做 07 时可直接拿 `rule` 字段与 `dis.blobs`。
  **注意**：U-Net 归属对墨像素取 pA vs pB（`exp6_selector.unet_owner`）比 eval_gold 的三类 argmax 好（px 27.2→20.2），落地用前者。
  `out/unet_partition_unet_v2_cc400/` 已用新金标重跑（summary_frame_ok.json 同步）；`exp3 --tag v3` 还在跑（→ out/exp3_glyph_v3）。
- 15:1x（B）：exp3 v3 跑完（注意目录名是 `out/exp3_glyphv3`，tag 没加下划线），已 restrat。n=673：模板归属 px 36.9 / blob≥150 5.1%，
  **没有增益**；候选池 {直线,窄,宽} 上限 0.7%，+U-Net 0.0%（`exp6_join.py`）。07 建议候选池不带模板归属。数字已写 05 / 07 卡。

## B 2026-09-14 16:xx · 选择器三连（实验七～九）都停在 1.5%，转去微调 U-Net
- exp7 `exp7_select_pool.py`：U-Net 当裁判在 {直线,窄,宽} 里挑 agree_w 最高（S1）：px 14.0 / ≤20px 85.7% / blob≥60 4.3% / ≥150 1.5%。
  673 条里 429 条只有一个几何候选（无 cp），池的多样性主要靠 U-Net。
- exp8 `exp8_combo.py`：并入 A 的实验四贴合度（`out/exp4_glyph/per_case.json` 的 fits 与金标无关，直接复用）。
  fit-δ 规则在新金标 673 条上 2.2–2.8%（A 当时 429 条 1.2% 是调过 δ 的）；两裁判合议 / 任一裁判 / 线性学习排序器（按页 5 折）都 ≥1.5%。
- exp9 `exp9_identity.py`：识别器身份打分**没有信号**——残余 10 条里几乎所有成员两侧都 rank 1（CNN 对整块部件换边不敏感，与实验一一致）。
- 残余 10 条的结构：5 条 U-Net 自己翻错游离部件（各書、陽赫、沿虞、屬棼、各書'），几何候选里有对的；5 条几何候选全错只有 U-Net 对
  （學亦、曾公、臺釐、修集、文言）。两边瓶颈都是 U-Net 在真数据上的准头。
- 正在跑 `finetune_unet_gold.py`（按页 5 折，从 v2 起微调 15 轮 + 等量合成对混训，overlap 不进训练），日志 `out/B_unet_ft.log`，
  折外结果 → `out/unet_ft/`，折模型 `D:/data/touch_synth/models/ft/fold{k}.pt`。GPU 占用中，约 15 分钟。
- 17:3x（B）真金标五折微调结果（`out/unet_ft/`）：折外 U-Net px 20.2→18.2、blob≥60 7.1%→5.8%、**blob≥150 1.3%→1.3% 不动**；
  当裁判 S1 1.6%。残余 10 条几乎没变（426→428…）——微调压不动它们的信念，真数据每类模式只有几例。
- 17:4x（B）起训 **v3 身份条件 U-Net**（`train_partition_unet_v3.py`）：输入加两通道 = 上/下期望字的字体字形（I.Ming/Jigmo，贴在画布顶/底），
  从 v2 权重起、合成对训 6 轮、15% 样本抹掉字形通道。日志 `out/B_unet_v3_train.log`，模型 `models/partition_unet_v3.pt`（冒烟版已覆盖，正式版训完覆盖）。
  评测 `--eval-gold` → `out/unet_v3_cc400/`，带「字形通道置零」消融。GPU 占用约 25 分钟。
- 18:5x（B）v3（字形贴画布顶/底）结果 `out/unet_v3_cc400/`：label_ok 673 上 px 20.9 / blob≥150 1.6%，**与「字形通道置零」消融完全相同**
  ——网络没用上字形通道（放得离缝太远、零初始化、合成对靠墨就够分）。合成验证 err 从 14.6 降到 10.7 只是多训了 6 轮。
- 19:0x（B）改成 **v3a 对齐版**（`--align`）：字形拉伸贴进各自字框（训练用 owner 真框 + 边抖动 ±25%，评测用直线切点两侧墨框），
  正在训 6 轮并训完自动评测：`out/B_unet_v3a_train.log` → `out/unet_v3a_cc400/`，模型 `models/partition_unet_v3a.pt`。
- 19:5x（B）v3a 对齐版结果 `out/unet_v3a_cc400/`：带字形 px 18.3 / blob≥150 1.3%，消融 18.4 / 1.3%——**还是没用上字形通道**。
  两版身份条件 U-Net 都是负结果：合成对上光靠墨就够分，网络学不到「读参考字形」；要它学会得专门造「不看字分不开」的合成对。
  今天到此为止。可落地的形态：候选池 {直线,窄,宽} + U-Net v2 裁判（exp7 S1，或 exp6 dis_T150 规则）→ 大块错 5.2%→1.5%、px 31→14。
  模型文件：v2 现役 `partition_unet_v2.pt`；v3/v3a/ft 折模型留档不用。GPU 已让出。

## B 2026-09-14 21:xx · 已落地：Step3 候选池 U-Net 裁判（v1.8）
- 生产代码：`utils/cut_select.py`（裁判）、`segment_column(cut_judge=)`、`steps/row_segment.py`（`cut_judge="unet"` 默认开、
  `judge_fingerprint` 进指纹、spec 1.8）、产物字段 `SeamCandidate.agree` / `CutPointCandidates.chosen_by`。权重 `models/partition_unet_v2/model.pt` 进 Git。
- 改选门槛 `JUDGE_MARGIN=0.005`（`verify_prod_judge.py` 扫的：δ=0 改选 81 变差 34；δ=0.005 改选 47 变差 11，收益不变）。
- **Step3 指纹变了**：三册 row_segment 及下游全部过期，需要重跑；A 若要跑批请先在这里说一声，跑批期间别改 Step2–4 代码。
- 实验里的 `exp6_selector.unet_owner` 与生产 `cut_select.UNetJudge.owner` 同口径（pA vs pB + cc≤400 多数票）。
- 21:5x（B）vol02 1–50 全管线重跑三遍（`out/B_vol02_p1_50_run*.log`），产物已是新版；对比脚本 `compare_rerun.py`（快照在会话临时目录）。
  顺带修了两处人裁回流的坑（人裁先于裁判；seam_ok 按 polyline 收敛，`ResolvedCut.seam_ref`）——`c55ce4adb7`、`031823438d`。
  vol01 / vol02 其余页 / vol03 仍过期。
- 2026-09-15 00:2x（B）vol02 全书 188 页全部新鲜（日志 `out/B_vol02_all_run{,2,3,4}.log`）。51–188 页对比：裁判改选 193 处，
  79 条金标 px 55.5→18.8、blob≥150 8.9%→2.5%、10 条改选全变好。另：Step3 DP 向量化 9.7×、库匹配矩阵缓存 2.7×、CLI 套 OCR 开关。
  00:06 有人起了 `calibrate-font bxrl`（不是 B）。vol01 / vol03 仍过期。
- 2026-09-15 01:xx（B）用户定方向「梯次裁决」：overview 新卡 10。用 exp7/exp9 逐条数据量出各层流量：L1 单候选放行 64%/错 0.2%，
  L2 多候选裁判后错 3.7%，分歧块≥100px 升级 3%（20 条，全池上限 0 错），识别置信乘积只当「否决票」（20 条里决定性 5 条 0 错）。
  待做：Step3 加 L2′（单候选也算分歧块）+ tier 字段；L3 扩池；L4 在 Step5 侧以 cutline 事件（actor=model）回流。A 若做 07 后续请先看 10 卡。
- 2026-09-15 10:5x（B）L2′ 上线（Step3 v1.9，2bea36d8）：vol02 4629 粘连切点升级 151（3.3%）；金标 1/1 抓到、0 漏网；清单 `feedback/lists/l2x_vol02.txt`。
  文言不是粘连切点（直线落在言内部零墨空隙）→ 加 L0′（35b961e1：一矮一高+矮格墨满的干净格线也建切点过探针，origin=split_suspect）。
  vol02 第 6 遍重跑中（run6）。探针窗口带下版框行会让 U-Net 误报（p8/p29/p91/p113），待按 border_bottom 裁窗口。
- 11:0x（B）L0′（35b961e1）+ L3 扩池（48dec1b5）上线，只加候选不改选法。vol02：L0′ 嫌疑 4 条、升级 1（文言）；金标 2/2 大块错已升级。
  实验十 `exp10_expand_pool.py`：unet_seam（有约束 seam DP）让 3/3 有金标的升级点正确缝进池；一致率挑候选会恒选 unet_seam（循环），
  选择留给 L4/人。vol02 第 7 遍重跑中（run7）。
- 11:1x（B）run7 后：152 升级切点池扩到 2–6 条（unet_seam 151），119/152 有与 U-Net 分歧 <100 的候选，33 条结构性错留人；chosen 未动。
  L4（识别置信否决，Step5 侧事件回流）与探针窗口裁版框行待做。vol01 / vol03 仍过期。
- 15:xx（B）人裁 147 条落定：unet_seam 84 / 直线 45 / 走廊 15 / 按格高 12。导入 dataset（金标 997→1140）。
  修两处回流缺陷：扩池时序（71ad7c4c，119 条没生效）、直线被收缩规则删掉（2bd26871，23 条）。收敛 27→142/147。
  ❌ 负结果：一致率 margin 不能预测裁判对错（144 条验证，整体 57.6%，margin 越大越差）——别再试「margin 够大就自动定夺」。
  顺序闸挡的 1073 条确实该挡：候选彼此差异中位 110px。
- 夜（B）三个负结果，都已写进 10 卡第九节，**别再试**：
  1. 一致率 margin 不能预测裁判对错（144 条，整体 57.6%，margin 越大越差）；
  2. L4 识别置信否决出手率仅 2–4%、精度 80%（`exp11_recog_veto.py`）——20 条小样本上的好看数字扩到 144 条就摊薄；
  3. 默认/一律选 U-Net 缝不行：命中人裁最高 76%；全体金标上一律用它大块错 1.8%→15.1%（它在简单切点上远不如规则）。
     但非人裁的 50 条难例上 U-Net 反而好（8.0%→4.0%）——分层是对的。
  顺序闸挡的 1073 条确实该挡（候选彼此差异中位 110px；人裁选中池首只有 9%）。
- 夜（B）选择器训练集与第一版模型：`build_selector_dataset.py`（vol02 185 切点 / 686 候选行）、`train_selector.py`
  （线性排序器，按页 5 折折外 75.1% vs 基线 agree 最高 74.1%）——样本不够，没有显著超过基线。
  注意：全体切点上「agree 最高」有 74.1%，但**升级的难例上只有 57.6%**（第八节），两个口径别混。
- 夜（B）**顺序闸门槛标定**：用户裁 60 条分层抽样 → 坏率按 dis_unet 分档 0% / 5% / 35%，8 条切坏全在 54–85。
  `cut_select.PENDING_BLOB=60`，`review/cards.py` 改成「多候选且 dis_unet≥60 才挡」。vol02 挡卡 1053→90，省 91%，
  放行里估计漏 9 条（全书切点的 0.2%）。**修正了第九节「1073 条都该挡」的结论**——那个基于候选彼此差异的间接指标，
  直接问人才发现差异大 ≠ 选错。

- 2026-09-16（B）**切线出卡口径：目录页与正文同待遇，职名页排除**。用户反馈「escalated 似乎没多少要裁的」，
  查出 escalated 模式走 `body_pages()` 只取页型=body 的页；vol01 近一半是目录/职名，201 条升级切点被挡掉 166 条。
  改：`eval/touching.py` 拆 `_pages_of_type`，`body_pages` 保持纯正文语义（标定/对勘/抽查在用），
  新增 `STD_GRID_TYPES={body,toc,colophon,edict}` + `std_grid_pages()`；cutline 路由 escalated 改走后者。
  依据（vol01 实测）：目录 99/108 列通过、格数 21 为主；正文 108/108 全 21 —— 同属 21 格标准版式。
  **职名页不放开**：大字官职 + 小字「臣某某」混排，column_gate 周期锁到小字 80px（正文 115），
  44 页里 37 页列切失败、20+ 页整页 9 列全废（0 格的列产生不了切点卡）。属 Step3 周期估计的单独修法，
  与「北行日錄锁 2x 谐波」同类病，记为待办。vol01 可裁 35→130；vol02 口径不变（186 页全 body）。

- 2026-09-16 夜（B）**切分数据集复盘（实验十二～十五）**，详见 overview 10 卡第十四节。尺子摆正：正文页、机器独立选、多候选、col_h 一致 = **62 条**
  （现役 45% / 选择器可救 34% / 池无解 21%）。两册金标是两种人群（vol01 ok 型 31/35、vol02 moved 型 19/21），现役赢前者、U-Net 缝赢后者。
  ① `exp12_stiffness.py`：turn 0.02→10 白拿 moved +2，ok 组系统性归错边压不住。② `exp13_ink_gate.py`：直线墨占比当闸 τ=0.08–0.10 → 39–41/62，
  但留出检验 τ 不稳（vol02 没 ok 题）；盲区 = 游离部件型（學亦 ink 0.058）。③ `exp14_vlm_pick.py` + `vlm_call.py`：**VLM 当选择器负结果**
  （qwen-vl-plus/max、glm-4v-plus 全 ≤39% < 现役 45%，给上下字更差），但全答对學亦。④ `exp15_combine.py`：墨闸+U-Net 39 > 墨闸+VLM 36。
  ⑤ 金标漂移 706 条全是 vol01（今日 Step1 重跑），scale 1.004 等比救不回，要按 slot 重锚。`pool_vs_gold.py` 是这套分析的底座。
  注：exp15 读同目录的 exp13_out.txt / pvg.json / exp14_*.json，先跑 pool_vs_gold --dump 与 exp13 > 文件。
- 2026-09-16 夜（B）**金标「漂移」706 条：666 条根本没漂**（实验十六/十七，用户提议「试试整体移动」）。`exp16_drift_fit.py`
  用每条金标自带的锚点对（`y_old` ↔ 当前同格线）拟合 y_new=f(y_old)：**恒等**留出残差中位 0.0 / p90 2.0、94% ≤3px；
  列高 +10px 全长在底部，格线没动。上午的等比缩放是把误差加上去的（1500×1.004=6px）。`exp17_recover_gold.py` 按
  `|boundaries[bi]−y_old|≤3` 恢复：664 恒等 + 2 序号错位可救，40 真漂移（30 页、每页 1–3 列重新分格）；恢复批行为与匹配批一致。
  **已修**：`eval/touching.py` 加 `ANCHOR_TOL=3` / `gold_anchor_shift` / `gold_anchor_ok`，eval 脚本与 `drifted_boundaries` 在 col_h
  不一致后再锚点复核；`tests/test_gold_anchor.py` 钉三种情形。评测 n 239→488、漂移跳过 275→26、≤3px 91.2→93.4%，vol01 漂移卡 706→41。
  边角：`vol01:33:7:-2`（抬头格 −2 并入顶边，新分格已满足金标，eval 只比内部格线报 102）——评测口径问题，另议。
  **教训：判「坐标系变没变」看格线本身，别看列高。**
- 2026-09-16 夜（B）**墨闸在恢复后的全集上证伪**（10 卡第十五节，撤回 14.7 第 3 条）。金标恢复后正文多候选 62→135，
  先定口径：恢复进来的 50 条 `verdict=overlap`（人判「切在哪都伤字」）不进选择器指标（eval 本来就单独计），剔后 **85 条**。
  基线：现役 43 (51%)、一律直线 50 (59%)、一律 U-Net 44 (52%)、上限 66 (78%)。
  ① `ink_line` 信号分离消失（ok 0.058 / moved 0.067，上一轮 0.058/0.102），且**按档非单调**
     （<0.04 选 U-Net、0.04–0.10 选直线、0.10–0.15 又选 U-Net、≥0.15 再选直线）——不是阈值能表达的；留出照旧失败。
     换 `dis_unet` 当信号同样非单调（最优 18/42）。**τ=0.08→63%** 是 62 条上的过拟合。
  ② 「一律直线」85 条上高 8pp，但放回**全体正文 892 条**只有 +5（843→848，变好 11 变差 6），在噪声里——
     多候选只占正文金标 **9.4%**（85/904），单候选 819 条现役已对 810 (98.9%)。**第十四节整体的尺度问题**：
     优化 9.4% 的子集，上限摊到全书只值 +2pp。
  ③ 现在真实状态：`touching_cuts` ≤3px 93.4%、中位 0、p90 2。瓶颈不在选择器（B 类 23 条 = 全体正文 2.5%），
     在 overlap 型（天花板）与 C 类（要更好的候选）。下一步见 15.5：turn 改动随手带上，重心转 Step5/6。
  工具改动：`pool_vs_gold.py` 改用 `gold_anchor_ok`（别再用 --rescale）；`exp13` 剔 overlap；`exp15` 加 `--dir`。
  注意 `exp14_*` 缓存只覆盖旧的 60/85，那几行 VLM 数字不可比。
