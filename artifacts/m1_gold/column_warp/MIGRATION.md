# column_warp 金标迁移（M1·A 道，2026-09-30）

## 结论
- 原金标：`column-warp/samples/*.json` **115 列**（vol01 57 + vol02 58），都只有 `text_band` + `column_fingerprint` + `profile`；
  **`border_class`（上下版框类别）在本克隆里 0 条**——README/metadata.json 写的「64 条」（vol01 32 列）不在 samples 也不在 items.jsonl，
  且没有 `end_fingerprint`，即便找回人裁类别也无法证明端裁剪图还在，**无法迁移**。bxgb 另有 31 条 `border_class` 类别（items.jsonl，
  来自控制台直连裁决，无指纹无存图）同理**不迁**。
- 迁入 v2：**86 列**（fingerprint 5 / profile 71 / remedy_clean 10），失效 **29 列**。明细 `migration_report.json`，迁入样本 `samples_v2/`，失效清单 `invalidated.json`。
- 失效原因（29）：列图宽变了（窗口/边线换过，x 坐标系不同）且投影曲线变了 18；仅投影曲线变了（>0.012）10；含 2 条 mixed 无补救通道（vol01/146 c8、vol02/188 c4）；
  vol01 1 条只宽变。

## 判据（只看图，不看算法答案）
v2 列图 = `cache/<册>/column_raw/pNNNNcNN.png`（Step2 矫正+去噪，与旧 `regen_step2_columns.py` 导出图同义，但窗口纵向多 ~50–70px），
见 `column_warp_v2.py` 文档。三档任一：
1. `fingerprint`：整列图指纹差 ≤6 灰阶（旧 migrate 脚本同口径）且宽差 ≤3px——只有 5 条，因为纵向窗口变了指纹整体漂移。
2. `profile`（新增）：宽差 ≤2px 且样本里存的**人当时看的投影曲线**与现图同 x 的平均绝对差 ≤0.012。标定：指纹档 MAD 0.002~0.0097；宽差≥10px 的真变列 MAD≥0.0235。
3. `remedy_clean`：仅 clean 列，宽差 ≤3px，人标点在新图上墨占比仍 ≤0.01；canonical 按新图重推（旧值记 `canonical_was`）。
**没有用「算法现在判得对不对」**留用任何一条。

## 脚本
`migrate_m1_column_warp.py`（本目录）：`python research/scripts_oneoff/migrate_m1_column_warp.py ../open-guji-dataset/char-segmentation/column-warp --out artifacts/m1_gold/column_warp`；
评测 `scripts/eval_column_warp.py`（默认 `--source v2`，评测时现场过同一道闸，数据集样本文件本身没改）。
