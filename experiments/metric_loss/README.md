# metric_loss — embedding 度量损失实验（非生产代码）

**性质**：实验脚本，`open_guji_cv/` 包不 import 这里的任何文件，管线与控制台也不依赖它。
只读生产产物（`cache/glyph_bench`、`cache/oov_bench`、各 workspace 的 glyph.db）与
`D:\data\glyph-sources\`，不写产物、不改金标。产出一律落 `out/`（gitignore，可重算）。

**结论正本**：overview 仓
`项目进展/图片初步数字化/进度/Step5-字符识别/5b-生僻字候选/06-给embedding加独立度量损失.md` §九。

## 一句话结论（2026-09-17）

**度量损失（ArcFace / CosFace / 纯余弦头）在真刻例上一律为负收益，不采纳。**
真正的收益是训练轮数 160 → 60：`oov_bench` emb top-1 **67.8% → 73.2%**，
不改一行网络代码。换 checkpoint 必须同时把 `FORM_EMB_GAP` 从 0.12 改 **0.03**，
否则 `fixed_form` 通道放行率从 76.1% 塌到 0.6%。

| 文件 | 作用 |
|---|---|
| `data.py` | 留出字种切分；康熙/字统网/三本书真刻例的加载与归一化 |
| `train.py` | 与 `scripts/train_glyph_cnn.py` 同架构同超参，**只换损失**（ce / cosface / arcface，可调 margin、comp 权重、余弦头） |
| `evaluate.py` | 留出集的 embedding 检索评测（候选集大小可加 distractor 调节） |
| `baseline.py` | 用现役 checkpoint 在留出集上打基线（顺手实测「分类头类外恒 0」） |
| `to_prod_ckpt.py` | 余弦头 checkpoint → 生产 `CnnCandidates` 能加载的线性头形状 |
| `eval_oov_fast.py` | 官方 `scripts/eval_oov.py` 的同口径快速版（6,276s → 16s），带 `--verify` 对齐校验 |
| `run_matrix.sh` | 实验矩阵（已跑 4 档后按用户裁定停止，见结论正本 §9.7） |

## 两个踩过的坑（别重踩）

1. **类外评测集的样本量可以靠字典源撑大，但那样撑出来的集会把结论带反。**
   本实验另建的大集（n=25,747，96% 查询是字典/字统网干净印本图）上
   margin 是**正**收益；官方 `oov_bench`（314 条全真刻例）上是**负**的。
   口径（查询图必须是真刻例）比样本量重要。

2. **字统网的模板不能让它回落到 `篆/甲骨/金`。** 第一版建集没限定书体，
   模板落到篆书/甲骨文上，于是在测「印刷体查询 × 甲骨文模板」——
   那是跨书体识别，不是类外泛化，基线被压到 34.7%。两侧一律限 `印/楷`
   （`data.PRINT_STYLES`）。

## 复现

```bash
# 1. 建留出集 + 打基线（现役 checkpoint）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe experiments/metric_loss/data.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe experiments/metric_loss/baseline.py

# 2. 训一档（60 epoch ≈ 25 分钟，RTX 3080）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe experiments/metric_loss/train.py \
  --epochs 60 --font-per-class 24 --extra-per-class 4 \
  --extra-real "zitools:D:/data/glyph-sources/zitools/p1:印,楷" \
  --heldout experiments/metric_loss/out/split_eval.json \
  --loss ce --out experiments/metric_loss/out/ce_base

# 3. 转生产形状 → 跑官方靶子（首次会渲染 7 万字模板库，约 20 分钟；之后 16s）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe experiments/metric_loss/to_prod_ckpt.py \
  --src experiments/metric_loss/out/ce_base/best.pt --dst experiments/metric_loss/out/ce_base/prod.pt
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe experiments/metric_loss/eval_oov_fast.py \
  --ckpt experiments/metric_loss/out/ce_base/prod.pt

# 4. 回归护栏（结果在 out/guardrails/）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/eval_zero_shot_fusion.py \
  --model experiments/metric_loss/out/ce_base/prod.pt --split unseen --emb
EX="--extra kangxi:D:/data/glyph-sources/kangxi/crops@cache/exp_extglyph/kangxi_verified_v2.txt \
    --extra zitools:D:/data/glyph-sources/zitools/p1:印,楷"
PYTHONIOENCODING=utf-8 PYTHONPATH=. ./.venv/Scripts/python.exe cache/exp_extglyph/eval_closedset.py \
  --model experiments/metric_loss/out/ce_base/prod.pt $EX --tag NEW
PYTHONIOENCODING=utf-8 PYTHONPATH=. ./.venv/Scripts/python.exe cache/exp_extglyph/calib_gap.py \
  --model experiments/metric_loss/out/ce_base/prod.pt $EX --tag NEW
```
