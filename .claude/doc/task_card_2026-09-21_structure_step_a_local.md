# 任务卡 · 结构感知识别 Step A：本机要做的事（2026-09-21）

> 放到 overview 仓：`项目进展/图片初步数字化/进度/Step5-字符识别/5b-生僻字候选/07-结构感知-StepA-本机任务卡.md`
> （云端会话的仓库范围只有 `open-guji/*`，`open-guji-core/overview` 推不进去，所以先落在
> `open-guji-cv/.claude/doc/`，人搬一下。）
>
> 背景与设计：`open-guji-cv/.claude/doc/structure_aware_recognition_design.md`（第一部分方案、
> 第二部分实施、§13 落地记录）。分支 `claude/compassionate-bardeen-mzigti`，共 11 个提交。

## 云端已做完（全 CPU，测试全绿，不需要你动）

| 块 | 内容 | 入口 |
|---|---|---|
| M0-① | IDS 解析器（10.2 万行 0 失败）、停集词表 K=20 → 1,700 部件、结构码/槽位、倒排索引 | `clustering/ids_struct.py`、`config/ids/components_v1.tsv` |
| M0-② | 部件袋头概率输出（r5 里一直没用过的头）、Top-30 一致性重排（**缺省关**） | `RareCandidatesParams.struct_rerank` |
| M0-③ | IDS 兜底检索接进面板 / CLI；候选带 `struct` 字段；前端「按结构查」+ 结构解释（dist 已构建） | `rare <book> --top ⿰ --slot-comp L=言 --comp 俞`、`/api/rare/search/{book}` |
| M1 云端侧 | 训练脚本 `--struct-heads`（结构头 18 类 + 槽位部件头，默认关 = r5 配方）；推理侧自动识别有无新头（r4/r5 照常）；重排有槽位头就用槽位头 | `scripts/train_glyph_cnn.py`、`cnn_candidates.py` |
| 顺带 | genmin 三套字体接进 `FONT_ORDER`；字体集 + 模型指纹补进产物新鲜度（拉下来 `rare_candidates` 会过期一次，正常） | `font_candidates.py`、`steps/rare_candidates.py` |

## 本机要做的（按顺序，每条一个命令）

### 1. 拉分支、装依赖、跑测试（10 分钟）

```
git fetch origin claude/compassionate-bardeen-mzigti && git checkout claude/compassionate-bardeen-mzigti
uv pip install -e .   # 无新依赖
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m pytest tests/test_ids_struct.py tests/test_rare_ids_fallback.py tests/test_rare_candidates_step.py tests/test_font_candidates.py --junitxml=cache/junit.xml
```

### 2. 两个开关要不要开（各一条命令，CPU，分钟级）

```
# ② 零训练重排：oov_bench 上 基线 vs 重排（扫 weight × top_m，按来源分层）
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_struct_rerank.py --json cache/exp/struct_rerank_r5.json
```
**top-1 与 top-10 都不掉才开**：`books/<id>.yaml` 的 `rare_candidates` 参数加 `struct_rerank: true`。
掉了就不开，把数字记进设计稿 §13。

```
# genmin 三套字体：对照 r5 基线 unseen 严格 96.9 / oov 73.2
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_zero_shot_fusion.py --split unseen --emb
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_oov.py --json cache/exp/oov_r5_genmin.json
```
首次会重建 emb 索引（多三套字体，约 30 分钟）。掉了就把 `FONT_ORDER` 里的 `genmin` 拿掉。

### 3. Step A 训练（GPU，RTX 3080 约 30–40 分钟）

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/train_glyph_cnn.py \
  --epochs 60 --font-per-class 24 --extra-per-class 4 \
  --extra-real "zitools:D:/data/glyph-sources/zitools/p1:印,楷" \
  --struct-heads --out cache/glyph_cnn_r6
```
与 r5 唯一的区别是 `--struct-heads`（多两个头，损失各权 0.5）。训练日志每轮多两列
`struct` / `slot@3`。

### 4. Step A 验收（CPU，分钟级）

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_struct_heads.py --ckpt cache/glyph_cnn_r6/best.pt --json cache/exp/struct_heads_r6.json
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_oov.py --ckpt cache/glyph_cnn_r6/best.pt
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/eval_zero_shot_fusion.py --model cache/glyph_cnn_r6/best.pt --split unseen --emb
```
通过线（设计稿 §5 M1）：

| 指标 | 线 |
|---|---|
| unseen 严格 top-1 | ≥ 96.9（不掉） |
| oov_bench 314 条 emb top-1 / top-10 | ≥ 73.2 / 90.4（不掉） |
| 结构头准确率（合体字） | ≥ 95% |
| 槽位头 top-3 | 报数即可（第一次有这个数） |
| 重排 slot-head vs baseline | top-1、top-10 不掉 |

过线 → 拷到 `models/glyph_cnn_r6/best.pt`、改 `cnn_candidates._resolve_default_ckpt` 的优先级、
**重标 `escalate_threshold`**（`experiments/metric_loss/calib_escalate.py`，换 checkpoint 必做）、
`FORM_EMB_GAP` 复核（r5 换上时那个坑）。不过线 → 把数字记进设计稿 §13，不换。

### 5. 给云端一个数据包（一次，几十 MB）

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/export_train_bundle.py --out cache/train_bundle.zip
```
放到云端能拿到的地方（工作区仓的 LFS / 网盘均可）。有了它，云端能自己跑 2/4 两步的
评测和结构金标审查页，不用每次等本机。

### 6. 结构金标 300 条（人裁，M2）

等 3/4 有了 r6，云端出审查页（`review-artifact`），你在手机上裁「结构 + 槽位部件」。
这一批是回答「对噪点/模糊稳不稳」的靶子，没有它鲁棒性只是感觉。

## 不要做的

- 不把任何重排 / 结构信号接进放行（`seed_admit`）：只出候选（设计稿 §4.3）。
- 不用整理本正字的 IDS 当异体字标签（标签一律 shape）。
- 不在评测集上调 K / 权重再报同一集的数（先建集再动手）。
