# HANDOFF D1 — context-correction 金标去泄漏（任务卡 #323）

分支：cv `claude/D1-ctx-gold-1001`（基于 origin/main）；dataset `claude/D1-ctx-gold-1001`（`context-correction/samples_v2/` + README + metadata，已推）。未合 main，未改默认行为。

## 1. 泄漏成因（与任务卡假设有出入，先更正）

**构造代码里没有「把整理本字塞进池」。** `build_context_correction_dataset.py --from-seed` 的池 = `fuse_priors(库匹配候选, OCR top1+s2t)`，无 `extra`；
线上 seed 上下文通道（`seeding.py` ~L1000）确实 `extra=[(整理本字,1.0)]`，但该通道进库的字位 `ORIGIN["context"]=None` 已被剔出集。
对账：rescued 文件里同一次运行的 9 格，用上式重算与冻结池**逐位全等**（含 source=rapidocr 的低概率候选）。

真正的泄漏是**选格偏差**：金标只存在于被进库协议收下的格——align 通道要「OCR=整理本字」双信号一致，human 通道多半是对 OCR 提议点确认。OCR 读错且库没有的格没人收，不在集里。证据：
- align 层 1152 格，**金标池外 = 0**；human 层 529 格，池外 167。167 个不可救格**全是 human**。
- 金标非首选 379 格里 354 个（93%）金标只在 OCR 候选里（align 277/277），glyph 层只有 **25** 个。
→ 候选源/概率形状/名次整套特征带着「谁是被收下的」。X1 的 +17% 是这个，不是注入。
**局限**：phase9_seed 队列与 ocr_carrier 在本机 output/、不进 git，云端无法重跑构造，也拿不到「未被收下的格」，所以 v2 不能真正补出无偏样本，只能分层。

## 2. v2 统计（n=1681，11 页 vol01）

池与 v1 逐字相同，只加标注（`scripts/build_context_correction_v2.py`，从 v1 派生）：source 改名 `glyph`/`ocr`；`gold_reach`；`selection_biased`。

| 层 | 格数 | 其中 top1 错（可救） | 说明 |
|---|---|---|---|
| glyph（金标在字形库候选） | 1101 | **25**（top1 97.73%） | **头条** |
| ocr_only（金标只在 OCR 候选） | 413 | 354 | `selection_biased`，不进头条 |
| unreachable（金标不在池） | 167 | 0（不可救） | 如实保留，全 human |

来源分布：候选 glyph 6817 / ocr 738。origin：align 836 glyph+316 ocr_only+0 不可救；human 265+97+167。

## 3. 新基线（现行规则 gate 0.70；本书语料=工作区 `corpus/zongmu_wuyingdian_reference.txt`，挖掉 2232 字；通用 daizhige_zhaoling）

整集 top1 67.52%（1135/1681）——复现 X1。可救 379 / 不可救 167。
- 纯通用 +gate0.70：救30/坏3；其中 **glyph 层 救2/坏3，ocr_only 层 救28/坏0，unreachable 层 2 次误改**。
- 混合0.9 +gate0.70：救26/坏4；glyph 层 救5/坏4，ocr_only 救21/坏0。
→ 现行规则的头条 +1.3~1.6% **几乎全来自有偏层**；在 glyph 层（可救 25）净增益 −1~+1 格，等于零。

## 4. 学出来对照（`exp_step6_learned.py --samples-dir samples_v2 --reach glyph`，按页留一折、嵌套 τ，池含 OCR 候选）

with_book，n=1101、可救 25：

| | 改字 | 救 | 坏 | 净 |
|---|---|---|---|---|
| 规则 gate0.70 | 10 | 4 | 6 | −0.18% |
| LR | 9 | 8 | 1 | +0.64% |
| HGB | 3 | 2 | 1 | +0.09% |

no_book：规则 gate0.70 救2/坏3；LR 救2/坏0；HGB 救1/坏2。
**不可判，但同向偏好 LR**：差别是个位数格（25 个可救），不到统计功效。
对照（证明偏差仍在）：`--reach glyph,ocr_only`（n=1514、已去 is_rapid）LR +7.7%、HGB +17.0%，规则 gate0.70 救20/坏5——**把有偏层放回去泄漏立刻复现**，所以头条必须只用 glyph 层。
LR 特征组消融（glyph 层）单格级波动，无稳定结论。

## 5. 学出来的能否替换手调规则（用户新口径：不降且明显简化即可接受）

- 性能：glyph 层 LR ≥ 规则（不降，且有害翻转更少），但样本太小，只能说「没证据变差」。
- **代码量：现在没有简化。** 规则一侧：`recognize_flow.fuse_priors/_decide/rank_candidates/semantic_margin` ≈150 行 + `GatedNgram` 25 行 + 常量（DB/OCR 权重、λ=0.55、门槛 0.70、本书/通用 LM 权重 0.9/0.1）。
  学出来一侧：`step6_signals.py` 133 行（28 特征，仍要通用/本书 LM 查询与窗口 logp）+ LR 系数 + Platt + τ 文件，另需训练/校准脚本；LM 与形近表依赖一个都没少。
  只有把特征砍到 3~5 个（OCR p/名次 + LM 窗口 logp）才可能比现状短，消融没能稳定指出这个子集。
- 结论：**不建议据此替换**；等 vol03 影子金标或补出无偏格后再判，且要先做特征裁剪。

## 6. 已改文件（cv）
`scripts/build_context_correction_v2.py`（新）、`scripts/eval_context_correction.py`（`--samples-dir`、`by_reach`）、`scripts/exp_step6_learned.py`（`--samples-dir/--reach/--lr-only`）、`open_guji_cv/steps/step6_signals.py`（X1 带入，`is_rapid` 兼容 `ocr` 源）、`doc/d1_ctx_gold_results/*.json`。
成本：远低于 $6（两次 1 分钟级评测 + 克隆）。
