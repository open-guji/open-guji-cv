# 云端跑评测（`guji eval run`）

2026-09-30 E 道实测整理。目标：在没有本机工作区、没有 GPU 的云端容器里，把尽可能多的评测跑起来。

## 1. 环境

```bash
uv venv .venv --python 3.12
uv pip install -e '.[console,torch,dev]'
uv pip install scipy opencc-python-reimplemented   # 缺口：scipy 没进任何 extra（CLAUDE.md 本机步骤里有，pyproject 里没有）
.venv/bin/python -c "import torch, scipy, cv2, httpx"
```

三个仓按**同级**摆（评测里大量 `../open-guji-dataset/...` 相对路径按 cwd=引擎仓解析）：

```
/home/user/open-guji-cv            # 引擎仓，cwd 必须在这
/home/user/open-guji-dataset       # 测试集仓（可软链；GIT_LFS_SKIP_SMUDGE=1 浅克隆，LFS 只有指针）
/home/user/guji-workspace          # 工作区仓（浅克隆，约 35k 文件）
```

## 2. 环境变量

```bash
export GUJI_WORKSPACE=<overlay 或 guji-workspace/96mid1ogzk-…四庫總目>   # 册定义 books/ 与原图 data_full/ 都从这里找
export GUJI_PRODUCTS_DIR=<沙箱目录>          # --from-raw 现跑的产物写这里，绝不写工作区正式 products
export PYTHONIOENCODING=utf-8 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

### 金标里有两本书：用 overlay 工作区

`page` 类金标锚点既有四庫 `vol01/vol02`，也有北行日錄 `bxgb`（在另一个工作区 `988g7gsqhd-…`）。
`load_book` 只认一个 `GUJI_WORKSPACE/books/`，所以 bxgb 相关评测（column_warp / instance_quality /
recrop / touching_cuts）会报「没有这册书的定义」。不改代码的做法——建一个**只含软链**的 overlay：

```bash
G=/home/user/guji-workspace
A="$G/96mid1ogzk-欽定四庫全書總目武英殿刻本"; B="$G/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"
O=/tmp/ws_overlay; mkdir -p $O/books $O/data_full
for f in $A/books/*.yaml; do ln -s "$f" $O/books/; done; ln -s $B/books/bxgb.yaml $O/books/
ln -s $A/data_full/zongmu $O/data_full/zongmu; ln -s $B/data_full/bxgb_scan $O/data_full/bxgb_scan
for d in config corpus workspace.yaml; do ln -s "$A/$d" $O/$d; done
export GUJI_WORKSPACE=$O
```

## 3. 命令

```bash
python -m open_guji_cv eval list                       # 每个评测能不能跑、为什么不能
python -m open_guji_cv eval --from-raw --timeout 3000 run [评测id ...]   # 缺产物就从原图现跑 Step1-3
```

⚠ **选项必须放在 `run` 之前**（`eval --from-raw run x`），放后面 argparse 报 unrecognized arguments。
不给 id = 跑全部「轻量」的。`--from-raw` 只补金标页缺的产物，已有的不重跑。

## 4. 耗时（4 核，无 GPU）

- `--from-raw` 补 vol01/vol02 金标页：每页 Step1→Step3 约 1–4 s；四庫+北行合计约 500 页，约 20 分钟。
- `bottom_offset_oneside` 单个 ≈ 215 s，`bottom_offset_gold` ≈ 32 s；其余评测本身 < 2 s，时间全在补产物。
- 整批 `eval run --from-raw` 首次约 25 分钟，之后产物在沙箱里，几分钟。

## 5. 坑（本次修掉的 + 仍在的）

| 现象 | 原因 | 处理 |
|---|---|---|
| 某个评测引用本工作区没有的册 → 整批 `eval run` 抛 FileNotFoundError 崩掉 | `_bootstrap_missing` 不捕异常 | 已修：只让这一个评测 failed 并写原因（`eval/runner.py`） |
| `unsupported_layout` 读 `D:\workspace\open-guji-dataset\…` | 金标路径写死 Windows 绝对路径 | 已修：默认 `../open-guji-dataset/page-type/expected.json`，加 `--gold` |
| seam / truncation / page_crop / char_drop / jiazhu_tail / left_cut / right_cut / side_rule / text_band / geometry 在云端「✓ 0%」「回归门通过」或报 ZeroDivision/KeyError | 这 10 个脚本默认读 **v1 链产物** `./output/<册>/phase3_char_grid`（退役链，云端没有），没有就静默扫到 0 页 → **假通过 / 假回归**（text_band 「回归门失败：字格 47431→0」就是假的） | 已修：注册表加前提 `v1_output`，不满足时标 skipped 并写原因，不再执行 |
| `column_warp` 报「读不到列图 output/vol01/step2_columns/…」 | 评测读 `scripts/regen_step2_columns.py` 预先导出的列图 | 未接入 `--from-raw`；需先 `regen_step2_columns.py <册> --gold-pages` |
| `frame_strip` 「parse_metrics 解析到 0 条指标」 | 脚本真实输出「0 个样本（65 个格位已消失）」——金标格位已全部过期，是**空跑**，不是解析器坏了 | 金标需要重标；评测层不改 |
| `pagetype` n=0、`truncation` n=0 | 同属空跑（前者缺产物口径、后者 v1） | 见上 |
| `touching_cuts` parse_metrics 0 条 | 需补 bxgb 产物后再看，见基线表 | — |
| `scipy` 缺 | 没进 extras | 手装 |

## 6. 云端确实跑不了的

- 需要 OCR 引擎 / GPU：`char_ocr`、`font_fallback`、`struct_heads`、`struct_rerank`
- 重活且依赖本地字形库/模型：`clustering`、`db_match`、`match_pairs`、`match_triplets`、`degradation`、`oov`、`zero_shot*`、`seen_test_single_proto`、`guard_ceiling`
- 需要语料：`confusable_lm`、`context_correction`、`align_replace_gate`
- 需要 s1~s6 中间产物：`crop_margin`
