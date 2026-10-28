# Open Guji CV - 项目说明

## 语言
- 默认使用中文进行交流

## 项目概述
古籍刻本图像 → 逐字转写的引擎：切分（Step1–4）、识别与定字（Step5–7）、人裁回流（Step8）、导出（Step9）。
数据集与评测在隔壁仓 `open-guji-dataset`；原图在 `guji-workspace`（git，2026-10-19 起只存原图）；册配置、人裁、台账、字形库在**中心库**（`guji db sync`，见 `doc/datastore.md` 第六节）；产物在各机本地。

## 先看哪份
文档都在仓根 `doc/`（2026-10-06 起；原 `.claude/doc/` 已并入，旧路径对照见 `.claude/doc/README.md`）。

| 要做什么 | 读 |
|---|---|
| **整理一册书（从开工到交付）** | **[doc/runbook/整理一册书.md](../doc/runbook/整理一册书.md)** |
| 用控制台、`guji` 命令 | [doc/console_manual.md](../doc/console_manual.md) |
| 开新书、找数据在哪 | [doc/workspace_layout.md](../doc/workspace_layout.md) |
| 看包分层、谁能依赖谁、改动前要注意什么 | [doc/module_map.md](../doc/module_map.md)（守卫：`tests/test_architecture.py`） |
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
- **分支**（2026-10-20 起，`doc/版本号规矩.md` 第三节）：PR 一律投 **`dev`**；发版时从 dev 切 `rc/vX.Y.Z` 测试，rc 只收本版修复（修复合回 dev），测完 rc 用 merge commit 合进 main，**在 main 的合并提交上打 `vX.Y.Z` 才算发完**，打完跑 `python scripts/check_release_tags.py` 核对。main 不直接收 PR。合之前跑 `python scripts/check_rc_target.py <目标分支>`。
- **产物指纹**：Step 模块和它的 `code_deps` 一改，各书产物就判过期。动这些文件前想清楚是否值得让各书重算。
  纯提速、产物逐字节不变的改动，用 `scripts/code_equiv.py check` 证明后登记进 `core/code_equiv.py`，不让各书过期（见该模块头）。
- **测试只依赖本仓库、只依赖 `tests/` 下冻结的数据**；单元测试自己造数据（`tests/helpers.py`），对真书数据的质量断言归评测（`guji eval run`），不进测试。细则见 `tests/conftest.py` 模块头、`tests/fixtures/README.md`；`tests/test_suite_hygiene.py` 是守卫。
- 跑全量：`.venv/Scripts/python -m pytest tests/ -s -p no:cacheprovider -n auto`（`-s` 必须带；`-n auto` 用 pytest-xdist 按核数并行，随 `[dev]` 装；Windows 下要结果就加 `--junitxml=…` 再解析）。2026-10-25 实测（装 torch、4 核）：原先串行 11 分钟，Step1–4 复用后串行 6 分钟，并行 2 分 23 秒。单跑几个文件不用 `-n`，起 worker 反而慢。
- 新测试要能并行：不往模块级 `os.environ` 写东西不还原、不写进程外的共享路径；要从原图跑 Step1–4 用 `helpers.run_keben_from_raw`（同进程同输入只真跑一次）。
- 装了 torch 才跑的约 7 条，装了 `rapidocr-onnxruntime` 才跑的 3 条，缺件是跳过不是失败。

## 环境
- Python 3.12，用 uv 建 `.venv`：`uv venv .venv --python 3.12 && uv pip install -e ".[torch,dev]"`；要控制台再装 `uv pip install -e ../guji-console`（2026-10-28 拆成独立包，`guji console` 由它提供）。仓里旧的 `venv/` 是死的。
- **装完自检** `python -c "import torch, scipy, cv2"`：缺件不报错，只会悄悄降级。`guji pipeline`／`step` 起跑前会查这次要跑的步骤缺不缺 torch／权重／joblib，缺了拒跑（`--allow-missing-deps` 放行）。
- 环境变量：`PYTHONIOENCODING=utf-8`（Windows 必设）、`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`、`GUJI_WORKSPACE=<书的工作区>`。
- 带 book 的命令都要 `-w <工作区>`。
- 产物在 `<工作区>/products/<book>/<step>/p0024.json`，列图和字块在 `cache/`，任务记录在 `runs/`。

## 字形库
- 一本书的字形真源在**中心库**，本机副本在数据目录 `$GUJI_DATA_HOME/<分支>/<工作区 id>/output/glyph_store/`（加 `feedback/events/`）；
  工作区里只留 `workspace.yaml` 和标记 `.central.json`。开工 `guji db sync -w <工作区>`（没迁的先 `guji db migrate`），
  审完再 `guji db sync`。SQLite 索引 `output/glyph.db` 在工作区，拉到新字形库时自动重建。
- 本仓 `output/glyph_store/` 是测试用的样本库；根目录早期遗留的跨书 `glyph_store/` 已于 2026-10-06 删除（可从分支 archive/pre-cleanup-2026-10-06 找回）；字体字形不进 git，由 `fonts/` 确定性重建（见 `fonts/README.md`）。

## 云服务器（2026-09-30 起搁置）
- 内存额度、systemd 托管控制台等旧说明见 `doc/snap_autoimport.md` 与 overview `机器清单.md`。整理一本书一律在本地做。
