# B. 数据存放调研：跑完 CV 的结果存哪（GUJI-636 子题）

> 2026-10-20 洛杉矶，只读调研。来源：open-guji-cv（main `a00dbdb`，v0.4.7-5）、guji-workspace（main `422f1d5`，浅克隆）、
> guji-workspace-data、book-text（main `ffbf1d496`）、open-guji-dataset（`7e13ee1`）、kaiyuanguji-web、ai-team；
> Jira GUJI-598／610／627／636；中心库只读实查（读令牌，Worker `data.open-guji.com`，main rev 12021，2026-10-20 07:12Z）。
> 标「建议」的是推测，其余都给出处。

---

## 〇、三处存储的现行分工（一句话）

- **中心库 = Neon Postgres（项目 `aged-credit-71244565`，分支 main／ci／exp/*）＋ Cloudflare R2（正式桶 `guji-assets`、实验桶 `guji-assets-exp`）＋ Worker `guji-data`（`https://data.open-guji.com`）**。
  2026-10-19 起（GUJI-608）人裁、台账、批次、`config/**`、字形库账本、册 yaml、workspace.yaml、整理本、语料清单的唯一真源。
  出处：cv `doc/datastore.md` 第六节；guji-workspace-data `README.md`；ai-team `通用/中心库设计.md` 文首。
- **R2 只放二进制／大包**：刻例图、锚图、整理本 txt（`sha256/<2>/<sha>.<ext>`）、汉字库部件包、产物包 `pack/`、数据目录快照 `snapshot/`、每日库备份 `backup/`。正式桶挂公开域名 `https://blob.open-guji.com/<键>`（10-19 sheldon 定「按哈希公开」）。
- **guji-workspace git**：只放原图（`data_full/`）＋ `workspace.yaml`、`.central.json`、README；另实际上还放着 `reports/`、`experiments/`、快照孤儿分支 `snap/*`、`_shared/train_bundle.zip`、v1 遗留 `output/*`。
- **本地**：products、cache、glyph.db、runs、数据目录副本（`$GUJI_DATA_HOME`，缺省 `~/.guji-data`）。
- **book-text git**：char／cord／norm／punct／entity（真源，main）；`proof/<书>/<章>/sprites.pointer.json`。
- **open-guji-dataset**：评测金标（git，222 MB）；Release：雪碧图资产 `proof-<书>-<章>-<n>`、归档包 `archive-<书>-<版本>-<n>`。
- **腾讯云 COS（data.kaiyuanguji.com）**：网站读的一切：book-text 数据包 `current/`、书影 IIIF `iiif/`、待审单 `proof/`、雪碧图 `proof/<书>/<册>/`、公开意见清单 `proof/fixes/`。
- **EdgeOne KV**：公众意见原始票（`/api/cellreview`、`/api/charfix`）。

---

## 一、中心库表（`open_guji_cv/datastore/schema.sql`，同 guji-workspace-data `schema/schema.sql`）

来源列：每行带 `ws, src_path, src_line, raw, rev`（部分有 `doc jsonb`）。`changes(rev bigserial, tbl, op, ws, pk, old_sha, new_sha)` 全局递增；`source_files(ws, src_path, tbl, sha256, bytes, n_lines, final_newline)` 用来整文件还原、核对。

| 表 | 来自数据目录哪个路径（`datastore/scope.classify`） | 主键（另加 ws） | 备注 |
|---|---|---|---|
| `workspaces` | `workspace.yaml` | ws | raw＝全文 |
| `books` | `books/*.yaml` | book | 册配置 |
| `events` | `feedback/events/*.jsonl`、`feedback/vision/*.jsonl` | src_path, id | 只追加；Worker `POST /v1/events` 也写 |
| `consumed` | `feedback/consumed/*.jsonl` | consumer, src_line | 只追加 |
| `anchors` | `feedback/anchors/*.jsonl` | src_path, event, key | 只追加 |
| `anchor_patches_meta` | `feedback/anchor_patches/**.png` | src_path | 只存 sha，图进 R2 |
| `corpus_files` | `corpus/**` | src_path | 只存 sha，文本进 R2（`.txt`） |
| `verdicts` | `feedback/verdicts/**/*.jsonl` | src_path, id | 金标信封 |
| `files`（视图 `lists`、`batches`） | `feedback/lists/**`、`feedback/candidates/*`、`feedback/*.jsonl`、`review/batches/**`、`config/**`（含 `config/corpus-pack/vN/`）、glyph_store 杂项 | src_path | 整文件 |
| `glyph_sources/instances/glyphs/exemplars/admissions/evictions/approx_labels/approx_clears/pairs/meta/events` | `output/glyph_store/*.jsonl`、`instances/*.jsonl`、`events/*.jsonl` | 照 `clustering/glyph_db.py` | `glyph_instances.patch_sha`→R2；`kind='font'` 不进 |
| `freeze_baselines`、`cv_versions`、`snapshots` | 无（设计说由 close-check／发布流程写） | — | **实查三表全空**（2026-10-20） |
| `imports`、`db_meta` | — | — | 审计 |

不进库（datastore.md 第二节）：`*.bak*`、`_backup_*`、`consumed_bak_*`、`data_full/`、`output/` 其余、`reports/`；`corpus/` 原先不进，10-19 S1 起进 `corpus_files`。

### 1.1 实查（main rev 12021，`/v1/tables/source_files`）

| 工作区 | 册 | events 行 | consumed 行 | anchors 行 | verdicts 行 | glyph_instances | files 个数／MB | corpus_files |
|---|---|---|---|---|---|---|---|---|
| siku-zongmu（四庫，`96mid1ogzk`） | vol01–10 | 18,191（13.9 MB） | 39,928 | 4,891 | 5,038 | 18,557 | 199／2.98 | 17 个 48.2 MB |
| beixing-guben（北行，`988g7gsqhd`） | bxgb | 2,345 | 11,164 | 0 | 482 | 4,851 | 28／0.85 | 1 个 68 KB |
| qtw-draft（全唐文） | v006–v010 | 8,631 | 1,527 | 0 | 0 | 6,506 | 4 | 16 个 0.89 MB |
| glyphlib-qkp-v1（共享刻例库） | — | 1,076（promote） | — | — | — | 1,076 | 1 | — |
| corpus-base（底库清单） | — | — | — | — | — | — | — | — |

- 锚图：`anchor_patches_meta` siku 2,787 张、bxgb 1 张；**2026-10-20 实测 2,788 个 sha 在 `blob.open-guji.com` 全部 HEAD 200**（GUJI-627 第一件「R2 缺 121 张锚图」数据上已补齐，卡仍是「待办」）。
- 书库语料清单：siku `config/corpus-pack/v1…v6`；各册 yaml 现钉 `corpus: 6`（vol09 实验记录写的是 c2，之后又升）；bxgb `corpus: 1`；qtw 未钉。无一册写 `glyph_pin`、`cv_version`。
- 冻结：只有 vol01 写了 `freeze: {at: 1.0.0, cv_version: 0.4.5, cv_commit: 456b30c5…, snapshot: snap/96mid1ogzk/vol01/20261020T0142}`——基线指向 **guji-workspace git 的快照分支**，不是中心库表。
- 待审单：siku `feedback/lists/proofing/96mid1ogzk/{001,004–010}.pending.json`（共 1.03 MB；001 是 117 字节 0 格；004 280 格、rev `004-r3`、cv_version `0.4.6.dev`；字段有 `why/cls/lib_top/lib/ctx/ref/occ/margin`，**无 `img`/`sprites`**）。公众意见 `feedback/lists/web/96mid1ogzk/001-r2.jsonl`。
- 小异常：`feedback/.write.lock`（0 字节锁文件）被收进 `files` 表（`scope.classify` 对 `feedback/<单文件>` 一律归 files；guji-workspace `.gitignore` 拦它，scope 没拦）。

### 1.2 命令（cv `guji db …`，datastore.md 第五、六节原文）

```bash
export GUJI_DATA_TOKEN=<令牌>      # READ/EXP/PROD 三把，环境变量 GUJI_DATA_TOKEN_{READ,EXP,PROD}
guji db migrate -w <工作区>        # 一次性：工作区数据挪进数据目录，写 .central.json
guji db pull    -w <工作区>        # 中心库 → $GUJI_DATA_HOME/<分支>/<ws>/；拉到新字形库才重建 glyph.db
guji db push    -w <工作区>        # 数据目录 → 中心库（直连 PG，或 NEON_DATABASE_URL 经 443 WebSocket 桥）
guji db sync    -w <工作区> [--watch 600]   # 拉＋合并＋推；只追加台账三方合并，其它文件双改则 SyncConflict
guji db status / diff / branch create|delete / import --from exp/…
python -m open_guji_cv.datastore backup | restore-check --endpoint <ci 端点>   # 每日备份、每周恢复演练
```

- push 先锁 `changes`，基准 rev 之后有人写过就 `StaleBase`；只追加台账少行拒绝；整个文件消失要 `--allow-delete`。
- pull 拉图：`/v1/assets/sign-batch` 签，正式桶直接回 `blob.open-guji.com` 地址；图缓存 `GUJI_DATA_CACHE`（缺省 `~/.cache/guji-data`）。
- 新机器先取数据目录快照 `GET /v1/snapshots/<ws>`（R2 `snapshot/<branch>/<ws>/<rev>.tar.gz`，每分支每 ws 只留最新；siku 约 20 MB），再向库要差异（workcopy.py `_seed_from_snapshot`）。
- 借库：`workspace.yaml` 的 `glyph_lib.borrow: [<ws>]`，只读副本 `$GUJI_DATA_HOME/<分支>/.borrowed/<ws>/`。共享层 `corpus-base`、`glyphlib-*` 普通 push 拒绝。
- 实验分支：数据目录、glyph.db、products 都落 `$GUJI_DATA_HOME/exp__GUJI-…/<ws>/`；新图进 `guji-assets-exp`；Neon 免费档最多 10 个分支。

## 二、R2 布局（guji-workspace-data `worker/src/*.ts`、cv `datastore/r2.py`、`packs.py`）

| 前缀 | 内容 | 写入方 | 实查 |
|---|---|---|---|
| `sha256/<2>/<sha>.png` | 刻例图、锚图 | `guji db push`（经 Worker 签上传，核 sha、不覆盖） | 首导 30,480 对象 90.7 MB（datastore.md 三、四节） |
| `sha256/<2>/<sha>.txt` | 整理本、hanzi 部件包 | 同上；hanzi 见 `open_guji_cv/hanzi/pack.py` | siku 整理本 48 MB |
| `snapshot/<branch>/<ws>/<rev>.tar.gz` | 数据目录快照（缓存） | `db pull/sync` 后自动 PUT | siku 20 MB |
| `pack/products/<ws>/<册>/<标签>/{manifest.json, part-000.tgz…}` | 产物包（每段 ≤64 MB，Worker 单对象 ≤95 MB） | `guji products pack push` | 见下 |
| `pack/products/<ws>/<册>/main-ptr` | 该册正式结果指针 | `pack push --main` / promote（方法论文档；本地 cv 检出未见 promote 代码） | vol04–10 有 |
| `pack/rare-index/glyph_cnn_r5/…` | 生僻字 embedding 索引 | `guji products pack push-index` | 73.7 MB |
| `backup/<YYYY-MM-DD>/` | 每日全表 COPY+gzip＋manifest.json，保留 30 天 | 每日云端定时会话 `datastore backup` | 首演练 27 文件 12 MB（读令牌不可读） |

**产物包实查**（`GET /v1/packs?bucket=main`，53 个对象 241.9 MB）：
- siku vol01 `snap-20261020T0142-cv0.4.5`（7.2 MB，与 freeze 基线同名的快照，也在 git snap 分支）；
- vol04 `v0.4.6-cujiao`、`cv0.4.7-c1-g-82293e-{control,layout-prior,new-glyphs}`；vol05–10 `v0.4.6-cujiao`、`cv0.4.7p9-c2-g-82293e-baseline` 等，每包 3–13 MB；
- **`products/ws/vol01..03/vunknown-20261020T0308`**：工作区名落成了 `ws`、cv 版本 `unknown`——`packs._ws_name()` 在拿不到 `.central.json` 且 `workspace_root()` 为空时回退 `"ws"`；`pack fetch vol01 -w <siku>` 找不到这三包。
- bxgb、qtw 无任何产物包。

产物包 manifest 字段（packs.py）：`name, ws, book, label, cv_version, cv_commit, created, note, files, steps{步:文件数}, bytes, parts[{name,bytes,sha256}]`。标签规矩 `cv<版本>-c<语料号>-g<字形库号>-<改动名>`（ai-team `domain/CV/规范/受控重跑方法论.md` 第六节）。每包对应一页实验记录 `guji-workspace/<书目录>/experiments/<册>/<标签>.md`（git）。

## 三、本地（各机）

| 物件 | 路径 | 代码出处 | 量级 |
|---|---|---|---|
| products（Step1–7 产物＋每步 `_manifest.jsonl`） | `<工作区>/products/<book>/<step>/p0024.json`；实验分支在数据目录 | `products/store.py`、`manifest.py`（字段 key, fingerprint, sha256, params_hash, upstream, code_rev, self_hash, invalidated, recheck, soft, book, cv_version） | 一册打包 3–13 MB（vol09 3,459 文件 12.6 MB）；四庫 10 册早期估 86 MB |
| cache（列图、字块、归一图块） | `<工作区>/cache/<book>/<kind>/<key>.png`＋`_stamps.json` | `products/cache.py`，LRU 缺省上限 20 GB | 不进包、不进快照；`guji cache warm` 重建（vol04 121 页 288 s） |
| runs（控制台任务记录） | **引擎仓根 `runs/`**（`GUJI_RUNS_DIR` 可改），cv `.gitignore` 拦 | `console/jobs.py::default_runs_root` | 小 |
| glyph.db | `<工作区>/output/glyph.db`（实验分支在数据目录） | `core/workspace.py::glyph_db_path`；`ops/central_glyph` | 不带字体域约 220 MB，带字体域 3.09 GB（中心库调研） |
| 字体域（kind=font） | glyph.db 内，`font_manifests` 表不导出 | `guji glyph-db import-font`（约 10–15 分）；字体档在引擎仓 `fonts/` | — |
| 数据目录 | `$GUJI_DATA_HOME/<分支>/<ws>/`（books、feedback、review、config、corpus、output/glyph_store）＋ `.central-state.json` | `datastore/workcopy.py` | siku 整拉约 50 MB＋1.9 万张图 |
| 字统网缓存 | `$GUJI_DATA_HOME/_shared/zitools/` | runbook S11-b | 换机重取 |
| hanzi 库 sqlite | `$GUJI_DATA_HOME/_shared/hanzi/<版本>/` | `hanzi/pack.py`（从 R2 按 sha 取） | — |
| zl.py 状态 | `<ws>/../zhengli-state/<册>.json` | runbook 〇·五 | — |
| 导出目录（char/cord/norm、lines.md、pages.json） | `--out <dir>`（任意） | `scripts/export_guji_format.py`、`formats/guji_format.py` | — |
| `products_snap/`（`guji snapshot make`） | 工作区内 | — | 可重做 |

## 四、guji-workspace git 现在存什么（main `422f1d5`，5,087 个跟踪文件）

- 书目录 2 个：`96mid1ogzk-欽定四庫全書總目武英殿刻本`（`id: siku-zongmu`，原图 `data_full/zongmu/vol01–10` 1,713 张、388 MB）、`988g7gsqhd-北行日錄…`（`id: beixing-guben`，`data_full/bxgb_scan` 56 张、154 MB）。另有 `qtw-draft/`（只有 workspace.yaml、.central.json、.gitignore、SNAPSHOT_NOTE.md；**`.gitignore` 拦 `data_full/`，全唐文原图不在 git**）。
- 仍在 git 的非原图：`reports/<册>/…`、`experiments/<册>/<标签>.md`、v1 遗留 `output/book9/`、`output/vol01_v2view/patches`（520 张）、`output/border_review/img` 等；`feedback/web/2026-10-18{,b}.jsonl`（旧公众意见）、`feedback/verdicts.bak-*`、`consumed_bak_*`；`_shared/train_bundle.zip`（30.9 MB）；`exports/sandbox_products/`。
- 孤儿分支：`snap/<ws短id>/<book>/<yyyymmddThhmm>`（guji-snap/1，明文文件树：manifest.json＋products/＋attach/，`open_guji_cv/snap/`）；`idx/<kind>/<key>`（大模板索引）。冻结基线（`ops/freeze.py::load_baseline`）用 `git show <分支>:manifest.json` 读它。
- `.gitignore`（10-19）拦 `*/books/`、`*/feedback/{events,consumed,anchors,anchor_patches,verdicts,lists,candidates}/`、`*/review/batches/`、`*/config/`、`*/output/glyph_store/`、`*/feedback/*.jsonl`；书目录 `.gitignore` 拦 `products/`、`cache/`、`output/glyph.db`。
- README：「整完即删，不是长久存放之所」；「可再生的不进 git，人产出的进中心库」。

## 五、book-text（文本 v0.1 怎么进库）

- 目录：`Book/<shard>/<id>/manifest.json` ＋ 版本目录（`is_original: true` 的，四庫是 `default/`，另有 `cv-proof/` 放 vol03 粗校 0.1.1 并存）。四庫 `Book/g/z/k/96mid1ogzk/default/`：001–010 的 char/cord/norm（001–003 另有 punct、entity），47 MB。
- `index.json` `chapters[]`：`n, file, title, char_file, cord_file, norm_file, punct_file, entity_file, pages, text_version, punct_version, entity_version, proofing, headings`。实查：001 `1.0.0 proofing`、002 `1.0.1`、003 `1.0.2`、004 `0.2.2`、005/006 `0.1.1`、007–010 `0.1.0`，0.x 都 `proofing: true`，**都没有 `pending_file`**。
- 版本规矩（`docs/VERSIONING.md`）：0.x＝平台粗校完；0.1.0 用 overview `scripts/book-text/bump_original.py <目录> --init --version 0.1.0`，章条目 `proofing: true`；main 受保护走 PR；CI `check.yml` 跑 V1 validate-collated、V2 `validate_text_format.py --strict --baseline`、V3 check_license。
- 校验器 F-OV-01…12：01 三线版本；02 伴生层锚点；04 `*_file` 存在，文本 0.x 时 `cord_file` 必填；06 `proofing`；07 `pending_file`（有才校）；08 pending 0.2 字段类型；09–11 雪碧图指针 `proof/<书>/<册>/sprites.pointer.json`（`tag/manifest_sha256/rev`，CI `--fetch-assets` 从 open-guji-dataset Release 下 `assets.json` 核 sha）；12 标题符。
- `docs/ORIGINAL.md`：`pending_file` 「2026-10-20 起待审单只放中心库、每日发布到 COS，本仓不再放」；「书影、cv 的中间产物、人裁事件、字形库不在 book-text，留在 IA 和 guji-workspace」（这句已过时：人裁、字形库在中心库）。
- 实查 `proof/` 下只有 `96mid1ogzk/001/sprites.pointer.json`（tag `proof-96mid1ogzk-001-2`，rev `001-r2`）。
- runbook S19：「推到 book-text 的 **`wip/siku`** 分支」；VERSIONING：0.1.0 要并 main。两处口径不同（当前 main 上已有 004–010 的 0.x）。

## 六、待审单、雪碧图、公众意见的流（ai-team `team/整理/设计/待审单与公众意见走中心库.md` v0.1、kaiyuanguji-web）

```
seed_admit 产物 ─ ai-team team/整理/GUJI-543/pending_list.py [--cards <册>.cards.alt.json（guji audit alt 出）]
   └→ --ws <ws> --text-id <书id>：$GUJI_DATA_HOME/main/<ws>/feedback/lists/proofing/<书id>/<章>.pending.json
   └→ guji db sync → 中心库 files 表
kaiyuanguji-web .github/workflows/proofing-sync.yml（每天 21:23 UTC；PROOF_WS 缺省只 siku-zongmu）
   opinions：中心库待审单的 (书,rev) → EdgeOne KV /api/cellreview 管理读 → PUT /v1/files feedback/lists/web/<书>/<rev>.jsonl
             （GUJI-597：/api/charfix 等 → feedback/lists/web/<书>/fixes.jsonl）
   publish ：→ COS proof/index.json（{books:{书:{章:{rev,n}}}}）、proof/<书>/<章>.pending.json、proof/fixes/<书>.json
雪碧图：ai-team GUJI-557 sprite_build.py（读 cord.json＋pending.json＋原图 data_full）、ex_build.py（读 glyph_store）、alt_build.py
   → webp＋assets.json（guji-proof-assets/0.1）→ open-guji-dataset Release `proof-<书>-<章>-<n>` ＋ book-text 指针
   → data.yml「sprites」job（sync-proof-sprites.mjs）→ COS proof/<书>/<册>/*.webp
网站：nextjs/src/lib/proofing.ts 先读 COS `https://data.kaiyuanguji.com/proof/<书>/<章>.pending.json`，取不到退回 book-text pending_file；
     框从 book-text cord_file 查；书影 lib/facsimile.ts `https://data.kaiyuanguji.com/iiif/<书>/<册>/manifest.json`
意见落裁决：web_opinions.py fetch --from-db <ws> → events（batch `H-web-<册>-<日期>`）→ db sync → 重导待审单
```

- 设计 §1 写「雪碧图真源在 R2，待审单顶层 `sprites[]`」；§3a 记「雪碧图暂仍走 GUJI-557 的 Release＋sync-proof-sprites」。实查中心库 004–010 pending **无 img 字段**，book-text 只有 001 一个指针 → vol04–10 精校页目前没有字块雪碧图。
- 网站读 KV 管理令牌：Worker 角色 `web`（TOKENS_WEB_JSON），只能读 `feedback/lists/proofing/**`、`web/**`，只写 main 的 `feedback/lists/web/**`。

## 七、书影

- 源：IA（浙大 CADAL 扫描，`_tif.zip`）；`kaiyuanguji-web/ops/iiif/siku_zongmu_iiif.py` 切三档 WebP（1-bit：放大档原图 1-bit WebP 无损）→ COS `iiif/<bookId>/<册>/<页序>/full/<宽>,/0/default.webp` 与 manifest（手动触发 `iiif-siku-zongmu.yml`）。
- CV 读的原图：guji-workspace git `data_full/`（四庫、北行）；全唐文原图不在 git。
- 中心库设计 3.2：「原图（564 MB）第二批上，或继续以 IA 为源（GUJI-598 定）」。GUJI-598「书影归档后的落点定论（原图 vs WebP）」：**待办**。三阶段流程 §8：「书影原图归档后必须能取到——放哪待 Mila／Eliot 定（IIIF 上的 1-bit WebP 是否够用要 CV 判）」；GUJI-562 演练：「留」表不含原图，缺了 status 页数 0。

## 八、评测金标与归档

- open-guji-dataset（git 222 MB）：按功能模块分片，统一金标信封 `items.jsonl`；`guji gold import <分片> --book <册> --ids <清单>` 从工作区 `feedback/verdicts` 显式导入（runbook S15）。中心库 `verdicts` 表另存裁决表（导入的来源）。
- 归档包：ai-team `team/整理/GUJI-562/archive_plan.py <书目录> --out archive_manifest.json --pack <包目录>`（脱敏：事件 `reviewer` 去 @ 之后）→ open-guji-dataset Release `archive-<书>-<版本>-<n>`（未压缩 tar；10-17 四庫预演练 20,737 文件 205 MB）→ `guji archive fetch <tag> --out <空目录>`（`ops/archive_fetch.py`，核 GitHub digest）。
  三阶段流程 §8 的「留」表与 archive_plan.py 都按**旧的 git 布局**（`feedback/…`、`output/glyph_store/` 在书目录里）写；10-19 起这些在中心库数据目录。未核实现有 Release 列表（本会话无 dataset 仓 API 权限）。

## 九、Jira 现状

- GUJI-598（书影落点）待办；GUJI-610（国内通道：COS 导出＋国内意见入口转发）待办，验收要国内网络实测——实际 proofing-sync 已把待审单发到 COS、意见从 KV 拉进中心库，但「国内入口转发中心库」是 Action 每日拉，不是实时转发。
- GUJI-627：①R2 缺 121 张锚图（vol04–09）→ 10-20 实测全部可取；②语料库 v1 与 `groups/freq.json`、`l2/jys.json` 不符 → 之后出了 v2…v6，各册钉 6。卡仍「待办」，可关（建议核一次新容器 `db pull` 与 glyph_match 不加绕过）。

---

## 十、大表：数据物件 → 存哪 → 谁写 → 谁读 → 量级

| 物件 | 真源／现在存哪 | 副本 | 谁写 | 谁读 | 量级 |
|---|---|---|---|---|---|
| 原图 | guji-workspace git `data_full/`（四庫、北行）；全唐文只在本地 | IA（源）；COS `iiif/` WebP（四庫） | `guji import-pdf`／人 | Step0–4、cache、雪碧图脚本 | 四庫 388 MB、北行 154 MB |
| Step1–7 产物 | 本地 `products/<册>/<步>/` | R2 `pack/products/…`（四庫 vol01、04–10）；git `snap/*` 分支 | 引擎 | 下游步、导出器、pending_list、close-check | 一册 3–13 MB 压缩 |
| manifest／指纹 | 本地 `_manifest.jsonl`（随产物） | 随产物包／快照 | 引擎 | `guji status`、close-check、reuse | 小 |
| cache 列图／字块 | 本地 `cache/`（LRU 20 GB） | 无 | 引擎 | Step5+、雪碧图、审阅 | 每册数百 MB 级（推测） |
| runs 任务记录 | 引擎仓根 `runs/` 本地 | 无 | 控制台 | 控制台 | 小 |
| glyph.db | 本地 | 无（可重建） | rebuild／db pull | glyph_match 等 | 220 MB／3 GB |
| 字形库 glyph_store | 中心库 `glyph_*` 表 | 数据目录副本；刻例图 R2 `sha256/*.png` | admit／人裁消费者→db push | rebuild、ex_build | siku 1.86 万例；图 90 MB |
| 字体域 | 引擎仓 `fonts/`（确定性重建） | glyph.db 内 | import-font | glyph_match、rare | — |
| 人裁事件 | 中心库 `events` | 数据目录 | 控制台／H 道／Worker | 消费者、绑定、seed_admit | 2.9 万行 |
| 台账 consumed | 中心库 `consumed` | 数据目录 | 消费者 | 幂等判断 | 5.3 万行 |
| 锚／锚图 | `anchors` 表；图 R2 | 数据目录 | 人裁 | 绑定、训练 | 4,891 行／2,788 张 |
| 册配置 yaml | 中心库 `books` | 数据目录 | 人 | 全管线 | 16 册 |
| workspace.yaml | 中心库 `workspaces` | **guji-workspace git 也有一份** | 人 | 控制台、借库 | 小 |
| 语料库 corpus | 整理本 `corpus_files`＋R2 txt；清单 `files`（`config/corpus-pack/vN`）；底库文件在引擎仓、清单在 `corpus-base` | 数据目录 | 人／`guji corpus build` | align_ref、context_decide、seed_admit… | siku 48 MB |
| 基线包 | R2 `pack/products/<ws>/<册>/<标签>/` | 实验记录 md 在 guji-workspace git | `pack push` | `pack fetch`、`products diff` | 53 对象 242 MB |
| 快照 snap | guji-workspace git 孤儿分支 `snap/*` | vol01 另有 R2 同名包 | `guji snap pack` | `snap import`、freeze | 一册约 10 MB |
| char/cord/norm | book-text main `default/` | 导出目录本地 | export_guji_format.py→PR | 网站（经 data.yml→COS） | 四庫 47 MB |
| proof.json | 只在 legacy 导出与 samples（guji-proof/0.1） | — | guji_format.py | 无现役读者 | — |
| pending.json | 中心库 `files` `feedback/lists/proofing/<书>/<章>.pending.json` | COS `proof/` | pending_list.py＋db sync | 网站、proofing-sync | 每章 0.1–0.25 MB |
| 预裁雪碧图 | open-guji-dataset Release＋book-text 指针（只 001） | COS `proof/<书>/<册>/` | sprite_build/ex_build/alt_build | 精校页 | 每册数 MB（推测） |
| 公众意见 | EdgeOne KV → 中心库 `files` `feedback/lists/web/` | COS `proof/fixes/` | 网站／proofing-sync | H 道 web_opinions.py | 很小 |
| 评测金标 | open-guji-dataset git `items.jsonl` | 中心库 `verdicts`（来源） | `guji gold import` | `guji eval run` | 222 MB |
| 归档包 | open-guji-dataset Release `archive-…` | — | archive_plan.py | `guji archive fetch` | 四庫约 205 MB |
| 每日备份 | R2 `backup/<日期>/`（30 天） | — | 定时会话 | restore-check | 12 MB/天 |

## 十一、断点

### 只在某台机器、丢了就没了（或代价大）
1. **全唐文原图**：qtw-draft `.gitignore` 拦 `data_full/`，中心库不收，未见 IA 以外的归档记录。
2. **bxgb、qtw 的产物**：R2 无产物包；只有本地（qtw 有 09-27 的旧 snapshot make 目录在 Z15 沙箱，已过期）。四庫 vol02、vol03 也没有 `products/siku-zongmu/vol0{2,3}/…` 包（只有落到 `ws` 名下的 `vunknown` 包）。
3. **runs/**、字统网缓存、zhengli-state：本地，丢了可重建但不可追溯。
4. **reports/**（请审单、`cards.alt.json`、Step9 md/html、收尾体检）：中心库不收，只能靠手工提交 guji-workspace git；runbook S8/S20 还让往 overview 写（overview 已淘汰）。
5. **导出目录**（char/cord/norm、lines.md、pages.json、meta）：推 book-text 前只在本地；`pages.json`、`lines.md` 不进 book-text main（生成分支），三阶段 §8 要求「写明落点」仍未定。
6. **glyph.db 里没导出的人裁**：push 前先导出（db push 会做），但跑了消费者却不 sync 的机器上人裁只在本地 glyph.db。
7. **实验分支数据目录、产物**：`$GUJI_DATA_HOME/exp__…/`，分支删了就没了（设计如此）。

### 两处存放、可能不一致
1. **workspace.yaml**：中心库 `workspaces` 表＋guji-workspace git 工作树。
2. **冻结基线**：册 yaml `freeze.snapshot` 指 git `snap/` 分支；R2 有同名产物包；中心库 `freeze_baselines`／`snapshots`／`cv_versions` 表空着。三处没对齐，close-check 只认 git。
3. **待审单**：中心库 → COS；book-text 旧 `pending_file` 已删但校验器保留、网站保留回退。
4. **雪碧图**：设计说 R2 真源，实际走 dataset Release＋book-text 指针。
5. **book-text 分支**：runbook 说 `wip/siku`，规范说 0.1.0 并 main（main 上已有 004–010）。
6. **产物包工作区名**：`products/ws/…` 与 `products/siku-zongmu/…` 两套名。
7. **归档「留」表**：按旧 git 布局写，与中心库数据目录不一致；archive_plan.py 能否从数据目录打包未核。
8. guji-workspace git 里残留 `feedback/web/2026-10-18*.jsonl`、`verdicts.bak-*`、`consumed_bak_*`（中心库不收备份类），以及中心库设计写的「git 每日导出作第二备份」实际没做（git 冻结，备份只在 R2 `backup/`，与图同一个云）。
9. 文档：datastore.md 第五节写 pull 还原到 `<工作区>/output/central/<分支>/…`，第六节写数据目录；book-text ORIGINAL.md 说人裁、字形库在 guji-workspace。

### 没有定论
- GUJI-598 书影落点（原图进 R2？保留 IA？1-bit WebP 是否够 CV 用）。
- GUJI-610 国内通道：现在是每日 Action 拉 KV、发 COS；「国内实测能读能提交」未验；`PROOF_WS` 只配了 siku-zongmu，新书要手加。
- GUJI-627：数据已补，卡未关。
- 雪碧图真源（R2 vs Release）。
- products 正式结果的登记处（main-ptr 只在 vol04–10；freeze 表空）。
- 归档：Release 是公开的，中心库私有；归档后中心库工作区设只读（共享方案 4.2）未实现。

## 十二、建议的存放原则（建议）

1. **按「能不能重算 × 谁要读」分三档**：人产出的、不可重算的 → 中心库（文本行进 Neon，二进制按 sha 进 R2）；可重算但贵的 → R2 包（产物包、索引包、快照），只增不改，带 manifest 和 sha；便宜可重算的 → 本地（cache、glyph.db、runs）。git 只留原图和人读文档。
2. **一个物件只有一个真源，其余都标「派生／缓存」**：freeze 基线收进 `freeze_baselines` 表（指向 R2 包名＋cv＋中心库 rev），不再指 git 分支；snap 孤儿分支逐步退为 R2 产物包。
3. **出 0.1.0 时一次性落盘清单**（建议写进 runbook 出口）：①`guji db sync`；②`products pack push --main`（含 Step1–7，记 rev）；③导出目录（char/cord/norm＋lines.md＋pages.json＋meta）打成 R2 包；④pending.json 进中心库；⑤雪碧图进 R2（顶层 `sprites[]`），由 proofing-sync 发 COS；⑥reports 中要留的（请审单、cards.alt.json、体检）进中心库 `files`（扩 `scope.classify` 收 `reports/<册>/*.md|json` 小文件）或随产物包。
4. **原图**：新书原图进 R2（按 sha，私有或按哈希公开同刻例图），guji-workspace git 不再增长；IA 只当来源。全唐文先补齐。
5. **网站只读 COS**：中心库→COS 用一个 Action，书单从中心库 `workspaces` 自动列，不靠 `PROOF_WS` 手配。
6. **防名字漂移**：`pack push` 拿不到工作区 id 时报错而不是回退 `ws`；清理 `products/ws/*`。
7. **归档**：「留」表改成「中心库该工作区的 `db pull` 数据目录＋R2 图＋1.0.0 产物包名＋原图位置」，Release 只放脱敏后的公开部分；中心库工作区设只读。
