# 样本字形库（**不是真库**）

从《四庫全書總目》真库抽的 150 个字头 / 900 条刻例 / 900 张图，**只用来跑测试**。

真库（2,664 字头 / 16,557 刻例）在 `siku-zongmu-workspace` 私有仓。
跑真书要设：

```bash
export GUJI_WORKSPACE=/path/to/siku-zongmu-workspace
```

重新生成：

```bash
python scripts/make_sample_store.py \
  --src /path/to/siku-zongmu-workspace/output/glyph_store --chars 200
```
