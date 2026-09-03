# open-guji-cv 近期任务

> 来源：overview 项目下发（2026-09-03 更新）。此前 2026-02 下发的「Volume 1 / Volume 2」任务
> 已完成或挂起，归档在文末。
> **算法层**的待办仍以 `.claude/doc/pipeline_handbook.md` §3 与 `segmentation_v2_pipeline.md`
> 「下一步」为准；本文件只放 overview 下发的**架构层**任务。

## 🎯 架构：控制台 + 四个抽象

设计全文：[doc/console_architecture.md](doc/console_architecture.md)。
四个抽象 Step / Product / Gold / Event，上面架一个本地控制台。按 P0 → P4 推进，
每阶段单独可交付，旧 CLI 始终可用。

两条硬约束（用户 2026-09-03）：
- **只建模 v2 链**（Step1 边框 → Step2 单列矫正 → 交接闸 → Step3 切格 → Step4 字框收缩 → 下游）。
  v1 的 s1..s6 / phase2 / phase3 不包壳、不注册；phase2..phase9 产物目录 P3 时清掉。
- **数值长期、图像即算**（设计 §3.8）：Step1 只存线，Step2 只存 warp 参数 / 文字带 / border_class，
  Step3 只存字格，Step4 只存紧框 + flags；列图、字块、归一图块一律走 `ctx.materialize` 的本地缓存
  （LRU、有上限），缺了现算。长期存图的只有原始扫描和人裁过的图（金标 assets、GlyphDB 范例）。

### P0 骨架 —— ✅ 已落地（2026-09-03，分支 `feat/console-p0` 提交 `d63d1b4`；记录见设计 §8.1）

- [x] `core/`：spec.py、step.py、book.py、pipeline.py、engine.py（指纹、stale 沿 DAG 下传）、anchor.py
- [x] `products/`：store / manifest / cache（LRU 20 GB）/ kinds（borders、column_windows、gate_manifest、cells、char_index + 三种缓存图）
- [x] `steps/`：五个薄适配 + `_warpmap.py`（列图 → 原图逆映射，含三段折线）
- [x] `pipelines/keben_body_v2.yaml`；`books/vol01.yaml`、`vol02.yaml`（各 12 页 dev_set）
- [x] `console/`：FastAPI + 无构建前端（总览矩阵 / 运行 + SSE 日志 / 产物叠图）；`guji-cv console`
- [x] CLI：`guji-cv pipeline | step | status | cache`，`guji` 独立入口；旧命令原样
- [x] 验收：vol01 第 24 页全链 2.4 s；dev_set 12 页 35.6 s；第二遍全跳过；改参数只下游过期；
      产物目录只有 JSON，列图 / 字块在 `cache/`；`tests/test_core_v2.py` 9 条全过
- [ ] P0 尾巴：包 `page_type_gate` / `grid_prior`；`when` 求值；Step4 直接喂半宽夹注框（现在合成满宽格再拆一次）
- 环境：`venv/` 已死（Store Python 3.13 被卸），用 `uv venv .venv --python 3.12` +
  `uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented`
- 算法层待办（P0 跑出来的）：vol01/119 页级周期估成 70 → 9 列 DP 无解；vol01/60 c8 DP 无解；vol01/42 被 L1 列宽拦下（已知）

### P1 反馈 —— ✅ 已落地（2026-09-03，提交 `6130449`；记录见设计 §8.2）

- [x] `feedback/`：events（信封 + 只追加日志 + 幂等记账）、harvest（四种旧格式）、
      routes（kind × step → 消费者）、consumers（gold_add 已实现）
- [x] `gold/`：统一金标信封 + 分片仓（upsert / retire / mark_stale / summary）
- [x] `review/batches.py` 批次登记（含「发布前必须先收割」的闸）+ `review/shell.py` 双传输
- [x] 控制台审查视图 + 7 个 API；CLI `batch` / `events` / `gold`
- [x] 验收：真实 column-split 60 条裁决走完 收割 → 路由 → 金标，分布 ok 56 / extra 2 / miss 2
      与分片 README 一致；重复收割与重复消费不产生副本。19 条测试全过，全量 627 条零失败
- **修掉三处格式对齐 bug**（各有回归测试）：GUJI-SEG-REVIEW 前缀在 `t` 字段里且 `t` 非时间戳；
  marks 值是 `{"s":N}` 且 2/3 语义反了；续裁要 `{id:{"v","t"}}` 不能传扁平串
  （`build_border_gold_reviews.py --verdicts` 至今仍有这个 bug，迁它时一并修）
- [ ] P1 尾巴：`glyphdb_admit` / `glyphdb_recrop` 两个消费者（现在照旧走 `seed-ingest`）；
      把「界行切分裁决台」真改成 server 模式跑一轮真人裁；`column-split` 分片补 metadata.json

### P2 金标 → P3 增量与存储 → P4 扩展

见 doc/console_architecture.md §8 的表。要点：P3 用 `guji pin` 把数值产物钉进 git 的 `pins/`
后再把 `output/`、`data_full/` 移出 git 并清 v1 目录；P4 切到 v2 Step4 时 GlyphDB / seed 队列的
`instance_id` 要按内容一次性重键到 v2 口径（右上、从 1）。

### 已裁定（用户 2026-09-03，见设计 §9）

- 快照仓：**本地**（仓库外目录，`GUJI_SNAPSHOT_DIR`），只给自己和少数开发者看，存免费的地方；
  `github_release` 只作可选免费镜像，不引入付费桶。
- git 历史：**稳定后重写**（P3 落地、分支收敛后跑 filter-repo）。
- 控制台：**先跑本机**（Windows 开发机），iPad 走 Tailscale。
- 数据集仓：**不合并**，独立存在，GoldStore 走 `../open-guji-dataset`。
- 锚点规范坐标：**右上角原点** `raw_page_px@top-right`（古籍从 top-right 起）；v1 左上原点只作遗留声明；
  `core/anchor.py` 负责与 cv2 互转。

### 与 overview 的约定

- 每阶段完成后更新本文件与 overview `项目进展/图片初步数字化/todo.md`。

---

## 历史（2026-02 下发，已归档）

- Volume 1（ce01）OCR pipeline 与夹注检测：已完成。
- Volume 2：已处理，等 guji-platform merge。
- Volumes 2–10（06064238.cn ~ 06064246.cn）：挂起。
