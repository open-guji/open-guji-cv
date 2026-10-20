# A. CV pipeline 段调研笔记（GUJI-636 M9 平台粗校流程梳理）

调研日期 2026-10-20（洛杉矶）。只读。仓库 `/home/user/open-guji-cv`，检出分支 `claude/tender-lovelace-5pjy19`（= main `07d846d`（v0.4.7+1）再加 #251/#256/#266 三个提交）。
远端：`origin/rc/v0.4.8` 为当前待发分支（`af4c3e9` 开，最新 `d235520`）；PR #255（页级并行提速）是 **draft、未合**，分支 `claude/youthful-meitner-zub00i`，base 写的是 `main`（不是 rc/v0.4.8）。
补充参考（不在 cv 仓，但流程里点名）：ai-team `team/整理/重跑vol04-10/`（vol04–10 粗校实跑记录）、`team/整理/GUJI-543/pending_list.py`、`team/整理/GUJI-557/*`、`team/整理/GUJI-556/异常表模板.md`、`team/整理/设计/文本整理三阶段流程.md`（R1–R6 定义）。

标记：【事实】带出处；【推测】为我的判断。

---

## 0. 关键文件索引

| 主题 | 文件 |
|---|---|
| 一册书标准流程 | `doc/runbook/整理一册书.md`（432 行，v2 2026-10-06，后续多次补丁） |
| 执行脚本 | `scripts/zhengli/zl.py`（990 行）、`collect_exit.py`（R1–R5 取数）、`exit_report.py`（拼报告）、`s8_vision.py`、`snap_import.py` |
| 交付体检 | `open_guji_cv/ops/close_check.py`（322 行）、`ops/release_gates.py`（2c/2d） |
| CLI 入口 | `open_guji_cv/cli_v2.py`（`add_parser` 在 2459–3015 行）、`cli_db.py`、`cli_exp.py`、`cli_glyph_db.py`、`cli_products.py` |
| 管线定义 | `open_guji_cv/pipelines/keben_body_v2.yaml` |
| 中心库 | `doc/datastore.md`（第五、六、七节） |
| 受控重跑 | `doc/受控重跑.md` |
| 版本规矩 | `doc/版本号规矩.md` |
| 人审率分析 | `doc/research/人审率分析-vol04-09/`（分析报告.md、README.md、TSV、M7交接/、切分缺陷清单/） |
| 切分现状 | `doc/research/切分现状梳理与新方向-2026-10-19.md` |
| 内存诊断 | `doc/research/pipeline单进程内存诊断-2026-10-17.md` |
| 格级复用 | `doc/design/12-重跑粒度-格级复用设计.md` |
| 人裁锚定 | `doc/design/15-人裁锚定与重切后重绑定.md` |

---

## 1. 管线本体（keben_body_v2）

`open_guji_cv/pipelines/keben_body_v2.yaml`（2026-10-18 删 Step5-c `ocr_candidates`、Step6b `group_decide`）：

```
page_survey(Step0) → border_detect(Step1) → column_warp(Step2，挂 column_gate 闸) → row_segment(Step3)
→ cell_shrink(Step4) → glyph_match(5-a) → rare_candidates(5-b) → align_ref(5-d) → context_decide(Step6) → seed_admit(Step7)
```
闸：`border_detect_gate`、`column_gate`、`row_segment_gate`（collect_exit.py `GATES`）。
产物：`<ws>/products/<book>/<step>/pNNNN.json` + `_manifest.jsonl`；图像缓存 `<ws>/cache/<book>/<kind>/`；任务记录 `runs/`。

Step5–7 要点（`doc/design/Step5-7-操作一览.md`）：只有 Step7 定放行；5-a 三档 same(cov≥0.996 & wmax≤12)/unsure(0.85–0.996)/diff；共识升档（cov≥0.99、比次优异字高≥0.03、≥3 例人裁）；5-d 两种对位（8-gram+difflib；`align: coord` 坐标对位，格数对不上退回）；Step6 门槛 margin 0.70，只重排不改字；Step7 十条通道 + 补放（witness3/coord/seal/rare_ref/juan_rule/variant_tie/group_flow…）+ 闸（occluded/nonchar/runt/shadow_veto…）。

**指纹（判新鲜）**：sha256(step.version, params, code_hash, 上游产物 sha)。code_hash = 本 Step 模块 + `code_deps` 源码哈希（`doc/console_manual.md` §1）。2026-10-06 起只认代码不认注释。
**字形库指纹**：`glyph_match.db_fingerprint` 自 2026-09-25 起是 **soft param**——记录、不判过期（`steps/glyph_match.py` 模块头 60–70 行）；要吃新库用 `guji recheck`。`seed_admit` 的 `human_verdicts_fingerprint`、`approx_fingerprint` **是硬参数**（10-19 夜 db sync 引入他人人裁导致 vol04–10 全部 stale 即此，见 §6）；`glyph_pin: N` 把它换成 `glyph-gN`（`doc/受控重跑.md` 一）。
**语料钉**：册 yaml `corpus: N`，五步（glyph_match、rare_candidates、align_ref、context_decide、seed_admit）指纹只认版本号；开跑前核清单，漂移拒跑（`GUJI_CORPUS_DRIFT=warn` 绕）。
**cv 版本护栏**：册 yaml `cv_version: "x.y.z"` → `step/pipeline` 版本不符拒跑（退出码 2），`--allow-cv-mismatch` 绕（`doc/版本号规矩.md` 五）。
**格级复用**：`core/reuse.py`，Step5-a/5-b 按格 `bbox_page`±1px 复用旧记录（`doc/design/12` §六）；`GUJI_NO_REUSE=1` 关。

---

## 2. CLI 子命令（`cli_v2.py` add_parser 实况，2026-10-20 检出）

pipeline, step, rerun, binarize, preclean, split, locate-gutter, witness-align, witness-align-stream, calibrate, survey, calibrate-font, seed-witness, import-pdf, snapshot, release, deploy, archive, snap, status, close-check, export, audit, store, recheck, fp-migrate, console, cache, batch, label-batch, events, eval, gold, product, check, cards, rare, corpus, glyphlib, promote, variants, collate, progress, runs；
另注册：`db`（cli_db.py:202：migrate/pull/push/sync/status/branch/import/diff）、`exp`（cli_exp.py:175：run/report/flips/list/ui）、`glyph-db`（cli_glyph_db.py:139：rebuild/import-font/stats/export…）、`products`（cli_products.py:88：diff、pack push/fetch/list/push-index/fetch-index、rc/v0.4.8 加 promote、exclusions）。

关键参数：
- `status <book> --pages dev_set|all|3-6 --json`（输出首行是「工作区 …」头，需截到第一个 `{`）；**`status` 用 `code_ok=False`（严口径）**（`core/engine.py:494`）。
- `close-check <book> --pages all --export-dir --chapter --notes --tier final|rough --strict-cv --pending --json`（cli_v2.py:2712–2727）。
- `audit admitted|jys|count|sheet|alt|alt-eval`（2739–）。
- `export md|format`（2729–）；`format` 只出 lines/pages/norm，char/cord 仍要 `scripts/export_guji_format.py --format char-cord`。
- `recheck --chars/--verdicts/--dead/--all/--dry-run`；`rerun <book> --stale`；`fp-migrate --code-formula/--trust --apply`。
- `pipeline --jobs` 缺省 = CPU 数（cli_v2.py:2459），但 main 上只有 `border_detect`、`line_detect` 标 `parallel_safe=True`，其余步 `--jobs` 不起作用（PR #255 才加）。

---

## 3. runbook 端到端（`doc/runbook/整理一册书.md` 精读）

### 3.1 规矩（0.2 七条，40–51 行）
不改 cv 代码（开 `[整理→CV]` 卡）；人裁只经控制台或 guji 写；不加 `--force`、只从受影响最上游起跑；审期间不整册重算；整理本和证人都不是标准答案；提交只 add 具体文件；问人攒成一张请审单。
交付物：`NNN.char.json`、`NNN.cord.json`、`NNN.norm.json`，推 book-text `wip/siku` 分支（40 行）。

### 3.2 脚本 zl.py（〇·五，13–28 行；代码 `scripts/zhengli/zl.py:809–831`）
步骤：`env → ws → yaml → [import-snap] → survey → compute-a → calibrate → glyphdb → cache-verify → rare → compute-b → snap-pack → audit → contact → vision-gate(闸) → sheet(闸) → human-count → export → taboo → close`。
没覆盖（要人/会话）：S4 异常页看图、版面先验抄值、S8 看图、S11 第 4 节、S12 人裁、S14 提交、S15 入测试集、S18 目测、S19 推 book-text、S20 收尾记录（26 行）。
**runbook 自述「尚未整册实跑」**（28 行）。

### 3.3 各步（S1–S20）

| 步 | 命令（原文） | 输入 | 输出/写到哪 | 验收 | 耗时（文档数字） |
|---|---|---|---|---|---|
| S1 环境 | `uv venv .venv --python 3.12 && uv pip install -e ".[console,torch,dev,shadow]" ruamel.yaml`；自检 `import torch, scipy, cv2, joblib, sklearn` | — | .venv | 能 import；`guji status` 出表 | — |
| S2 仓与资源 | `guji db sync -w $WS`（首次 `db migrate`，新机器 `db pull`，要 `GUJI_DATA_TOKEN`）；云端 ws 稀疏克隆约 700MB | 中心库、guji-workspace（原图） | 数据目录 `$GUJI_DATA_HOME/<分支>/<ws id>/` | 卡上记 cv、ws 提交号（一册钉一个 cv 提交） | 拉库 4.5 分（vol04 实跑，ai-team） |
| S3 书 yaml | 标准 seed_admit 11 键 + `iron_gate: true`；`guji calibrate <册> -w $WS --pages all --with-bottom-gap` 抄 `period_prior`/`bottom_gap` | 册 yaml（中心库） | 册 yaml | 缺 `period_prior` 被闸 2/3 拦；calibrate 必须在 column_gate 之后 | — |
| S4 预检拆页 | `guji survey <册> -w $WS`；`guji locate-gutter` | 原图 | — | 异常页逐页看图三选一，拿不准停 | — |
| S5 Step1–7 | `guji pipeline keben_body_v2 <册> --pages all -w $WS`；推荐 `--to cell_shrink` → S6 建库 → S5-b → 一次 `--from glyph_match` | 原图、yaml、glyph.db、语料 | products/cache | status 全新鲜、失败 0；记人审率 | 4 核 Step1–4 约 15 分，Step5–7 约 60 分（glyph_match 10–13 s/页）（145 行）；分块口径 Step1–4 5s/页、Step5–7 25–30s/页（149 行） |
| S5-b rare | 备表：导包 `guji snap import snap/96mid1ogzk/rare-index-vol08/20260928T1136 …` 或 `guji cache build-rare-index --book <册> --jobs 4 -w $WS`；`guji cache warm --book <册> --pages all --jobs 4`；`--from rare_candidates --to rare_candidates` 后 `--from seed_admit` | CNN 模板表 `models/glyph_cnn_r5/emb_<key>.npz` | products | 不跑则 rare_ref 通道 0 格 | 冷建表 45–50 分（单核）/10 分（4 核）；预渲 121 页 288 s；5-b 整册约 6 分（1.4 s/页） |
| S6 字形库重建 | `guji glyph-db rebuild -w $WS --no-borrow`；`guji glyph-db import-font -w $WS --edition font:jigmo --jobs 4`、`font:iming`；`guji glyph-db stats` | 字形库真源 + 字体 | `output/glyph.db`（230MB→3.1GB） | 两域都有数 | jigmo 约 8 分 20；ai-team vol04 实跑 jigmo 7.3+iming 4.3 分 |
| S7 缓存校验 | `guji cache verify --book <册> -w $WS [--fix]` | cache | — | 错位 0 | 约 5 分 |
| S8 放行错穷举 | 先 S9，再 `guji audit admitted <册> -w $WS`；联系页 `scripts/zhengli/s8_vision.py`；分层抽 300 格看图 | 对勘 json、产物 | `$WS/reports/<册>/<册>.放行错穷举.md/.json`；复制到 overview `书/<册>/放行错穷举-vN.md` | 认字差异档逐格看图 | vol03：355 格=认字 36/异体 196/系统性 123 |
| 看图结论入库 | `guji events import-vision $WS/reports/<册>/看图结论.jsonl --book <册> -w $WS [--dry-run]` | jsonl | `feedback/vision/vision-看图结论.jsonl` + 分片 `char-recognition/vision-checks` | wrong 的格回待审，挂 vision_flag | — |
| S9 对勘 | `guji collate <册> --console "" -w $WS` | 证人 | `reports/<册>/collation_*.{html,json}` | — | — |
| S10 己已巳 | `guji export format …` 后 `guji audit jys <册> -w $WS --export-dir …` | lines.md | `<册>.己已巳.md`、`.muse_input.jsonl` | 逐格按文意判 | export 15 s |
| S11 请审单 | `guji audit sheet <册> -w $WS` → `reports/<册>/<册>.请审单.md`；控制台 `guji console --no-auth` | 待审队列 | 请审单；云端做 Artifact 审查页，回复后 `POST /api/events` 代写 | 一次一类活、≤30 分钟 | — |
| S11-b 相似字 | `guji audit alt <册> -w $WS --fetch-zi` → `reports/<册>/<册>.cards.alt.json`；`python3 <ai-team>/team/整理/GUJI-543/pending_list.py …`；`python3 <ai-team>/team/整理/GUJI-557/alt_build.py …` | 卡片、CNN | cards.alt.json；雪碧图 `alt-<章>.webp` 同步上 COS | 「待审 N 格，出 alt M 格」 | 0.1–0.15 s/格；字统网首次十几分钟到半小时 |
| S12 人裁核数 | `guji audit count <册> -w $WS --since <时间> [--expect <清单>]` | 事件 | — | 退出码 0；无漏审、事件带锚 | — |
| S13 收尾闸 | `guji status <册> --pages all -w $WS --json` 看 `closure_gaps`/`closure_mismatches` | — | — | closure_gaps=0 | — |
| S14 推中心库 | `guji db sync -w $WS [--dry-run]`（= `guji store commit`/`db push`） | 数据目录 | 中心库（Neon Postgres + R2） | close-check 第 8 项 | — |
| S15 入测试集 | `guji gold import <分片> --book <册> --ids <清单> --dry-run` | 裁决表 | open-guji-dataset | updated=0 | — |
| S16 Step9 | `guji export md <册> -w $WS` → `reports/<册>/<册>.md` + `.approx.tsv`；`guji collate` | — | reports | — | — |
| S17 char/cord/norm | 有人裁先 `--from seed_admit`；`python scripts/export_guji_format.py --products $WS/products --book <册> --chapter NNN --meta doc/formats/samples/guji_format_v0.1/meta_volNN.json --out <dir> --format char-cord --keys cv`；`--split-table doc/formats/samples/guji_page_v0.2/split_table_siku.json` | products | `<dir>/NNN.char.json/cord.json/norm.json` | char 字数 = 定字格数 − 非字格数 | 导出 15 秒（ai-team） |
| S18 框抽检 | `python scripts/check_pages_json_boxes.py --pages-json … --n 20 …` | pages.json | png | 目测 20 字以上 | — |
| S19 推 book-text | 官方 `open-guji/book-text` 的 `wip/siku` 分支，只替换本章 char/cord/norm、改 index.json；目录 `Book/g/z/k/96mid1ogzk/` | — | book-text | 告诉文本总管 | — |
| S20 收尾 | `guji close-check <册> -w $WS --export-dir <S17 目录> --notes <overview>/项目进展/新书整理/书/<册>`；`python scripts/zhengli/collect_exit.py <册> -w $WS --export-dir <目录> --anomaly <册>-异常表.md -o input.json --report 粗校报告.md`；写 `overview/项目进展/新书整理/书/<册>/收尾记录.md` | — | 报告 | 机器项全过 | close-check 约 5 分（慢在 1b 缓存校验）；ai-team 实跑 5–12 分 |

另：2c/2d 两张单在数据目录 `feedback/lists/`：`<册>-重切清单.tsv`（`位置<TAB>原因`）、`<册>-对不上列交代.tsv`（`页<TAB>列<TAB>处理<TAB>说明`，处理 = 重切/改字/说明/一致）；人工整列定格写 `feedback/verdicts/char-segmentation/manual-cells/items.jsonl`，重跑 `--from row_segment --to seed_admit --pages <页>`（370 行，2026-10-20 vol01 18 列）。
避諱改字表（第 7 项）：zl.py `taboo` 步从 lines.md 生成 v0，会话补一句；**此前 S1–S20 没有一步产出它**（372 行）。

### 3.4 度量（第六节）
人审率 = 请审单定稿时待审格数 ÷ 总格数（另报含第 4 节改判口径）；准确率 = S8 分层 300 格；介入次数；总耗时；token；CV 卡。

---

## 4. 粗校完成判据

### 4.1 close-check 检查项（`ops/close_check.py`）
| 编号 | 名 | 机器判法 | 粗校档 rough |
|---|---|---|---|
| 1a | 产物新鲜 | `eng.status(code_ok=not strict_cv)`；只因代码/版本变了且 manifest 记正式 cv_version 的页算新鲜（v0.4.7 改）；册有 `freeze:` 时比快照 sha | 计 |
| 1b | 缓存不错位 | `cache_verify.verify_book(fix=False)` | 计 |
| 1c | 模型在场 | 本机有 torch、切点裁判权重、CNN 权重；rare_candidates 有字的页都有 emb 候选 | 计 |
| 2 | 待审清零 | `review.cards(only="review", skip_decided=True)` 计数；扣重切清单上的格；单列 vision_flag 数；**缺字形库直接 ERROR**（防假绿） | **只报数、恒 PASS**（`--tier rough`，Maren 10-17 定） |
| 2b | 收尾闸 | `closure_gaps`=0（已定字却没出字）；mismatches 报告项 | 计 |
| 2c | □ 有去向 | 导出文本每个 □ 在 `--pending` 或重切清单上（要 `--export-dir`） | 计（0.1.0/1.0.0 硬项，GUJI-624） |
| 2d | 对不上列有交代 | align_ref `coord_fallback` 列逐列在列交代单或重切清单；一页 ≥3 列没交代报 hot_pages | 计（硬项） |
| 8 | 推进中心库 | 迁过的工作区：数据目录没有未推改动；没迁直接 FAIL | 计 |
| 10/11 | lines.md / pages.json 自洽 | 每个字有框、无多余框（要 `--export-dir`） | 计 |
| 12 | Step9 产物 | `reports/<册>/<册>.md` 与 `collation_*.html` 存在 | 计 |
| 7/13 | 避諱表、收尾记录 | `--notes` 目录下文件存在 | 没给 notes 即 SKIP |
| 3/4/5/6/9/14 | 队列外改判、切分着落、己已巳、对勘、测试集、修图记录 | MANUAL | — |

退出：`machine_ok` = 非 manual/skip 项全 PASS。
注意：模块 docstring 第 8 项仍写「工作区 git 里没有未提交改动」，代码已改为中心库口径（docstring 过期）。runbook 第五节表说第 9 项「能机器判」，代码里是 MANUAL。

### 4.2 粗校出口 R1–R5（`scripts/zhengli/collect_exit.py` + `exit_report.py`；定义在 ai-team `设计/文本整理三阶段流程.md` 90–95 行）
| 项 | 标题 | 取数 | 结果 |
|---|---|---|---|
| R1 | 全部页步骤跑完，固定 CV 版本下无 stale | `guji status --pages all --json`（**严口径 code_ok=False**）+ close-check 1b + 2b | PASS/FAIL |
| R2 | 三道闸失败列都有去向 | `gates.query.blocked_units`（border_detect_gate/column_gate/row_segment_gate）对照异常表「现象」栏里的 pN/colM（有结论的行） | PASS/FAIL |
| R3 | 人审率（目标 <1%，不卡出口，须写原因） | close-check 第 2 项 class_counts ÷ 导出 pages.json 全部 cells | REPORT（必须有数字 + `--reason`） |
| R4 | 异常清单都有结论 | 解析异常表 md（行号必须纯数字，第 4 列结论非空） | PASS/FAIL |
| R5 | 导出过格式检查 | close-check `--tier rough` 机器项全过（老 cv 无 --tier 时手工剔第 2 项） | PASS/FAIL |
总判：R1/R2/R4/R5 全 PASS 且 R3 有数字和原因 → 可出 0.1.0（exit_report.py 退出码 0）。
**R6**（用户 10-19 定）：整页/整列不丢字不错位——闸1 页级跳过的页逐张看图、`colgap.py`、`widthscan.py`。**collect_exit.py 不取 R6**；colgap/widthscan 不在 cv 仓（推测在 ai-team 某处）。
异常表模板 `异常表模板.md` 在 ai-team `team/整理/GUJI-556/`，cv 仓里没有（collect_exit.py:297 帮助文字引用它）。

### 4.3 人审率口径（至少三套，数字互不可比）
1. runbook 第六节：请审单定稿时待审格 ÷ 总格数。
2. collect_exit R3：close-check 审卡队列（含 vision_flag、扣重切清单）÷ pages.json 全部 cells（含非正文、标题槽）。
3. 人审率分析：未放行、**非标题槽**、去掉刚重裁页 ÷ 160,159 格 = 1.02%（vol04–09）。
4. book-text pending.json（`pending_list.py`：seed_admit admit=false 且不含 excluded）与 close-check 队列差「非字格」（GUJI-555 vol04 466 对 454，差 12 格，runbook 343–348 行）。

---

## 5. 每册人审数（数字与来源）

### 5.1 粗校报告 R3（ai-team `team/整理/重跑vol04-10/volNN-粗校报告.md`，cv rc/v0.4.5–0.4.6）
| 册 | 页 | 待审/总格 | 率 | 分类（close-check class） |
|---|---|---|---|---|
| vol04 | 221 | 303/34515 | 0.88%（看图判错 70） | 其他 120、印章遮挡 52、库缺字 41、近形字 34、替换对齐 23、参照冲突 16、己已巳 13、异体 4 |
| vol05 | 188 | 275/28950 | 0.95% | 其他 115、近形 37、库缺字 34、替换对齐 28、参照冲突 23、己已巳 16、遮挡 15、异体 7 |
| vol06 | 150 | 231/23488 | 0.98% | 其他 72、参照冲突 39、替换对齐 39、库缺字 30、己已巳 18、近形 18、遮挡 11、异体 4 |
| vol07 | 135 | 203/21174 | 0.96% | 其他 77、遮挡 32、替换对齐 28、己已巳 21、参照冲突 15、近形 13、异体 9、库缺字 8 |
| vol08 | 69 | 197/10698 | 1.84% | 参照冲突 73（书类存目整理本书名卷数多处不同）、其他 42、替换对齐 19、遮挡 18、近形 16、库缺字 16、己已巳 8、异体 5 |
| vol09 | 265 | 489/42022 | 1.16% | 其他 155、参照冲突 76、替换对齐 68、近形 46、库缺字 46、己已巳 45、遮挡 43、异体 9 |
| vol10 | 175 | 312/28929 | 1.08% | 其他 122、替换对齐 49、库缺字 36、遮挡 31、近形 31、参照冲突 21、己已巳 16、异体 6 |
全部「可出 0.1.0」。README 同一处的数字与报告不一致：vol04 README 写 437/34522=1.27%（早一轮）、vol09/vol10 README 称「遮挡 272/262 格占一半/八成以上」，而 class 里印章遮挡只有 43/31（【推测】272/262 是 doubt=occluded 计数口径，与 class 不同）。
更早：vol04 v0.2.0 466/34523=1.35%（ai-team GUJI-555）；vol03 13/17366=0.07%（vol03 已大量人裁）；vol01 R3 FAIL「取不到待审数（待审 0 格）」（GUJI-556/vol01-粗校报告.md，10-17）。

### 5.2 人审率分析 vol04–09（`doc/research/人审率分析-vol04-09/分析报告.md`，cv rc/v0.4.6）
口径：未放行、非标题槽、去掉 vol04 p216–218、vol07 p128/130；1,641/160,159 = 1.02%。
各册率：vol04 0.78%、vol05 0.93%、vol06 0.96%、vol07 0.95%、vol08 1.81%、vol09 1.16%（29 行）。
各册格数（由 TSV 算）：vol04 267、vol05 269、vol06 226、vol07 199、vol08 194、vol09 486。
分类（6 册）：
| 类 | 格 | 占 | 说明/去向 |
|---|---|---|---|
| A 整理本没字 | 373 | 23% | A1 坐标对位说空位 126、A2 整理本〓 90、A3 列格数不符 86、A4 冲突整列退回 69、A5 整页锚不上 2；根因是我们的切分/对位，不是整理本 |
| B 码位异体 | 397 | 24% | 巻↔卷 171（库里卷 40 例巻 0 例；40/40 看图是巻形）、其余 226（別/别 14、出/岀 7…）→ 交 M7 |
| C 形近字组 | 279 | 17% | 己已巳 116、日曰/日目 78、入人八 13、曾會 10、象彖 10、問間 9…；主因 `group_flow_abstain` 163 → M7 |
| D 印章/污损遮挡 | 158 | 10% | 保持人审 |
| E/F/H 冲突/库没有/库=整理本被拦 | 134 | 8% | 后续 |
| G 对齐改字层 | 115 | 7% | 抽 40 格测错率再定采信档 |
| I 其余库 unsure | 185 | 11% | 缺第二证据 |
分册 cls（A..I）：vol04 [81,33,41,41,11,7,10,10,33]；vol05 [71,69,54,15,1,9,14,7,29]；vol06 [64,40,36,11,13,3,34,7,18]；vol07 [39,44,34,32,3,1,16,6,24]；vol08 [28,83,25,17,10,5,11,1,14]；vol09 [90,128,89,42,23,11,30,6,67]。
路线图（81–93 行，含 10-19/10-20 调整）：
1. 空位判非字 —— **撤回**（126 格里 22 整页破损、近方 8–10 格真字、扁条多为半字；只剩纯黑块约 6 格）；改「切分缺陷清单」（P22/F67/S31/B6）。
2. 巻：补库或过渡开关 171 —— 用户定交 M7。
3. 列级对位救援 —— **离线评估后下调为约 0，不做**（救 93/233 列，A3/A4 155 格只 11 格落在可救列，坐标对位不进任何放行通道）。
4. 异体按对图审进用字账 ~150（约 60 次点击）—— 交 M7。
5. M7 补形近字文意规则 100–150。
6. 对齐改字层采信档 70–100（vol03 人裁 197 格里 195 格=整理本）。
7. 切分源头：列长先验 —— A 类主力。`切分现状梳理…` §十二：`row_segment.layout_prior` 修好 A1/A3/A4 281 格所在 187 列中的 95 列（133 格），剩 53 列（104 格）；20 列集中在 5 页整页破损。
预期：1+2 → 约 0.85%；加 3–6 约 0.6%（3 已撤，实际更少）。
**数据不在仓**：卡片全集、patches 在 `/mnt/project-files/人审率分析/data/`；分类脚本未入库（README 35–37 行）。

### 5.3 切分在错误中的占比（`切分现状梳理…` 一节末）
vol04 S8 逐格看 298 格：对 149、错字 26、切分错 18、乱码 85、非字 15——几何类约占八成；七册待审 2204 格里「切分坏」366 格（3%–29%）。Step3/4 活路径约 250 个数值/开关。

---

## 6. 实跑经验（ai-team 重跑vol04-10 README，cv 仓外，但直接是本段流程）
- 每册耗时（云上 4 核）：vol04 Step1–4 40 分（jobs 3）、Step5–7 67 分、close-check 约 9 分、对不上列逐列看图约 1 小时（人工大头）；vol05 27/67 分、导出+待审单+看图交代 25 分、出口 8.5 分；vol06 26/55 分、收尾 40 分（出口跑三遍）；vol07 26/59 分；vol08 25/46 分；vol09 65/51 分、出口 12 分；vol10 38/79 分。
- 并跑：「本册 Step5–7（jobs 4）＋下一册 Step1–4（jobs 1）」墙钟一册约 2.5 小时→约 1.5 小时。
- seed_admit 单进程可吃 6.6 GB；两册 seed_admit 并跑会 OOM。
- **10-19 夜 `guji db sync` 拉进别的会话的人裁 → `rare_candidates`、`seed_admit` 参数指纹变 → vol04–10 全 stale、R1 不过**；每册 `--from rare_candidates` 重跑 12–17 分。经验：出口检查前先 `db sync` 再 `status`。（之后才有 `glyph_pin`。）
- 改 `params.border_detect` 让该册全部 Step1 过期，重跑 `--to border_detect` 约 7 分，下游按内容判新鲜。
- 三道闸、2c、2d、R2、collate 都拦不住整页/整列丢字（R6）；靠 widthscan/colgap + 看图。
- close-check 第 12 项只查文件在不在，vol04/05 用 10-06 旧报告也过了。
- collect_exit 异常表行号写「1b」会被跳过，R2 报找不到去向。
- 空白叶 row_segment_gate「DP 无解」要在异常表写一行，R2 才过。
- 云机重启悄悄杀后台任务。
- book-text：各册开 PR 到 book-text（#182/#183/#185/#190/#193/#195/#197），都改 `96mid1ogzk/default/CHANGES.md`，并行互相冲突要串行合；导出器写 char.json version 恒 0.1.0，已不是 0.1.x 的册出补丁前要先改回线上版本再 `bump_original.py`。

---

## 7. 文档明写的已知问题 / TODO / 负结果 / 手工步骤

1. runbook〇·五：zl.py「尚未整册实跑」；10 个环节仍要人或会话（S4/版面先验/S8/S11-4/S12/S14/S15/S18/S19/S20）。
2. S5 坑：老产物有「自证放行」，重算后待审变多是预期（153 行）；换字形库后 glyph_match 不自动过期，要 `--from glyph_match --force`（154 行，唯一允许 --force）。
3. S5-b：首页现建 CNN 模板表看着像卡死（p3 停 18 分钟）；不预渲字块每页再加 11–13 秒；5-b 没标 parallel_safe；多进程同时冷启动同一册 5-b 会互相踩临时文件（172 行）。
4. S6：不要把 Step1–4 和建库并行（row_segment 14 s vs 3 s/页）；glyph.db 230MB→3.1GB。
5. S7：从别处换进产物或更新字形库后必须先 cache verify，否则重算读到错位字块而状态仍「新鲜」（191 行）。
6. S8「不是真穷举」：只覆盖与证人对得上的格；context 通道是放行错大头；沙箱里不跑 vision-gate 正式导入（会写工作区本体）。
7. S11 云端：审查页 `check_fixedpoint.py` 要 playwright，云端 venv 没装要手装。
8. S11-b：缺 torch 时 `audit alt` 只打一行「CNN 不可用」、一格不出；字统网无数据许可，网站是否排除只来自字统网的候选「待用户定」。
9. S13：「待审队列为 0」不等于真清零（失效老人裁回队列并预勾）。
10. S17：close-check 待审数 ≠ 导出 `review: pending` 数（差非字格，vol04 466 对 454）；精校以控制台/close-check 队列为准。
11. 六·一云端：`guji snap pack` 在稀疏克隆上失败要加 GIT_CONFIG 环境变量；产物不进 git、容器会回收，每次整册算完都要推快照；Windows 快照 CRLF 哈希不对要用 `snap_import.py`；Windows 上 `guji snap` 卡在 fcntl（#413）。
12. `doc/workspace_layout.md` §3.2：跨书共享刻例库（B 层）原写「还不存在」，现在中心库已有 `glyphlib-qkp-v1`（datastore.md 第六节）——工作区文档过期。§3.3 北行日錄 db 是真源的已知缺口。
13. `doc/datastore.md` 三：四庫 `vol01-cutline*.jsonl` 14 个事件 id 相同内容不同；`consumed/glyphdb_admit.jsonl` 178 处重复——「导入照收，等人定」。
14. `doc/research/pipeline单进程内存诊断…`：每个 Step 惰性加载的大对象跑完不释放，连跑涨到 3.0G/4.5G，服务器 `MemoryHigh=3G` 节流成每页 240 s；建议「每 Step 一个子进程」或步间清缓存——**诊断，未改代码**。
15. `doc/research/文档说有但代码里没有.md`：三条防御（R4 细长横条、整理本先只留汉字、先归语义层再 difflib）文档有代码没有，待量。
16. `doc/pipeline_handbook.md` §15.5：「交付基线：目前无一册被认定」（vol02–10 main yaml 与最新快照 sha 均不一致，vol01 无快照分支）。
17. `doc/design/15` §七：P3「还是同一个字吗」卡不急做；P4 排除名单/切线裁决/逐列字数裁决并入锚定机制未做（rc/v0.4.8 加了 `guji products exclusions` 处理排除清单重切后改号）。
18. `doc/cloud_eval.md` §5：scipy 没进任何 extra；10 个评测读 v1 链产物（已标 skipped）；char_ocr/font_fallback 云端跑不了。
19. 服务器人审平台 runbook 六：2 核 7.4G 不跑整册重算；`GUJI_FORBID_INLINE_INDEX=1`；vol06–10 从未建过列图缓存（§十三）。
20. `doc/console_manual.md` 开头：切线/夹注/异体三个 tab 用法「待补」。
21. 人审率分析：分类脚本未入库，数据在共享盘。
22. 切分现状 §十二：坐标对位按格位配字、格号漂移对它影响多大「未核」。

---

## 8. 我读出来的流程问题（标【推测】的是判断）

### 8.1 文档/脚本与「中心库化」（10-19）不同步
- runbook S2 资源表写字形库真源在 `$WS/output/glyph_store/`、`$WS/feedback/events/`（95 行）；S4 坑让在 `feedback/events`、`verdicts`、`glyph_store/instances` grep——10-19 起这些在 `$GUJI_DATA_HOME/<分支>/<ws id>/`，工作区根只剩 `workspace.yaml`、`.central.json`（datastore.md 152 行）。
- **zl.py `st_yaml` 读 `ctx.ws/books/<册>.yaml`（zl.py:445）**——迁过的工作区册 yaml 在数据目录，按代码会报「缺书 yaml」停下【推测：实测会停】。zl.py 也没有 `db pull/sync` 步，`ws` 步仍 git 克隆 ws 拿提交号，`snap-pack` 仍走旧 `guji snap pack`（git 分支快照），不是 `guji products pack push`（R2）。
- GUJI-557 `build_pending_02.sh` 的 `ex_build.py --store "$W/output/glyph_store"` 同样指旧位置。
- close_check.py docstring 第 8 项还写「工作区 git」。
- `doc/console_manual.md` §8 目录速查仍写人裁事件在 `../open-guji-dataset/feedback/events/`、册 yaml 在 `open_guji_cv/books/*.yaml`——都过期。
- `doc/workspace_layout.md` §四「库路径变了产物就该过期——glyph_match 指纹带库指纹」与 2026-09-25 起 db_fingerprint 改 soft param 矛盾；`doc/design/12` §八「人裁进库让库指纹变 → 全量」同样过期。
- RELEASES.md 写「服务器只跟 `production` 分支」，服务器 runbook 写「直接跟 main」。

### 8.2 overview 已淘汰，但流程仍往 overview 写
ai-team CLAUDE.md（2026-10-20）：overview 不再写新东西。runbook S8（放行错穷举复制到 overview `书/<册>/`）、S20（`--notes <overview>/项目进展/新书整理/书/<册>`、收尾记录写 overview）、S2 合扫拆页裁剪表在 overview、S4 修图记录 `Commons修图记录.md`——落点全部失效；close-check 7/13 依赖 `--notes` 目录。**收尾记录、避諱表、放行错穷举的新落点没人定**。

### 8.3 book-text 推送方式与文档不一致
runbook S19 写推 `wip/siku` 分支、不进 main；ai-team 实跑是每册开 PR（book-text#182 等）合并、改 `CHANGES.md`、用 `bump_original.py` 升版本。导出器 version 恒写 0.1.0 是已知坑。pending.json 由 ai-team 的 `pending_list.py` 生成（不在 cv），口径（seed_admit admit=false）与 close-check 队列不同（差非字格、差「排除名单里带无锚老人裁字放回待审」的格，见 pending_list.py 头注）；pending_list 还要 `--review-queue` 才按审卡队列出。

### 8.4 关键脚本不在 cv 仓、没有版本
`pending_list.py`、`alt_build.py`、`sprite_build.py`、`ex_build.py`、`build_pending_02.sh`、`异常表模板.md`、`colgap.py`、`widthscan.py`、`bump_original.py`（book-text）都在 ai-team 或别处的工单目录（GUJI-543/556/557），runbook 用 `<ai-team>/team/整理/GUJI-xxx/` 路径引用；没有测试、没有版本号。人审率分析的分类脚本「在我的临时目录」。

### 8.5 版本/指纹坑
- **R1 用 `guji status`（严口径）、close-check 1a 用宽口径（v0.4.7 起）**：cv 发 PATCH 改了 code_hash 后，1a 过、R1 不过（vol09 实际踩到：Step1 在 #218 前跑，261 页过期）。同一出口两套新鲜判据。
- 人裁指纹在 seed_admit（和 rare_candidates）是硬参数：任何会话 `db sync` 推人裁 → 所有没钉 `glyph_pin` 的册 seed_admit 过期。`glyph_pin` 缺省关、第一次写上本身让 seed_admit 过期一次；runbook S3 标准配置里没有 `glyph_pin`。
- glyph_match 的库指纹不判过期：已过粗校的册看不出它用的是旧库判决（只在 status「漂移」列报页数）；要靠人记得 `recheck`。
- 一册钉一个 cv 提交跑到底 vs 实跑里 vol04–10 混用 rc/v0.4.5 与 rc/v0.4.6（R3 原因栏写「p55、p123 用 rc/v0.4.6 补切」），而 rc 版本号按规矩「不得作为正式依据」；pipeline_handbook §15.5「无一册被认定交付基线」。
- 冻结 `freeze:`、`cv_version:` 护栏、`glyph_pin`、`corpus:` 四种钉子都是逐册手写 yaml，没有一个命令一次把一册「钉成粗校基线」【推测】。
- PR #255 的 `core/code_equiv.py`「代码等价登记」把指纹换回旧哈希——又一条让指纹不等于代码的路径，需要配套审计【推测】。

### 8.6 产物去向不清（products 不在中心库）
三套存产物的机制并存：`guji snap pack`（guji-workspace git 快照分支，runbook 六·一仍要求每次重落都推）、`guji snapshot make`（本机拷贝）、`guji products pack push`（R2，v0.4.7 起；rc/v0.4.8 加三样版本标签 + main 指针 + 实验记录写工作区仓 `experiments/<册>/<标签>.md`）。runbook 没提 `products pack`；zl.py 只会 `snap pack`。「哪份是本册 0.1.0 的正式产物」需要人记。glyph.db、cache 不入库，新机器要重建（字体域 jigmo+iming 约 12–15 分）。

### 8.7 谁也不负责 / 断点
- 「对不上列逐列看图」是人工最大头（vol04 约 1 小时），2d 单子格式定了，但谁来看、看完谁复核不在 cv 文档里。
- 异常表（R4）是手写 md，靠正则解析 pN/colM（宁宽勿窄），格式错就 R2 FAIL。
- 测试集导入（S15）、修图记录（14）、己已巳（5）、对勘（6）全是 manual，粗校档也不查；collect_exit 只看 close-check 机器项。
- 2c 依赖 book-text 的 `NNN.pending.json`：先有 pending 才能过 2c，而 pending 由 ai-team 脚本在导出之后生成——cv 出口检查依赖下游产物，顺序是「导出→pending_list→close-check」【推测：容易漏给 --pending，此时只认重切清单】。
- close-check 第 12 项只查文件在不在（用旧报告也过）。
- `vision_flag` 格在 close-check 队列里但导出不为它造 pending glyph（S17 末）。
- 粗校档第 2 项恒 PASS，人审率只「报」，没有任何阈值闸；R3 原因栏要人写一句（`--reason`）。

### 8.8 人审率口径与分类不统一
close-check class（其他/库缺字/印章遮挡/近形字/己已巳/替换对齐/参照冲突/异体）与人审率分析 A–I 类不是一套；collect_exit R3 原因栏自承「根因未逐类核」，「其他」常占 35–45%。分母也不同（含不含标题槽、非正文）。同一册 vol04：0.78%（分析）、0.88%（粗校报告）、1.27%（README 早一轮）、1.35%（v0.2.0）。

---

## 9. 性能

### 9.1 各步耗时数字
- runbook S5（4 核云端）：Step1–4 约 15 分、Step5–7 约 60 分；glyph_match 10–13 s/页；分块口径 Step1–4 约 5 s/页、Step5–7 25–30 s/页。
- ai-team 实跑：Step1–4 25–65 分、Step5–7 46–79 分；单册墙钟约 2.5 小时，并跑后约 1.5 小时。CHANGELOG 0.4.7：「云上一册 1.5–2.5 小时」。
- S5-b：冷建 CNN 模板表 45–50 分单核 / 10 分 4 核；R2 取回 30MB 约 4 秒（`products pack fetch-index`）；预渲字块 2.4 s/页；5-b 约 1.4 s/页，整册约 6 分。
- 字体域：jigmo 7.3–8.3 分、iming 4.3 分；glyph.db 3.1GB。
- close-check 5–12 分（慢在 1b 缓存校验）；cache verify 约 5 分。
- 中心库：db pull 4.5 分（vol04 拉库）；从空目录拉 qtw-draft 7 分；北行旧版逐张签 17 分。
- `doc/design/12`（bxgb 54 页旧数，含已删 OCR）：glyph_match 12.7 s/页 38%、ocr 17.0 s/页 34%、border_detect 6.9 s/页 13%；格级复用后全书 45 → 25.9 → 11.4 分。
- PR #255 描述：4–10 册耗时 glyph_match 49%、row_segment 23%、seed_admit 10%。

### 9.2 已做的优化
- 格级复用（Step5-a/5-b，2026-09-20）。
- db_fingerprint 改 soft（2026-09-25），人裁进库不再全书 glyph_match 过期；`recheck` 点名。
- `cache build-rare-index --jobs`、`cache warm --jobs`、`products pack push-index/fetch-index`（索引存 R2）。
- 真刻例原型缓存两档（5-b 25 分 → 6 分）。
- `RunContext._raw` 上限 2 页（09-27）；`_emb_cache` 修颠簸（09-28）。
- 中心库：只要变了的文件、按 sha 公开 CDN 取图、push 只传新图、R2 工作区快照。
- `glyph_pin`/`corpus:` 防无谓过期；`fp-migrate` 只改写指纹不重算。
- 并跑（本册 5–7 + 下册 1–4）。
- **PR #255（draft，未合，base=main）**：页级并行 row_segment/cell_shrink/glyph_match/seed_admit（`core/parallel.py` 登记，不进 code_deps）；vol04 46 页 4 核：border_detect 54→15 s、row_segment 65→26 s、glyph_match 231→80 s、cell_shrink 27.8→9.1 s、seed_admit 82→50 s（整册估 270→90 s），产物逐字节相同；热点：glyph_match 逐页 −24%（331→251 s/46 页）、seed_admit 每页 2.3→0.85 s、context_decide 首页 6–7→2 s（LM 按内容缓存）、align_ref 起跑 16→7 s；代码等价登记 `core/code_equiv.py` + `scripts/code_equiv.py check`。修 `font_candidates._row_norms` 按 id 缓存的真 bug，并给 seed_admit 补 code_deps → **各册 rare_candidates、seed_admit 会判过期**。另加「跑完 Step6 手动推 LM」`products pack push-index`（runbook 改动）。

### 9.3 还缺的
- 单进程内存累积（3–6.6 GB）没修：诊断建议每 Step 子进程或步间清缓存，未做；seed_admit 两册不能并跑。
- rare_candidates 仍未页级并行（runbook 171 行；PR #255 也没登记它）。
- 会改产物的提速没做：glyph_match 合批矩阵乘（快 10 倍但浮点末位变）、少做复核；row_segment 91% 是 U-Net 前向，torch 多线程争抢慢 10 倍（PR #255 doc）。
- 新容器必付：通用 LM 现训约 28 s（PR #255 才加 R2 分发，且要手动推）、glyph.db 字体域重建 12–15 分、glyph_match 每进程建库 HOG 约 17–18 s。
- close-check 1b 缓存校验 5 分钟，每次出口都付；R1/R5 失败重跑要再付。
- 人工环节（对不上列看图 ~1 小时/册、异常表、请审）占墙钟比例未量。
- PR #255 base 指向 main 不符合版本规矩（应进 rc/v0.4.8）；合入后各册 rare_candidates/seed_admit 过期，要排重算窗口。
