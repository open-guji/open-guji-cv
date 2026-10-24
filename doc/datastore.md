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
- **取图不经 Worker（2026-10-19 起）**：正式桶挂了公开域名 `https://blob.open-guji.com/sha256/<2>/<sha>.<ext>`
  （按 sha 寻址、不能列目录、走 CDN 缓存；sheldon 定「按哈希公开」）。Worker 签下载时直接回这个地址，客户端不用改，
  旧版也一样。Worker 请求只剩查表和签名（每批 250 张一次）：从空目录整库拉殿本 173 次、全唐文 68 次、北行 59 次
  （原先每张图一次，殿本约 1.85 万次）。实验桶仍经 `/v1/blob`。上传照旧经 Worker（核 sha、不覆盖）。
  用量日报见 guji-workspace-data 仓 `scripts/usage_report.py`。
- **借库（2026-10-19 起，共享方案 S4）**：迁过的工作区在 `workspace.yaml` 的 `glyph_lib.borrow` 里写**被借工作区的名字**
  （如 `borrow: [siku-zongmu]`，以后的共享刻例库写 `glyphlib-qkp-v1`）。`db pull`／`db sync` 顺带把那个工作区的
  `output/glyph_store/` 拉到只读副本 `$GUJI_DATA_HOME/<分支>/.borrowed/<工作区>/`（与它自己的数据目录分开，本机同时在整理它也不互相盖），
  带上它重建 glyph.db；副本旁 `.borrowed-state.json` 记拉到的 rev，被借工作区没新写入就不重拉、不重建。
  借来的东西不算本地改动、不会被 push。`guji glyph-db rebuild` 也认工作区名（没 pull 过就报错让先 pull）。
  写路径的条目（旧布局）照旧当本地目录；借自己报错。借来的人裁记成 `borrowed_human`（S3 修法），不当铁证。
- **共享层只读**：`corpus-base` 和 `glyphlib-*` 工作区，普通 `db push`／`db sync` 一律拒绝；只有升级脚本
  （`push(..., shared_writer=True)`）能写，`glyphlib-*` 还只能写一次（发布过就不可改，出新版开新工作区）。
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
export GUJI_DATA_TOKEN=<正式令牌>             # GUJI_DATA_TOKEN_PROD；只读的话不用设：没设时自动用 GUJI_DATA_TOKEN_READ
guji db migrate -w <工作区> --dry-run         # 一次性：先看工作区里的数据与库是否一致
guji db migrate -w <工作区>                   # 数据挪进数据目录、工作区里删掉、写标记；glyph.db 不动
guji db pull    -w <工作区>                   # 中心库 → 数据目录；拉到新字形库才重建 glyph.db
#   …照常跑 cv（控制台、step、H 道）…
guji db push    -w <工作区> [--dry-run]       # 数据目录 → 中心库（guji store commit 在迁过的工作区上也走这里）
guji db status  -w <工作区>                   # 落后几条、哪些文件没推
guji db sync    -w <工作区> [--dry-run]       # 拉＋合并＋顺带落库＋推一步做完（日常用这个）
guji db sync    -w <工作区> --watch 600       # 每 10 分钟一轮，不退出（服务器上替代旧的 glyph_store_sync 定时器）
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
- **sync 顺带落库**（2026-10-24 起）：拉完合完，对还没落进字形库的人裁只跑 `glyphdb_admit`、`glyph_audit` 两个消费者
  （`feedback/auto_admit.py`），落了就再推一次，返回里 `glyph_admit` 记各消费者的结果、`left` 是没落成留着的事件。
  别的消费者（金标、排除名单）不跑。取不到字块的（本机没有那一页的产物和字块缓存）不记账，留给有产物的机器或 A23 扫尾；
  `--no-admit` 或 `GUJI_AUTO_ADMIT=0` 关。为什么要有这一步、字形库更新谁来做，见 `doc/受控重跑.md` 第六节。
- **连库**：push 直连 Postgres。有 `GUJI_DATA_PG_DSN` 就用；没有就读 `NEON_DATABASE_URL`，在本进程起 WebSocket 桥（云会话只通 443）。
- `push`／`sync` 写 `main`，或用 `--branch exp/…` 写实验分支（见下「实验分支」）；不写 `ci`。
- **sync（自动合并）**：库里在基准 rev 之后没人写过就直接推；有人写过，先把库里的拼到旁边逐文件比：
  库里改了、本地没改的用库里的；本地改了、库里没改的留本地的；两边都改了的，只追加台账（events、consumed、anchors）
  按「共同前缀＋库里新行＋本地新行」合（同一行只留一份），别的文件两边都改了就整次停下（`SyncConflict`），什么都不动，
  要库里的用 `pull --force`，要本地的手工合。合完拉到新字形库就重建 glyph.db，再推本地剩下的改动。
  `--watch` 下冲突、断网只记一行到 stderr，下一轮再试。
- close-check 第 8 项在迁过的工作区上查「数据目录有没有没推的改动」，不再查 git。

验收（`tests/datastore/test_datastore_workcopy.py`，本地 Postgres）：migrate 后工作区里只剩 workspace.yaml、标记、
glyph.db（逐字节不变）和产物，数据目录与提交逐字节相同，路径函数指向数据目录；不一致时 migrate 拒绝、`--keep-local`
后成为待推改动并推成功；两台机器之间 pull／push、旧版本被拒、`--force` 重拉、删文件与台账少行被拒、库里删了本地也删；
新机器 pull 重建的 glyph.db 与从 git 字形库 rebuild 的全部表逐行相同；glyph.db 改了 push 前先导出；两台机器各自追加事件后 sync，两边的行都进库、另一台再 sync 拿到同一份文件，
书 yaml 两边都改则 `SyncConflict` 且本地不动。
守卫 `tests/test_central_paths.py`：包内不许从工作区根直接拼这些目录。

### 实验分支（2026-10-19 起）

试新功能、跑会写库的 A/B 时，不碰正式库：从 main 开一个 Neon 分支（写时复制，秒级），整个工作区换到那个分支上读写，
完了比一比，要的显式导回 main，然后删分支。只比参数、不写库的 A/B 照旧用 `guji exp`（见 `exp_framework.md`），不用开分支。

```bash
export GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_EXP            # 实验令牌就够；导回 main 那一步才要正式令牌
B=exp/GUJI-<卡号>-<小写说明>                           # 名字规矩同 Worker：必须带卡号，最多 63 字
guji db branch create $B                              # 从 main 当前状态开；--from-rev N 从某个 rev 开
export GUJI_DATA_BRANCH=$B                            # 之后本 shell 里一切都对这个分支（也可每条命令加 --branch $B）
guji db pull -w <工作区>                              # 拉到 $GUJI_DATA_HOME/exp__GUJI-…/<工作区>/，重建该分支自己的 glyph.db
#   …照常跑 cv：products 也落在该分支的数据目录里，不碰工作区的 products/ 和 glyph.db…
guji db sync -w <工作区>                              # 推到实验分支（新图进实验桶）
guji db diff -w <工作区>                              # 与 main 逐文件比：哪些文件不同、只在一边有、哪些人裁事件只在实验分支上
unset GUJI_DATA_BRANCH
guji db import --from $B -w <工作区> --dry-run        # 人裁事件导回 main（要正式令牌）；--events ids.txt 只导挑出的
guji db branch delete $B                              # 用完就删（Neon 免费档整个项目最多 10 个分支）
```

- **怎么隔离**：`GUJI_DATA_BRANCH`（或 `--branch`）覆盖工作区标记 `.central.json` 里的分支（标记文件不改），
  `core.workspace` 的路径函数都跟着走：数据目录 `$GUJI_DATA_HOME/<分支，/ 换成 __>/<工作区 id>/`；
  glyph.db 缺省 `<该数据目录>/output/glyph.db`，products 缺省 `<该数据目录>/products/`（`GUJI_GLYPH_DB`、`GUJI_PRODUCTS_DIR` 显式给了仍优先）。
  所以同一台机器、同一个工作区可以一边在 main 上整理，一边在实验分支上试，互不覆盖；`unset` 就回到 main。
- **写哪里**：`push`／`sync` 只许 `main` 和 `exp/GUJI-<号>[-说明]`。实验分支经 Neon API（`NEON_API_KEY`，项目 `NEON_PROJECT_ID`，
  缺省中心库项目）查到该分支的端点，再用 `NEON_DATABASE_URL` 的账号经 443 桥连（子分支继承口令）。新图传实验桶 `guji-assets-exp`。
- **取图**：实验分支是从 main 分出来的，老图在正式桶；在实验分支上拉图时正式桶 404 的自动去实验桶取。
- **比较** `guji db diff -w <工作区> [--branch $B] [--against main] [--show N]`：只读两边的 `source_files` 与图清单（不下载内容）：
  `changed`（两边都有、sha 不同，带两边行数）、`only_in_branch`、`only_in_against`、`events_only_in_branch`（即 import 会导的）。
  分开以后 main 也可能有新写入，所以报的是「现在不同的」，不分是谁改的。产物（products）的对比用 `guji exp report` 或直接比两个 products 目录。
- **导回正式库**：只有显式的路，不整分支合并。人裁事件用 `guji db import`（经 Worker、按 id 幂等，要正式令牌）；
  别的文件（册 yaml、配置、台账）把实验分支数据目录里要的那几个文件拷到 main 的数据目录，再在 main 上 `guji db sync`，留正常的 push 记录。
- 实验分支的写入在 `imports`／`changes` 里照样留痕（`stats.branch`），开删分支记 Workers Logs。

### 整理本与语料库清单（2026-10-19 起，共享方案 S1）

- **收录**：`corpus/**`（整理本）进新表 `corpus_files`，做法同锚图：库里只记 `src_path`、`sha256`、`bytes`，
  文件本身进 R2（`sha256/<2>/<sha>.txt`，Worker 的 `/v1/assets/sign*` 带 `"ext": "txt"`）。
  语料库清单从 `<工作区>/corpus-pack/vN/` 挪到数据目录 `config/corpus-pack/vN/`，随 `config/` 进 `files` 表。
  工作区根的旧 `corpus-pack/` 不再收录。
- **补迁**：已经迁过的工作区，`guji db migrate -w <工作区>` 再跑一次，把工作区根留下的 `corpus/`、`corpus-pack/`
  挪进数据目录，成为待推改动（同 sha 的直接删工作区里的那份；数据目录里有同名不同内容的就停下）。然后 `guji db push`。
  第一次推会在库里建 `corpus_files` 表（`import_scans` 里 `apply_schema`）。
- **路径**：`core/workspace.corpus_dir()` 迁过的工作区指数据目录 `corpus/`；数据目录里还没有、工作区根还有旧的时退回工作区根。
  `corpus_pin.pack_root()` 同理。钉了版本的册指纹是 `corpus-vN`，没钉的册指纹按文件名＋内容算，都与文件放哪无关：
  殿本 10 册×17 步搬家前后 `self_hash` 逐位相同，`guji corpus verify` v1 无 changed／missing。
- **新旧版本混用**：旧版 cv 不认 `corpus_files`，pull 不还原整理本，读的仍是工作区根的 `corpus/`；新版 cv 碰到没部署新表的
  旧 Worker（`no_table`）当作空表。所以 **guji-workspace 删掉 `corpus/`、`corpus-pack/` 要等带 S1 的版本（v0.4.5）发了、
  各机升级之后**，否则旧版会静默退回本仓的样本语料。

验收（`tests/datastore/test_datastore_workcopy.py`）：补迁后推、另一台 pull 逐字节相同；同名不同内容拒绝补迁；
路径函数跟着数据目录走；旧 Worker 没有 `corpus_files` 时 pull 照常。

**在线实测（2026-10-19，云会话，main rev 1356）**：qtw-draft 从空目录还原 33 个文件、6,506 张刻例图
（6,538 次 Worker 请求，约 7 分钟，重建 glyph.db 6,506 个实例）；随即试推（自动经 443 桥连 Neon main）全部表 0 变更。

### 两级语料库清单（2026-10-19 起，共享方案 S2）

- **底库 `b<M>`**：引擎仓里的语料文件（字表、IDS、异体、形近、规则……，`corpus_pin.ITEMS` 里根是 `repo` 的）登记在
  中心库只读工作区 `corpus-base` 的 `config/corpus-base/b<M>/manifest.json`，记 `repo_commit`（这些文件必须都已提交，
  还原就切到那个提交）和代码常量 `NEVER_MATCH_FAMILIES` 的哈希。`guji corpus build-base [--note …]` 出新版：
  拉 `corpus-base`（库里还没有就新开）→ 写 `b<M+1>` → 以升级脚本身份推（`push(shared_writer=True)`）。旧版不动。
  本机工作目录在 `$GUJI_DATA_HOME/<分支>/.shared/corpus-base/`。要写库权限（同 `db push`）。
- **书库 `v<N>`**：`guji corpus build -w <工作区> --base latest|<M>` 出两级清单，写 `base: M`，只登记工作区里的文件
  （整理本、字频、L2、工作区异体）；本机引擎仓文件与 b<M> 不符就拒绝（先出新底库，或切到它的提交）。
  新书用 `guji corpus init -w <工作区>`（＝钉最新底库出 v1）。出完 `guji db push`。不给 `--base` 照旧出单级清单，
  殿本 v1 是单级的，不变。
- **拉**：书库清单写了 `base` 的工作区，`db pull`／`db sync` 顺带把底库清单拉成只读副本
  `$GUJI_DATA_HOME/<分支>/.borrowed/corpus-base/`（同借库，记 rev，没新写入不重拉）；`build --base`、`init` 也会先拉。
- **起跑前硬校验**：册钉了 `corpus: N`，读语料的五步（`corpus_pin.CORPUS_STEPS`）开跑前对清单（两级的连底库）核文件，
  有改动或缺失就拒绝（`CorpusDrift`）；清单之后新出现的文件只警告（不在这版承诺里，出下一版收进去）。
  临时绕过设 `GUJI_CORPUS_DRIFT=warn`。`guji status` 等只读命令照旧只警告。10-19 殿本 v1：改动 0、缺失 0、新增 27（新字组规则与 L2 表）。

验收（`tests/test_corpus_pack.py`、`tests/datastore/test_datastore_workcopy.py`）：底库只登记引擎仓文件、不覆盖、未提交拒绝；
书库只登记工作区文件、verify 两级一起对、本机没有底库报错；硬校验改动拒绝、新增只警告、`warn` 绕过、只对钉了的读语料步生效；
build-base 第一次新开 `corpus-base`、再出新版旧版还在、普通 push 拒绝；新机器 pull 顺带拉底库清单。

### 共享刻例库（2026-10-19 起，共享方案 S5）

- **出新版**：`guji glyphlib build -w <来源书工作区> --name glyphlib-<族>-v<N> [--min-confirm 2] [--per-char 3] [--note …]`。
  从来源书的字形库真源与人裁事件里挑：人裁过（`label_status='human'`）、在至少 `--min-confirm` 个不同批次确认过
  （`confirm` 的 `v=confirm` 且字形一致，或 `cell_review` 选了这个字）、体检没标异常、不是近似字，每字最多 `--per-char` 张
  （确认批次多的优先）。门槛 sheldon 10-19 定为「确认两次」（缺省值）。
- **现有版本**：`glyphlib-qkp-v1`（殿本 `siku-zongmu` 出，1,076 例、827 字，10-19 推进中心库 rev 8296）。
- **出什么**：本机数据目录 `$GUJI_DATA_HOME/<分支>/glyphlib-…/` 下的 `output/glyph_store/`（edition 是族名 `glyphlib-<族>`，
  跨版本不变；实例 id 加来源前缀 `<来源工作区>:`，来源 id 写成 `<来源工作区>.<原来源>`）和升格记录
  `feedback/events/promote.jsonl`（一张刻例一行：来源工作区、来源实例、确认批次数、门槛）。刻例图逐字节照搬，R2 里同 sha 不另存。
  出完先装一遍库（`rebuild_from_store`）核对能装，再规范导出。
- **推**：加 `--push` 以升级脚本身份推（`push(shared_writer=True)`），第一次新开工作区；同一版再推拒绝，出新版开新名字。
- **用**：别的书在 `workspace.yaml` 写 `glyph_lib: {borrow: [glyphlib-qkp-v1]}`，`guji db pull` 拉只读副本、带上它重建 glyph.db；
  借来的实例记成 `borrowed_human`，不当本书铁证。
- **匹配时降一档**（v0.4.7 起，S6）：Step5-a 判 same 的库条目里有本书的，用本书那条；只有借来的条目判 same 就降成 unsure，
  字进候选交上下文裁决，记 `via="borrowed:<条目 id>"`，不再走共识升档、近形决胜。被借库的名字进 `glyph_match` 的硬参数
  `borrow_fingerprint`，借的库换版本这一步判过期；没借库的书参数哈希、判决都不变。
- **10-19 本地试算（殿本，不推）**：人裁 4,374 例 → 确认两批以上且体检干净 1,149 例 → 每字 3 张 **1,076 例、827 字**；
  图与来源逐字节相同；借进全唐文重建，1,076 例都是 `borrowed_human`。

### 字形库快照 g<N>（2026-10-21 起，GUJI-727）

- **出号**：`guji glyph-db snapshot -w <工作区> [--note …]`，数据目录要先推干净（快照对得上中心库的 rev）。出 `config/glyph-pack/g<N>/manifest.json`：
  `output/glyph_store/` 与借来的字形库每个文件的路径、sha256、类型，`digest` 是条目内容哈希（不带版本号）。内容与最新一版相同拒绝。
- **存**：清单随 `config/` 进 `files` 表；**已发布的清单不可改**（push 守卫同语料库清单）。清单登记的文本随第一次推它的 `guji db push` 按 sha 传 R2
  （`sha256/xx/<sha>.txt`），本机文件已与清单不同就拒推；刻例图早已按 sha 在桶里。同 sha 不另存，没变的 `instances/<册>.jsonl` 不占新空间。
- **取**：`glyph-g<N>.db` 在工作区本地，`guji db pull/sync` 与 `guji pipeline/step` 起跑前按各册 `glyph_pin` 自动建：本机同 sha 的文件、本机图缓存优先，
  缺的从 R2 取；`guji glyph-db pin-verify --pin N` 只从 R2 拼一遍核对。字体域从当前 `glyph.db` 拷。用法与指纹口径见 `core/glyph_pin.py` 模块头。

### 升格候选（2026-10-19 起，共享方案 S7，先做语料部分）

- `guji promote mine -w <工作区> [--min-confusable 3] [--out 清单.json]`：只读，从本书对勘裁决（`collate_verdict`）挖两类候选，
  对照引擎仓已有的表标「已有」：**形近对**（人判整理本对、不是异体：CV 把 B 认成 A，同一对 ≥3 次；异体表里已有的字对不算），
  **异体对**（人判是异体；表里没有的标 `needs_source`，要补字书出处才能升格）。审过的走引擎仓 PR 改表 → `guji corpus build-base`。
- 10-19 殿本：对勘裁决 704 条 → 形近新候选 3 对（𨜊→卿 19、撰→𢰅 4、巳→已 3；日→曰 4 已在表里）、异体新候选 14 对（蒙𫎇 34、內内 20、別别 18 …）。
  前两对形近其实像异体，人审时再分。门槛待 sheldon 定；归档时跑这一步要写进整理组的归档流程（验收后集成时再提）。

## 七、备份与恢复（GUJI-611）

每日例行任务（云端定时会话）跑 `python -m open_guji_cv.datastore backup`：同一快照里导出全部表（`COPY` 文本格式、gzip），
附 `manifest.json`（每表列、行数、逐行排序后的 sha256、序列值、rev），经 Worker `PUT /v1/backups/<日期>/<文件>`
存进正式桶 `backup/<日期>/`，清单最后传（有清单才算完整），清掉 30 天前的。每周日再跑
`restore-check --endpoint <ci 分支端点>`：取最新完整备份，删表、按 `schema.sql` 重建、`COPY` 回去、设序列，
按同样口径重算逐表对。恢复只许打到 main 以外的端点。

要从备份救 main：先在 Neon 开一个新分支，`restore-check --endpoint <新分支端点> --date <日期>` 恢复并核对，
确认后在 Neon 控制台把它设为主分支（或把 main 重置到它）。这一步要用户点头。

**首次演练（2026-10-19，rev 1356）**：26 张表 189,964 行，备份 27 个文件 12 MB，31 秒；恢复到 ci 分支 39 秒，逐表行数与哈希全部一致。
