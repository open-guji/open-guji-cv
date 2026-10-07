# Open Guji CV - 项目说明

## 语言
- 默认使用中文进行交流

## 项目概述
古籍刻本图像 → 逐字转写的引擎：切分（Step1–4）、识别与定字（Step5–7）、人裁回流（Step8）、导出（Step9）。
数据集与评测在隔壁仓 `open-guji-dataset`；各书的数据（原图、产物、人裁、字形库）在 `guji-workspace`。

## 先看哪份
文档都在仓根 `doc/`（2026-10-06 起；原 `.claude/doc/` 已并入，旧路径对照见 `.claude/doc/README.md`）。

| 要做什么 | 读 |
|---|---|
| **整理一册书（从开工到交付）** | **[doc/runbook/整理一册书.md](../doc/runbook/整理一册书.md)** |
| 用控制台、`guji` 命令 | [doc/console_manual.md](../doc/console_manual.md) |
| 开新书、找数据在哪 | [doc/workspace_layout.md](../doc/workspace_layout.md) |
| 改算法之前 | [doc/pipeline_handbook.md](../doc/pipeline_handbook.md)（踩坑、量法、负结果）、[doc/segmentation_v2_pipeline.md](../doc/segmentation_v2_pipeline.md)（切分四步） |
| 各步的设计与失败案例 | [doc/design/](../doc/design/) |
| 调研、文献、基准、负结果 | [doc/research/](../doc/research/) |
| 格式（guji-page、guji-format、pages.json） | [doc/formats/](../doc/formats/) |
| 开关开不开（A/B 实验、开关登记）| [doc/exp_framework.md](../doc/exp_framework.md)、[doc/开关登记表.md](../doc/开关登记表.md) |
| 产物指纹、过期、跨册新鲜度 | skill `cv-pipeline-ops` |
| 已退役与过期的文档 | [doc/archive/](../doc/archive/)（含旧 CLAUDE.md 的长索引原文） |

## 怎么干活
- **前台用控制台，后台用 `guji` 命令**：`pipeline` / `step` / `status` / `close-check` / `recheck` / `cache` / `collate` / `gold` / `eval` …
  别直接调 `scripts/` 下的散脚本做书的整理，runbook 里点名的除外。
- 当前只优化**正文页**；目录、职名、序跋、牌记先不管，指标按正文与非正文分开报。
- 旧的 v1 命令（`python -m open_guji_cv run/extract/preprocess`）已退役，不要在上面加东西。

## 改代码的规矩
- **产物指纹**：Step 模块和它的 `code_deps` 一改，各书产物就判过期。动这些文件前想清楚是否值得让各书重算。
- **测试只依赖本仓库、只依赖 `tests/` 下冻结的数据**；单元测试自己造数据（`tests/helpers.py`），对真书数据的质量断言归评测（`guji eval run`），不进测试。细则见 `tests/conftest.py` 模块头、`tests/fixtures/README.md`；`tests/test_suite_hygiene.py` 是守卫。
- 跑全量：`.venv/Scripts/python -m pytest tests/ -s -p no:cacheprovider`（`-s` 必须带；Windows 下要结果就加 `--junitxml=…` 再解析）。
- 装了 torch 才跑的约 7 条，装了 `rapidocr-onnxruntime` 才跑的 3 条，缺件是跳过不是失败。

## 环境
- Python 3.12，用 uv 建 `.venv`：`uv venv .venv --python 3.12 && uv pip install -e ".[console,torch,dev]"`。仓里旧的 `venv/` 是死的。
- **装完自检** `python -c "import torch, scipy, cv2"`：缺件不报错，只会悄悄降级。
- 环境变量：`PYTHONIOENCODING=utf-8`（Windows 必设）、`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`、`GUJI_WORKSPACE=<书的工作区>`。
- 带 book 的命令都要 `-w <工作区>`。
- 产物在 `<工作区>/products/<book>/<step>/p0024.json`，列图和字块在 `cache/`，任务记录在 `runs/`。

## 字形库
- 一本书的字形真源在**工作区** `output/glyph_store/`（加 `feedback/events/`），SQLite 索引 `output/glyph.db` 可重建：
  `guji-cv glyph-db rebuild -w <工作区>`。
- 本仓 `output/glyph_store/` 是测试用的样本库；根目录早期遗留的跨书 `glyph_store/` 已于 2026-10-06 删除（可从分支 archive/pre-cleanup-2026-10-06 找回）；字体字形不进 git，由 `fonts/` 确定性重建（见 `fonts/README.md`）。

## 云服务器（2026-09-30 起搁置）
- 内存额度、systemd 托管控制台等旧说明见 `doc/snap_autoimport.md` 与 overview `机器清单.md`。整理一本书一律在本地做。
