# 模型检查点（不可重建的真源）

`glyph_cnn_r4/best.pt`（18.8 MB）是 `scripts/train_glyph_cnn.py` 训出的 CNN 分类器，
Step5-b（生僻字候选）与 embedding 检索都靠它。与 `glyph_store/`、`fonts/` 同一条
判断标准——**能不能确定性重建**：这个不能，重训要 GPU + 数小时，所以进 Git，
不放进 `/cache/`（那条规则忽略的是可从原图/字体现算的中间产物）。

```
models/glyph_cnn_r4/best.pt
```

加载路径见 `open_guji_cv/clustering/cnn_candidates.py` 的 `DEFAULT_CKPT`：
新 clone 直接从这里读；本机旧路径 `cache/glyph_cnn_r4/best.pt`（若存在）仍优先生效，
不强迫已有工作区搬文件。

换模型（重训后要换现役 checkpoint）：把新 `best.pt` 提交到这个目录即可，
是一个正常的 Git 提交，历史与版本管理都是免费的。旧版本留在 Git 历史里，
不必像 GitHub Release 那样自己维护 tag。
