# HANDOFF R1 —— replace 位采信做成学习模型（2026-10-01，任务卡 overview #334 R1 节）

**结论：不可接受，不接入。** 现行「长度闸 ∧ 库证据闸」在同一标签集上，同错采下采信量不输学习模型（LR/HGB 都更低），
同采信量下错采数不更少；也无法靠它安全放宽长段（数据撑不起）。`align_ref` **一个字节没改**（本分支只加实验脚本与结果）。

## 0. 环境与缺口（先说清）
- 挂仓：`open-guji-core/overview`（push）与 `open-guji/open-guji-dataset`（push）**被权限分类器拒绝**（未绕过）；
  `open-guji/guji-workspace`（read）已挂。因此**读不到任务卡 #334 / 总方向 / 16-盘点原文**，也**写不了 #334 评论**——
  口径全按任务书转述 + cv 仓内文档执行。需要的话请别的道代贴本文件。
- 云端无 OCR、无字块缓存（图块）。载体串只用 `glyph_match`（`slots_from_evidence(match, None)`）；
  **无图像特征**（r5 embedding 余弦）。老评测脚本里该余弦本身分辨力差（见其注释），不是主因。
- 快照：vol01 = `products-snap/vol01-20260927`（32b9c2b），vol02 = 老快照 `products-snap/vol02-20260927`（cd04496）；
  都不含 `rare_candidates` 的完整页，也没有 `ocr_candidates`。

## 1. 数据集（`build_dataset.py`）
全部等长 replace 位（与生产同源 `align_ops`，不过闸）：vol01 1425 + vol02 1083 = **2508**（与任务书一致）。
每位 ~50 个信号：段长/位置/左右 equal 夹持、列内位置、页级（替换率、锚定票数、`dominance`、`vote_frac`）、
库（top1 cov、与次优差、库字与 gold/hyp 相等/异体、gold 在库候选名次与分）、5-b（有无 gold、名次、top1 是否 gold/hyp）、
同段一致性（段内均/最小 cov、段内异体数、库强认下却≠gold 的位数）、异体/形近关系。

**标签对上方式与丢弃数**
| 册 | 事件 | 来源 | 结果 |
|---|---|---|---|
| vol02 | 4687 confirm 事件 | `feedback.bindings.book_bindings` + `usable`（后到覆盖、认撤下） | 撤下作废 68、绑定不采信 571 → 落 **1897** 格 |
| vol01 | 4048 事件 | **绑定表在云端对不上**：4048 条全落 `unanchored` 且早于现行切分（无图块缓存、无补锚），全丢 | 改用快照 `seed_admit` 的 **human 通道**（服务器 Step7 已过绑定表）507 格；其 shape 里有 UTF-8 乱码（`别`→`åˆ«`），按 cp1252 还原 |

落到 replace 位的有标签数 **966**（vol01 232 / vol02 734）；采对 951、采错 15。
**注意的偏倚**：标签格全部在 5-b 面板里（`rare_has`=1），即“送过人审的难格”，不是 replace 位的随机样本；
vol01 另有 1193 个 replace 位无标签。

## 2. 正面比（同一 966 标签集，页分组 5 折 × 20 次随机分折）
现行：长度闸 ∧ 库证据闸 **采信 921，错采 9**（仅长度闸 933/错 18 ·仅库闸见 result.json）。

| 方案 | 同错采 ≤9：采信量 | 同采信 ≥921：错采数 | 零错采：采信量 |
|---|---|---|---|
| **现行（点）** | **921** | **9** | — |
| LR（全特征） | 885.7±54 | 9.95±0.7 | 52±28 |
| HGB（全特征） | 881.7±45 | 10.65±1.3 | 100±97 |
| HGB 仅 段长+库+关系 | 900.2±36 | 9.2±1.2 | 39±15 |

曲线数据：`scripts/experiments/replace_gate/results/curves.csv`（seed0，LR/HGB 逐点）、`curve.png`（现行点标星）。

**为什么赢不了**：15 个错采里 6 个已被库证据闸拦下（日/曰、入/人 的“库强认 hyp”类）；剩下 **9 个全是“库没认下（cov 0.93–0.99、unsure）、
载体本身是乱码、人读出生僻字”**——整理本字也不对（踳、𬋕、筍、巡…）。这类和 912 个整理本字对的 unsure 格在已有信号上不可分
（错样本 lib_gold_rank、m_cov 均值与对样本几乎重合）。要拆开它得靠**图像**（读字形像不像 gold），云端缺字块。

## 3. 消融（hgb 去掉一组，同错采 ≤9 的采信量，full=881.7）
seg 865.8 / loc 862.8 / page 850.2 / lib 850.6 / rel 847.0 / rare 869.0 / segcons 852.0。各组去掉都略降，但标准差 25–70，
**差异淹没在噪声里**（总共才 15 个负例）；没有哪一组能当作“可删”的结论。

## 4. 长段（≥4 字）能否放宽
人裁里非闸内共 33 格（≥4 字 16 格），**全部采对**（0 错）。模型在“同错采阈值”下放进 28–32 格（≥4 字 14–16），也是 0 错。
但这只说明这 33 格里放宽没出事——**33 个无错只能把错采率上界压到 ≈9%（rule of three）**，而现行闸 1.0%（9/921，Wilson 95% ≈ 0.5–1.8%）；
**数据撑不起“安全放宽”**。已导出待标名单 `results/to_label.tsv`（86 个未人裁的非闸内位，按 LR 分升序，最拿不准的在前；
建议先标 ≥4 字的 ~48 个 + 没夹住的），标到 ≥150 格再复测才有意义。

## 5. 对 Step7 影子模型的影响
**无**（未接入，产物不变）。若日后接入：放宽的 replace 位会进 `align_ref` 通道、改变影子模型的“整理本关系/对齐可靠度”信号分布
（放宽越多，`align_op==replace` 且被采信的占比越高）→ 需要重训或重标定。

## 6. 复现
```bash
# 临时工作区：软链 guji-workspace 书目录，products/vol01、vol02 指向 zst 快照解包目录；glyph db 重建到临时路径
GUJI_WORKSPACE=<ws> GUJI_GLYPH_DB=<tmp>/glyph.db PYTHONPATH=. python scripts/experiments/replace_gate/build_dataset.py vol01 vol02 \
    --human-channel-books vol01 --out rows.jsonl
python scripts/experiments/replace_gate/train_eval.py rows.jsonl --out results --repeats 20
```
依赖 sklearn、matplotlib（画图可选）。`rows.jsonl` 不入库（含人裁标签，可重建）；`results/dataset_meta.json` 是丢弃数台账。

## 7. 建议
1. 不接入；现行两道闸保留。
2. 要往前走须补 **图像信号**（本机有 r5 embedding：gold vs 载体字余弦、gold 模板名次）并扩 **随机抽样的人裁**（不只在难格），负例要到 ≥60 才有统计力。
3. 长段放宽先按 §4 的名单补标。
