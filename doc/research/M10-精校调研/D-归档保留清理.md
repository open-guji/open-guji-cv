# 调研 D：1.0 之后的收尾——冻结、归档、数据保留、工作区清理、局部修订通道

> GUJI-637「M10 精校流程梳理」调研的一部分。2026-10-20（洛杉矶）只读调研：没改任何仓库，没写 Jira，没删任何东西。
> 证据来源：本地仓 guji-workspace（`422f1d5`，浅克隆）、guji-workspace-data、open-guji-cv（`a00dbdb`）、open-guji-dataset（`7e13ee1`）、book-text（`ffbf1d49`）、ai-team（`f960641`）；中心库用读令牌只读查（`/v1/status` rev 12001、`/v1/tables/*`、`/v1/packs`）；`git ls-remote` 查各仓远端分支和 tag；Jira GUJI-562/564/567/568/598/599/601/624/627。
> 标「推断」或「未核」的结论没有实测过。

---

## 一、数据清单（以四庫總目 vol01 为例）

「1.0 后用处」一列的缩写：**回归**＝以后算法回归评测；**训练**＝训练、标注数据；**修订**＝1.0 后局部修订；**复现**＝复现当时的结果；**网站**＝阅读页、校对页。

| # | 数据 | 现在存在哪 | 量级（vol01／全书） | 能再生吗 | 1.0 后用处 | 现状备注 |
|---|---|---|---|---|---|---|
| 1 | **原图** `data_full/zongmu/volNN/*.png`（1-bit G4 存 PNG） | guji-workspace git（main）；源头是 IA `0606130x.cn`。北行日錄另有 NLC 的 PDF（`source/`） | vol01 65 MB；殿本 10 册 388 MB；北行 154 MB | **部分不能**：vol03 p105–108、vol04/07/09 的四联叶是从 IA 原图拆出来的（拆页表在 cv `doc/formats/samples/guji_page_v0.2/split_table_siku.json`，GUJI-625 还在改拆页算法），不是 IA 直出 | 复现、回归、训练、修订（重切一定要用原图） | 中心库设计 §3.2 说「原图第二批上 R2」，一直没做；GUJI-598 落点没定 |
| 2 | 册配置 `books/volNN.yaml`（含 `freeze:` 段、`corpus:`、`glyph_pin`、版式常量） | 中心库 `books` 表（10-19 起真源）；数据目录有本机副本 | 每册约 5 KB | 不能（人写的） | 复现、修订 | vol01 已写 `freeze:`（见问题 3） |
| 3 | 整理本、语料清单 `corpus/**`、`config/corpus-pack/vN` | 中心库 `corpus_files`（文本存 R2 `.txt`）＋`files` | 约 1 MB 级 | 能（来自维基文库、代字阁）；但「钉的那一版」只在这里有 | 复现、回归（align_ref 和 context 的输入） | GUJI-627：v1 钉选和当前文件不符 |
| 4 | 护栏与配置 `config/`（排除名单、groups、variants） | 中心库 `files`（kind=config） | 殿本约 1.5 MB | 不能（含人工） | 复现、训练（排除名单就是负样本） | — |
| 5 | **products**（13 步 × 页，`products/<册>/<步>/p*.json`＋`_manifest.jsonl`） | 各机本地；**快照**在 guji-workspace 的孤儿分支 `snap/96mid1ogzk/<册>/<时刻>`（共 55 条）；**产物包**在 R2 `pack/products/<ws>/<册>/<标签>`（`guji products pack`） | vol01 2,692 个文件，打包 7.2 MB；R2 产物包共 53 个对象 242 MB（10-19～20 两天） | 原则上能（同代码、同库、同原图），但要钉住代码、库、语料三样，见问题 1、8 | 复现（冻结基线）、修订（diff 的「前」）、回归（当基线预测） | 服务器另有 `products-siku.tar` 1.0 GB，**只有一份**（GUJI-564） |
| 6 | cache（列图、字块、归一图块） | 各机本地 `cache/` | 每册 GB 级（服务器上殿本工作区共 13 GB，含 cache、glyph.db 及备份） | 能（原图＋products） | 只有绑定重算、seed_admit 要用；不必保留 | 恢复演练实测：cache warm 约 21 分钟 CPU（vol03） |
| 7 | runs/ 任务记录、日志 | 本地 | 小 | 无所谓 | 排查 | 不必保留 |
| 8 | **人裁事件** events／consumed／anchors／anchor_patches（锚图）／verdicts（金标信封，含 manual-cells） | 中心库表；锚图、刻例图存 R2 正式桶（按 sha，公开域名 blob.open-guji.com） | 10-18 时 events 27,732 行、consumed 52,034、anchors 4,891、verdicts 5,494；锚图约 2,205 张 | **不能** | 训练（最值钱）、复现、修订 | GUJI-627：R2 缺 121 张锚图，`db pull` 整次失败 |
| 9 | 待审单、重切清单、对不上列交代 `feedback/lists/` | 中心库 `files`（kind=list） | 殿本 41 个文件，1.1 MB | 不能 | 复现、修订（2c、2d 的证据） | — |
| 10 | 公众意见 `feedback/lists/web/<书>/<rev>.jsonl` | 中心库 `files`（网站每日任务写）；10-18 以前的两份还在 workspace git `feedback/web/` | 每天几到几十行 | 不能 | 修订（1.0 后的主要输入）、训练 | 带 `voter` 哈希和 `note` 原文；公开归档前要过脱敏 |
| 11 | **字形库** `glyph_store`（刻例 PNG＋JSONL） | 中心库 `glyph_*` 表；刻例图存 R2 | 殿本刻例 3 万级（R2 计划去重后 30,480 个对象，90.7 MB，10-18） | 人裁那部分不能 | 训练（刻例＝带标签的字图）、复现（seed_admit 的输入） | 一个工作区一份，10 册共用；共享库 `glyphlib-qkp-v1`（1,076 例）另开工作区，只能写一次 |
| 12 | glyph.db（SQLite 索引） | 各机本地 | 不含字体域约 230 MB，含字体域 3.09 GB（服务器） | 能（`db pull` 时重建；字体域由字体文件确定性生成） | 只有复现时要 | 服务器上有多份 `.bak`（GUJI-567 评论 13745） |
| 13 | **冻结基线**登记 | vol01 yaml 的 `freeze:` 段；中心库 `freeze_baselines`、`snapshots`、`cv_versions` 三张表**都是空的**（10-20 实查） | — | — | 复现 | 见问题 3 |
| 14 | **文本** char／cord／norm／punct／entity＋`index.json`＋`CHANGES.md` | book-text main `Book/g/z/k/96mid1ogzk/default/` | vol01：char 1.2 MB、cord 3.3 MB、punct 0.8 MB、entity 1.2 MB；殿本目录共 49 MB | 不能（含手改，见问题 4） | 网站、回归（**整册的格框加定字就是金标**）、修订 | vol01 文本 1.0.0（#199），标点、实体 1.0.0（#201） |
| 15 | decision.json（候选字、存疑格） | 规范草案 `docs/design/2026-10-decision.json规范草案.md`，**没有一册真的落了这个文件** | — | — | 修订、训练 | — |
| 16 | 校对页书影切图 sprites | open-guji-dataset Release `proof-96mid1ogzk-001-1／-2`；book-text 只放指针 `proof/96mid1ogzk/001/sprites.pointer.json` | — | 能（原图＋cord） | 网站（1.0 后 pending 清空，基本不用了） | — |
| 17 | 归档包 | open-guji-dataset Release：**只有** `archive-96mid1ogzk-vol03-0.1.0-1`（`96mid1ogzk-keep.tar`，205 MB，演练用） | — | — | 冷备 | 包里是整个工作区的「留」表（10 册事件＋整库），不是一册 |
| 18 | 金标分片（benchmark） | open-guji-dataset 仓 | 仓 222 MB | 不能 | 回归 | Step7 定字**没有**分片（见问题 15） |
| 19 | 报告、实验记录（collation html/json、shadow、experiments/*.md） | guji-workspace git `reports/`（殿本 50 MB）、`experiments/` | — | 多数能 | 复现时可以追溯 | 不在中心库 |
| 20 | 修订对照表 `<册>-r<n-1>_to_r<n>.tsv` | 设计说放 ai-team `team/整理/修订/`，**这个目录不存在**，一份都没出过 | — | 能（两份 products diff） | 修订（公众意见按 rev 重新挂到新格号） | — |
| 21 | Step9 正式产出（`volNN.md`、对勘、pages.json、册 meta、避諱表） | 各机本地 `reports/` 或会话沙箱 | 小 | 能 | 复现、网站 | 三阶段流程 §8 要求写明落点，没落实 |
| 22 | 中心库每日备份 | R2 正式桶 `backup/<日期>/`，保留 30 天 | 每天约 12 MB | — | 灾备 | 和数据在同一个 Cloudflare 账号 |
| 23 | cv 代码 | open-guji-cv tag `v0.4.x`；冻结用的提交在分支 `recut/vol01-on-0.4.5`；服务器 `cv-all-1016-final.bundle` | — | — | 复现 | 见问题 1 |

**guji-workspace 每个目录现在放了什么**（1.5 GB＝工作树约 856 MB＋`.git` 660 MB，浅克隆）：

| 目录 | 大小 | 内容 | 判定 |
|---|---|---|---|
| `96mid…/data_full/zongmu/vol01–10` | 388 MB（65/69/23/45/37/29/26/13/52/34） | 原图，1,713 个文件 | 真源，留 |
| `96mid…/output/` | 207 MB | `book9/` v1 时代产物 58 MB（1,810 个文件）；`vol01/`、`vol02/` 旧 v2 产物各 42 MB；`self_assess_r2–r4` 39 MB；`review_flank_gate` 11 MB；`border_review` 8 MB；`vol01_v2view`、`glyph_selfcheck`、`inner_probe`、各类 `*_cards.jsonl` | **都是整理过程留下的旧东西**，不是原图 |
| `96mid…/reports/vol01–10` | 50 MB | collation、shadow、verdict_drift | 过程报告 |
| `96mid…/feedback/` | 4 MB | `verdicts.bak-*`、`consumed_bak_20260904`、`web/2026-10-18*.jsonl` | 备份，中心库不收 |
| `96mid…/experiments/` | 156 KB | vol04–10 各产物包的实验页 | 索引，有用 |
| `96mid…/README.md`、`ORIGIN.md` | — | README 还写着「glyph_store 进 git、真源在这里」 | **过期** |
| `988g7gsqhd…/` | 177 MB | 原图 154 MB、NLC PDF 7 MB、reports 12 MB、output 4 MB；`config/`、`review/batches/` 只剩 `.gitkeep`，`feedback/_backup_*`、`verdicts.bak-*` | 同上 |
| `_shared/train_bundle.zip` | 30 MB | glyph_bench＋oov_bench 评测包 | 跨书机器产物 |
| `exports/`、`qtw-draft/` | 小 | 沙箱产物说明、全唐文的空工作区标记 | 可清 |
| 远端分支 | — | `snap/*` 55 条、`claude/*` 17 条、`z8/qtw-draft`、22 个 PR ref | snap 是冻结依赖，见问题 2 |

---

## 二、现状与问题

严重度：**高**＝影响复现、会丢数据或卡住归档；**中**＝流程有缺口，要设计；**低**＝文档、元数据。

### 问题 1（高）冻结代码不在任何 tag 上，而且所在分支可能已被列进删除名单
- **证据**：中心库 `books/vol01` 的 `freeze.cv_commit: 456b30c505fc9b805c4a759a904a994d978d50fb`，注释是「recut/vol01-on-0.4.5 = 0.4.5 + 人工指定格补丁」。`git ls-remote` 显示这个提交只有分支 `refs/heads/recut/vol01-on-0.4.5` 指着，tag 列表里没有它（v0.4.5 是 `004bc889`）。`manual_cells` 后来作为 row_segment 1.20 合进了 main（`4838d7c`），改了 code_hash。
- **风险**：GUJI-567 M8 收尾评论说「151 个过期远端分支已交 Ops 删除」，删的是哪些没有清单。recut 分支一删，冻结基线的代码就再也找不回来。服务器上的 cv bundle 是 10-16 打的，不包含这个提交。版本号规矩第五节说过，「有 `cv_version` 的产物才能被视为可复现」，可冻结包的 manifest 里 `cv_version` 是 null（见问题 3）。

### 问题 2（高）冻结快照存在 guji-workspace 的 git 分支里，和「清理工作区」正面冲突
- **证据**：`ops/freeze.py::load_baseline` 用 `git -C <工作区> show snap/…:manifest.json` 读基线，只认工作区 git 里的 snap 分支，或者工作区相对路径下的 `manifest:`。R2 里虽然有一份 `products/siku-zongmu/vol01/snap-20261020T0142-cv0.4.5`（7.2 MB），但 freeze 不认产物包。
- **后果**：只要按 README 的「整完即删」把书目录或 snap 分支删掉，冻结册的 close-check 1a 就读不到基线。另外，工作区 git 已经说好「只存原图」，snap 分支却还在往里加（10-19 到 10-20 vol01 一天就推了 4 条），仓只会越长越大。

### 问题 3（高）冻结基线并没有冻住：1.0.0 之后指针被改过，也没有登记
- **证据**：
  - book-text `CHANGES.md` 1.0.0 那一行（#199）和 GUJI-624 评论 13979 写的冻结快照都是 `snap/96mid1ogzk/vol01/20261019T2303`；中心库里 vol01 yaml 现在写的是 `snapshot: snap/96mid1ogzk/vol01/20261020T0142`，`cv_commit` 换成了 recut 分支。10-20 用 manual_cells 重切了 18 列，重切之后才改的。
  - R2 包的 note 写着「未含 24 条重绑人裁（待落地）」；包 manifest 里 `cv_version: null`，`cv_commit: 07d846d9…`（这是打包那台机器的代码，不是生成产物的代码）。
  - 中心库 `freeze_baselines`、`snapshots`、`cv_versions` 三张表都是空的。设计稿写的是「由 close-check／发布流程写」，但没有命令去写。
  - ai-team `team/CV/各册产物cv版本登记.md` 的 vol01 行还停在 10-17 的 `cfa5edce`。
- **后果**：现在说不清「1.0.0 对应哪一份产物」。冻结基线变成了一个随手可改的 yaml 字段，改了不留版本、不留理由。

### 问题 4（高）1.0.0 的文本不是从冻结产物导出来的，「重导 char.json 逐字节一致」这条验收对 vol01 不成立（推断，未实测）
- **证据**：CHANGES 0.1.4、0.1.5、1.0.0 三行：职名页 24 列是按整理本手工改字；「cord 在原列框内按行近似分格」；补的字「按墨迹取框」；「66 格在重切清单、字已手改入文本」。GUJI-624 评论 13967 也说双行小注切乱的列是手工重建格号。
- **后果**：归档验收沿用的是三阶段流程 §8 和 562 恢复演练步骤 §3「重导的 char.json 与归档时逐字节相同」。vol03 0.1.0 能过，是因为它没有手改；vol01 1.0.0 按原文验收必然不过。以后每一册的精校阶段都会有手改，所以要换一个验收口径（见第三节 3.2）。

### 问题 5（高）归档脚本已失效：既扫错了目录，打包粒度也不对（卡住 GUJI-599）
- **证据**：`ai-team team/整理/GUJI-562/archive_plan.py` 的 `KEEP` 列的是书目录下的 `feedback/events`、`output/glyph_store`、`books`、`corpus`……10-19 写入切换之后，这些都搬到了工作区外的数据目录 `$GUJI_DATA_HOME/<分支>/<ws>/`（cv `doc/datastore.md` 第六节）。现在对书目录跑，「留」表会整个缺失。
- 粒度：它一次把整个工作区（10 册事件＋整个字形库＋语料＋reports）打成一个 tar。已经发布的 `archive-96mid1ogzk-vol03-0.1.0-1` 名义上是 vol03，实际是全书。
- 演练步骤里的 `rebuild --no-replay -w W`、「从 git 真源重建」也都是迁移前的做法。现在应该是 `guji db pull --rev N`，或者从备份恢复。

### 问题 6（高）GUJI-599「vol01 真实归档」为什么还没做
1. 卡上唯一的评论（10-18）列了两件前置：`store check` 有 23 个文件的差，服务器上有老的未提交文件。10-19 的中心库迁移（rev 1378 逐文件 0 差异）实际上已经让这两件过时了，卡上没人更新。
2. 归档脚本失效（问题 5），没人改。
3. 书影落点 GUJI-598 没定，而恢复演练离不开原图（562 步骤 §6、§7 实测）。
4. vol01 1.0.0 之后还在改：10-20 重切 18 列、换冻结指针、24 条人裁待落地（问题 3），GUJI-624 也没关。所以「到底归档哪一版」本身没定。
5. 无人负责：assignee 为空，执行人写的是「子对话 G」；M8 收尾时把 598、599 都摘出了 Epic，没有挂进新里程碑。
6. 发 Release 有权限门槛：云会话建 Release 返回 403。vol03 那次是用户本人发的（GUJI-568）。

### 问题 7（中）书影的落点没定，IA 原图也不能直接替代工作区原图
- **证据**：GUJI-598 没有任何评论。562 演练 §7：IA zip 和工作区原图逐页二值相同，**但** vol03 p105–108 是 09-27 拆页的成果，不是 IA 直出；GUJI-625 还在改四联叶的拆页算法。WebP 能不能代替原图做绑定，对比（orig-bind、webp-bind 两个工作区）一直没做，那两个工作区还占着服务器 1.2 GB。
- **后果**：要是只靠 IA，就必须同时冻结拆页表和拆页代码的版本。北行日錄的源头是 NLC 的 PDF，不在 IA 上。

### 问题 8（高）中心库只存「当前状态」，半年后还原不出冻结那一刻的人裁库和字形库
- **证据**：中心库是镜像式的，行被删就真删。changes 表只记 `old_sha/new_sha`，不存内容。10-18 以来已经有 `glyph_instances` 删 44 行、`glyph_exemplars` 删 51 行、`anchor_patches_meta` 删 1,946 行。每日备份只保留 30 天（GUJI-611）。`--from-rev` 开分支靠的是 Neon 的时间点恢复（`worker/src/branches.ts`），免费档只能回退 6 小时（中心库设计 §八）。
- **后果**：`freeze_baselines.db_rev` 就算登记了，过了 30 天也没法照着它恢复库。seed_admit 的输入（人裁、字形库）只能靠「冻结那一刻把本书的库导出来放进归档包」来保住。现有任何流程都没有这一步。

### 问题 9（中高）备份都在同一处，设计里的第二份备份已经没了
- **证据**：中心库设计 §八写的是「git 每日导出继续存在，作为第二份备份，也是公开发布的来源」。可实际上 guji-workspace 的 git 冻在 `6bef1ada`，没有反向导出。现在中心库的备份和 R2 图在同一个 Cloudflare 账号里；R2 的刻例图、锚图没有第二份；服务器上的三个 products tar 只有一份（GUJI-564：用户只核了 bundle）。

### 问题 10（中高）R2 缺 121 张锚图，任何新机器都拉不下殿本工作区（GUJI-627）
- vol04–09 共缺 121 张，`guji db pull` 碰到第一个 404 就整次中止。这是归档、恢复演练的硬前置，卡还在「待办」。

### 问题 11（中）中心库、R2、工作区 git 都会一直长，没有保留策略
- **R2 产物包**只增不改。两天里出现了 53 个对象、242 MB，其中有垃圾：`products/ws/vol01–03/vunknown-*` 三个包（ws 名退化成了 `ws`，约 21 MB）；vol07 有两个字节数一样的重复包（`cvunknown-…` 和 `cv0.4.7p9-…`，都是 6,393,733 B）。照受控重跑的节奏（10 册 × 每天若干标签 × 每包 3–13 MB），一个月就是 GB 级。
- **锚图**来回增删：库里 `anchor_patches_meta` 插入 2,797 行、删除 1,946 行，可 R2 对象从来不删，孤儿对象只会越积越多。
- **Neon**：10-18 灌入后 161 MB，免费档上限 1 GB、10 个分支。changes 表每写一行就多一条，10-18 到 10-20 记了 10,083 条变更。现在离上限还远，但没有任何人在盯。
- **guji-workspace**：删目录不会让 clone 变小（包已经 660 MB），只有轮换仓或改写历史才能真正瘦身，这要用户点头。

### 问题 12（中）guji-workspace 名义上「只存原图」，实际上还堆着大量整理完的东西
- 见第一节的目录表：殿本 `output/` 207 MB、`reports/` 50 MB、`feedback/*.bak` 4 MB，北行 `reports/` 12 MB，还有 `_shared`、`exports`、`qtw-draft`；书目录 README 也过期了。仓根 README 写着「整完即删」，但没说什么时候、谁来删、删之前要满足什么条件。

### 问题 13（中）冻结册没有运行护栏：用新代码重跑冻结册不会被拦
- **证据**：vol01 yaml 只在 `freeze:` 段里写了 `cv_version: "0.4.5"`，顶层没有 `cv_version:`。版本号规矩第五节的护栏只认顶层字段，所以在 main（0.4.7）上 `guji pipeline … vol01` 照跑不误。freeze 只影响 close-check 的 1a。
- **后果**：1.0 后做局部修订时，如果有人在 main 上跑了几页，冻结册里就混进了不同版本代码的产物，事后只能靠 1a 报警才发现。

### 问题 14（中高）1.0 后的局部修订通道没闭合
- `定稿后增量修订.md` §5 第 1 步写「事件进 guji-workspace，Ethan 在 cv main 重算」：两处都已过时，事件现在进中心库，main 也不是冻结时的代码。
- 导出用的 `export_guji_format.py` 是从 products 整章导出，会把手改过的格（问题 4）冲掉。没有「只换改过的页、其余保留」的合并工具。
- 对照表要求「长期保存在 `team/整理/修订/`」，这个目录不存在，一份对照表都没出过。
- 快照命名对不上：规矩里写 `<册>-r<n>`，实际分支是按时刻命名的；pending.json 的 `rev` 停在 0.1.x 的 `001-r2`，1.0.0 之后没有 r 号。公众意见按 rev 重新挂到新格号（GUJI-552）就没有锚可用。
- 改冻结指针算不算一次修订、要不要出新版本号，没有规定（问题 3 就是这么来的）。

### 问题 15（中）人裁要当训练集用，没有标准的提取格式
- open-guji-dataset `STEP_MAP.md` 里，Step7 定字（全流程最关键的一层标签）写的是「复用人裁历史回放（open-guji-cv 仓 feedback/events/），未落 dataset 仓独立分片」。这个路径早就不对了。
- 事件格式跟着 cv 一起演进：Owen 交接里提到，旧代码 `4324e4b` 读不懂 `kind=cell_review`。所以归档包里的原始事件，离开当时那一版 cv 就很难解释。
- `scripts/export_train_bundle.py` 只打 glyph_bench 和 oov_bench；`guji gold import`（runbook S15）只把部分分片写进 dataset。缺一个「这一册所有人裁 → 带标签样本」的导出。

### 问题 16（中）1.0 书本身就是最好的回归基准，但没有抽出来；vol02/03 不能当金标
- 一册 1.0 的 cord（像素框）加 char（定字），就是整册逐格的「框＋字」金标，比现有任何分片都完整。现在没人把它冻结成评测集；`guji eval run` 的注册表里也没有这种「整册」评测器。
- book-text `VERSIONING.md` 写明：vol02、vol03 是「按旧定义定的 1.0.0」，没走过精校，不能当金标。

### 问题 17（低）book-text 元数据小毛病
- vol01 文本已经 1.0.0，`index.json` 里仍是 `proofing: true`（VERSIONING 要求升 1.0.0 时加 `--proofing off`）。
- 没有一册真的有 decision.json。
- CHANGES 记的冻结快照和 yaml 里的不一致（问题 3）。

### 问题 18（低）文档、落点过时
- runbook S20 还让人往 overview 写收尾记录，overview 10-20 已经淘汰。
- runbook 只写到 S20 交付为止，没有「1.0 → 冻结 → 归档 → 清理」这一节。
- 各册产物cv版本登记表的 vol01 行过期。

### 问题 19（低中）公开归档的隐私口径要复核
- 已发布的 vol03 包是全工作区，含 10 册事件。脱敏规则只处理 `reviewer` 字段里 @ 之后的部分；公众意见的 `voter` 哈希、`note` 原文（里面有「【测试】Eden …」这样的测试数据）进公开仓之前要另定规则。中心库设计 §九也说「公众意见来源要脱敏」。

---

## 三、保留与清理方案

### 3.1 分层保留：热、温、冷

| 层 | 什么时候 | 留什么、放哪 | 删什么 |
|---|---|---|---|
| **热**（整理中，0.x → 1.0） | 开工到 1.0.0 | 全部：原图（工作区）、本地 products、cache、glyph.db、中心库 main、各次 snap／产物包 | 只删可再生的临时东西 |
| **温**（1.0 之后的修订期，建议 1.0 后 90 天，或下一次修订合入后再起算 90 天） | 1.0.0 发布当天进入 | ① **冻结包**：R2 `pack/products/<ws>/<册>/freeze-<文本版本>`，加 pin 标记，不受保留期清理；② 中心库本书行照留（体量小）；③ 原图照留；④ cv 冻结 tag；⑤ 书级字形库在冻结 rev 的导出包（问题 8） | 本机 cache、glyph.db 和它的 `.bak`、本册的实验产物包（main 指针和 freeze 以外的，超过 30 天就删） |
| **冷**（归档） | 归档包发布、恢复演练通过 | ① 公开：dataset Release `archive-<书>-<册>-<版本>-<n>`（脱敏）；② 私有：R2 `pack/archive/<ws>/<册>/<版本>`（不脱敏的全量，供内部复现）；③ 冻结评测集分片进 dataset 仓；④ 文本留在 book-text | 本册的 snap 分支（要先让 freeze 认 R2 包）、工作区里本册的原图（要先确认原图已有落点，见下）、本册的过程报告（先打进归档包） |

原图落点（替 GUJI-598 给出的选项，**待用户定**）：
- **A**：每册原图打进私有归档包（R2）。殿本每册 13–69 MB，R2 免费 10 GB 放得下。最省事。
- **B**：只记 IA 标识＋每页 sha＋拆页表版本，恢复时从 IA 拉下来再拆。最省空间，但拆过的页要靠拆页代码确定性复现，GUJI-625 改算法以后就不一定复现得出来。
- **C**：WebP。要等 CV 做完绑定对比才能判，目前没有结论。
- 建议选 **A**，或者 **A+B 记账**；B 里拆过的页一律按 A 处理。

### 3.2 「一册书归档包」应该装什么

包名 `archive-<book_id>-<册>-<文本版本>-<n>`。一册一个包；书级字形库单独一个包、所有册共用，见下。

```
manifest.json      guji-archive/1：book_id、册、text/punct/entity 版本、book-text 提交、cv tag 与提交、
                   中心库分支＋rev＋导出 sha、冻结产物包名与 sha、原图来源表（每页 sha、IA 标识、拆页表 sha）、
                   各类条数（事件、锚记录、锚图、人裁格、□、待审）、手改格清单 sha、脱敏规则版本
text/              book-text 当版的 NNN.char/cord/norm/punct/entity/index 条目、CHANGES 节选（让包能自成一体）
products/          冻结快照（13 步）＋ Step9 产出（volNN.md、对勘、pages.json、册 meta、避諱表）
central/           只取本册：books/volNN.yaml、events（book==册）＋anchors＋anchor_patches（PNG）、
                   verdicts（含 manual-cells）、lists（待审单、重切清单、对不上列交代、公众意见）、consumed 本册行
glyphstore-ref     指向书级包 archive-<book_id>-glyphstore-r<rev>（冻结 rev 时的 glyph_store 导出：jsonl＋刻例 PNG）
images/            方案 A 时放本册原图；方案 B 时只放 images.tsv（页、sha、来源、拆页参数）
revisions/         本册历次对照表 <册>-r<n-1>_to_r<n>.tsv
labels/            标准化标签，见 3.4（cells.jsonl、segdefects.jsonl、manual_cells.jsonl……）
hand_edits.tsv     文本里「不是从产物导出来的」格：格号、原因、出处（PR、事件 id）
RESTORE.md、SHA256SUMS
```

**恢复验收换口径**（解决问题 4）：
1. `guji archive fetch` 加 `guji db` 的一条恢复命令（要新做，用 central/ 和 glyphstore 包恢复，不连库）能还原数据目录；`glyph-db rebuild` 能成功。
2. 从 products/ 重导 char、cord：**不在 hand_edits.tsv 里的格**与 text/ 逐字节一致。
3. hand_edits.tsv 里的每一格都能追到事件、manual-cells 或某个 PR。
4. 条数和 manifest 一致；公开扫描 0 命中。

### 3.3 从 1.0 书里抽「冻结评测集」

- **落点**：open-guji-dataset 新分片 `book-gold/<book_id>-<册>-<文本版本>/`，用统一金标信封 `items.jsonl`，`label_origin: text-<版本>`。
- **每格一条**：`{page, col, slot, sub, bbox(cord 坐标), char, kind(正文/夹注/抬头/阙文), page_type, in_body, provenance(machine_admit/human/hand_edit), cv_pred(冻结产物里的字与状态), lane}`。图按 sha 和 IA 来源引用，不进仓。
- **切分**：按页固定种子，留 20% 做 test，其余做 dev。指标正文和非正文分开报（cv CLAUDE.md 定的规矩）；目录、职名这些页打 `in_body=false`。
- **永不改**：1.0 后的修订出新分片（如 `-1.0.1`），旧的保留。这样每次 cv 发 MINOR 都能拿同一把尺量（冻结基线规矩 L1 影响报告）。
- **评测器**：`guji eval run book-gold` 报四个数：放行格错放率、人审率、切分 F1（IoU≥0.5 对 cord）、□ 数。
- **入选门槛**：只收真正走完精校的 1.0（vol01 可以；vol02、vol03 要等补精校）；hand_edit 的格单独标出来，评切分时可以排除。

### 3.4 人裁导出成训练集的格式（补问题 15）

新增导出命令，建议叫 `guji archive export-labels <册>`，输出带 schema 版本、不依赖当时 cv 代码就能读：
- `cells.jsonl`：格号、页图 sha、bbox、最终字、来源事件 id 列表、裁决类型（confirm/override/seg_defect/cut/…）、批次、当时的 cv_version、reviewer 代号；
- `segdefects.jsonl`、`manual_cells.jsonl`（切分训练用）；
- `confusables.jsonl`：从 `collate_verdict` 挖出的形近对和异体对，复用 `guji promote mine`；
- 字块图按 sha 放 R2（公开域名），这样训练机器不用拉整个工作区。

### 3.5 工作区清理：规则与触发时机

| 什么时候 | 做什么 | 前提 |
|---|---|---|
| T1：册到 1.0.0（当天，最迟 7 天内） | 打冻结包（pin 住）；打 cv tag；写 `freeze_baselines` 一行（要新做命令）；yaml 顶层加 `cv_version`；导出书级字形库包 | — |
| T2：本册归档包发布＋恢复演练通过 | 删本机 cache、products（只留冻结包）、glyph.db 备份；删本册的实验产物包；删本册 snap 分支 | freeze 能认 R2 包（要改 cv） |
| T3：全书各册都已归档 | 工作区里删书目录（原图有落点之后）；中心库把这个 ws 标成只读归档（借库规则已经有「共享层只读」的先例） | 用户点头 |
| 每月 | R2 产物包：不是 main 指针、不是 freeze，且超过 30 天的删；清掉垃圾包（`products/ws/*`、重复的 cvunknown）；实验分支超过 7 天的删；已合并的 `claude/*` 分支删；看一眼 Neon 用量 | 删 R2 要正式令牌 |
| 每季度 | guji-workspace 仓轮换：把旧仓打成 bundle 传到 Release 当历史备份，新仓的 main 只放在整理的书 | 用户点头（这是破坏性动作） |
| 立刻可做（低风险） | 殿本 `output/` 的旧产物、`reports/`、`feedback/*.bak`，北行的同类东西：先打成「书级遗留包」放 Release，再从工作区 tip 删掉；修 README | 先确认没有代码引用这些路径 |

**中心库会不会也无限长**：行数随人裁线性增长，体量小（每册顶多几万行），1 GB 内能放很多书。会失控的是 R2 产物包、孤儿图和备份，用上表的月度规则就能管住。另外建议每季度把私有全量 dump 拷一份到 Cloudflare 以外的地方（比如用户本机或 Google Drive），解决问题 9，这要用户点头。

---

## 四、1.0 后的局部修订通道

原则（延续冻结基线规矩）：**1.0 后不整册重跑；文本（book-text）是真源；products 只是「最近一次能复现的机器结果」；每次修订都必须留下 r 号、对照表、事件。**

| 类型 | 例子 | 怎么走（命令） | 会不会和冻结冲突 |
|---|---|---|---|
| A 改字（同格换字），含网站公众意见 | 53:7:13 初→敕 | ① 人裁事件：控制台或 H 道写，`guji db sync` 推上中心库；② book-text PR 直接改 char（patch 版本），CHANGES 里写事件 id；③ CI 的 F-OV-02 核标点、实体锚点；**不跑 pipeline** | 不冲突：close-check 1a 只记「基线后新人裁 N 条待落地」 |
| B 放行态变（□ ↔ 字） | 切坏格录字 | 同 A；格号不变 | 同上 |
| C 重切一列或几列 | 职名页 18 列 | ① 写 `feedback/verdicts/char-segmentation/manual-cells/items.jsonl`，`guji db sync`；② 在**冻结 tag 的 worktree** 上只跑这几页：`guji pipeline keben_body_v2 <册> --from row_segment --to seed_admit --pages <页>`；③ `revision_cells.py diff --before <冻结包解出的目录> --after products` 出对照表，存进归档落点；④ **只替换这几页**的 char/cord，要新做页级合并导出，保护 hand_edits；⑤ 打新快照包 `<册>-r<n+1>`，`freeze_baselines` 新增一行（版本＝新文本版本），yaml 的 `freeze` 指过去；⑥ book-text PR；⑦ 标点、专名按 GUJI-541 报三个数 | **会冲突，而且应该冲突**：1a 会报「产物 sha 与快照不符」，必须走第 ⑤ 步重新冻结。不允许只改 yaml 指针、不出新版本（问题 3 那样） |
| D 补页 | p196 | 同 C，`--pages` 写新页 | 同 C |

为了让这条通道走得通，cv 和工具要补的东西：
1. **freeze 认 R2 产物包**（`freeze.pack: products/<ws>/<册>/<标签>`），不再依赖工作区 git 的 snap 分支；
2. **冻结册护栏**：冻结册上跑 `pipeline`/`step`，必须带 `--revision <r>`，并且装的代码等于冻结 tag（或者显式给 `--allow-cv-mismatch`）；
3. **`guji freeze register`**：写 `freeze_baselines`、`snapshots`、`cv_versions`，同时打 tag 请求；
4. **页级合并导出**：只重导指定页，其余页和 hand_edits 原样保留；
5. **对照表的长期落点和 r 号**：建议放进归档包的 `revisions/`，以及 book-text 的 `proof/<书>/<册>/revisions/`，和公众意见重挂共用一套编号。

---

## 五、建议的领域：输入、输出、验收标准

**领域名**：1.0 收尾与数据保留（冻结 → 归档 → 清理 → 局部修订）

**输入**
- 一册到 1.0.0 的 book-text 提交（char/cord/norm/punct/entity、CHANGES、index）；
- 中心库本 ws 在冻结时的 rev（人裁、字形库、语料钉选、册 yaml）；
- 冻结 products（R2 产物包）与生成它的 cv tag；
- 原图及其来源表（IA 标识、拆页表）；
- 手改格清单（2c、2d 的单据加 CHANGES 里的手改记录）。

**输出**
1. 冻结登记：cv tag，`freeze_baselines`、`snapshots`、`cv_versions` 各一行，yaml 顶层加 `cv_version` 护栏；
2. 一册归档包（公开脱敏版加私有全量版）加书级字形库包；
3. 冻结评测集分片 `book-gold/…`，加评测器；
4. 标准化标签导出 `labels/`；
5. 清理执行记录（删了什么、在哪个前提下删的），以及更新过的 README、runbook 收尾一节；
6. 1.0 后修订通道的命令与规矩（第四节），落进 cv `doc/` 和 ai-team `domain/`。

**验收标准**
- 冻结基线可复现：从冻结 tag 加冻结包加归档包，在空目录上 `close-check` 1a 全过；冻结 tag 和产物包在仓、桶删分支之后依然取得到；
- 归档包按 3.2 的口径恢复：非手改格 char/cord 逐字节一致，手改格 100% 可追溯，条数一致，公开扫描 0 命中；
- 拿 R2 的私有 dump，不连中心库也能把「冻结 rev 时的本册人裁加字形库」恢复出来；
- 冻结评测集上能跑出四个数，并且写进下一次 cv MINOR 的 L1 报告；
- 演练一次 A 类和一次 C 类修订：C 类留下 r 号、对照表、新的 freeze 行，hand_edits 一格不丢；
- 清理之后：工作区里只剩在整理的书的原图；R2 产物包里只剩 main 指针、freeze 和 30 天内的实验包；中心库仍在免费额度的 70% 以内。

**先后顺序建议**（先解卡、再保命、再优化）：
1. 修 GUJI-627 缺图；给 vol01 冻结代码打 tag（或者至少确认那个分支不在删除名单里）。这两件最急。
2. 定冻结版本：vol01 的 1.0.0 认 2303 还是 0142，由用户定；写 freeze 登记。
3. 用户定书影落点（3.1 的 A/B/C）。
4. 改归档脚本：从数据目录取、按册打包、换验收口径；然后做 vol01 真实归档（GUJI-599）。
5. cv 补四件：freeze 认 pack、冻结册护栏、freeze register、页级合并导出。
6. 冻结评测集、标签导出、清理规则、仓轮换。
