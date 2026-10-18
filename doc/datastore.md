# 中心库：表结构、导入、核对、R2 上传

> GUJI-603（工作包 8.2）与 GUJI-605（8.4）。设计见 ai-team `通用/中心库设计.md`。
> 代码在 `open_guji_cv/datastore/`，不进任何 Step 的 `code_deps`，改它不会让产物过期。

## 一、怎么用

装依赖：`uv pip install -e ".[datastore]"`（psycopg；boto3 只有真上传 R2 才用）。

连库只认环境变量 `GUJI_DATA_PG_DSN`（或 `--dsn`）。连接串含口令，**不进仓、不进 Jira、不进聊天**。
Neon 的 ci、main 两个分支各有一个连接串，先灌 ci、核对通过再灌 main。

```bash
# 钉住 guji-workspace 的一个提交，读的是提交里的 blob，与工作树、稀疏检出无关
python -m open_guji_cv.datastore import  --repo <guji-workspace> --commit <sha> --actor <谁>
python -m open_guji_cv.datastore verify  --repo <guji-workspace> --commit <sha> --quiet
python -m open_guji_cv.datastore r2-plan --repo <guji-workspace> --commit <sha> --manifest plan.jsonl
```

- `import --dry-run` 只算差别不写库；`--ws <id>` 只导一个工作区。
- `verify` 退出码 0 = 库与提交逐行一致。
- `r2-plan` 默认只出清单；设了 `GUJI_DATA_PG_DSN` 会顺便和库里的 sha 对一遍。
  真上传加 `--execute`，要 `R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`。

## 二、口径

**进库的文件**（每个工作区，即仓根下含 `workspace.yaml` 的目录）：

| 文件 | 表 | 主键（另加 ws） |
|---|---|---|
| `workspace.yaml` | `workspaces` | — |
| `books/*.yaml` | `books` | book |
| `feedback/events/*.jsonl`、`feedback/vision/*.jsonl` | `events` | src_path, id |
| `feedback/consumed/*.jsonl` | `consumed` | consumer, 行号 |
| `feedback/anchors/*.jsonl` | `anchors` | src_path, event, key |
| `feedback/anchor_patches/**.png` | `anchor_patches_meta`（只存 sha） | src_path |
| `feedback/verdicts/**/*.jsonl` | `verdicts` | src_path, id |
| `feedback/lists/**`、`review/batches/**`、`config/**`、`feedback/*.jsonl`、`feedback/candidates/*` | `files`（整文件；视图 `lists`、`batches`） | src_path |
| `output/glyph_store/*.jsonl`、`instances/*.jsonl`、`events/*.jsonl` | `glyph_*`、`glyphs` | 照 `clustering/glyph_db.py` |
| `output/glyph_store/patches/*.png` | `glyph_instances.patch_sha` | — |

不进库：`*.bak*`、`_backup_*`、`consumed_bak_*` 这类备份，`data_full/`、`output/` 其余产物、
`reports/`、`corpus/`。导入报告的 `skipped` 按目录列出跳过了什么。

**每行都带来源**：`src_path`、`src_line`、`raw`（原文）、`rev`。`source_files` 记每个文件的
sha256、行数、末尾换行，空文件也在。核对就是从库里把文件拼回来，和提交里的 blob 比哈希。

**幂等**：按主键比内容哈希（`raw`；刻例实例再加图的 sha），只写有差别的行，每写一行在
`changes` 记一条并分配全局递增的 `rev`。一张表首次灌入（≥1000 行、库里原本没有）整批只记一条、共用一个 rev。同一提交重跑 0 写入、rev 不动。行号变了但内容没变
（字形库导出重排）只改 `src_line`，不算变更。全部在一个事务里。

**删除护栏**：提交里没了的行，库里也删（镜像）。但 `events`、`consumed`、`anchors` 是只追加的
台账，发现要删行就整次拒绝，除非 `--allow-delete`——防止拿旧提交把新人裁冲掉。

**R2**：键 `sha256/<前两位>/<sha>.png`，只收被实例引用的刻例图和全部锚图，跨工作区去重。
上传先 HEAD，已有就跳过；PUT 带 Content-MD5，传完核 ETag。

## 三、首次实测（2026-10-18，本地 Postgres 16，guji-workspace main `7a05390`）

| 项 | 数 |
|---|---|
| 工作区 / 册 | 3 / 16 |
| 进库文件 | 441 个文本文件 ＋ 1,862 张锚图 ＋ 29,837 张刻例图 |
| 行 | events 27,732；consumed 52,034；anchors 4,891；verdicts 5,494；glyph_instances 29,837；glyph_exemplars 29,754；glyph_admissions 29,837；glyphs 6,140 |
| 首次导入 | 约 20 秒；首导按表整批记变更，changes 1,327 行，rev 0 → 1,327 |
| 同一提交重跑 | 0 写入，约 12 秒 |
| 核对 | 185,904 行逐行哈希、441 个文件整文件哈希、31,699 张图 sha，0 差异 |
| 库大小 | 约 151 MB（VACUUM FULL 后）。Neon 免费档每项目 1 GB（调研线程核实），放得下 |
| R2 计划 | 31,699 个文件 → 去重后 30,480 个对象，90.7 MB |

增量：从 `8b07012` 起逐个导入到 `7a05390` 共 6 个提交，每步核对都是 0 差异；
最后一步（10-17 亲裁 曰→師、別→所）落成 2 行实例更新、2 例刻例替换。
拿旧提交回灌被删除护栏拦下（events 少 7 行）。

**数据问题（导入照收，等人定）**：四庫 `feedback/events/vol01-cutline.jsonl` 与
`vol01-cutline-split_char.jsonl` 里有 14 个事件 id 相同、内容不同（`evt_vol01-cutline-split_char_000001…`）。
库里两份都留（主键带 src_path）。`consumed/glyphdb_admit.jsonl` 等有 178 处同一事件记了两次（99 处整行重复），按行号都留。
