# instance_quality 金标迁移（M1 道 C 组，2026-09-30）

## 结论

| | 条数 |
|---|---|
| 原金标 `instances/expected.json`（vol01 362 + vol02 200；`items.jsonl` 里 legacy 部分同源） | **562** |
| **迁移到 v2 已验证层**（`instances/instances_v2.json` 的 `items`） | **77**（clean 73 + contaminated 4） |
| 已失效（`retired`，带原因） | 485 |

失效原因（485 条，分母=562，逐类互斥）：

| 原因 | 条数 | 说明 |
|---|---|---|
| 无人裁图块（`patches/` 里没有这条的图，没有任何图像凭证） | 170 | 其中 vol02 `seg_review_r1` truncated 88、vol01 truncated 33、vol01 clean 26… |
| 图块与 v2 同位字块**不是同一张图** | 247 | NCC<0.93 或尺寸差>8px 或该 pos 在 v2 不存在——v2 切分（row_segment 1.12 等）已变 |
| 目视：图块与标签不符 | 61 | 见下「推翻前提」 |
| 目视：放大仍拿不准 | 1 | vol02:180:3:8（clean 标签，图块底部有碎渣） |
| 同一 v1 键在 expected.json 里有互相矛盾的多个标签 | 6 | 3 个键各同时标了 contaminated 与 not_text（vol01/12:1:20 等） |

## ⚠ 推翻任务书的一个前提：「instances/patches 是人当时看的图」——**不是**

逐张目视幸存图块（联系表 `sheets/`，共 139 张候选）发现：**标 contaminated / truncated / not_text 的 65 张
图块里，只有 4 张图上真有所标缺陷，其余 61 张画的是干净完整的字。**
原因：README「2026-08-24 预处理重建轮」明写「参照图块已按新产物刷新 415 张；大量 defect 标签描述的是旧产物的缺陷，
重建后缺陷本体已被修复」——图块被刷新成新产物的图，标签却还是刷新前人给的。
于是「图块与 v2 字块同一张图」**只**证明「这是新产物的图」，**不**证明「人看的就是它」，更不证明标签还成立：
若只用这一道门，迁出来的是 41 条「contaminated」标在干净字上的金标，自检检出率会被算成 0%、而且是假的。
所以加了第二道门（目视一致性），并保留了 `visual_review.json` 供复核。

## 迁移判据（三道门，全部是图像/目视，不含「算法现在判得对不对」）

脚本：`migrate_instances.py`（`candidates` → `sheets` → 目视 → `apply`）。

1. **有人裁图块**：`patches/<册>_<页>_<列>_<idx>.png` 存在。
2. **图块 = v2 字块**：同页、v2 `pos == v1 idx + 1` 且列号相同（recrop 上这条规律 31/31 成立）、尺寸各差 ≤8px、
   σ=1 模糊后归一化互相关 ≥0.93（同图实测 0.96~1.00）→ 锚到 v2 (col, slot)。
3. **标签↔图块一致性（目视）**：`visual_review.json` 登记。规则：clean=完整干净本字；contaminated=图上有明显别人的墨；
   truncated=缺笔；not_text=不是字；放大仍拿不准入 `unsure` 踢出。
   4 条保留的缺陷：vol01:9:2:6（「十」左侧一道横渣）、vol01:9:3:2（「諭」左侧孤点）、vol01:17:3:21（「蔣」底部碎渣）、
   vol01:25:2:21（「人」右上孤点）——**都是很淡的残渣**，不是大块混入。

## v2 原生人裁（`items.jsonl` 里 595 条，无 legacy_source）——**没迁，另作「未验证」参考读数**

这些是 v2 审查页上人裁的（键已是 v2 slot），其中 vol01/vol02 缺陷 96 条、bxgb 缺陷 130 条、clean 361 条。
但它们**没有保存任何当时的图块/指纹**（`workspace/feedback/anchors/vol02.jsonl` 里这类「无字裁决」的锚全是 null，
原因栏写「无当时图块，无从核对」），所以不满足「人当时看的图还在」。我试过对缺陷条目逐张目视「现行字块上是否
确有所标缺陷」，前 12 条里多数看不出（标签所述缺陷已被后续改动修好或极淡），按「判不准不入金标」停手，
未继续——**需要你决定**要不要投入人力继续（见 HANDOFF）。
评测脚本用 `--with-unverified` 把它们另报一块（标「参考读数，不进主结果」）。
**根治办法**：以后审查页落人裁事件时顺带存字块 sha / 指纹（现在 `gold/drift.py` 已有 `fingerprint`），
这样下一轮金标天然可迁。

## 文件

- `instances_v2.json`（= 数据集 `char-segmentation/instances/instances_v2.json`）：`items` 77 + `retired` 485
- `candidates.json`（过前两道的 139 张候选 + 前两道的失效记录）、`sheets/`（目视用联系表）、`visual_review.json`（目视结论，可复核）
- `migrate_instances.py`
- 评测 `scripts/eval_instance_quality.py` 默认读 v2（`--v1` 旧读法；`--with-unverified` 另报未验证层）；
  指标名与计算函数 `evaluate_self_detection` **一字未动**。
- 旧 `expected.json` / `items.jsonl` **未改动**（它们仍是 recrop 评测与 v2 原生条目的来源）。
