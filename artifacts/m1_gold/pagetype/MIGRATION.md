# pagetype 迁移清单（M1，2026-09-30）

- **空跑原因**：`scripts/eval_pagetype.py` 按 v1 布局读 `output/<册>/<页>.png`（云端/现行工作区没有这个目录），
  每页 `imread` 为 None 被静默 `continue`，n=0，指标全 0 却「✓ 通过」。
- **金标**：`page-type/expected.json` 共 394 条，标的是**原图**页型（vol01 206 + vol02 188），原图未变，
  金标键是 book/page、不依赖任何切分口径 → **全部保留，金标未动**（迁 0 / 失效 0）。
- **评测改动**：图像改从工作区册定义的原图（`load_book(book).raw_path(page)`）读，旧 `output/` 路径留作回退；
  找不到原图的页会打印警告计数而不是静默跳过。`refine_page_type`（body→roster 细化）依赖 v1 `phase3_char_grid`，
  v1 链产物不存在时不执行——策略级（skip/custom/standard）指标不受影响，roster 与 body 同属切分策略。
- **新基线**（沙箱 overlay 工作区，`eval run pagetype`，126 s）：n=394，策略准确率 99.49%，
  误跳过正文 0 页（lost_rate 0），该跳过页检出率 80%（4/5；漏 vol01/205 colophon）。
- **对照上次**：`open-guji-dataset/page-type/README.md` 「网格策略准确率 99.5%（383 页，另跳过 11 页 uncertain）」；
  现在 394 页、uncertain 0（11 页后来补了标）。同口径同数，无回归。
