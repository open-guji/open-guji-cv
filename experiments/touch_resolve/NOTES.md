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
