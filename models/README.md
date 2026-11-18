# 模型检查点（不可重建的真源）

> **2026-11-10（v0.7.0）起模型文件不进 git**（用户 11-04 定，`doc/design/模型系统.md` 4.2 第 1 条）：真源在 R2，
> 本仓只带 `config/model-registry.json`（路径 → sha256）。`guji model fetch` 按表取回到本目录；`guji pipeline`、
> 测试开跑前（`tests/conftest.py`）、`install_release.py` 都会自动取（要 `GUJI_DATA_TOKEN` 或 `_READ`）。
> 换模型：放好文件 → `guji model registry` 重写表 → `guji model upload --execute` 传 R2 → 提交表。下文「进 Git」是旧说法。

`glyph_cnn_r5/best.pt`（18.8 MB，**2026-09-17 起现役**）是
`scripts/train_glyph_cnn.py` 训出的 CNN 分类器，Step5-b（生僻字候选）与
embedding 检索都靠它。与 `glyph_store/`、`fonts/` 同一条判断标准——
**能不能确定性重建**：这个不能，重训要 GPU + 数小时，所以进 Git，
不放进 `/cache/`（那条规则忽略的是可从原图/字体现算的中间产物）。

```
models/glyph_cnn_r5/best.pt   # 现役
models/glyph_cnn_r4/best.pt   # 上一代，可切回
```

**r5 与 r4 同配方同数据，只把训练轮数 160 → 60**（`research/metric_loss/`）：
类外 314 条真刻例 emb top-1 67.8% → **73.2%**，护栏 unseen 1,327 严格 top-1
95.4% → 96.9% 不退反涨。长训练在拿类外泛化换类内精度。
度量损失（ArcFace/CosFace）在真刻例上一律为负，已证伪不采纳。
结论正本：overview `Step5-字符识别/5b-生僻字候选/06-给embedding加独立度量损失.md` §九。

⚠️ **换 checkpoint 要连着重标三个值**（判据都形如「模型分数 < X」，全绑分数分布）：

| 值 | 位置 | r4 | r5 |
|---|---|---|---|
| `FORM_EMB_GAP` | `clustering/variant_form.py` | 0.12 | **0.03** |
| `escalate_threshold` | `books/<id>.yaml` 的 `font.charset` | 0.85 | **0.95**（北行刻本实测）|
| `HOG/CNN/EMB_WEIGHT` | `clustering/cnn_candidates.py` | 0/1/4 | 不变 |

沿用旧值不会报错，**闸会静默关死**（r5 沿用 0.12 → 异体定形放行率 76%→0.6%；
沿用 0.85 → 字表阶梯升级率 66%→0.5%，类外 top-10 掉 13 点）。

加载路径见 `open_guji_cv/clustering/cnn_candidates.py` 的 `DEFAULT_CKPT`：
新 clone 直接从这里读；本机旧路径 `cache/glyph_cnn_r4/best.pt`（若存在）仍优先生效，
不强迫已有工作区搬文件。

换模型（重训后要换现役 checkpoint）：把新 `best.pt` 提交到这个目录即可，
是一个正常的 Git 提交，历史与版本管理都是免费的。旧版本留在 Git 历史里，
不必像 GitHub Release 那样自己维护 tag。

## `glyph_sim_qtw/`、`glyph_sim_base_v1/`（5a 相似度 CNN）

`glyph_match.sim_model` 开关用的度量学习 CNN（`clustering/sim_cnn.py`），每个目录一份 `model.pt` 加同目录的分数校准表 `calib.json`。

```
models/glyph_sim_qtw/       # 全唐文字形库训的，只给全唐文用
models/glyph_sim_base_v1/   # 通用底座 v1（2026-11-17）：殿本、史記、全唐文三书合训，新书开书直接用
```

底座的 `calib.json` 是通用保守包络表（对没见过的书取最不利的折算）。版本就是目录名的 `_v<N>`：并进新书重训时出 `glyph_sim_base_v2/`，
旧目录不动，书配置里写的路径决定用哪一版。用法、门槛、重训与换版步骤见 guji-manager `doc/参考/5a相似度模型.md`。

## `stroke_evidence_v1/`（5b 笔画证据，2026-11-18）

册配置 `font.stroke_evidence` 开关用的三个文件（`clustering/stroke_evidence.py`，缺省关）：

```
models/stroke_evidence_v1/net.pt            # 笔段检测权重（合成数据训，不含任何书的刻例）
models/stroke_evidence_v1/skel.npz          # GlyphWiki KAGE 骨架索引：97,681 字、149,881 个地区形
models/stroke_evidence_v1/skel_forms.json   # 字 → 各地区形在索引里的位置
```

换权重或重建索引出 `stroke_evidence_v2/`，旧目录不动。原理、开关、证据见 `doc/design/5b-笔画证据.md`。

## `partition_unet_v2/model.pt`（11 MB，2026-09-14 起现役）

Step3 候选池裁判：类别无关的逐像素归属 U-Net（`open_guji_cv/utils/cut_select.py`）。只用合成粘连对训练
（`research/touch_resolve/synth_pairs.py` 造对、`train_partition_unet_v2.py --train` 16 轮，GPU 约 1 小时），
零人工标注；实验记录在 overview `Step3-逐字切分/05-高级切分算法.md`「档 3」与实验六～七。
同一条判断标准：不可确定性重建 → 进 Git。加载路径 `cut_select.DEFAULT_CKPT`；权重的 (mtime_ns, size) 指纹进
`RowSegmentParams.judge_fingerprint`，**换权重 Step3 产物自动 stale**。

