# -*- coding: utf-8 -*-
"""字位流 `slots.py` 与整理本 `witness.py`：识字、定字和 guji-manager 共用的两块底层。

原 Step9 结果整理（导出、与整理本对勘、体检表、截条图）已在 v0.9.0 整个搬到 guji-manager
`guji_manager/output/`（第五步 `output`）；这里只留两块被 cv 步骤（如 `align_ref`）与 manager 共同读的库。
**不进 `core.step.STEPS`**。
"""
