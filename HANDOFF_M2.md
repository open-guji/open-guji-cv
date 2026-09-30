# HANDOFF_M2 — Step5–7 相关评测云端可跑性 + 基线（2026-09-30，M2 道）

分支 `claude/M2-eval-recog-0930`（基于 origin/main `f2616b4`，未合 main）。只改评测脚本 / 文档，**没改任何算法默认值**。
环境：4 核 15 G 无 GPU，torch 2.14 CPU；测试集仓浅克隆（LFS 指针）、`guji-workspace` 浅克隆；
`GUJI_WORKSPACE` 指 E 道文档的 overlay（软链四庫 + bxgb），`GUJI_PRODUCTS_DIR` 指沙箱，未碰 ws 正式 products。
overview 仓 `add_repo` 无权限（not found），E 道基线文件未读，靠 `doc/cloud_eval.md` + 各评测脚本/`.claude/doc` 对照。

## 0. 一句话

**原先「云端跑不了」的 16 项里 14 项能在 CPU 上跑出数，缺的几乎都是输入而不是算力。** 真正跑不了的只有
`char_ocr`、`font_fallback`（缺数据）和 `struct_heads` 的完整版（缺带结构头的 checkpoint，r6 不在仓里）。
对照 doc **没有发现回归**（含 1 项需要注意的口径差，见 §3）。Step7 回放评测见 §4 与 `doc/step7_replay_eval.md`。

## 1. 准备输入（按需，都在 `doc/cloud_eval.md` §6 写了）

| 输入 | 来源 | 备注 |
|---|---|---|
| `cache/glyph_bench`（15,482）+ `cache/oov_bench`（314） | `guji-workspace/_shared/train_bundle.zip` → 解到 cv 仓 `cache/` | zip 里多套一层 `cache/`，`mv cache/cache/* cache/` |
| r5 checkpoint | 仓内 `models/glyph_cnn_r5/best.pt` | 已在 git |
| 70,304 字 r5 embedding 模板表 | `eval_oov` 首跑现建 → `models/glyph_cnn_r5/emb_<key>.npz`（72 MB，gitignored） | **单核约 44 分钟**；建一次，oov/degradation/seen_test/struct_* 共用。guji-workspace 远端**没有** `idx/rare_emb/*` 孤儿分支（只有 `models-snap/rare-index-*` 的三条旧的），所以没法直接拉 |
| 本书语料 | 工作区 `corpus/zongmu_wuyingdian_reference.txt`（34.5 万字）| **仓内同名文件只有 17 KB 残片**，用它 `context_correction` 会悄悄少训 98% 的语料 |
| 通用语料 | 仓内 `corpus/external/daizhige_zhaoling.txt` | |
| Step7 产物 | `guji-workspace` 分支 `products-snap/vol01-20260927`（32b9c2b，Step1–7）、`products-snap/vol02-20260927`（cd04496，Step2 修复前）| `zstandard` 解（云端没有 `zstd` 命令）|

## 2. 逐项结果

口径：耗时为 4 核 CPU 实测；「doc」列为 `.claude/doc` 里最近一次记载。

| 评测 | 云端能跑？ | 跑法 / 输入 | 基线（本次） | 耗时 | 与 doc 对照 |
|---|---|---|---|---|---|
| **match_triplets** | ✅ | `eval_match_triplets.py <集>/glyph-match/triplets --report`（集拷到沙箱，脚本会写 results）| control 53 / **1.000**；nearmiss 57 / **1.000**；hard 132 / **0.250**（margin −0.0079）| 2.5 s | hard 0.250、control/nearmiss 1.0 与 `glyph_match_stack.md`「2026-09-17 hard 142 条 0.250」一致；n 变是集在扩（hard 按定义每次扩集必降）✓ |
| **match_pairs** | ✅ | `eval_match_pairs.py <集>/glyph-match/pairs --dump pairs.npz` | 67,965 对（排除 8,107 → 59,858）；固定闸 0.996：knn precision **0.9997** recall **0.1084**；**硬约束下最大 recall 0.2422 @闸 0.991**（precision 0.99923）| 2 m 19 s | doc 最近 0.1444 @0.9945；现在更高（集重建，对数 71,497→67,965）。precision 硬约束守住 ✓ |
| **guard_ceiling** | ✅ | 吃上一项的 `--dump`；`--guard config/confusable_font_degraded.json --tau 0.93 0.95 0.97` | 无护栏：闸 0.9932 / recall **0.1931**；degraded τ0.93：闸 0.9699 / recall 0.7362（3.8×）；τ0.97：0.5268（2.7×）| 0.5 s | doc「无护栏闸 0.9932 / recall 0.1881」✓；护栏档 doc 0.5592（106 对护栏）口径不同，量级一致 ✓ |
| **clustering** | ✅ | `eval_clustering.py <集>/char-clustering`（冻结模式）| purity vol01 **0.99965**（2853/2854）/ vol02 **1.0**（2677/2677）/ human **1.0**；碎片率 2.64/2.77/2.58；难例对 60.8/56.1/40.0% | 37 s | doc .99967/.99901/1.0；vol01 同为「1 个脏簇」，vol02 反而更好 ✓ |
| **db_match** | ✅ | `eval_db_match.py <集>/char-clustering [--cov-high 0.97]` | 默认闸 0.992：覆盖 7.1 / 12.4 / 14.9%，精度全 **1.0000**；**闸 0.97：35.3 / 44.3 / 54.0%**，精度全 1.0000 | 4.5 min ×2 | doc「现行基线」闸 0.97：35.9 / 44.8 / 54.8 → 差 −0.6/−0.5/−0.8 pt，精度不变，**判不回归**（集排除名单更新）。⚠ doc 里 8.7/16.3/18.1 是闸 0.996 的更旧口径，与现默认闸 0.992 不可直接比——别拿默认闸的数去对 8.7 |
| **zero_shot**（整字 vs 拆字）| ✅（修了 Windows 路径）| `eval_zero_shot.py --n 300` | unseen n=300：whole **76.3 / 92.7 / 95.0**；parts 51.0 / 73.3 / 81.7 | 1.6 min | doc whole 73.0/90.3/93.0（随机抽样 + 字体集不同）；结论「parts 没有一个超过基线」复现 ✓ |
| **zero_shot_fusion** | ✅ | `eval_zero_shot_fusion.py`（默认 r5）| unseen 1,327 严格：hog 79.2/94.3/96.2；**cnn 96.8/98.6/98.7**；rrf 90.7/98.1/98.5 | 2 min | `structure_aware_recognition_design.md` 护栏「cnn 96.8」**逐位一致** ✓ |
| **rare_char**（n=21）| ✅（加回退）| `eval_rare_char.py --dataset <集>/rare-char` | top-10：全部 21：现状 33.3% → 字体 **76.2%**；**真难题 14：0% → 78.6%**；稀有但有候选 7：100% → 71.4%；命中时中位名次 1 | 36 s | 真难题 **78.6** 与 doc 逐位一致 ✓。⚠ 金标 patch 是 Windows 路径，云端用 glyph_bench 同格图回退（**20/21**，`凜` 库里是 `凛` 对不上），口径：回退图是已归一化图。n 仍只有 21 |
| **oov** | ✅（要 70k 表）| `eval_oov.py --json` | 314 条 / 138 字种：**emb 74.5 / 89.8 / 91.7**；cls 恒 0；glyphdb 80.5/96.1、user 63.3/83.5 | 44 min（建表）；之后 <1 min | doc r5 73.2/…/90.4 → 本次 **+1.3/+1.3**，不回归。（doc 是 09-17 的 baseline_r5.json；云端 CPU 与本机 GPU 有浮点差，且 bench 之后扩过）|
| **degradation** | ✅ | `eval_degradation.py` | emb@1/@10：clean 76.1/95.9；blur0.8/1.5、erode、dilate、hline、vline、edge3px 基本不动（74.5~78.7）；**blur2.5 21.7/53.2**；occl10 71.3/95.2、**occl20 38.5/83.4、occl30 16.6/49.7**；stamp 62.1/94.3；结构(最近类) clean 97.7 | 数分钟 | 与任务卡 T5③ 结论「粗细/断墨/贴边免疫、σ2.5 与 ≥20% 遮挡才塌、塌时 top-10 先撑」吻合 ✓ |
| **seen_test_single_proto** | ✅ | `--model models/glyph_cnn_r5/best.pt` | 459 类 / 1,963 查询：font_only **97.4**/99.9/99.9；font_plus_real **98.8**/99.9/99.9；cls_ref 99.8 | 数分钟 | doc 无逐项记载可对，只看「单原型逼近分类头」直觉成立（98.8 vs 99.8）|
| **struct_rerank** | ✅ | `eval_struct_rerank.py --json` | baseline top-1 8.9 / top-5 84.7 / top-10 91.7；best 「m=10 w=2」**top-1 25.8**、top-5 76.8、top-10 91.7；m=30 各档 top-10 掉 | ~8 min | `structure_aware_recognition_design.md`「本机实测①」**逐位一致**（云端 CPU = 本机 GPU 结果）✓ 结论不变：top-1 换 top-5，不开 |
| **struct_heads** | ⚠ 半个 | `eval_struct_heads.py --ckpt models/glyph_cnn_r5/best.pt` | r5 **没有结构头**，只出第 3 项：baseline 8.9/84.7/91.7，comp-bag 22.0/74.5/87.3（与上一项 m=30 w=1 同）| 数分钟 | **缺**：带结构头的 checkpoint（设计稿里的 `glyph_cnn_r6`，不在仓里）；谁补：本机 GPU 训的人把 r6 传到 `_shared/` 或 `models/`。或走任务卡 T1 的「冻结 r5 + CPU 训线性探针」（`probe_struct_heads.py`）|
| **confusable_lm** | ✅ | `eval_confusable_lm.py <集>/confusable-context/cases.json --book-corpus <ws>/corpus/zongmu_wuyingdian_reference.txt --general-corpus corpus/external/daizhige_zhaoling.txt --mode heldout` | n-gram(3) heldout：真难档 **90.6%** / 送分档 97.5% / 合计 **96.1%**（n=154，多数类 76.0%）| 14 s | 集 README 首轮 87.5/97.5/95.5 → 持平略升 ✓。⚠ 用仓内 17 KB 残片本书语料会得 96.9/93.4/94.2，**别用** |
| **context_correction** | ✅ | `eval_context_correction.py <集>/context-correction --book-corpus <ws>语料 --general-corpus … --gate 0.70 --sweep 0,0.5,0.9,1.0` | n=1,681，基线 top-1 67.52%；纯通用 **+1.61%（救 30/改坏 3，有害翻转 0.26%）**；本书 0.5：+1.67%（29/1）；0.9：+1.31%（26/4）；纯本书 +0.65%（23/12）| 17 s | 纯通用行与 `pipeline_handbook.md`「+1.61% 30/3 0.26%」**逐位一致** ✓；doc 的「混合 0.9 = +2.32% 41/2」**复现不了**（三份本书语料都试了：+1.31/+1.25/+1.37%）——集在那之后换过（doc 当时基线/样本数不同），**此条需本机确认是集变了还是混合配置变了**，在 #305 里标「待核」|
| **align_replace_gate** | ✅（限有 Step5-a 产物的册）| `eval_align_replace_gate.py -w <overlay> --books vol01 --out <dir>`；vol02 用老快照另指 `GUJI_PRODUCTS_DIR`；再 `--report-only --books vol01,vol02` | 全部等长 replace 位 2,508，人裁 696（gold 对 97.6%）；现役长度闸 G0：采信 95.3%、**错采 17/658 = 2.6%**、漏采 38/679；不设闸错采 17/696 | vol01 2 m 44 s | doc T7「现役长度闸 19/491 = 3.9%、库证据闸 5/476 = 1.1%」——现在人裁更多（513→696）、错采率更低；量的是同一批位，无回归 ✓。⚠ vol02 用的是 cd04496 老快照（Step2 修复前），载体只有 glyph_match（云端无 OCR，与生产差一路）|
| **llm_context** | ✅ mock；真调用部分 | `build_llm_context_evalset.py` 建集（150/359 题）→ `eval_llm_context.py` | mock baseline **3.33%**、mock gold **100%**；**真 GLM：`glm-4-flash` 28.0%（42/150，解析失败 0%，答案在候选内 149/150）**；`glm-4-plus`/`glm-4-air` 账户欠费（code 1113）跑不了 | mock 秒级；glm-flash 3.7 min | 见下 |
| **char_ocr** | ❌ | 引擎能跑（`rapidocr-onnxruntime` 装得上，CPU 即可，非 GPU）| **缺数据**：金标 9,571 条的图块路径是 `D:\workspace\…\cache\vol01\char_patch\pXXXXcYYsZ.png`，云端没有这批图 | — | 谁补：本机把 `cache/vol01/char_patch` 里金标对应的图导成 zip 放 `_shared/`（估计几十 MB）。试过用 glyph_store 实例 bbox 从原图重切：bbox 是 v1 预处理坐标系，切出来对不上，**此路不通**。脚本已修：图块全缺时报错退出（以前印 0.00% 假基线）|
| **font_fallback** | ❌ | 读 v1 链 `output/<册>/phase9_seed/queue.jsonl` + 字体版库（`glyph-db import-font`）| 缺 v1 产物 | — | 谁补：本机 v1 output，或把脚本改读 v2 `seed_admit`/`glyph_match` 产物（工作量小，但要动评测逻辑，本次没动）|

### llm_context 的 3.3% 有没有意义

**没有，它只是接线自检。** 评测集专挑「现役 gated_ngram 判错」的槽位，「现有策略在此集上按构造应为 0」；
mock `baseline` 模式复述现役答案，所以应≈0（3.33% 是 5/150 题碰巧候选并列），mock `gold` 模式 100% 证明打分与解析链路通。
要看 LLM 有没有价值得真调用：这次用 `glm-4-flash`（唯一有额度的）得 **28.0%**——在现役策略必错的 150 题里救回 42 题，
**方向上说明外部 LLM 有增量**，但：① 只是最弱的 flash，`glm-4-plus`（脚本默认）欠费没法测；② 只量了「ngram 错的」一侧，
没量「ngram 对的 LLM 会不会改坏」——要真评估需要对称评测集（ngram 对/错各一半），这是评测集设计缺口。
调用走的是沙箱代理的注入凭据（`GLM_API_KEY` 设成占位即可）；缓存在沙箱，未入库。

## 3. 需要你注意的三处

1. **context_correction「混合 0.9」doc 复现不了**（§2）；纯通用行逐位一致，说明评测口径没坏，是集或配置在 doc 之后变了。待本机核。
2. **db_match 的 doc 基线有两套闸**（0.996 旧 / 0.97 现行），默认闸现在是 0.992，三者互不可比。建议在 `glyph_match_stack.md` 基线表统一标闸值。
3. **静默假数据三处**（已修两处）：`eval_zero_shot` 和 `eval_rare_char` 在 Linux 上因反斜杠读不到图，前者 ZeroDivision、后者把读不到的当「字体未命中」算进分母；`eval_char_ocr` 读不到图印 0.00%。
   同类隐患还在 `build_*`/`train_glyph_cnn.py`（`cv2.imread(it["png"])`），没动。建议所有 glyph_bench/oov 读图走统一的 `_png()`。

## 4. Step7 回放评测（`scripts/eval_step7_replay.py` + `doc/step7_replay_eval.md`）

- **能做、已做、只读**：读工作区 `feedback/events` + 快照里的 `seed_admit` 产物，不碰 `EventLog`/`consumed`/产物。输出：放行精度（按通道）、落人审的可挽回率、循环健全性、排除名单冲突、编号漂移页剔除。
- **但现有事件量不出放行精度**（vol01 实测）：741 个人裁格里 502 格是 Step7 自己抄人裁（`use_human_verdicts`，循环），122 格在排除名单，其余是没放行的；**自动放行 ∧ 有人裁字 = 0 格**。
  原因是结构性的：人裁只审被送审（没放行）的格，放行的格没人看。
- 能稳定给的三个数：`human` 通道健全性 502/507 = 99.0%；落人审被人标切坏/非字 95+2；排除名单里人却读出字 122（名单误伤待复核）。可当回归护栏。
- **要真放行精度 → 对自动放行格做按通道分层的随机抽检**（抽检批名含 `audit`，脚本自动归 `sampled` 档）；严格回放（`use_human_verdicts=False` + 留一摘库重跑 5-a→7）要整库，工程量在「按格摘刻例」，先做抽检。详见 doc §4。
- vol02 只有 Step2 修复前的老快照，回放出的 match_ref 93.9%（n=33）要先剔 11 个「格号漂移」页，**只当演示**。

## 5. 改动清单

`scripts/eval_step7_replay.py`（新）、`doc/step7_replay_eval.md`（新）、`HANDOFF_M2.md`（新）、
`scripts/eval_char_ocr.py`（图全缺报错退出、路径归一）、`scripts/eval_rare_char.py`（glyph_bench 回退 + 图源计数）、
`scripts/eval_zero_shot.py`（路径归一）、`tests/test_eval_v2.py`（step7_replay 进 NOT_REGISTRY_SHAPED；`test_eval_v2` 24 通过）、
`doc/cloud_eval.md` §6（重写）。

## 6. 复现备忘

```bash
export GUJI_WORKSPACE=/tmp/ws_overlay GUJI_PRODUCTS_DIR=/tmp/m2_products PYTHONIOENCODING=utf-8 PYTHONPATH=.
# 本书语料一律用工作区那份，不要用仓内 corpus/ 下 17KB 残片
```
