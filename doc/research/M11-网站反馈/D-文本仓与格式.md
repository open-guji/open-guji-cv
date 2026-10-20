# D：文本仓（book-text）与格式规范调研 —— 为 GUJI-638「M11 网站反馈流程梳理」

> 调研时间：2026-10-20（洛杉矶）。
> 读的版本：book-text 本地 HEAD `ffbf1d496`（#202），另抓了 origin/main `fd8f15d7f`（#205，比本地新一个提交）；guji-format `0bc3f79`（＝book-text `.github/guji-format.pin`）；book-index-manager `d06dcf8`；open-guji-cv `a00dbdb`；ai-team `f960641`。
> 记法：事实后面括号写出处（仓:路径 或 命令）。**推测**的地方明确标「推测」。

---

## 0. 结论先行（给 M11 设计用）

1. **网站上「一个字」的定位键是格位 key**：`(book_id, 版本目录 key, 册 NNN, a="页:列:格[a|b]")`，校验字是 char 里该格的 `c`，另带 `text_version`。字下标（offset）只是缓存，不能当定位键。
2. **格位 key 在「改字」时稳定，在「拆格／并格／插删格／夹注改判」时会变**。已有实例：#205 把 `90:5:1`、`90:6:1` 改成 `90:5:1a`、`90:6:1a`；#177 把 `90:6:2` 拆成 `2a`／`2b`。
3. **设计上的「不透明稳定 ID」没有进 book-text 的 char**。只有 cord 带可选的 `id`。手补的格没有 `id`。两次 CV 跑出来的同一格，`id` 也约有 6% 对不上。
4. **改文本的唯一入口是 book-text 的 PR**，靠 `bump_original.py` 升版本、写 CHANGES.md。改字有两条来路：CV 重导出（整册覆盖）和人直接改 char／cord（手补、拆格）。**这两条路之间没有「人工改过」的标记，也没有自动回写**。CV 缺补格、删格事件，所以人在 book-text 里补出、拆出的格，下次整册重导会不会被冲掉，没有机制保证。
5. **反馈到修订的追溯链断在两处**：
   - 读者改字意见（`/api/charfix` → 中心库 `fixes.jsonl`）在 ai-team 和 cv 仓里都找不到消费者。
   - CHANGES.md 只写散文、PR 号和卡号，不引意见 id。
   - 「旧 rev／旧 text_version 的意见映射到新格号」要用的对照表目录 `team/整理/修订/` 还不存在。

---

## 1. book-text 的结构

### 1.1 仓的总体

| 项 | 数 | 出处／命令 |
|---|---|---|
| 条目 manifest | 8,791（Book 9、Work 8,782） | `git ls-tree -r --name-only HEAD \| grep 'manifest.json$' \| cut -d/ -f1 \| sort \| uniq -c` |
| 版本 kind | transcription 11,222、collated 65、self_collated 2 | 同上，`git cat-file --batch` 后 grep `"kind"` |
| `is_original: true` 的版本 | **2 个，都在四庫總目 `96mid1ogzk`**（`default/`、`cv-proof/`） | 同上，grep `"is_original": true` |
| `.md` 文件 | 164,041 | `git ls-tree -r --name-only HEAD \| grep -c '\.md$'` |
| 仓里的 `*.pending.json` | **0**（10-20 起不再放进本仓） | `git ls-tree -r --name-only HEAD \| grep pending` 为空；book-text `docs/ORIGINAL.md` §二 |
| 仓里的 `*.decision.json` | **0**（只有 `scripts/tests/fixtures/decision/` 下的夹具） | 同上 grep `decision.json` |
| 远端分支 `derived` | **不存在** | `git ls-remote origin \| grep -i derived` 无结果 |

条目布局：`<Work|Book>/<c1>/<c2>/<c3>/<id>/`，分片目录取 id 的尾三字符（book-text `README.md`；guji-format `spec/07`）。每个条目下有：

- `manifest.json`：列出全部版本；`versions[0]` 永远是 `default`。
- `default/` 与其他 `<key>/` 版本目录：每个目录里有 `index.json`（章目录）＋各章文件。
- 另外可能有 `fragments/`、`sources/`。

### 1.2 两类正文

**（a）转录本、整理本（非 original）**：每章一个 `NNN.md`，整理本另有同名 `NNN.json`（sections，由 md 派生）。

- 转录本例：`Book/8/e/8/96kzkdm8e8/`。注意它是**《紅樓夢》程甲本（維基文庫）**，不是四庫總目。`default/001.md`…`120.md` 是纯段落 md，章首写 `## 第一回…`。`index.json` 记了 `revision: "1.0.0"`，但这个字段不维护（book-text `README.md`「版本」节）。
- 整理本例：`Work/0/0/0/d59f2mox0000/default/001.md`，内容是 `# 易類`／`## 易類`／一行一条书目。`001.json` 是 `sections[{level,type,title,content,work_id}]`。
- md 记法见 guji-format `spec/03-guji-markdown.md`、`syntax.md`。
- **转录本、整理本不跟踪版本**（book-text `docs/VERSIONING.md` §二）。

**（b）original（四庫總目 `Book/g/z/k/96mid1ogzk/`）**：**没有 `NNN.md`**。main 上只放真源 JSON：

| 文件 | 是什么 | 规范 |
|---|---|---|
| `NNN.char.json` | 每格定下的字；**文本线版本号就是它的顶层 `version`** | guji-format `spec/02` |
| `NNN.cord.json` | 每格像素框（IIIF canvas 坐标），不存字 | `spec/01` |
| `NNN.punct.json` | 标点、分段、标题符（v0.2） | `spec/04` |
| `NNN.entity.json` | 专名，链 book-index | `spec/05` |
| `NNN.norm.json` | 异体→通行字（现在全是空 `items: []`，94 字节） | `spec/06` |
| `index.json` | 章条目：`*_file` 声明，`text_version`／`punct_version`／`entity_version` 镜像，`proofing`，`pages`，`headings`（目录缓存） | `spec/07` §3.3 |
| `CHANGES.md` | 每次升版本一行：`日期｜册｜线｜旧→新｜说明｜PR` | `spec/07` §三·4 |

- `lines.md`、`rich.md` 按规范是生成物，应放 `derived` 分支（book-text `docs/ORIGINAL.md` §一、§四）。**但远端现在没有 `derived` 分支**（见 1.1）。网站阅读页按「对读章」直接读 char＋cord（book-index-manager `ui/src/components/TextReader.tsx:46-48` `isDuiduChapter`）。
- 文件清单命令：`git ls-tree -r -l HEAD Book/g/z/k/96mid1ogzk`。
  - `default/` 下有 001–010 的 char、cord、norm，001–003 另有 punct、entity，以及 `CHANGES.md`、`index.json`。
  - `cv-proof/` 下只有 003 的 char、cord、norm，以及 `CHANGES.md`、`index.json`。
- 另有仓根 `proof/96mid1ogzk/001/sprites.pointer.json`：`{tag:"proof-96mid1ogzk-001-2", manifest_sha256, rev:"001-r2"}`，是雪碧图指针（F-OV-09／11 用）。

### 1.3 用户点名的几样，逐项核对

| 用户问的 | 有没有 | 详情与出处 |
|---|---|---|
| 字→格号（页／列／格）映射 | **有，而且是主键** | char 每格 `{"a":"3:4:6a","c":"兩"}`，`a`＝`页:列:格[子列]`。cord 用同一个 `a` 挂像素框。页号→IIIF canvas：`https://data.kaiyuanguji.com/iiif/<book>/canvas/<册2位>/<页4位>`（book-text `docs/ORIGINAL.md` §三；guji-format `spec/02` §二） |
| `proofing` 字段 | **有** | `index.json` 的 `chapters[]` 里。0.x 时必须为 `true`（F-OV-06）。vol01 已是 1.0.0，仍写着 `proofing: true` |
| pending 文件 | **曾有，已删** | 10-20 起待审单只放中心库 `feedback/lists/proofing/<书>/<章>.pending.json`，每日发 COS `proof/`。book-text#200 删了 vol01 的 `001.pending.json` 和 `pending_file` 字段；F-OV-07 保留（有就校验）。出处：book-text `docs/ORIGINAL.md` §二；ai-team `team/整理/设计/待审单与公众意见走中心库.md`；`文本整理三阶段流程.md` §6.2 |
| `text_version` | **有** | 章条目 `text_version`＝char 顶层 `version`（F-OV-01）。punct、entity 顶层也有 `text_version`，表示对着哪一版文本做的 |
| CHANGES | **有**，`default/CHANGES.md`、`cv-proof/CHANGES.md` | 只有 `bump_original.py` 能写（book-text `CLAUDE.md`） |
| 修订对照表 | **book-text 里没有** | 设计要求放 ai-team `team/整理/修订/<册>-r<n-1>_to_r<n>.tsv`，由 `revision_cells.py` 生成（`team/整理/设计/定稿后增量修订.md` §1b、§4），**但该目录不存在**（`ls team/整理/修订/` 报不存在；工具在 `team/整理/GUJI-541/revision_cells.py`） |
| `-r<n>` 快照 | **只在文字里** | r 号（`001-r2`、`vol01-r1`）是 guji-workspace 快照名和待审单 `rev`。book-text 里只写进 CHANGES 的说明列和 `sprites.pointer.json`。`scripts/check_changes.py` 校验：凡「文本」线、带「快照 <哈希>」的行，必须写 r 号和 cv commit 前 8 位 |

### 1.4 docs/ 下与反馈、勘误、专名有关的文档

- `docs/ORIGINAL.md`：original 的文件体系、`*_file` 声明、`pending_file`（已废）、标题符、页码→IIIF、`derived` 分支。
- `docs/VERSIONING.md`、`docs/design/2026-10-文本版本号与仓库流程.md`：三条线、major＝质量等级、patch／minor 按「一册 ≤50 处」分界、F-OV-01～03、`bump_original.py`。
- `docs/design/2026-10-decision.json规范草案.md`：候选字层草案；正式版是 guji-format `spec/08`。
- `docs/design/2026-10-每字坐标格式-v0.1.md`（guji-page 副本）：§六「稳定 ID 与重切」写明「外部引用（网站深链、校勘、人裁）**一律引 `id`**，不引 `cv_id` 或下标」。
- `docs/reports/2026-10-GUJI-541-锚点迁移模拟.md`：册 002／003 实体锚点在改字、拆格、删格、插格、并格下的迁移模拟。
  - 改字 300 格：002 有 99 条实体受影响，**自动跟上 0**，99 条全部「失效待看」。
  - 标点线迁移「未做（后补）」。
- `docs/专名/`：专名判准、建档、不建档清单、回挂记录（GUJI-44、GUJI-240）。专名不在 M11 范围内，从略。
- **book-text docs 里没有「读者反馈」「勘误」的流程文档**。相关设计都在 ai-team `team/整理/设计/` 和 `team/网站/`。

### 1.5 CI（`.github/workflows/`）

| 工作流 | 触发 | 查什么 |
|---|---|---|
| `check.yml` | **2026-10-20 起只在每夜 11:00 UTC（洛杉矶 04:00）和手动触发时跑**，PR 和合并不再跑 | ① manifest／index 过 guji-format schema（版本按 pin 固定）；② V1 `validate-collated.py`（只放过存量 `d59f1iqd854w/default/108.md`）；③ V2 `validate_text_format.py --strict --baseline`（含 F-OV-01～12）；④ F-OV-02 报数（标点 `pre_char` 对不上 N 条、实体失效待看 N 条）并贴 PR 评论；⑤ V3 `check_license.py`；⑥ decision 夹具哈希；⑦ 单测；⑧ `pin-drift`（guji-format main 的 `schemas/` 与 pin 不同就红，不阻塞） |
| `check-changes.yml` | **只手动触发** | `check_changes.py`：CHANGES.md 里「文本版本 ↔ r 号 ↔ cv 版本」三项对应，只查 2026-10-17 以后的行 |

- PR 前改为本地跑 `python3 scripts/local_check.py`：只查改动条目的 V2，以及全仓 V1、V3、索引一致。**不含 schema 校验和单测**（book-text `CLAUDE.md`；`scripts/local_check.py` 文件头）。
- 校验器规则（`scripts/validate_text_format.py`）：
  - F-OV-01：版本格式、镜像一致、伴生层 major 不高于文本线。
  - F-OV-02：伴生层锚点校验字。
  - F-OV-03：major ≥2 要有验收记录。
  - F-OV-04：`*_file` 声明。
  - F-OV-05：decision。
  - F-OV-06：proofing。
  - F-OV-07：pending。
  - F-OV-08：guji-proof 0.2 新键的类型。
  - F-OV-09～11：雪碧图桶清单。
  - F-OV-12：标题。

---

## 2. 格式规范逐字段（guji-format，以及 cv 仓里的 guji-page／guji-proof）

> guji-page、guji-proof、pages.json **不在 guji-format 里**：
> - guji-page 规范在 open-guji-cv `doc/formats/guji_page_v0.2.md`（book-text `docs/design/2026-10-每字坐标格式-v0.1.md` 是 v0.1 副本）。
> - guji-proof 0.2 字段表在 ai-team `team/CV/guji-proof-0.2-字段表-GUJI-557.md`，实现在 cv `open_guji_cv/review/proof_fields.py`。
> - pages.json 是旧形态（A1 导出），10-06 起在 book-text 里被 cord 取代（book-text `docs/design/2026-10-文本版本号与仓库流程.md` §十）。
> - guji-format `spec/README.md:34`：「原 guji-page（Level 1）在 book-text 里拆成 cord（几何）和 decision（候选）；原 guji-cell（Level 2）改名 char 并去掉候选」。

### 2.1 char（`spec/02-guji-char.md`，schema `guji_char_v0.1`）

**顶层**

| 字段 | 说明 |
|---|---|
| `$schema` | 格式版本 URL |
| `version` | 文本线内容版本；正则 `^[0-3]\.\d+\.\d+$` |
| `review` | major ≥2 时必填，含 `date`／`signed_by`／`sample` |
| `book_id` | 条目 id |
| `volume` | 册号，＝章 `n` |
| `pages[]` | 每张扫描图一项；没有字的页也要有 |

**页**：`page`（扫描顺序号，从 1 起，＝IIIF seq；**不是**版心叶码）、`label`（版心叶码）、`columns[]`。

**列**：`col`（从右往左，从 1 起，版心列、空列也占号）、`raised`（抬头格数）、`lead_blank`（行首空格数）、`kind`（`body`／`banxin`／`blank`）、`cells[]`。**数组顺序就是读序**。

**格**（`additionalProperties: false`，不许有别的字段）：

| 字段 | 说明 |
|---|---|
| `a` | 格位 key |
| `c` | 定下的一个字 |
| `lane` | `main`／`solo`／`jz_r`／`jz_l`；`solo` 推不出，必须写 |
| `lacuna` | `true`＝阙文，此时 `c` 写 □ |
| `guess` | 残字推测 |
| `zi` | 组字原形（IDS 或描述） |

**格位 key 的数法**（§二）：

- 写法 `<页>:<列>:<格>[a|b]`，正则 `^\d+:\d+:-?[1-9]\d*[ab]?$`。
- 「格」从版框上沿往下数；留白格、排除格**也占号**，所以 char 里一列的格号可以有空缺。
- 抬头出框的格记负数（`-1`、`-2`），没有第 0 格。
- 双行夹注：`a`＝右列，`b`＝左列，两列都从夹注起始格起数；夹注之后的正文从「起始格＋max(a 字数, b 字数)」接着数。
- 格号口径＝cv 的几何格号，由切分量出来，不由字数推算。
- **格位 key 只在一章（＝一册）内唯一**。跨章深链写 `v<册>/<格位>`，只用在链接里，文件里不写（`spec/00` §4.1）。

### 2.2 cord（`spec/01`）

- **页**：`page`、`image{width,height,sha256}`、`canvas{id,seq,width,height}`、`producers.cv{tool,rev,pipeline,steps,products_sha,snapshot}`。
- **regions[]**：`id`、`kind`、`box`、`rules`。
- **columns[]**：`col`、`kind`、`box`。cord 收全部列框，包括没有字的列。
- **cells[]**：`a`、`box[x,y,w,h]`，**`id`（可选，「稳定框 id，重切后同一框不变」，base36 约 11 位）**。不许有 `c`。
- **marks[]**：`kind`（`blank`／`seal`／`excluded`）、`box`、`id`、`col`、`slot`、`occludes`、`note`。
- 改 cord 不升任何版本线。

### 2.3 punct（`spec/04`，v0.2）

- 顶层：`version`、`text_version`。
- 条目：

| 字段 | 说明 |
|---|---|
| `mark` | 标点符号 |
| `kind` | `point`／`break`／`heading` |
| `pos` | `before`／`after` |
| `anchor` | 格位 key（original 必填） |
| `char_offset` | 缓存 |
| `pre_char` | 校验字，＝该格 `c`；标题符不写 |
| `source` | 如 `glm:…`、`rule:reflow`、`claude:…` |
| `label`、`toc` | 只用于标题 |

- 改字后逐条核 `pre_char`：全对得上，只把 `text_version` 跟过去；对不上，修好后升 patch 或 minor（§155）。
- 在两段交界处插字时，由改字工具判定新字归前段还是后段（§128）。

### 2.4 entity（`spec/05`，v0.2）

- 条目：`id`（`e00002` 形，文件内编号）、`type`、`text`（校验字＝区间各格 `c` 依读序拼起来）、`anchor{start,end}`（格位 key）、`span{start_offset,end_offset}`（缓存）、`target`、`group`（复合专名）。
- 书名：`《》` 的锚点必须与 `work` 实体的起止相同。

### 2.5 decision（`spec/08`，v0.1 或 v0.2）

- 条目：`cell`、`current`（校验字）、`kind`（`uncertain`／`variant`）、`status`（`open`／`resolved`／`rejected`）、`cands[{text,src,conf,why,note}]`（≤5 个）、`by`、`note`。
- v0.2 新增 `reason`（`unclear`／`seg_bad`／`seg_recut`／`seg_missing_page`）、`route`（`recut`／`list`／`add_page`）、`route_ref`。
- **不改文本**：裁定后改字改的是 char（文本线 patch），本条 `status` 改为 `resolved`。不跟踪版本。
- 规范写「现在还没有任何 decision 数据」，仓里也确实 0 个文件。**这是 1.0 之后「请人再判」的现成载体，但还没用起来。**

### 2.6 guji-proof 0.2（ai-team `team/CV/guji-proof-0.2-字段表-GUJI-557.md`；cv `review/proof_fields.py`）

- 册级 `pending.json` 顶层：`rev`（`<册>-r<n>`）、`cv_version`、`cv_commit`（必填）、`cells[]`。后来加了 `sprites[]`（中心库设计）。
- 0.1 已有的单格字段：`id`、`a`、`method`、`review`、`channel`、`cand{lib,ocr,rare,ref}`、`conf`。
- 0.2 新增的单格字段：

| 字段 | 内容 |
|---|---|
| `why` | 待审原因机器码，没有码时写 `["none"]` |
| `cls`／`cls_sub` | 分类 |
| `lib_top` | 字形库前 5 名 `[{c,s}]` |
| `lib` | `{verdict,cov,wmax}` |
| `ctx` | `{c,margin,src}` |
| `margin` | 领先幅度 |
| `ref` | `{c,op}`，整理本对位字 |
| `ocr` | `[{c,src}]` |
| `stale` | `{c,ts,state}`，旧裁预勾 |
| `occ` | `{c,ref_blank}`，印章遮挡 |
| `img` | `{s,x,y,w,h}`，雪碧图里 96×96 的字块 |
| `ctximg` | 首版不做 |
| `ex` | 每个候选字 ≤5 个本书例子 |
| `alt` | 以字找字，≤30 个 |

- 章级 `proof.json` 只加 `cls`／`why`／`conf`。
- 雪碧图：`proof/<书>/<册>/p<页4位>.webp`；桶清单 `assets.json`（`guji-proof-assets/0.1`）。

### 2.7 guji-page v0.2（cv `doc/formats/guji_page_v0.2.md`）

- 一页一个 JSON，文本流 `text` 是真源，版面分区→列→段，字框 `glyphs` 在 IIIF canvas 上。
- 每个字框带 `id`（**不透明稳定 ID**）、`cv_id`（`book:page:col:slot[a|b]`，随重切变）、`glyph_id`、`method`、`review`、`channel`、`cand`、`prev`（重切时压到的旧 ID）。
- §六「稳定 ID 与重切」：
  - `mint_id("g", page_id, cv_id, row_segment 产物 sha)`。
  - `carry_ids`：同一张图上 IoU ≥0.85 沿用旧 ID；0.6–0.85 且一对一也沿用；拆、合、部分重合给新 ID，并写 `prev`。
  - 外部引用一律引 `id`。
- **这套稳定 ID 没有带进 book-text 的 char**（char 格对象不许有别的字段）。只有 cord 的 `cells[].id` 是它的残留。

### 2.8 「一个字在网站上的位置」怎么唯一定位、跨版本稳不稳

**唯一定位**：`book_id` ＋ 版本目录 key ＋ 册 `NNN` ＋ `a`，配校验字 `c` 与 `text_version`。像素位置由 cord 同一个 `a` 的 `box` 加 `canvas.id` 给出。

- 网站改字接口的实际 key 就是这么拼的：`cf:<book>:<volume>:<text_version>:<cell_id>:<voter>`（kaiyuanguji-web `edge-functions/api/charfix.js:189-193`）。`old_char` 取 char 里的原字（`nextjs/src/lib/charfix.ts` 文件头）。
- 一段文字的意见：`cs:<book>:<vol>:<tv>:<start>-<end>:<sub>:<voter>`。
- 专名意见：`ce:<book>:<vol>:<entity_id>:<voter>`。
- **注意：key 里没有版本目录 key**（`default` 还是 `cv-proof`），见 5.6。

**跨版本是否稳定**（依据 `定稿后增量修订.md` §3 的四类修订，加实测）：

| 修订类型 | 格位 key | 字下标 offset | cord `id` |
|---|---|---|---|
| A 同格改字 | 不变 | 不变 | 不变 |
| B 放行态变（□↔字） | 不变 | 不变 | 不变 |
| C 重切、拆格、并格、插删格、夹注改判 | **变**：被拆、被删的格消失；夹注 a/b 重编号会让其后整列平移（`shift`） | 变 | 按 IoU 承接，拆合给新 id |
| D 整页补入 | 新增 | 其后全变 | 新 |

**实测**：

- vol01 1.0.0→1.0.1（#205）：删掉 key `90:5:1`、`90:6:1`，新增 `90:5:1a`、`90:6:1a`，没有改字。命令：`python3 -I 调研临时脚本 cmp.py（未入仓）`，比较 HEAD 与 origin/main 的 `001.char.json`。
- vol03 两个 original 版本（`default/003` 1.0.2 对 `cv-proof/003` 0.1.1，两次独立 CV 产出）：
  - key 分别是 17,370 和 17,368；共有 17,364；只在 default 6 个，只在 cv-proof 4 个；同 key 不同字 23 格。
  - **cord `id` 同 key 同 id 的只有 16,297 个**，约 1,067 个共有格的 id 不同（约 6%）。所以 cord id 跨 CV 重跑并不完全稳定。
- 手补的格没有 cord `id`：`default/003.cord.json` 的 `57:1:3`、`57:1:4`（p57「見矣」手补，#168），共 2 格。

---

## 3. 数据现状（四庫總目 `96mid1ogzk`，本地 HEAD）

命令：`调研临时脚本 stats.py（未入仓）`（逐册 `git show` char 和 cord 后统计）。章条目元数据来自 `git show HEAD:Book/g/z/k/96mid1ogzk/default/index.json`。

| 册 | 文本线 | proofing | 标点／实体 | 格数 | □ | lacuna |
|---|---|---|---|---|---|---|
| default/001 | **1.0.0**（origin/main 已到 1.0.1，#205） | true | 1.0.0／1.0.0（#201） | 24,364 | 0 | **1**（`52:2:1` 字为「定」却带 `lacuna:true`，是 0.1.5 把 □ 改成「定」时的残留，违反 spec 02「lacuna 时 c 写 □」） |
| default/002 | **1.0.1** | — | 1.5.1／1.10.0 | 30,478 | 0 | 0 |
| default/003 | **1.0.2** | — | 1.5.1／1.10.0 | 17,370 | 0 | 0 |
| default/004 | 0.2.2 | true | — | 34,515 | 262 | 262 |
| default/005 | 0.1.1 | true | — | 28,950 | 256 | 256 |
| default/006 | 0.1.1 | true | — | 23,488 | 220 | 220 |
| default/007 | 0.1.0 | true | — | 21,174 | 182 | 182 |
| default/008 | 0.1.0 | true | — | 10,698 | 181 | 181 |
| default/009 | 0.1.0 | true | — | 42,022 | 453 | 453 |
| default/010 | 0.1.0 | true | — | 28,929 | 281 | 281 |
| cv-proof/003 | 0.1.1 | true | — | 17,368 | 19 | 19 |

- **≥1.0.0 的 3 册**（001–003，共约 72,212 格）；**0.x 的 7 册**（004–010，共 189,776 格）；另有 cv-proof/003（0.1.1，与 default/003 并存）。
- 其他条目都不跟踪版本（只有 `96mid1ogzk` 是 original）。
- **待审格数仓里统计不了**：pending 已移出 book-text。能统计的近似量是 0.x 各册 `lacuna`（阙文 □）合计 **1,835 格／189,776＝0.97%**。CHANGES 里写的是 CV 待审口径，例如：
  - vol04 首版「待审 466/34523=1.35%」，0.2.2「待审降到 0.88%」；
  - vol03 粗校「待审 13 格/17366」；
  - vol01 1.0.0「待审 0」。
- **COS 上公开的待审索引**：`curl https://data.kaiyuanguji.com/proof/index.json` → `{"books":{"96mid1ogzk":{"001":{"rev":"001-r2","n":0}}}}`。**只有 vol01，0 格。** vol04–10 虽然是 0.x、`proofing: true`（网站会挂「欢迎帮助校对」），精校页却没有待审单可读。
- 公开的读者意见清单 `https://data.kaiyuanguji.com/proof/fixes/96mid1ogzk.json` → **404**（还没发过）。
- `norm` 各册都是空表；`decision` 0 个文件；punct 和 entity 只有 001–003 有。

---

## 4. 现有文本修订路径

1. **唯一写入口是 book-text main 的 PR**。
   - main 受保护：一批活一个分支，开一个 PR，squash merge。由文本总管审；original 升 major 要用户点头。
   - 升版本只用 `scripts/book-text/bump_original.py`：它同时改 char 和 index 的版本号，写 `CHANGES.md`，核伴生层锚点（全对上就把 `text_version` 跟过去，对不上就拒绝）。
   - 出处：book-text `CLAUDE.md`「提交与推送」；`docs/design/2026-10-文本版本号与仓库流程.md` §一、§九。
2. **改字有两条来路，CHANGES 里都看得到**：
   - **（a）CV 重新导出，整册覆盖 char／cord**：
     - 粗校首版，如 004 →0.1.0（#162）；
     - 整册从原图重跑，如 004 0.1.0→0.2.0「cv rc/v0.4.5 全册从原图重跑」（#182）；
     - 局部重切再导出，如 001 0.1.2 第 196 页整页重切（#172）。
     - 流程：人裁事件进 guji-workspace／中心库 → CV 重跑 → 整理导出 → PR（`文本整理三阶段流程.md` §5.2、§6.2；`定稿后增量修订.md` §5）。
   - **（b）人直接改 char／cord**：
     - #168 p57 手补 2 字，cord 框「取自原图」；
     - #177 双行小注拆格，cord「按原框左右对半拆」；
     - #179 职名页 24 列按整理本改字、补抬头字、删框线碎片，cord「在原列框内按行近似分格」；
     - #184 vol02/03 对整理本逐列比对后改错，「补删格的 cord 按原框近似」；
     - #191 去掉 #184 带进来的非法 `lane` 字段；
     - #205 p90 首字改小注 a 行。
3. **人工改字会不会被下次 CV 导出覆盖**：
   - **book-text 里没有任何「人工改过」的标记**。char 格不许加字段；cord 里手补的格只是没有 `id`。唯一的记录是 CHANGES 那一行散文。
   - **CV 侧缺能表达这些改动的 override 事件**：
     - `文本整理三阶段流程.md` §5.3 列为「没有」的有：**补格（漏了一个字）、删格（误切出的多余格）**、版框／列框坐标、逐页页型、整列重切。
     - 排期是「窗口甲（10-20）前不动」，Mila 10-21 拆卡。
     - 所以 #168／#177／#179 这类补格、拆格，CV 现在没法用事件重现。
   - **实际做法是人工对账**：
     - vol01 0.1.6（#194）：「整册在云端用现行 cv 重跑后与本文逐格比，用户在『重跑对比定字』页定 14 格…这 128 格另写成人裁事件进中心库」；
     - #205：「与 cv 中心库 p90 人工框（2026-10-20 推库）一致」。
     - 说明人在用「重跑→和 book-text 逐格比→人裁→回写中心库」的办法防覆盖，**但这是按次手工做的，没有工具强制**。
   - **推测**：0.x 册（004–010）下一次「整册从原图重跑」（像 #182 那样）导出的 char 会整体替换旧 char。若在那之前有人在 book-text 里手补过而没写成中心库事件，就会被冲掉。1.x 册重切按 GUJI-541 流程走对照表，但对照表比的是 CV 新旧产物，本来就看不到 book-text 里的手改。
4. **伴生层（标点、专名）跟改字**：
   - 类型 A／B 靠 F-OV-02 自动核锚点；
   - 类型 C／D 要按对照表迁移，再报「受影响、自动跟上、失效待看」三个数（`定稿后增量修订.md` §5、§6）。
   - 保护规则依赖标点 `source: human:` 标记。按 Maren 实测，002 的 6,774 条标点里一条 `human:` 都没有（同上 §6），「保护规则等于空的」。

---

## 5. 断点与问题（每条带出处）

1. **反馈锚在格位 key 上，修订一改格号，旧意见就落空**
   - 网站改字 KV key＝`book:vol:text_version:cell_id`（`charfix.js:189-193`）。
   - 格号会变的实例：#205 `90:5:1→90:5:1a`；#177 `90:6:2→2a/2b`；#179 删碎片格、补抬头字。
   - 设计要求「旧 rev 的意见用对照表把 `a` 映射到新格号，映射不到的列给人」（`定稿后增量修订.md` §1b），但：
     - (a) 对照表目录 `team/整理/修订/` 不存在；
     - (b) 1b 只写了精校页 `cellreview` 按 `rev` 走，读者改字 `charfix` 按 `text_version` 落键，不带 `rev`；
     - (c) #184、#194、#205 这些 1.x 修订的 CHANGES 行没有快照、没有 r 号，`check_changes.py` 也只查带「快照」的行。
2. **设计里的稳定 ID 没落地到文本层**
   - guji-page §六说深链、校勘一律引不透明 `id`，但 char 没有 id（spec 02 §4.4 `additionalProperties:false`）。
   - cord `id` 是可选的；手补格没有 `id`（003 `57:1:3`、`57:1:4`）；两次 CV 产出同 key 的 id 约 6% 不同（§2.8 实测）。
   - 所以现在没有一个能扛住拆格、重切的锚。
3. **人改 book-text 与 CV 导出之间没有机制保证一致**
   - CV 缺补格、删格事件（三阶段 §5.3）；char 没有出处标记；只能人工「重跑对比」（#194）。
   - 残留实例：
     - vol01 `52:2:1` 字为「定」却仍带 `lacuna:true`（本地 HEAD）；
     - #191 修的是 #184 手改时带进的非法 `lane` 字段，导致 render_lines 报错。
   - **推测**：0.x 册整册重跑会冲掉未回写中心库的手改。
4. **没有「反馈 → 修订」的追溯链**
   - CHANGES 只写散文、PR 号、GUJI 卡号，不引意见 id 或 voter。
   - 唯一一次公众意见落地是 vol01 0.1.3（#173：「网站公众意见 9:7:17 臼…」）。追溯靠中心库事件批次名 `H-web-vol01-2026-10-18`（`待审单与公众意见走中心库.md` §2E），book-text 里没有回链。
   - 读者改字意见每日进中心库 `feedback/lists/web/<书>/fixes.jsonl`（kaiyuanguji-web `nextjs/scripts/proofing-sync.mjs:6`、`lib/fixes-sync.mjs`），**但在 ai-team 和 open-guji-cv 里 grep `fixes.jsonl`／`charfix` 都没有消费脚本**。`web_opinions.py` 只处理 `cellreview`。
   - 三阶段 §6.3 设想的「提交 → 初审 → 终审 → 批次合入 book-text」**推测**还没实现。
5. **0.x 册有「欢迎校对」横幅却没有待审单**：COS `proof/index.json` 只有 001（n=0）；004–010 都是 `proofing: true`（§3）。
6. **同一册有两个 original 版本**（`default/003` 1.0.2 与 `cv-proof/003` 0.1.1，manifest note 写「是否替换由文本总管和用户后定」）。网站改字的 ctx 和 KV key 里都没有版本目录 key（`charfix.ts`、`charfix.js` 里 grep `versionKey`／`cv-proof` 为空）。**推测**：如果两个版本都能在网站上读、能提意见，意见会分不清属于哪个目录（两边 `text_version` 不同，key 不会冲突，但下游要靠 tv 反推目录）。
7. **PR 不再跑云端 CI（10-20 起）**：改字类 PR 的 F-OV-02 锚点检查只靠提交人本地 `local_check.py` 和每夜全量。`local_check` 不含 schema 和单测（`local_check.py` 文件头）。三阶段 §6.3 原定「改字的下游检查走合入 PR 的 CI」，与现状不符。
8. **文档之间不一致，设计 M11 时容易读到旧口径**：
   - guji-format `spec/00` §4.3 写「文本线还在 0.x 时不得有这两条线（标点、实体）」；`定稿后增量修订.md` §1a 同口径。但 10-18 用户已改为允许（book-text `docs/design/2026-10-文本版本号与仓库流程.md` §四、§七），vol01 也确实在文本 0.1.x 时有过 punct／entity 0.1.0（CHANGES #174）。
   - book-text `docs/ORIGINAL.md` §五写「vol03 另有 `003.decision.json`」，仓里没有；spec 08 写「现在还没有任何 decision 数据」。
   - `ORIGINAL.md`、spec 00 §五都说 lines／rich 在 `derived` 分支，远端没有这个分支。
   - book-text `README.md` 里升版命令写的还是 `python3 <overview>/scripts/book-text/bump_original.py`，CLAUDE.md 说已迁入本仓。
9. **网站收的意见范围比 M11 宽**：`SPAN_SUBS` 含 `punct`、`para`、`heading`、`entity`（`nextjs/src/lib/fixes.ts`），另有 `ce:` 专名意见。M11 只管文字，要定这些意见去哪，或者过滤掉。
10. **book-index-manager 的通用反馈不带文字定位**：`FeedbackForm`／`FeedbackTab` 只提交 `{type: bug|resource|suggestion|contact, content, contact?, pageUrl, resourceId}`，状态有 `pending/in_progress/resolved/wontfix/duplicate`（`ui/src/components/FeedbackTab.tsx:12-14`、`FeedbackList.tsx:14`），没有格位、版本、选中文字。M11 的「选字报错」走的是 kaiyuanguji-web 的 `/api/charfix`，不是这套。
11. **意见有保留期**：charfix 的 KV TTL 是 180 天（`charfix.js:27`），cellreview 的 TTL 是 60 天（三阶段 §6.2）。每日 proofing-sync 把全量快照写进中心库，所以 sync 断太久会丢意见。**推测**：现在每日定时已开（`待审单与公众意见走中心库.md` §3a），风险不大。

---

## 附：本次用到的命令与脚本

- 文件清单：`git -C /home/user/open-guji/book-text ls-tree -r -l HEAD Book/g/z/k/96mid1ogzk`
- 逐册统计：`调研临时脚本 stats.py（未入仓）`
- 版本间格位、cord id 比对：`调研临时脚本 cmp.py（未入仓）`（需要先 `git fetch --depth=3 --filter=blob:limit=200k origin main`）
- 远端分支：`git ls-remote origin`
- 公开待审索引：`curl -sS https://data.kaiyuanguji.com/proof/index.json`
