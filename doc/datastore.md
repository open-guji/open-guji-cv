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

**只通 443 的环境（云会话）**：5432 出不去，先起本地桥，经 Neon 的 WebSocket（443）连库，导入、核对代码不变：

```bash
python -m open_guji_cv.datastore.wsbridge <Neon 端点 host> --port 15432 &
export GUJI_DATA_PG_DSN="host=127.0.0.1 port=15432 dbname=neondb user=<角色> password=<口令> sslmode=disable options=endpoint=<端点 id>"
```

本地端口用 `sslmode=disable`（加密在 wss 那层），不要 `channel_binding`。服务器能直连 5432，用不着桥。

- `import --dry-run` 只算差别不写库；`--ws <id>` 只导一个工作区。
- `verify` 退出码 0 = 库与提交逐行一致。
- `r2-plan` 默认只出清单；设了 `GUJI_DATA_PG_DSN` 会顺便和库里的 sha 对一遍。
  真上传加 `--execute`：默认走 R2 S3 接口，要 `R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`；
  `--via worker` 经 guji-data Worker（`/v1/assets/sign` 拿链接再 PUT），要 `GUJI_DATA_TOKEN`，
  `--bucket exp|main`，每张图两次 Worker 请求（免费档每天 10 万次），用 `--limit` 分批。

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

## 四、Neon ci 试灌（2026-10-18，云会话经 wsbridge，guji-workspace main `7a05390`）

| 项 | 结果 |
|---|---|
| 首次导入 | 3 个工作区 188,404 行进库，import_id 1，rev 0 → 1,327，约 59 秒 |
| 核对 `verify` | 0 差异（同本地口径：逐行、逐文件、逐图 sha） |
| 同一提交 `import --dry-run` | 0 变更 |
| 库大小 | 161 MB（`pg_database_size`，未 VACUUM FULL） |
| R2 计划对库 | 30,480 个对象 90.7 MB，与库里 sha 集合完全相同 |

## 五、客户端 `guji db`（GUJI-606，工作包 8.5）

会话、本机用的命令，全部经 guji-data Worker（只通 443 也能用），不要连接串：

```bash
export GUJI_DATA_TOKEN=<读令牌>          # 环境变量里的 GUJI_DATA_TOKEN_READ；不进仓、不打印
guji db status -w <工作区>               # 分支、rev、令牌角色、本地快照落后几条
guji db pull   -w <工作区>               # 还原字形库并重建 glyph.db
guji db pull   -w <工作区> --rev 1346    # 钉版本（该工作区 1346 之后没变才放行）
guji db branch list
guji db branch create exp/GUJI-606-try --from-rev 1346   # 要实验令牌
guji db import --from exp/GUJI-606-try -w <工作区> --dry-run   # 实验结论导入正式库（写入切换后）
```

- `GUJI_DATA_URL` 缺省 `https://data.open-guji.com`；`GUJI_DATA_BRANCH` 或 `--branch` 选分支，缺省 `main`。
- **pull 怎么做**：按 `source_files` 把 `output/glyph_store/` 下每个文件从库里拼回（口径同 `verify`），
  每个文件核整文件 sha256，有一个不对就整次报错、不落盘；刻例图按 `glyph_instances.patch_sha`
  从本地缓存取，缺的经 `/v1/assets/sign-batch` 一次签 1000 张再下载（旧版 Worker 退回逐张签）。
  还原到 `<工作区>/output/central/<分支>/output/glyph_store/`，再走与 `guji glyph-db rebuild --no-replay --no-borrow`
  相同的 `rebuild_from_store`。工作区里 git 管着的 `output/glyph_store/` 不动。
- 读的过程中该工作区有新写入就重读（最多 3 次），保证拿到的是同一个版本。
- `glyph.db.central.json`（库旁）记分支、rev、拉取时间，`status` 用它算落后几条。
- 图缓存：`GUJI_DATA_CACHE`，缺省 `~/.cache/guji-data`，按 sha 存、取回时核 sha，同一张图只下一次。
- 借库（`workspace.yaml` 的 `glyph_lib.borrow`）暂不支持，配了就报错，照旧用 `glyph-db rebuild`。
- 直连 Postgres 的 `PgSource`（服务器、测试用）能读表，拿不到 R2 的图，要配合预先填好的缓存。

验收（`tests/datastore/test_datastore_pull.py`）：真字形库（admit → export）进 git → 导入 Postgres →
`pull`：还原的每个文件与提交逐字节相同；重建的 glyph.db 与直接从 git 的字形库 rebuild 出的库**全部表逐行相同**；
`--rev` 钉版本、篡改库内容被拒、实验分支事件导入、假 Worker 上的分页与批量签名。17 步 `code_hash` 不变。

**在线实测（2026-10-18，云会话，读令牌，main 分支 rev 1346）**：北行日錄（beixing-guben）`guji db pull`
还原 13 个文件、4,851 张刻例图（实验桶，Worker 尚未部署批量签名，逐张签，9,719 次 Worker 请求，约 17 分钟）；
还原的字形库与 guji-workspace `888cd82` 的 `output/glyph_store/` 逐字节相同（`diff -r` 无差别），
重建的 glyph.db 与从 git 字形库 rebuild 的库 14 张表逐行相同。

## 六、写入切换后（GUJI-608，2026-10-19 起）：中心库是唯一的家

guji-workspace 的 git **不再存数据**（人裁、台账、批次、人工配置、字形库、册 yaml）；最后一次从 git 灌进中心库的是
guji-workspace `6bef1ada`（main 分支 rev 1356，`verify` 0 差异）。原图、products、cache、glyph.db 不在中心库，照旧在工作区。

**布局**：工作区根只留 `workspace.yaml`（身份，库里也有一份）和标记 `.central.json`（`{ws, branch}`）。
数据在工作区外的**数据目录** `$GUJI_DATA_HOME/<分支>/<工作区 id>/`（缺省 `~/.guji-data`），布局同旧工作区。
`core/workspace.py` 见到标记就把 `feedback_root`、`verdicts_root`、`batches_root`、`exclusions_path`、
`glyph_store_path`、`books_dir`、`ws_config_dir` 指向数据目录；没有标记照旧（测试、没迁的工作区）。

```bash
export GUJI_DATA_TOKEN=<正式令牌>             # GUJI_DATA_TOKEN_PROD；只读的话读令牌就够
guji db migrate -w <工作区> --dry-run         # 一次性：先看工作区里的数据与库是否一致
guji db migrate -w <工作区>                   # 数据挪进数据目录、工作区里删掉、写标记；glyph.db 不动
guji db pull    -w <工作区>                   # 中心库 → 数据目录；拉到新字形库才重建 glyph.db
#   …照常跑 cv（控制台、step、H 道）…
guji db push    -w <工作区> [--dry-run]       # 数据目录 → 中心库（guji store commit 在迁过的工作区上也走这里）
guji db status  -w <工作区>                   # 落后几条、哪些文件没推
```

- **范围**：`books/`、`feedback/`、`review/`、`config/`、`output/glyph_store/` 下 `scope.classify` 认的文件，加 `workspace.yaml`，
  与导入器同一口径。
- **migrate**：工作区里的文件与库不一致就停下列出来（多半是检出旧了）；确认本地的才对加 `--keep-local`，
  数据目录先按库还原，再用这些文件盖上去，成为待推改动。glyph.db 不重建（库指纹会变、产物会判过期）。
- **基准**：数据目录的 `.central-state.json` 记拉取／推送时的 rev、每个文件的 sha、glyph.db 指纹。
  「本地改动」对的是基准，不连网；glyph.db 指纹变了（人裁消费者改了库）就先导出成字形库账本再比。
- **pull**：先在旁边拼好、逐文件核 sha，再换进数据目录（镜像；没被引用的刻例图留着）。本地有没推的改动就拒绝，`--force` 丢掉。
- **push 先比版本号**：拿到库锁（`LOCK TABLE changes`）后查该工作区在基准 rev 之后有没有别人写过
  （导入、push、Worker `/v1/events` 都算），有就整次拒绝（`StaleBase`），先 pull——同 git 的 non-fast-forward。
  只追加的台账（events、consumed、anchors）少了行拒绝；库里有的整个文件本地没了也拒绝，确认是真删加 `--allow-delete`。
  写库用导入器同一套差分（`import_scans`，`imports.source = 'push'`），`changes` 逐行留痕。新图先经 Worker 传正式桶。
- **连库**：push 直连 Postgres。有 `GUJI_DATA_PG_DSN` 就用；没有就读 `NEON_DATABASE_URL`，在本进程起 WebSocket 桥（云会话只通 443）。
- `push` 只写 `main`；实验照旧用 `guji exp` 和实验分支。
- close-check 第 8 项在迁过的工作区上查「数据目录有没有没推的改动」，不再查 git。

验收（`tests/datastore/test_datastore_workcopy.py`，本地 Postgres）：migrate 后工作区里只剩 workspace.yaml、标记、
glyph.db（逐字节不变）和产物，数据目录与提交逐字节相同，路径函数指向数据目录；不一致时 migrate 拒绝、`--keep-local`
后成为待推改动并推成功；两台机器之间 pull／push、旧版本被拒、`--force` 重拉、删文件与台账少行被拒、库里删了本地也删；
新机器 pull 重建的 glyph.db 与从 git 字形库 rebuild 的全部表逐行相同；glyph.db 改了 push 前先导出。
守卫 `tests/test_central_paths.py`：包内不许从工作区根直接拼这些目录。

**在线实测（2026-10-19，云会话，main rev 1356）**：qtw-draft 从空目录还原 33 个文件、6,506 张刻例图
（6,538 次 Worker 请求，约 7 分钟，重建 glyph.db 6,506 个实例）；随即试推（自动经 443 桥连 Neon main）全部表 0 变更。

## 七、备份与恢复（GUJI-611）

每日例行任务（云端定时会话）跑 `python -m open_guji_cv.datastore backup`：同一快照里导出全部表（`COPY` 文本格式、gzip），
附 `manifest.json`（每表列、行数、逐行排序后的 sha256、序列值、rev），经 Worker `PUT /v1/backups/<日期>/<文件>`
存进正式桶 `backup/<日期>/`，清单最后传（有清单才算完整），清掉 30 天前的。每周日再跑
`restore-check --endpoint <ci 分支端点>`：取最新完整备份，删表、按 `schema.sql` 重建、`COPY` 回去、设序列，
按同样口径重算逐表对。恢复只许打到 main 以外的端点。

要从备份救 main：先在 Neon 开一个新分支，`restore-check --endpoint <新分支端点> --date <日期>` 恢复并核对，
确认后在 Neon 控制台把它设为主分支（或把 main 重置到它）。这一步要用户点头。

**首次演练（2026-10-19，rev 1356）**：26 张表 189,964 行，备份 27 个文件 12 MB，31 秒；恢复到 ci 分支 39 秒，逐表行数与哈希全部一致。
