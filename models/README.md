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

## `partition_unet_v2/model.pt`（11 MB，2026-09-14 起现役）

Step3 候选池裁判：类别无关的逐像素归属 U-Net（`open_guji_cv/utils/cut_select.py`）。只用合成粘连对训练
（`experiments/touch_resolve/synth_pairs.py` 造对、`train_partition_unet_v2.py --train` 16 轮，GPU 约 1 小时），
零人工标注；实验记录在 overview `Step3-逐字切分/05-高级切分算法.md`「档 3」与实验六～七。
同一条判断标准：不可确定性重建 → 进 Git。加载路径 `cut_select.DEFAULT_CKPT`；权重的 (mtime_ns, size) 指纹进
`RowSegmentParams.judge_fingerprint`，**换权重 Step3 产物自动 stale**。

